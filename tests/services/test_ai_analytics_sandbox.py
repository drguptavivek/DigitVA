"""The AI analytics sandbox: what generated SQL can and cannot do (digitva-qwvt).

docs/policy/ai-analytics-questions.md, "What the generated SQL can read".

Two layers. ``validate_sql`` (the parser) refuses anything but a plain SELECT
over ``ai_cube`` with allowlisted functions; dangerous SQL is only ever
checked there, never sent to the database (the dev cluster is shared). The
database tests call ``sandbox._run`` directly, past the parser, to show the
role, READ ONLY, timeout and row cap hold on their own.
"""

import importlib.util
import pathlib
from unittest import mock

import sqlalchemy as sa

from app import db
from app.services import ai_analytics_catalog as catalog
from app.services import ai_analytics_sandbox as sandbox
from app.services.submission_analytics_mv import (
    COD_SNAPSHOT_MV_NAME,
    CORE_MV_NAME,
    DEMOGRAPHICS_MV_NAME,
    get_dm_kpi_from_mv,
)
from tests.ai_analytics_fixtures import (
    DUPLICATE_SID,
    RETIRED_SID,
    SITE_A,
    SITE_B,
    SITE_T,
    TRAINING_PROJECT_ID,
    TRAINING_SID,
    AiAnalyticsFixtures,
    sandbox_on_session_connection,
)
from tests.base import BaseTestCase

CUBE_COLUMNS = {
    "project_id", "site_id", "submission_month", "sex", "analytics_age_band",
    "workflow_state", "authoritative_source", "authoritative_who_bucket_section",
    "authoritative_who_bucket", "authoritative_icd", "smartva_cause1_who_bucket",
    "nqa_rating", "narration_language", "consent_mode", "odk_sync_issue_code", "dm_not_codeable_reason",
    *sandbox.ORG_NAME_COLUMNS, "final_saved_month", "final_saved_week", "n", "nqa_score_sum", "nqa_scored_n",
}
BY_SITE = "SELECT site_id, sum(n) AS n FROM ai_cube GROUP BY site_id ORDER BY site_id"

# Each must be refused by the parser. None is ever run.
REFUSED = {
    "repeat": "SELECT repeat('a', 900000000) AS x",
    "lpad": "SELECT lpad('a', 900000000, 'b') AS x",
    "rpad": "SELECT rpad(site_id, 900000000) AS x FROM ai_cube",
    "array_fill": "SELECT array_fill(1, ARRAY[900000000]) AS x",
    "generate_series in FROM": "SELECT g FROM generate_series(1, 600) g",
    "generate_series in SELECT": "SELECT generate_series(1, 600) AS g",
    "string_agg": "SELECT string_agg(site_id, ',') AS x FROM ai_cube",
    "array_agg": "SELECT array_agg(site_id) AS x FROM ai_cube",
    "concat": "SELECT concat(site_id, site_id) AS x FROM ai_cube",
    "doubling operator": "WITH a AS (SELECT site_id AS s FROM ai_cube), b AS (SELECT s || s AS s FROM a) SELECT s FROM b",
    "pg_sleep": "SELECT pg_sleep(10) AS x",
    "advisory lock": "SELECT pg_advisory_lock(42) AS x",
    "xact advisory lock": "SELECT pg_try_advisory_xact_lock(42) AS x",
    "query_to_xml": "SELECT query_to_xml('select 1', true, true, '') AS x",
    "set_config": "SELECT set_config('role', 'postgres', true) AS x",
    "current_setting": "SELECT current_setting('work_mem') AS x",
    "pg_read_file": "SELECT pg_read_file('/etc/passwd') AS x",
    "qualified function": "SELECT public.lower(site_id) AS x FROM ai_cube",
    "regclass cast": "SELECT 'va_users'::regclass AS x",
    "regproc cast": "SELECT 'now'::regproc AS x",
    "array cast": "SELECT site_id::text[] AS x FROM ai_cube",
    "long constant": "SELECT '" + "a" * 201 + "' AS x",
    "with recursive": "WITH RECURSIVE r(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM r) SELECT i FROM r",
    "other table": "SELECT count(*) AS c FROM va_users",
    "interviewer table (not built)": "SELECT count(*) AS c FROM ai_interviewer",
    "staff table schema-qualified": "SELECT count(*) AS c FROM pg_temp.ai_staff",
    "schema-qualified cube": "SELECT count(*) AS c FROM public.ai_cube",
    "temp-qualified cube": "SELECT count(*) AS c FROM pg_temp.ai_cube",
    "catalog": "SELECT relname FROM pg_class",
    "catalog through a pg_ CTE name": "WITH pg_class AS (SELECT 1 AS x) SELECT x FROM pg_class",
    "catalog in a subquery": "SELECT n FROM ai_cube WHERE site_id IN (SELECT rolname FROM pg_roles)",
    "locking": "SELECT n FROM ai_cube FOR UPDATE",
    "into": "SELECT n INTO stolen FROM ai_cube",
    "current_user": "SELECT current_user AS u",
    "array constructor": "SELECT ARRAY[1, 2] AS x",
    "array sublink": "SELECT ARRAY(SELECT n FROM ai_cube) AS x",
    "group by cube": "SELECT site_id, sex, sum(n) AS n FROM ai_cube GROUP BY CUBE (site_id, sex)",
    "to_char non-constant format": "SELECT to_char(submission_month, site_id) AS x FROM ai_cube",
    "percentile without within group": "SELECT percentile_cont(0.5) AS x FROM ai_cube",
    "insert": "INSERT INTO ai_cube (n) VALUES (1)",
    "delete in a CTE": "WITH gone AS (DELETE FROM ai_cube RETURNING n) SELECT * FROM gone",
    "two statements": "SELECT 1 AS a; SELECT 2 AS b",
    "syntax error": "SELECT FROM WHERE",
    "power operator": "SELECT 10 ^ 100000 AS x",
    "huge numeric exponent": "SELECT 1e131000::text AS x",
    "long numeric constant": "SELECT 123456789012345678901 AS x",
    "tiny numeric exponent": "SELECT 1e-131000 AS x",
    "five cube references": "SELECT count(*) AS c FROM ai_cube a, ai_cube b, ai_cube c, ai_cube d, ai_cube e",
    "five references through a CTE":
        "WITH t AS (SELECT n FROM ai_cube) SELECT count(*) AS c FROM t a CROSS JOIN t b CROSS JOIN t c CROSS JOIN t d",
    "five nested subqueries squaring a value":
        "SELECT x*x AS x FROM (SELECT x*x AS x FROM (SELECT x*x AS x FROM (SELECT x*x AS x FROM "
        "(SELECT x*x AS x FROM (SELECT 12345678901234567890::numeric AS x) a) b) c) d) e",
    "nine CTEs":"WITH " + ", ".join(f"c{i} AS (SELECT 1 AS x)" for i in range(9)) + " SELECT 1 AS x",
    "order by using an unlisted operator": "SELECT site_id FROM ai_cube ORDER BY site_id USING ~<~",
    "order by using a qualified operator": "SELECT n FROM ai_cube ORDER BY n USING OPERATOR(pg_catalog.<)",
}

ACCEPTED = (
    BY_SITE,
    "SELECT analytics_age_band, sum(n) AS deaths FROM ai_cube GROUP BY analytics_age_band ORDER BY deaths DESC",
    "WITH t AS (SELECT site_id, sum(n) AS c FROM ai_cube GROUP BY site_id) SELECT site_id, c, "
    "rank() OVER (ORDER BY c DESC) AS r FROM t",
    "SELECT extract(year FROM submission_month)::int AS y, sum(n) AS c FROM ai_cube GROUP BY 1",
    "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY n) AS median FROM ai_cube",
    "SELECT sum(n) FILTER (WHERE submission_month >= CURRENT_DATE - interval '12 months') AS c FROM ai_cube",
    "SELECT coalesce(nqa_rating, 'none') AS r, greatest(1, 2) AS g, nullif(1, 2) AS z, "
    "CASE WHEN n > 1 THEN 'many' ELSE 'one' END AS k FROM ai_cube",
    "SELECT site_id, sum(n) AS c FROM ai_cube GROUP BY ROLLUP (site_id)",
    "SELECT to_char(submission_month, 'YYYY-MM') AS m, sum(n) AS c FROM ai_cube GROUP BY 1",
    "SELECT a.site_id, sum(a.n) AS c FROM ai_cube a WHERE EXISTS (SELECT 1 FROM ai_cube b WHERE b.site_id = a.site_id) GROUP BY 1",
    "SELECT count(*) AS c FROM ai_cube a, ai_cube b, ai_cube c, ai_cube d",
    "WITH " + ", ".join(f"c{i} AS (SELECT 1 AS x)" for i in range(8)) + " SELECT 1 AS x",
    "SELECT n * 12345678901234567890 AS x, 1.5e10 AS y, 0.25 AS z FROM ai_cube",
    "SELECT site_id FROM ai_cube ORDER BY site_id USING <",
    "WITH b AS (SELECT site_id, sum(n) AS c FROM ai_cube GROUP BY site_id), s AS (SELECT site_id, sum(staff) AS s"
    " FROM ai_staff GROUP BY site_id) SELECT b.site_id, b.c, s.s FROM b LEFT JOIN s ON s.site_id = b.site_id",
    "SELECT coder_name, sum(finals) AS f FROM ai_coder GROUP BY coder_name",
    "SELECT project_id, depth, level_name FROM ai_org_levels",
)


class AiAnalyticsValidatorTests(BaseTestCase):
    """Parser only: nothing here reaches the database."""

    def test_dangerous_sql_is_refused_by_the_parser(self):
        with mock.patch.object(sandbox, "_sandbox_connection", side_effect=AssertionError("no DB")):
            for label, sql in REFUSED.items():
                with self.subTest(label):
                    with self.assertRaises(sandbox.SandboxError) as caught:
                        sandbox.run_query(sql, self.base_admin_user)
                    self.assertEqual(caught.exception.code, "invalid_sql", caught.exception.message)

    def test_plain_selects_over_the_cube_are_accepted(self):
        for sql in ACCEPTED:
            with self.subTest(sql=sql[:60]):
                self.assertEqual(sandbox.validate_sql(sql), sql)

    def test_built_in_reports_and_catalog_pass_the_parser(self):
        self.assertGreaterEqual(len(catalog.BUILT_IN_REPORTS), 8)
        entries = catalog.load_catalog()
        self.assertGreaterEqual(len(entries), 20)
        for item in [*catalog.BUILT_IN_REPORTS, *entries]:
            with self.subTest(item["key"]):
                sandbox.validate_sql(item["sql"])

    def test_parse_errors_reach_the_model_redacted(self):
        with self.assertRaises(sandbox.SandboxError) as caught:
            sandbox.validate_sql("SELECT 'secret value' 'other' FROM")
        self.assertTrue(caught.exception.model_message.startswith("42601: "))
        self.assertNotIn("secret", caught.exception.model_message)

    def test_redact_quoted(self):
        self.assertEqual(
            sandbox.redact_quoted('column "nope" of \'x y\' does not exist'),
            "column <value> of <value> does not exist",
        )

    def test_text_guard(self):
        for sql in ("SELECT 1; DROP TABLE va_users", "DROP TABLE va_users", "", "  ",
                    "SELECT 1 AS x;", "x" * (sandbox.MAX_SQL_LENGTH + 1), None):
            with self.subTest(sql=sql if not sql or len(sql) < 50 else sql[:20]):
                with self.assertRaises(sandbox.SandboxError) as caught:
                    sandbox.check_sql_text(sql)
                self.assertEqual(caught.exception.code, "invalid_sql")
        self.assertEqual(sandbox.check_sql_text("  with x AS (SELECT 1) SELECT * FROM x"),
                         "with x AS (SELECT 1) SELECT * FROM x")

    def test_migration_holds_the_same_reader_setup(self):
        path = next(pathlib.Path("migrations/versions").glob("a9e4c7f2b3d6_*.py"))
        spec = importlib.util.spec_from_file_location("ai_migration", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.READER_SETUP_SQL, sandbox.READER_SETUP_SQL)
        self.assertIn("SET work_mem = '16MB'", module.READER_SETUP_SQL)
        self.assertIn("SET temp_file_limit = '256MB'", module.READER_SETUP_SQL)
        self.assertIn(f"DEFAULT {sandbox.AI_OUTPUT_MAX_BYTES})", module.READER_SETUP_SQL)
        self.assertIn(f"least(max_bytes, {sandbox.AI_OUTPUT_MAX_BYTES})", module.READER_SETUP_SQL)
        self.assertIn(f"ERRCODE = '{sandbox.OUTPUT_TOO_LARGE_SQLSTATE}'", module.READER_SETUP_SQL)

    def test_setup_script_holds_the_same_reader_setup(self):
        script = pathlib.Path("deploy/sql/ai_reader_setup.sql").read_text()
        statements = "\n".join(
            line for line in script.splitlines() if not line.startswith(("--", "\\set"))
        )
        grant = (
            "DO $$\nBEGIN\n    EXECUTE format('GRANT digitva_ai_reader TO %I', current_user);\n"
            "EXCEPTION WHEN duplicate_object OR unique_violation THEN NULL;\nEND $$;\n"
        )
        self.assertIn(grant, sandbox.READER_SETUP_SQL)
        expected = sandbox.READER_SETUP_SQL.replace(
            grant, "SELECT format('GRANT digitva_ai_reader TO %I', :'app_user') \\gexec\n"
        )
        self.assertEqual(statements.split(), expected.split())


class AiAnalyticsSandboxTests(AiAnalyticsFixtures, BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_ai_fixtures()

    def setUp(self):
        super().setUp()
        patcher = sandbox_on_session_connection()
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, sql, user=None, **kwargs):
        return sandbox.run_query(sql, user or self.base_admin_user, **kwargs)

    def _raw(self, sql, user=None, timeout_ms=sandbox.STATEMENT_TIMEOUT_MS,
             max_bytes=sandbox.AI_OUTPUT_MAX_BYTES):
        """Past the parser: the database limits alone."""
        builds = [("ai_cube", sandbox.cube_select(user or self.base_admin_user))]
        return sandbox._run(db.session.connection(), builds, sql, timeout_ms, max_bytes)

    def _raw_refused(self, sql, code="db_error"):
        with self.assertRaises(sandbox.SandboxError) as caught:
            self._raw(sql)
        self.assertEqual(caught.exception.code, code, caught.exception.message)
        return caught.exception

    def test_cube_has_only_the_aggregate_columns(self):
        result = self._run("SELECT * FROM ai_cube")
        self.assertTrue(result.rows)
        columns = set(result.columns)
        self.assertEqual(columns, CUBE_COLUMNS)
        for forbidden in ("va_sid", "unique_id", "va_uniqueid_real", "narration", "nqa_user_id", "nqa_name"):
            self.assertNotIn(forbidden, columns)

    def test_reader_holds_select_on_no_app_relation(self):
        # Present first: the reader role and the relations it must not read.
        relations = db.session.execute(sa.text(
            "SELECT c.relname, has_table_privilege('digitva_ai_reader', c.oid, 'SELECT')"
            " OR has_any_column_privilege('digitva_ai_reader', c.oid, 'SELECT') AS can_read"
            " FROM pg_class c JOIN pg_namespace ns ON ns.oid = c.relnamespace"
            " WHERE ns.nspname = 'public' AND c.relkind IN ('r', 'm', 'v', 'p')"
        )).all()
        names = {name for name, _ in relations}
        for expected in ("va_submissions", "va_users", CORE_MV_NAME, DEMOGRAPHICS_MV_NAME, COD_SNAPSHOT_MV_NAME):
            self.assertIn(expected, names)
        self.assertEqual([name for name, can_read in relations if can_read], [])

    def test_reader_cannot_read_base_tables_or_mvs(self):
        for relation in (
            "va_submissions", "va_users", "va_user_access_grants", "va_ai_saved_queries",
            CORE_MV_NAME, DEMOGRAPHICS_MV_NAME, COD_SNAPSHOT_MV_NAME,
        ):
            with self.subTest(relation=relation):
                exc = self._raw_refused(f"SELECT count(*) AS c FROM public.{relation}")
                self.assertIn("permission denied", exc.message)
        # Unqualified, the function's search_path does not even see them.
        self.assertIn("does not exist", self._raw_refused("SELECT count(*) AS c FROM va_submissions").message)

    def test_reader_cannot_switch_back_to_the_app_role(self):
        exc = self._raw_refused("SELECT set_config('role', session_user::text, true) AS r")
        self.assertIn("security-definer", exc.message)
        self.assertEqual(self._raw("SELECT current_user AS u").rows, [{"u": "digitva_ai_reader"}])

    def test_writes_are_refused(self):
        self.assertEqual(
            self._raw("SELECT current_setting('transaction_read_only') AS ro").rows, [{"ro": "on"}]
        )
        self._raw_refused("WITH gone AS (DELETE FROM ai_cube RETURNING n) SELECT * FROM gone")
        exc = self._raw_refused("SELECT set_config('transaction_read_only', 'off', true) AS rw")
        self.assertIn("read-write", exc.message)
        # The session is usable afterwards and the temp table is gone.
        self.assertIsNone(db.session.scalar(sa.text("SELECT to_regclass('pg_temp.ai_cube')")))

    def test_function_caps_work_mem(self):
        self.assertEqual(self._raw("SELECT current_setting('work_mem') AS w").rows, [{"w": "16MB"}])

    def test_function_caps_temp_files(self):
        self.assertEqual(
            self._raw("SELECT current_setting('temp_file_limit') AS t").rows, [{"t": "256MB"}]
        )

    def test_output_is_capped_in_the_database(self):
        # Twenty 200-character rows are about 4 KB of JSON: over a 1 KB cap.
        sql = "SELECT repeat('a', 200) AS s FROM generate_series(1, 20)"
        self.assertEqual(len(self._raw(sql).rows), 20)
        with self.assertRaises(sandbox.SandboxError) as caught:
            self._raw(sql, max_bytes=1024)
        self.assertEqual(caught.exception.code, "result_too_large")
        # Under the cap the same query runs; the argument cannot raise the cap.
        self.assertEqual(len(self._raw("SELECT repeat('a', 200) AS s FROM generate_series(1, 4)",
                                       max_bytes=1024).rows), 4)
        self.assertEqual(db.session.scalar(sa.text(
            "SELECT pg_get_function_arguments('digitva_ai_run(text, integer)'::regprocedure)"
        )), f"query text, max_bytes integer DEFAULT {sandbox.AI_OUTPUT_MAX_BYTES}")
        self.assertIsNone(db.session.scalar(sa.text("SELECT to_regprocedure('digitva_ai_run(text)')")))

    def test_statement_timeout_applies(self):
        with self.assertRaises(sandbox.SandboxError) as caught:
            self._raw("SELECT pg_sleep(2) AS slept", timeout_ms=100)
        self.assertEqual(caught.exception.code, "timeout")

    def test_advisory_locks_are_released_after_the_run(self):
        held = "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
        took = "SELECT count(*) AS took FROM (SELECT pg_advisory_lock(424242)) l"
        self.assertEqual(self._raw(took).rows, [{"took": 1}])
        self.assertEqual(db.session.scalar(sa.text(held)), 0)
        # Without the unlock the lock would still be held here.
        with mock.patch.object(sa, "text", side_effect=lambda s: sa.sql.text(s.replace("pg_advisory_unlock_all()", "1"))):
            self._raw(took)
        self.assertEqual(db.session.scalar(sa.sql.text(held)), 1)
        db.session.execute(sa.sql.text("SELECT pg_advisory_unlock_all()"))

    def test_db_errors_reach_the_model_redacted(self):
        exc = self._raw_refused("SELECT nope FROM ai_cube")
        self.assertIn("nope", exc.message)
        self.assertEqual(exc.model_message, "42703: column <value> does not exist")

    def test_rows_are_capped_at_500(self):
        result = self._raw("SELECT g FROM generate_series(1, 600) g")
        self.assertEqual(len(result.rows), 500)
        self.assertTrue(result.truncated)
        # A trailing comment cannot swallow the LIMIT.
        self.assertEqual(len(self._raw("SELECT g FROM generate_series(1, 600) g --").rows), 500)
        self.assertFalse(self._run("SELECT 1 AS one").truncated)

    def test_scope_limits_the_cube_to_the_users_sites(self):
        admin_rows = self._run(BY_SITE).rows
        self.assertIn({"site_id": SITE_B, "n": 2}, admin_rows)
        self.assertEqual(self._run(BY_SITE, self.dm_user).rows, [{"site_id": SITE_A, "n": 1}])

    def test_cube_total_equals_the_analytics_api_total(self):
        from app.services.data_management_service import dm_grant_scope

        for user in (self.dm_user, self.base_admin_user):
            with self.subTest(user=user.email):
                scope = dm_grant_scope(user)
                api_total = get_dm_kpi_from_mv(
                    project_ids=sorted(scope.project_ids), project_site_pairs=scope.pairs,
                    unit_ids=scope.unit_subtree(),
                )["total_submissions"]
                cube_total = self._run("SELECT sum(n) AS total FROM ai_cube", user).rows[0]["total"]
                self.assertGreater(api_total, 0)
                self.assertEqual(cube_total, api_total)

    def test_retired_and_confirmed_duplicate_submissions_are_excluded(self):
        # Present in the base data first.
        rows = dict(db.session.execute(sa.text(
            f"SELECT va_sid, odk_missing FROM {CORE_MV_NAME} WHERE va_sid IN (:r, :d)"
        ), {"r": RETIRED_SID, "d": DUPLICATE_SID}).all())
        self.assertEqual(rows, {RETIRED_SID: True, DUPLICATE_SID: False})
        self.assertEqual(db.session.scalar(sa.text(
            "SELECT status FROM va_death_register WHERE va_sid = :d"), {"d": DUPLICATE_SID}), "duplicate")
        # Site B holds two counted submissions besides them.
        self.assertIn({"site_id": SITE_B, "n": 2}, self._run(BY_SITE).rows)

    def test_training_project_is_excluded(self):
        self.assertIn(
            TRAINING_SID,
            db.session.scalars(sa.text(f"SELECT va_sid FROM {CORE_MV_NAME} WHERE project_id = :p"),
                               {"p": TRAINING_PROJECT_ID}).all(),
        )
        # Outside a request (no training scope) the admin sees it ...
        self.assertIn({"site_id": SITE_T, "n": 1}, self._run(BY_SITE).rows)
        # ... and in a request, which runs in the exclude scope, nobody does.
        with mock.patch.dict(self.app.config, DIGITVA_TRAINING_PROJECT_ID=TRAINING_PROJECT_ID):
            with self.app.test_request_context("/"):
                sites = {row["site_id"] for row in self._run(BY_SITE).rows}
        self.assertIn(SITE_B, sites)
        self.assertNotIn(SITE_T, sites)

    def test_breakdown_counts_one_category_by_three_dimensions(self):
        groups = sandbox.breakdown(self.base_admin_user, "site_id", SITE_B)
        self.assertEqual(set(groups), set(sandbox.DRILL_BY))
        self.assertEqual(groups["workflow_state"], [("ready_for_coding", 2)])
        self.assertEqual(sum(n for _key, n in groups["sex"]), 2)
        # Scoped: the data manager sees nothing of site B.
        self.assertEqual(sandbox.breakdown(self.dm_user, "site_id", SITE_B)["sex"], [])
        # "(none)" is NULL: no submission has a final cause yet.
        none = sandbox.breakdown(self.dm_user, "authoritative_who_bucket", sandbox.DRILL_NONE)
        self.assertEqual(none["workflow_state"], [("ready_for_coding", 1)])
        with self.assertRaises(ValueError):
            sandbox.breakdown(self.dm_user, "n; DROP TABLE va_users", "x")

    def test_explain_checks_names_without_running(self):
        sandbox.explain_query(BY_SITE, self.dm_user)
        with self.assertRaises(sandbox.SandboxError) as caught:
            sandbox.explain_query("SELECT nope FROM ai_cube", self.dm_user)
        self.assertEqual(caught.exception.code, "db_error")
        with self.assertRaises(sandbox.SandboxError) as caught:
            sandbox.explain_query("SELECT repeat('a', 9) AS x", self.dm_user)
        self.assertEqual(caught.exception.code, "invalid_sql")

    def test_explain_keeps_percent_signs_and_colons(self):
        sql = ("SELECT site_id, n % 2 AS odd, to_char(submission_month, 'HH24:MI') AS t "
               "FROM ai_cube WHERE site_id LIKE '%a%'")
        # Unescaped, the driver raises on the %; over-escaped, the database
        # sees an operator %% that does not exist.
        sandbox.explain_query(sql, self.dm_user)

    def test_built_in_reports_and_catalog_run(self):
        for item in [*catalog.BUILT_IN_REPORTS, *catalog.load_catalog()]:
            with self.subTest(item["key"]):
                self._run(item["sql"], self.dm_user)


class AiAnalyticsNotConfiguredTests(AiAnalyticsFixtures, BaseTestCase):
    def test_missing_function_is_not_configured_not_a_db_error(self):
        db.session.execute(sa.text("DROP FUNCTION digitva_ai_run(text, integer)"))
        try:
            with mock.patch.object(sandbox, "_reader_ready", False), sandbox_on_session_connection():
                with self.assertRaises(sandbox.SandboxError) as caught:
                    sandbox.run_query("SELECT * FROM ai_cube", self.base_admin_user)
        finally:
            db.session.rollback()
        self.assertEqual(caught.exception.code, "not_configured")
        self.assertIn("ai_reader_setup.sql", caught.exception.message)
