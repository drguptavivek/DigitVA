"""GET /api/v1/me/home: one Home block per role held, counts inside each role's
own scope (docs/current-state/api-v1.md, "GET /api/v1/me/home").

Users and the AZTA01 tree (D1 > C1 > P1 > SC1, C1 > P2, D2) come from the
authz fixture.
"""
from datetime import UTC, datetime

from unittest.mock import patch

import sqlalchemy as sa

from app import db, limiter
from app.models import VaDeathRegister, VaProjectMaster, VaSubmissions, VaWebIntakeDraft
from app.services.authz import invalidate
from app.services.submission_analytics_mv import (
    CORE_MV_NAME,
    build_submission_analytics_core_mv_sql,
)
from tests.authz.fixture import TA, AuthzFixtureMixin, R, U
from tests.base import BaseTestCase

HOME = "/api/v1/me/home"


class MeHomeTests(AuthzFixtureMixin, BaseTestCase):
    PROJECT_ID = TA

    def setUp(self):
        super().setUp()
        limiter.reset()
        # The data manager block reads the core analytics MV; per-test isolation
        # rolls DDL back, so build it here (docs/policy/test-harness.md).
        db.session.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {CORE_MV_NAME} CASCADE"))
        db.session.execute(sa.text(build_submission_analytics_core_mv_sql(include_org_unit=True)))
        db.session.commit()

    def _home(self, user):
        self._login(str(user.user_id))
        response = self.client.get(HOME)
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        return response.get_json()

    def _death(self, number, status, unit, registered_by, pending_flag=None):
        db.session.add(
            VaDeathRegister(
                project_id=TA,
                site_id="AZS1",
                org_unit_id=self.units[unit].org_unit_id,
                death_number=number,
                unique_id=f"HOME-DEATH-{number}",
                deceased_name="Test Case",
                deceased_sex="female",
                date_of_death=datetime.now(UTC).date(),
                registered_by=registered_by.user_id,
                source="register",
                status=status,
                pending_flag=pending_flag,
            )
        )

    def test_signed_out_is_a_json_401(self):
        response = self.client.get(HOME)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json()["code"], "unauthorized")

    def test_no_grants_is_no_blocks(self):
        self.assertEqual(self._home(self.users["nobody"]), {"roles": [], "blocks": {}, "android_apk_url": None})

    def test_android_apk_link_only_when_a_clean_https_url_is_set(self):
        url = "https://github.com/drguptavivek/DigitVA/releases/download/android-v0.2.0/app.apk"
        with patch.dict(self.app.config, {"DIGITVA_ANDROID_APK_URL": url}):
            self.assertEqual(self._home(self.users["nobody"])["android_apk_url"], url)
        with patch.dict(self.app.config, {"DIGITVA_ANDROID_APK_URL": "http://insecure.example/app.apk"}):
            self.assertIsNone(self._home(self.users["nobody"])["android_apk_url"])

    def test_hosted_apk_download_and_both_links_on_the_help_page(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(self.app.config, {"DIGITVA_ANDROID_APK_DIR": folder,
                                              "DIGITVA_ANDROID_APK_URL": ""}):
                self.assertEqual(self.client.get("/download/android").status_code, 404)
                self.assertIn("has not been published", self.client.get("/help/mobile-app").get_data(as_text=True))
            with open(f"{folder}/digitva-collect-0.2.0-arm64-v8a.apk", "wb") as apk:
                apk.write(b"PK-test")
            url = "https://github.com/drguptavivek/DigitVA/releases/latest"
            with patch.dict(self.app.config, {"DIGITVA_ANDROID_APK_DIR": folder, "DIGITVA_ANDROID_APK_URL": url}):
                res = self.client.get("/download/android")  # signed out
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.mimetype, "application/vnd.android.package-archive")
                self.assertIn("digitva-collect-0.2.0-arm64-v8a.apk", res.headers["Content-Disposition"])
                self.assertEqual(res.get_data(), b"PK-test")
                res.close()
                page = self.client.get("/help/mobile-app").get_data(as_text=True)
                self.assertIn('href="/download/android"', page)
                self.assertIn(f'href="{url}"', page)

    def test_footer_links_the_public_mobile_app_help_page(self):
        page = self.client.get("/vaauth/valogin").get_data(as_text=True)
        self.assertIn("Open Expo web app", page)
        self.assertIn('href="/help/mobile-app"', page)
        self.assertEqual(self.client.get("/help/mobile-app").status_code, 200)  # signed out
        index = self.client.get("/help").get_data(as_text=True)  # signed out
        self.assertIn('class="btn btn-primary btn-sm" href="/help/mobile-app"', index)

    def test_a_coder_gets_only_the_coder_block(self):
        body = self._home(self.users["coder_p1"])
        self.assertEqual(body["roles"], ["coder"])
        self.assertEqual(set(body["blocks"]), {"coder"})
        coder = body["blocks"]["coder"]
        self.assertEqual(set(coder), {"ready", "practice", "completed", "recodeable"})
        self.assertFalse(coder["practice"])
        self.assertTrue(all(isinstance(coder[key], int) for key in ("ready", "completed", "recodeable")))

    def test_a_coding_tester_gets_a_practice_block_without_output_counts(self):
        coder = self._home(self.users["tester_ta"])["blocks"]["coder"]
        self.assertTrue(coder["practice"])
        self.assertIn("ready", coder)
        self.assertNotIn("completed", coder)

    def test_a_reviewer_gets_available_and_completed(self):
        body = self._home(self.users["reviewer_ta"])
        self.assertEqual(set(body["blocks"]), {"reviewer"})
        self.assertEqual(set(body["blocks"]["reviewer"]), {"available", "completed"})

    def test_a_data_manager_gets_workflow_counts(self):
        body = self._home(self.users["dm_c1"])
        self.assertIn("data_manager", body["blocks"])
        self.assertEqual(
            set(body["blocks"]["data_manager"]),
            {"screening_pending", "ready_for_coding", "not_codeable"},
        )

    def test_a_project_pi_gets_a_progress_block_without_counts(self):
        body = self._home(self.users["pi_ta"])
        self.assertEqual(body["blocks"]["progress"], {"roles": ["project_pi"]})
        # project_pi on a tree project oversees: the data manager and
        # supervisor blocks come with it, as the role gates do.
        self.assertIn("data_manager", body["blocks"])
        self.assertIn("interview_supervisor", body["blocks"])

    def test_supervisor_counts_flagged_open_and_submitted_in_scope_only(self):
        reporter = self.users["interviewer_p1"]
        self._death(991001, "registered", "P1", reporter, pending_flag="duplicate")
        self._death(991002, "scheduled", "P2", reporter)
        self._death(991003, "submitted", "P1", reporter)
        # D2 is outside C1: never counted, flag included.
        self._death(991004, "registered", "D2", reporter, pending_flag="cancel")
        db.session.commit()

        block = self._home(self.users["supervisor_c1"])["blocks"]["interview_supervisor"]

        self.assertEqual(block, {"flagged": 1, "needs_decision": 1, "open": 2, "submitted": 1})

    def test_a_second_complete_interview_without_a_flag_counts_as_needs_decision_only(self):
        reporter = self.users["interviewer_p1"]
        self._death(991011, "submitted", "P1", reporter)
        db.session.flush()
        case = db.session.scalar(sa.select(VaDeathRegister).where(VaDeathRegister.death_number == 991011))
        sid = db.session.scalar(sa.select(VaSubmissions.va_sid).where(VaSubmissions.va_form_id == "AZTA01AZS101"))
        case.va_sid = sid
        db.session.add(VaWebIntakeDraft(
            project_id=TA, site_id="AZS1", death_id=case.death_id, form_id="AZTA01AZS101",
            user_id=reporter.user_id, unique_id=case.unique_id, status="superseded",
            meta={"interviewOutcome": "completed"},
        ))
        db.session.commit()

        block = self._home(self.users["supervisor_c1"])["blocks"]["interview_supervisor"]

        self.assertEqual(block, {"flagged": 0, "needs_decision": 1, "open": 0, "submitted": 1})

    def test_death_reporter_counts_own_registrations_and_those_awaiting_interview(self):
        user = self.users["nobody"]
        db.session.add(self._grant_row(user, R.death_reporter, U, "P1"))
        other = self.users["interviewer_p1"]
        self._death(991101, "registered", "P1", user)
        self._death(991102, "submitted", "P1", user)
        self._death(991103, "duplicate", "P1", user)
        self._death(991104, "registered", "P1", other)
        invalidate(user.user_id)
        db.session.commit()

        body = self._home(user)

        self.assertIn("death_reporter", body["roles"])
        self.assertEqual(
            body["blocks"]["death_reporter"], {"registered": 2, "awaiting_interview": 1}
        )

    def test_interviewer_counts_own_open_cases_in_reach(self):
        db.session.get(VaProjectMaster, TA).web_intake_mode = "both"
        user = self.users["interviewer_p1"]
        other = self.users["supervisor_c1"]
        self._death(991201, "registered", "P1", user)
        self._death(991202, "paused", "P1", user)
        self._death(991203, "submitted", "P1", user)
        # Not mine: registered by someone else and never worked on by me.
        self._death(991204, "registered", "P1", other)
        db.session.commit()

        block = self._home(user)["blocks"]["interviewer"]

        self.assertEqual(block["needing_visit"], 2)
        self.assertEqual(block["drafts_in_progress"], 0)
