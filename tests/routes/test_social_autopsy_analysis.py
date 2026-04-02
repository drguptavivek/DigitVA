from datetime import datetime, timezone

from app import db
from app.models import (
    MasFormTypes,
    VaForms,
    VaProjectMaster,
    VaResearchProjects,
    VaSites,
    VaSocialAutopsyAnalysis,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from tests.base import BaseTestCase


class TestSocialAutopsyAnalysisRoute(BaseTestCase):
    BASE_PROJECT_ID = "SAA01"
    BASE_SITE_ID = "SA01"

    @classmethod
    def _make_user(cls, email, password):
        local_part, domain = email.split("@", 1)
        scoped_email = f"{local_part}.{cls.BASE_PROJECT_ID.lower()}@{domain}"
        return super()._make_user(scoped_email, password)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        form_type = db.session.scalar(
            db.select(MasFormTypes).where(MasFormTypes.form_type_code == "WHO_2022_VA_SOCIAL")
        )
        if not form_type:
            form_type = MasFormTypes(
                form_type_code="WHO_2022_VA_SOCIAL",
                form_type_name="WHO 2022 VA Social",
                is_active=True,
            )
            db.session.add(form_type)
            db.session.flush()
        cls.form_type_id = form_type.form_type_id

        project_master = db.session.get(VaProjectMaster, cls.BASE_PROJECT_ID)
        if not project_master:
            db.session.add(
                VaProjectMaster(
                    project_id=cls.BASE_PROJECT_ID,
                    project_code=cls.BASE_PROJECT_ID,
                    project_name="Base Test Project",
                    project_nickname="BaseTest",
                    project_status=VaStatuses.active,
                    project_registered_at=datetime.now(timezone.utc),
                    project_updated_at=datetime.now(timezone.utc),
                )
            )

        research_project = db.session.get(VaResearchProjects, cls.BASE_PROJECT_ID)
        if not research_project:
            db.session.add(
                VaResearchProjects(
                    project_id=cls.BASE_PROJECT_ID,
                    project_code=cls.BASE_PROJECT_ID,
                    project_name="Base Test Project",
                    project_nickname="BaseTest",
                    project_status=VaStatuses.active,
                    project_registered_at=datetime.now(timezone.utc),
                    project_updated_at=datetime.now(timezone.utc),
                )
            )

        site = db.session.get(VaSites, cls.BASE_SITE_ID)
        if not site:
            db.session.add(
                VaSites(
                    site_id=cls.BASE_SITE_ID,
                    project_id=cls.BASE_PROJECT_ID,
                    site_name="Base Test Site",
                    site_abbr=cls.BASE_SITE_ID,
                    site_status=VaStatuses.active,
                    site_registered_at=datetime.now(timezone.utc),
                    site_updated_at=datetime.now(timezone.utc),
                )
            )
        db.session.flush()

        form = VaForms(
            form_id="SAA01SA0101",
            project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID,
            odk_form_id="SOCIAL_FORM",
            odk_project_id="1",
            form_type="WHO 2022 VA Social",
            form_type_id=cls.form_type_id,
            form_status=VaStatuses.active,
            form_registered_at=datetime.now(timezone.utc),
            form_updated_at=datetime.now(timezone.utc),
        )
        db.session.add(form)

        submission = VaSubmissions(
            va_sid="uuid:test-social-analysis-saa01sa0101",
            va_form_id=form.form_id,
            va_submission_date=datetime.now(timezone.utc),
            va_odk_updatedat=datetime.now(timezone.utc),
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name="SOCIAL-1",
            va_uniqueid_real="SOCIAL-1",
            va_uniqueid_masked="SOCIAL-1",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=45,
            va_deceased_gender="Male",
            va_data={"sa01": 1.0},
            va_summary=["fever"],
            va_catcount={},
            va_category_list=["social_autopsy"],
        )
        db.session.add(submission)
        db.session.commit()
        cls.social_sid = submission.va_sid

    def test_save_social_autopsy_analysis_creates_parent_and_options(self):
        self._login(self.base_admin_id)
        csrf_headers = self._csrf_headers()

        resp = self.client.post(
            f"/api/v1/va/{self.social_sid}/social-autopsy",
            json={
                "va_actiontype": "vademo_start_coding",
                "selected_options": [
                    {"delay_level": "delay_1_decision", "option_code": "recognition"},
                    {"delay_level": "delay_2_reaching", "option_code": "financial_barrier"},
                    {"delay_level": "delay_3_receiving", "option_code": "delay_in_referral"},
                ],
                "remark": "Three delay factors selected",
            },
            headers=csrf_headers,
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["saved"])
        self.assertEqual(payload["selection_count"], 3)

        analysis = db.session.scalar(
            db.select(VaSocialAutopsyAnalysis).where(
                VaSocialAutopsyAnalysis.va_sid == self.social_sid,
                VaSocialAutopsyAnalysis.va_saa_by == self.base_admin_user.user_id,
                VaSocialAutopsyAnalysis.va_saa_status == VaStatuses.active,
            )
        )
        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.va_saa_remark, "Three delay factors selected")
        self.assertEqual(len(analysis.selected_options), 3)
        self.assertIsNotNone(analysis.payload_version_id)

        selections = {
            (item.delay_level, item.option_code)
            for item in analysis.selected_options
        }
        self.assertIn(("delay_1_decision", "recognition"), selections)
        self.assertIn(("delay_2_reaching", "financial_barrier"), selections)
        self.assertIn(("delay_3_receiving", "delay_in_referral"), selections)

        audit = db.session.scalar(
            db.select(VaSubmissionsAuditlog).where(
                VaSubmissionsAuditlog.va_sid == self.social_sid,
                VaSubmissionsAuditlog.va_audit_action == "social autopsy analysis saved",
            )
        )
        self.assertIsNotNone(audit)

    def test_save_social_autopsy_analysis_rejected_when_project_disabled(self):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.social_autopsy_enabled = False
        db.session.commit()

        self._login(self.base_admin_id)
        csrf_headers = self._csrf_headers()

        resp = self.client.post(
            f"/api/v1/va/{self.social_sid}/social-autopsy",
            json={
                "va_actiontype": "vademo_start_coding",
                "selected_options": [
                    {"delay_level": "delay_1_decision", "option_code": "recognition"},
                    {"delay_level": "delay_2_reaching", "option_code": "financial_barrier"},
                    {"delay_level": "delay_3_receiving", "option_code": "delay_in_referral"},
                ],
            },
            headers=csrf_headers,
        )

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(
            resp.get_json()["error"],
            "Social Autopsy is disabled for this project.",
        )

    def test_none_option_is_saved_and_overrides_other_options_in_same_delay(self):
        self._login(self.base_admin_id)
        csrf_headers = self._csrf_headers()

        resp = self.client.post(
            f"/api/v1/va/{self.social_sid}/social-autopsy",
            json={
                "va_actiontype": "vademo_start_coding",
                "selected_options": [
                    {"delay_level": "delay_1_decision", "option_code": "none"},
                    {"delay_level": "delay_1_decision", "option_code": "recognition"},
                    {"delay_level": "delay_2_reaching", "option_code": "financial_barrier"},
                    {"delay_level": "delay_3_receiving", "option_code": "none"},
                ],
                "remark": "None selected for delay 1",
            },
            headers=csrf_headers,
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload["saved"])
        self.assertEqual(payload["selection_count"], 3)

        analysis = db.session.scalar(
            db.select(VaSocialAutopsyAnalysis).where(
                VaSocialAutopsyAnalysis.va_sid == self.social_sid,
                VaSocialAutopsyAnalysis.va_saa_by == self.base_admin_user.user_id,
                VaSocialAutopsyAnalysis.va_saa_status == VaStatuses.active,
            )
        )
        self.assertIsNotNone(analysis)

        selections = {
            (item.delay_level, item.option_code)
            for item in analysis.selected_options
        }
        self.assertIn(("delay_1_decision", "none"), selections)
        self.assertNotIn(("delay_1_decision", "recognition"), selections)
        self.assertIn(("delay_2_reaching", "financial_barrier"), selections)
        self.assertIn(("delay_3_receiving", "none"), selections)

    def test_save_after_payload_change_creates_new_current_payload_row(self):
        self._login(self.base_admin_id)
        csrf_headers = self._csrf_headers()
        payload = {
            "va_actiontype": "vademo_start_coding",
            "selected_options": [
                {"delay_level": "delay_1_decision", "option_code": "recognition"},
                {"delay_level": "delay_2_reaching", "option_code": "financial_barrier"},
                {"delay_level": "delay_3_receiving", "option_code": "delay_in_referral"},
            ],
            "remark": "payload one",
        }

        resp = self.client.post(
            f"/api/v1/va/{self.social_sid}/social-autopsy",
            json=payload,
            headers=csrf_headers,
        )
        self.assertEqual(resp.status_code, 200)

        submission = db.session.get(VaSubmissions, self.social_sid)
        first_payload_version_id = submission.active_payload_version_id

        submission.va_data = {"sa01": 2.0}
        submission.va_odk_updatedat = datetime.now(timezone.utc)
        new_payload_version = ensure_active_payload_version(
            submission,
            payload_data=submission.va_data,
            source_updated_at=submission.va_odk_updatedat,
            created_by_role="vasystem",
        )
        db.session.commit()

        resp = self.client.post(
            f"/api/v1/va/{self.social_sid}/social-autopsy",
            json={**payload, "remark": "payload two"},
            headers=csrf_headers,
        )
        self.assertEqual(resp.status_code, 200)

        rows = db.session.scalars(
            db.select(VaSocialAutopsyAnalysis)
            .where(
                VaSocialAutopsyAnalysis.va_sid == self.social_sid,
                VaSocialAutopsyAnalysis.va_saa_by == self.base_admin_user.user_id,
            )
            .order_by(VaSocialAutopsyAnalysis.va_saa_createdat.asc())
        ).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].payload_version_id, first_payload_version_id)
        self.assertEqual(rows[0].va_saa_status, VaStatuses.deactive)
        self.assertEqual(rows[1].payload_version_id, new_payload_version.payload_version_id)
        self.assertEqual(rows[1].va_saa_status, VaStatuses.active)

    def test_save_rejects_blank_or_incomplete_submission(self):
        self._login(self.base_admin_id)
        csrf_headers = self._csrf_headers()

        resp = self.client.post(
            f"/api/v1/va/{self.social_sid}/social-autopsy",
            json={
                "va_actiontype": "vademo_start_coding",
                "selected_options": [],
                "remark": "",
            },
            headers=csrf_headers,
        )
        self.assertEqual(resp.status_code, 400)
        payload = resp.get_json()
        self.assertIn("Please answer every Social Autopsy delay question", payload["error"])
        self.assertEqual(
            set(payload["missing_delay_levels"]),
            {"delay_1_decision", "delay_2_reaching", "delay_3_receiving"},
        )
