"""Data-manager backend fixes: redacted coded_by sort (digitva-10fd), COD bucket
400s (208a), non-integer days/limit 400s (4xpd), has_smartva_failed (i347),
admin on the DM API (ujbi), sync/runs scope-then-limit (d92d)."""

import json
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaSyncRun,
    VaUserAccessGrants,
)
from app.services.data_management_service import dm_submissions_page
from app.services.submission_analytics_mv import (
    COD_MV_NAME,
    CORE_MV_NAME,
    DEMOGRAPHICS_MV_NAME,
    build_submission_analytics_core_mv_sql,
    build_submission_analytics_demographics_mv_sql,
    build_submission_cod_detail_mv_sql,
)
from tests.base import BaseTestCase


class DmBackendFixesTests(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}DF"
    SID_OK = "uuid:dmfix-ok"
    SID_FAILED = "uuid:dmfix-failed"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        cls._ensure_base_research_project_and_site()
        db.session.add(VaForms(
            form_id=cls.FORM_ID, project_id=cls.BASE_PROJECT_ID, site_id=cls.BASE_SITE_ID,
            odk_form_id="DMFIX_FORM", odk_project_id="73", form_type="WHO VA 2022",
            form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
        ))
        db.session.flush()
        for sid in (cls.SID_OK, cls.SID_FAILED):
            db.session.add(VaSubmissions(
                va_sid=sid, va_form_id=cls.FORM_ID, va_submission_date=now,
                va_odk_updatedat=now, va_data_collector="Collector",
                va_instance_name=sid, va_uniqueid_real=sid, va_uniqueid_masked=sid,
                va_consent="yes", va_narration_language="English",
                va_deceased_age=40, va_deceased_gender="male",
                va_summary=[], va_catcount={}, va_category_list=[],
            ))
            db.session.flush()
            db.session.add(VaSubmissionWorkflow(
                va_sid=sid, workflow_state="ready_for_coding",
                workflow_reason="test_seed", workflow_updated_by_role="vasystem",
            ))
        db.session.add(VaSmartvaResults(
            va_sid=cls.SID_FAILED, va_smartva_outcome=VaSmartvaResults.OUTCOME_FAILED,
            va_smartva_status=VaStatuses.active,
        ))
        db.session.commit()

    def _user(self, key, *roles):
        user = self._get_or_make_user(f"dmfix.{key}@test.local", "DmFix12345")
        for role in roles:
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project,
                project_id=self.BASE_PROJECT_ID, grant_status=VaStatuses.active,
            ))
        db.session.commit()
        return user

    def _order_by_sql(self, user, **kw):
        statements = []

        def grab(conn, cursor, statement, *a):
            if "ORDER BY" in statement and "LIMIT" in statement:
                statements.append(statement)

        engine = db.session.get_bind()
        sa.event.listen(engine, "before_cursor_execute", grab)
        try:
            dm_submissions_page(user, **kw)
        finally:
            sa.event.remove(engine, "before_cursor_execute", grab)
        return statements[-1].split("ORDER BY")[-1]

    # 10fd
    def test_redacted_viewer_coded_by_sort_is_ignored(self):
        collab = self._user("collab", VaAccessRoles.collaborator, VaAccessRoles.data_manager)
        pii = self._user("collabpii", VaAccessRoles.collaborator_pii, VaAccessRoles.data_manager)
        # data_manager unlocks PII on its own (should_redact_pii is an OR), so use
        # viewer-only users with a patched scope instead.
        from unittest.mock import patch
        with patch("app.services.data_management_service.should_redact_pii", return_value=True):
            redacted = self._order_by_sql(collab, sort_field="coded_by", sort_dir="asc")
        with patch("app.services.data_management_service.should_redact_pii", return_value=False):
            open_ = self._order_by_sql(pii, sort_field="coded_by", sort_dir="asc")
        self.assertIn(".name", open_)
        self.assertNotIn(".name", redacted)

    # i347
    def test_rows_carry_has_smartva_failed(self):
        dm = self._user("dm", VaAccessRoles.data_manager)
        rows = {r["va_sid"]: r for r in dm_submissions_page(dm, per_page=100)["data"]}
        self.assertTrue(rows[self.SID_FAILED]["has_smartva_failed"])
        self.assertFalse(rows[self.SID_OK]["has_smartva_failed"])
        failed = dm_submissions_page(dm, smartva="failed", per_page=100)["data"]
        self.assertEqual({r["va_sid"] for r in failed}, {self.SID_FAILED})

    def _create_analytics_mvs(self):
        """/kpi reads the analytics MVs, which conftest drops (test-harness.md)."""
        for mv in (COD_MV_NAME, DEMOGRAPHICS_MV_NAME, CORE_MV_NAME):
            db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {mv} CASCADE"))
        db.session.execute(sa.text(build_submission_analytics_core_mv_sql(include_org_unit=True)))
        db.session.execute(sa.text(f"CREATE UNIQUE INDEX dmfix_core_va_sid ON {CORE_MV_NAME} (va_sid)"))
        db.session.execute(sa.text(build_submission_analytics_demographics_mv_sql()))
        db.session.execute(sa.text(f"CREATE UNIQUE INDEX dmfix_demo_va_sid ON {DEMOGRAPHICS_MV_NAME} (va_sid)"))
        db.session.execute(sa.text(build_submission_cod_detail_mv_sql(include_icd11=True)))
        db.session.execute(sa.text(f"CREATE UNIQUE INDEX dmfix_detail_va_sid ON {COD_MV_NAME} (va_sid)"))
        db.session.commit()

    # ujbi
    def test_admin_without_dm_grant_reaches_submissions_and_kpi(self):
        self._create_analytics_mvs()
        self._login(str(self.base_admin_user.user_id))
        for path in ("/submissions", "/kpi", "/filter-options", "/coder-daily-stats", "/sync/runs"):
            resp = self.client.get(f"/api/v1/data-management{path}")
            self.assertEqual(resp.status_code, 200, f"{path}: {resp.get_data(as_text=True)[:200]}")
        data = self.client.get("/api/v1/data-management/submissions?size=100").get_json()
        self.assertIn(self.SID_OK, {r["va_sid"] for r in data["data"]})

    def test_gender_filter_ignores_case_in_list_kpi_and_options(self):
        sub = db.session.get(VaSubmissions, self.SID_OK)
        sub.va_deceased_gender = "Male"
        db.session.commit()
        try:
            self._create_analytics_mvs()
            self._login(str(self.base_admin_user.user_id))
            base = "/api/v1/data-management"
            for spelling in ("male", "MALE", "Male"):
                rows = self.client.get(f"{base}/submissions?size=100&gender={spelling}").get_json()["data"]
                sids = {r["va_sid"] for r in rows}
                # Both the mixed-case row and the lower-case row match; the subject is present before we judge absence.
                self.assertIn(self.SID_OK, sids, spelling)
                self.assertIn(self.SID_FAILED, sids, spelling)
            self.assertEqual(self.client.get(f"{base}/submissions?size=100&gender=female").get_json()["data"], [])
            kpi_male = self.client.get(f"{base}/kpi?gender=MALE").get_json()
            kpi_none = self.client.get(f"{base}/kpi?gender=female").get_json()
            self.assertGreaterEqual(kpi_male["total_submissions"], 2)
            self.assertEqual(kpi_none["total_submissions"], 0)
            genders = self.client.get(f"{base}/filter-options").get_json()["genders"]
            self.assertIn("male", genders)
            self.assertNotIn("Male", genders)
        finally:
            sub.va_deceased_gender = "male"
            db.session.commit()

    def test_non_dm_user_still_refused(self):
        user = self._user("nobody")
        self._login(str(user.user_id))
        self.assertEqual(self.client.get("/api/v1/data-management/submissions").status_code, 403)

    # 208a
    def test_cod_buckets_bad_params_are_400(self):
        self._login(str(self.base_admin_user.user_id))
        for path in ("aggregates", "export.csv"):
            for qs, code in (("date_from=nope", "invalid_date"), ("scheme_code=NO_SUCH", "unknown_scheme")):
                resp = self.client.get(f"/api/v1/cod-buckets/{path}?{qs}")
                self.assertEqual(resp.status_code, 400, f"{path}?{qs}")
                self.assertEqual(resp.get_json()["code"], code)

    # 4xpd
    def test_non_integer_days_is_400(self):
        self._login(str(self._user("kpidm", VaAccessRoles.data_manager).user_id))
        for url in (
            "/api/v1/analytics/dm-kpi/grid/?days=abc",
            "/api/v1/analytics/dm-kpi/pipeline/inflow-outflow?days=abc",
            "/api/v1/analytics/dm-kpi/pipeline/backlog-trend?days=0",
            "/api/v1/analytics/submissions/by-date?limit=x",
        ):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 400, url)
            self.assertEqual(resp.get_json()["code"], "invalid_request")

    # d92d
    def test_sync_runs_filters_scope_before_limit(self):
        dm = self._user("syncdm", VaAccessRoles.data_manager)
        other = self._get_or_make_user("dmfix.other@test.local", "DmFix12345")
        now = datetime.now(timezone.utc)
        mine = VaSyncRun(triggered_by="data-manager", triggered_user_id=dm.user_id,
                         started_at=now.replace(year=2000), progress_log=json.dumps([]))
        db.session.add(mine)
        for i in range(30):  # newer, out-of-scope runs that would fill the old LIMIT 25
            db.session.add(VaSyncRun(
                triggered_by="data-manager", triggered_user_id=other.user_id,
                started_at=now, progress_log=json.dumps([{"msg": "[ZZ99ZZ99] x"}]),
            ))
        db.session.commit()
        self._login(str(dm.user_id))
        runs = self.client.get("/api/v1/data-management/sync/runs").get_json()["runs"]
        self.assertEqual([r["sync_run_id"] for r in runs], [str(mine.sync_run_id)])
