import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectSites,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
    VaUserAccessGrants,
    VaUsers,
)
from tests.base import BaseTestCase


class DataManagerDashboardTests(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}01"
    SID = "uuid:data-manager-dashboard"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        db.session.add(
            VaResearchProjects(
                project_id=cls.BASE_PROJECT_ID,
                project_code=cls.BASE_PROJECT_ID,
                project_name="Base Test Project",
                project_nickname="BaseTest",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="Base Test Site",
                site_abbr=cls.BASE_SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="DM_DASHBOARD_FORM",
                odk_project_id="11",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSubmissions(
                va_sid=cls.SID,
                va_form_id=cls.FORM_ID,
                va_submission_date=now,
                va_odk_updatedat=now,
                va_odk_reviewstate="hasIssues",
                va_sync_issue_code="missing_in_odk",
                va_sync_issue_detail="test issue",
                va_sync_issue_updated_at=now,
                va_data_collector="Collector",
                va_instance_name=cls.SID,
                va_uniqueid_real=cls.SID,
                va_uniqueid_masked="masked-id",
                va_consent="no",
                va_narration_language="English",
                va_deceased_age=42,
                va_deceased_gender="male",
                va_data={"sid": cls.SID},
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.flush()
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=cls.SID,
                workflow_state="ready_for_coding",
                workflow_reason="test_seed",
                workflow_updated_by_role="vasystem",
            )
        )
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.app.extensions["celery"] = object()
        suffix = uuid.uuid4().hex[:8]
        self.dm_user = VaUsers(
            user_id=uuid.uuid4(),
            name=f"dm.{suffix}",
            email=f"dm.{suffix}@example.com",
            vacode_language=["English"],
            permission={},
            landing_page="data_manager",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status=VaStatuses.active,
        )
        self.dm_user.set_password("DataManager123")
        db.session.add(self.dm_user)
        db.session.flush()
        project_site_id = db.session.scalar(
            db.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == self.BASE_PROJECT_ID,
                VaProjectSites.site_id == self.BASE_SITE_ID,
            )
        )
        db.session.add(
            VaUserAccessGrants(
                user_id=self.dm_user.user_id,
                role=VaAccessRoles.data_manager,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site_id,
                notes="dm dashboard grant",
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()
        self.dm_user_id = str(self.dm_user.user_id)

    def test_dashboard_shows_odk_state_and_sync_issue(self):
        self._login(self.dm_user_id)

        response = self.client.get("/vadashboard/data_manager")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Has Issues", response.data)
        self.assertIn(b"Missing In ODK", response.data)
        self.assertIn(b"Sync Selected Form", response.data)
        self.assertIn(b"Refresh", response.data)

    def test_data_manager_can_trigger_scoped_form_sync(self):
        self._login(self.dm_user_id)
        headers = self._csrf_headers()

        with patch(
            "app.tasks.sync_tasks.run_single_form_sync.delay"
        ) as mocked_delay:
            mocked_delay.return_value.id = "task-form-sync"

            response = self.client.post(
                f"/vadashboard/data-manager/api/forms/{self.FORM_ID}/sync",
                headers=headers,
            )

        self.assertEqual(response.status_code, 202)
        mocked_delay.assert_called_once()

    def test_data_manager_can_trigger_scoped_submission_sync(self):
        self._login(self.dm_user_id)
        headers = self._csrf_headers()

        with patch(
            "app.tasks.sync_tasks.run_single_submission_sync.delay"
        ) as mocked_delay:
            mocked_delay.return_value.id = "task-submission-sync"

            response = self.client.post(
                f"/vadashboard/data-manager/api/submissions/{self.SID}/sync",
                headers=headers,
            )

        self.assertEqual(response.status_code, 202)
        mocked_delay.assert_called_once()
