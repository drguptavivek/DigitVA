"""The AI tables beyond the case counts: ai_org_levels, ai_staff, ai_coder and
the cube's new dimensions, their scope and what each run builds (digitva-qwvt).

docs/policy/ai-analytics-questions.md, 'Tables, staff results and "not
captured"'. Fixtures: tests/ai_analytics_fixtures.py with ``with_staff``.
"""

from unittest import mock

import sqlalchemy as sa

from app import db
from app.services import ai_analytics_sandbox as sandbox
from app.services import ai_analytics_tables as tables
from tests.ai_analytics_fixtures import (
    DISTRICT_ONE,
    DISTRICT_TWO,
    PROJECT_ID,
    SITE_A,
    SITE_B,
    SUBCENTRE_ONE,
    SUBCENTRE_TWO,
    AiAnalyticsFixtures,
    sandbox_on_session_connection,
)
from tests.base import BaseTestCase

STAFF_COLUMNS = {
    "project_id", "site_id", *tables.ORG_NAME_COLUMNS, "role", "coding_language", "staff",
    "signed_in_7d", "signed_in_30d", "never_signed_in", "granted_30d", "dormant_30d",
    "unverified_email", "no_coding_language", "in_training", "training_started",
}
CODER_COLUMNS = {
    "project_id", "coder_number", "coder_name", "coder_site_id", *tables.ORG_NAME_COLUMNS, "month",
    "finals", "median_alloc_to_final_min", "alloc_to_final_min_sum", "timed_finals",
    "finals_under_3_min", "smartva_compared", "smartva_match", "smartva_low_likelihood",
    "smartva_match_low_likelihood", "exact_icd_match", "reviewer_finals", "reviewer_changed",
    "unknown_cause", "neonate_finals", "neonate_unknown_cause", "doris_checked", "doris_rejections",
    "doris_warnings", "age_sex_confirmations", "causing_condition_unknown", "doris_overridden",
    "not_codeable",
}
CASE_COLUMNS = ("va_sid", "unique_id", "va_uniqueid_real", "narrative_text", "sex", "analytics_age_band",
                "email", "user_id", "workflow_state")
STAFF_BY_PLACE = (
    "SELECT site_id, org_l2_name, role, sum(staff) AS staff FROM ai_staff WHERE coding_language IS NULL"
    " AND project_id = 'AIQ001' AND role IN ('coder', 'interviewer') GROUP BY 1, 2, 3 ORDER BY 3, 1, 2"
)
CODERS = "SELECT coder_name, coder_site_id, sum(finals) AS finals FROM ai_coder GROUP BY 1, 2 ORDER BY 1"


class AiAnalyticsTablesTests(AiAnalyticsFixtures, BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_ai_fixtures(with_staff=True)

    def setUp(self):
        super().setUp()
        patcher = sandbox_on_session_connection()
        patcher.start()
        self.addCleanup(patcher.stop)

    def _rows(self, sql, user=None):
        return sandbox.run_query(sql, user or self.base_admin_user).rows

    def test_cube_carries_language_consent_units_and_final_dates(self):
        rows = self._rows(
            "SELECT site_id, narration_language, consent_mode, org_l1_name, org_l2_name, final_saved_month,"
            " final_saved_week, sum(n) AS n FROM ai_cube WHERE site_id IN ('AQ01', 'AQ02') AND org_l1_name IS NOT NULL"
            " GROUP BY 1, 2, 3, 4, 5, 6, 7 ORDER BY 1"
        )
        # The reviewer's final (16 September) is the authoritative one at site A.
        self.assertEqual(rows, [
            {"site_id": SITE_A, "narration_language": "english", "consent_mode": "yes",
             "org_l1_name": DISTRICT_ONE, "org_l2_name": SUBCENTRE_ONE,
             "final_saved_month": "2026-09-01", "final_saved_week": "2026-09-14", "n": 1},
            {"site_id": SITE_B, "narration_language": "english", "consent_mode": "yes",
             "org_l1_name": DISTRICT_TWO, "org_l2_name": SUBCENTRE_TWO,
             "final_saved_month": "2026-09-01", "final_saved_week": "2026-09-14", "n": 1},
        ])

    def test_org_levels_follow_the_callers_projects(self):
        expected = [{"depth": 1, "level_name": "District"}, {"depth": 2, "level_name": "Sub-centre"}]
        sql = "SELECT depth, level_name FROM ai_org_levels WHERE project_id = 'AIQ001' ORDER BY depth"
        self.assertEqual(self._rows(sql), expected)
        self.assertEqual(self._rows(sql, self.dm_user), expected)
        self.assertEqual(self._rows("SELECT DISTINCT project_id FROM ai_org_levels", self.dm_user),
                         [{"project_id": PROJECT_ID}])

    def test_unit_data_manager_sees_only_its_subtree(self):
        by_district = "SELECT org_l1_name, sum(n) AS n FROM ai_cube WHERE org_l1_name IS NOT NULL GROUP BY 1 ORDER BY 1"
        self.assertEqual(self._rows(by_district), [{"org_l1_name": DISTRICT_ONE, "n": 1},
                                                   {"org_l1_name": DISTRICT_TWO, "n": 1}])
        self.assertEqual(self._rows(by_district, self.unit_dm), [{"org_l1_name": DISTRICT_ONE, "n": 1}])

    def test_staff_is_scoped_to_the_callers_users_page(self):
        admin = self._rows(STAFF_BY_PLACE)
        self.assertEqual(admin, [
            {"site_id": SITE_A, "org_l2_name": None, "role": "coder", "staff": 1},
            {"site_id": SITE_B, "org_l2_name": None, "role": "coder", "staff": 1},
            {"site_id": None, "org_l2_name": SUBCENTRE_ONE, "role": "interviewer", "staff": 1},
            {"site_id": None, "org_l2_name": SUBCENTRE_TWO, "role": "interviewer", "staff": 1},
        ])
        # A site-A data manager: its own site's grants only.
        self.assertEqual(self._rows(STAFF_BY_PLACE, self.dm_user),
                         [{"site_id": SITE_A, "org_l2_name": None, "role": "coder", "staff": 1}])
        # A unit data manager over district One: that subtree only.
        self.assertEqual(self._rows(STAFF_BY_PLACE, self.unit_dm),
                         [{"site_id": None, "org_l2_name": SUBCENTRE_ONE, "role": "interviewer", "staff": 1}])

    def test_staff_counts_and_coding_languages(self):
        rows = self._rows(
            "SELECT coding_language, staff, never_signed_in FROM ai_staff WHERE role = 'coder' AND site_id = 'AQ02'"
            " ORDER BY coding_language NULLS FIRST"
        )
        # Headcount row first, then one row per language, lower case.
        self.assertEqual(rows, [
            {"coding_language": None, "staff": 1, "never_signed_in": 1},
            {"coding_language": "english", "staff": 1, "never_signed_in": 1},
            {"coding_language": "hindi", "staff": 1, "never_signed_in": 1},
        ])
        unverified = self._rows(
            "SELECT org_l2_name, unverified_email FROM ai_staff WHERE role = 'interviewer' ORDER BY 1"
        )
        self.assertEqual(unverified, [{"org_l2_name": SUBCENTRE_ONE, "unverified_email": 0},
                                      {"org_l2_name": SUBCENTRE_TWO, "unverified_email": 1}])

    def test_staff_and_coder_tables_hold_no_case_or_identity_columns(self):
        for table, expected in (("ai_staff", STAFF_COLUMNS), ("ai_coder", CODER_COLUMNS)):
            with self.subTest(table):
                result = sandbox.run_query(f"SELECT * FROM {table}", self.base_admin_user)
                self.assertTrue(result.rows)
                self.assertEqual(set(result.columns), expected)
                for forbidden in CASE_COLUMNS:
                    self.assertNotIn(forbidden, result.columns)

    def test_coder_metrics_from_allocations_assessments_and_doris(self):
        rows = {r["coder_name"]: r for r in self._rows("SELECT * FROM ai_coder WHERE project_id = 'AIQ001'")}
        self.assertEqual(set(rows), {"AI coder-a", "AI coder-b"})
        a, b = rows["AI coder-a"], rows["AI coder-b"]
        self.assertEqual(a["month"], "2026-09-01")
        self.assertEqual(a["coder_site_id"], SITE_A)
        self.assertEqual((a["finals"], a["timed_finals"], a["finals_under_3_min"]), (1, 1, 1))
        self.assertAlmostEqual(a["median_alloc_to_final_min"], 2.0)
        self.assertAlmostEqual(b["median_alloc_to_final_min"], 10.0)
        self.assertEqual(b["finals_under_3_min"], 0)
        self.assertEqual((a["exact_icd_match"], b["exact_icd_match"]), (1, 0))
        self.assertEqual((a["reviewer_finals"], a["reviewer_changed"], b["reviewer_finals"]), (1, 1, 0))
        self.assertEqual(
            {k: a[k] for k in ("doris_checked", "doris_rejections", "doris_warnings", "age_sex_confirmations",
                               "causing_condition_unknown", "doris_overridden")},
            {"doris_checked": 1, "doris_rejections": 1, "doris_warnings": 1, "age_sex_confirmations": 1,
             "causing_condition_unknown": 1, "doris_overridden": 1},
        )
        self.assertEqual((b["doris_checked"], b["doris_rejections"]), (0, 0))
        # The lifted not-codeable mark still counts, in the month it was made.
        self.assertEqual((a["not_codeable"], b["not_codeable"]), (1, 0))

    def test_coders_are_scoped_to_their_work_on_the_callers_cases(self):
        self.assertEqual(self._rows(CODERS), [
            {"coder_name": "AI coder-a", "coder_site_id": SITE_A, "finals": 1},
            {"coder_name": "AI coder-b", "coder_site_id": SITE_B, "finals": 1},
        ])
        for user in (self.dm_user, self.unit_dm):
            with self.subTest(user=user.email):
                self.assertEqual(self._rows(CODERS, user),
                                 [{"coder_name": "AI coder-a", "coder_site_id": SITE_A, "finals": 1}])

    def test_only_the_referenced_tables_are_built(self):
        self.assertEqual(sandbox._validate("SELECT sum(staff) AS s FROM ai_staff")[1], frozenset({"ai_staff"}))
        self.assertEqual(sandbox._validate("WITH ai_cube AS (SELECT 1 AS n) SELECT n FROM ai_cube")[1], frozenset())
        self.assertEqual(sandbox._validate("SELECT 1 AS one")[1], frozenset())
        refuse = mock.Mock(side_effect=AssertionError("not referenced"))
        with mock.patch.dict(tables._BUILDERS, {name: refuse for name in tables.TABLES if name != "ai_staff"}):
            self.assertTrue(self._rows("SELECT sum(staff) AS s FROM ai_staff"))
            self.assertEqual(self._rows("SELECT 1 AS one"), [{"one": 1}])
        refuse.assert_not_called()
        # What was not built does not exist for the reader.
        builds = tables.build_selects(self.base_admin_user, {"ai_cube"})
        with self.assertRaises(sandbox.SandboxError) as caught:
            sandbox._run(db.session.connection(), builds, "SELECT count(*) AS c FROM ai_staff", 5000)
        self.assertIn("does not exist", caught.exception.message)

    def test_reader_gets_select_on_exactly_the_built_tables(self):
        sql = ("SELECT has_table_privilege('ai_cube', 'SELECT') AS cube,"
               " has_table_privilege('ai_coder', 'SELECT') AS coder")
        builds = tables.build_selects(self.base_admin_user, {"ai_cube", "ai_coder"})
        self.assertEqual(sandbox._run(db.session.connection(), builds, sql, 5000).rows,
                         [{"cube": True, "coder": True}])
        self.assertIsNone(db.session.scalar(sa.text("SELECT to_regclass('pg_temp.ai_coder')")))
