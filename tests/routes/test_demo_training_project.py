from datetime import datetime, timedelta, timezone

from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaFinalAssessments,
    VaFinalCodAuthority,
    VaForms,
    VaInitialAssessments,
    VaNarrativeAssessment,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSocialAutopsyAnalysis,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
    VaUsers,
)
from tests.base import BaseTestCase


class TestDemoTrainingProjectRoute(BaseTestCase):
    DEMO_PROJECT_ID = "TRN001"
    DEMO_SITE_ID = "T001"
    DEMO_FORM_ID = "TRN001T00101"
    DEMO_SID = "uuid:demo-training-project"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)

        db.session.add(
            VaProjectMaster(
                project_id=cls.DEMO_PROJECT_ID,
                project_code=cls.DEMO_PROJECT_ID,
                project_name="Training Project",
                project_nickname="Training",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
                demo_training_enabled=True,
                demo_retention_minutes=10,
            )
        )
        db.session.add(
            VaResearchProjects(
                project_id=cls.DEMO_PROJECT_ID,
                project_code=cls.DEMO_PROJECT_ID,
                project_name="Training Project",
                project_nickname="Training",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.add(
            VaSiteMaster(
                site_id=cls.DEMO_SITE_ID,
                site_name="Training Site",
                site_abbr=cls.DEMO_SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.add(
            VaSites(
                site_id=cls.DEMO_SITE_ID,
                project_id=cls.DEMO_PROJECT_ID,
                site_name="Training Site",
                site_abbr=cls.DEMO_SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaProjectSites(
                project_id=cls.DEMO_PROJECT_ID,
                site_id=cls.DEMO_SITE_ID,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
        )
        db.session.add(
            VaForms(
                form_id=cls.DEMO_FORM_ID,
                project_id=cls.DEMO_PROJECT_ID,
                site_id=cls.DEMO_SITE_ID,
                odk_form_id="TRAINING_FORM",
                odk_project_id="12",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.add(
            VaSubmissions(
                va_sid=cls.DEMO_SID,
                va_form_id=cls.DEMO_FORM_ID,
                va_submission_date=now,
                va_odk_updatedat=now,
                va_data_collector="trainer",
                va_odk_reviewstate=None,
                va_instance_name="TRAINING-1",
                va_uniqueid_real="TRAINING-1",
                va_uniqueid_masked="TRAINING-1",
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=34,
                va_deceased_gender="Female",
                va_summary=[],
                va_catcount={},
                va_category_list=["vademographicdetails", "vacodassessment"],
            )
        )
        db.session.flush()
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=cls.DEMO_SID,
                workflow_state="ready_for_coding",
                workflow_reason="test_seed",
                workflow_updated_by_role="vasystem",
            )
        )
        cls.demo_plain_user = VaUsers(
            name="demo trainee",
            email="demo.trainee@test.local",
            vacode_language=["English"],
            permission={},
            landing_page="coder",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status=VaStatuses.active,
        )
        cls.demo_plain_user.set_password("DemoTrainee123")
        db.session.add(cls.demo_plain_user)
        db.session.commit()
        cls.demo_plain_user_id = str(cls.demo_plain_user.user_id)

    def _active_allocation_sid(self):
        return db.session.scalar(
            db.select(VaAllocations.va_sid).where(
                VaAllocations.va_allocated_to == self.base_coder_user.user_id,
                VaAllocations.va_allocation_for == VaAllocation.coding,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        )

    def setUp(self):
        super().setUp()
        db.session.execute(
            db.update(VaAllocations)
            .where(VaAllocations.va_allocation_status == VaStatuses.active)
            .values(va_allocation_status=VaStatuses.deactive)
        )
        db.session.execute(
            db.delete(VaFinalCodAuthority).where(VaFinalCodAuthority.va_sid == self.DEMO_SID)
        )
        db.session.execute(
            db.delete(VaFinalAssessments).where(VaFinalAssessments.va_sid == self.DEMO_SID)
        )
        db.session.execute(
            db.delete(VaInitialAssessments).where(VaInitialAssessments.va_sid == self.DEMO_SID)
        )
        db.session.execute(
            db.delete(VaNarrativeAssessment).where(VaNarrativeAssessment.va_sid == self.DEMO_SID)
        )
        db.session.execute(
            db.delete(VaSocialAutopsyAnalysis).where(VaSocialAutopsyAnalysis.va_sid == self.DEMO_SID)
        )
        db.session.execute(
            db.update(VaSubmissionWorkflow)
            .where(VaSubmissionWorkflow.va_sid == self.DEMO_SID)
            .values(
                workflow_state="ready_for_coding",
                workflow_reason="test_seed",
                workflow_updated_by_role="vasystem",
            )
        )
        db.session.commit()

    def test_coder_can_start_demo_project_without_specific_project_grant(self):
        self._login(self.base_coder_id)

        response = self.client.post(f"/coding/start?project_id={self.DEMO_PROJECT_ID}", headers=self._csrf_headers())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._active_allocation_sid(), self.DEMO_SID)

    def test_plain_user_can_start_demo_project_without_any_grant(self):
        self._login(self.demo_plain_user_id)

        response = self.client.post(f"/coding/start?project_id={self.DEMO_PROJECT_ID}", headers=self._csrf_headers())

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.DEMO_SID, response.get_data(as_text=True))

    def test_plain_user_dashboard_shows_demo_coding_shortcut_and_message(self):
        self._login(self.demo_plain_user_id)

        response = self.client.get("/coding/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("DEMO-CODING", html)
        self.assertIn("These are demo-training forms.", html)
        self.assertIn(self.DEMO_PROJECT_ID, html)

    def test_plain_user_sees_va_coding_nav_link_when_demo_project_exists(self):
        self._login(self.demo_plain_user_id)

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('href="/coding/"', html)
        self.assertIn("VA Coding", html)

    def test_plain_user_cannot_start_non_demo_project(self):
        self._login(self.demo_plain_user_id)

        response = self.client.post(f"/coding/start?project_id={self.BASE_PROJECT_ID}", headers=self._csrf_headers())

        self.assertEqual(response.status_code, 403)

    def test_demo_project_final_cod_expires_after_project_retention_window(self):
        self._login(self.base_coder_id)
        start_response = self.client.post(
            f"/coding/start?project_id={self.DEMO_PROJECT_ID}",
            headers=self._csrf_headers(),
            follow_redirects=True,
        )
        self.assertEqual(start_response.status_code, 200)
        self.assertEqual(self._active_allocation_sid(), self.DEMO_SID)

        before = datetime.now(timezone.utc)
        response = self.client.post(
            (
                f"/vaform/{self.DEMO_SID}/vafinalasses"
                "?action=vacode&actiontype=vademo_start_coding"
            ),
            data={
                "va_conclusive_cod": "I24-Other acute ischaemic heart diseases",
                "va_finassess_remark": "training final cod",
                "va_save_assessment": "1",
            },
            headers={
                **self._csrf_headers(),
                "HX-Request": "true",
            },
        )
        self.assertEqual(response.status_code, 200)

        final_row = db.session.scalar(
            db.select(VaFinalAssessments).where(
                VaFinalAssessments.va_sid == self.DEMO_SID,
                VaFinalAssessments.va_finassess_by == self.base_coder_user.user_id,
            )
        )
        self.assertIsNotNone(final_row)
        self.assertIsNotNone(final_row.demo_expires_at)
        expires_at = final_row.demo_expires_at.replace(tzinfo=timezone.utc)
        self.assertGreaterEqual(
            expires_at,
            before + timedelta(minutes=9),
        )
        self.assertLessEqual(
            expires_at,
            before + timedelta(minutes=11),
        )
