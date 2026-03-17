import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app import db
from app.models import (
    MapProjectSiteOdk,
    MapProjectOdk,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    MasOdkConnections,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissionAttachments,
    VaSubmissions,
    VaSyncRun,
    VaUserAccessGrants,
    VaUsers,
)
from tests.base import BaseTestCase


class DataManagerDashboardTests(BaseTestCase):
    FORM_ID = f"{BaseTestCase.BASE_PROJECT_ID}{BaseTestCase.BASE_SITE_ID}01"
    SID = "uuid:data-manager-dashboard"
    OUT_PROJECT_ID = "DMOUT1"
    OUT_SITE_ID = "DMO1"
    OUT_FORM_ID = "DMOUT1DMO101"
    OUT_SID = "uuid:data-manager-out-of-scope"

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
            MapProjectSiteOdk(
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_project_id=11,
                odk_form_id="DM_DASHBOARD_FORM",
                last_synced_at=now,
            )
        )
        odk_connection = MasOdkConnections(
            connection_name="Data Manager Test ODK",
            base_url="https://minerva.example.org",
            username_enc="enc-user",
            username_salt="1234567890abcdef1234567890abcdef",
            password_enc="enc-pass",
            password_salt="abcdef1234567890abcdef1234567890",
            status=VaStatuses.active,
        )
        db.session.add(odk_connection)
        db.session.flush()
        db.session.add(
            MapProjectOdk(
                project_id=cls.BASE_PROJECT_ID,
                connection_id=odk_connection.connection_id,
            )
        )
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
                va_odk_reviewcomments=[
                    {"body": "Needs correction from field team."},
                    {"body": "Narrative answer is incomplete."},
                ],
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
        db.session.add_all(
            [
                VaSubmissionAttachments(
                    va_sid=cls.SID,
                    filename="narrative1.jpg",
                    local_path="/tmp/narrative1.jpg",
                    mime_type="image/jpeg",
                    etag="etag-1",
                    exists_on_odk=True,
                    last_downloaded_at=now,
                ),
                VaSubmissionAttachments(
                    va_sid=cls.SID,
                    filename="audio1.mp3",
                    local_path="/tmp/audio1.mp3",
                    mime_type="audio/mpeg",
                    etag="etag-2",
                    exists_on_odk=True,
                    last_downloaded_at=now,
                ),
            ]
        )
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=cls.SID,
                workflow_state="not_codeable_by_coder",
                workflow_reason="test_seed",
                workflow_updated_by_role="vasystem",
            )
        )
        db.session.add(
            VaProjectMaster(
                project_id=cls.OUT_PROJECT_ID,
                project_code=cls.OUT_PROJECT_ID,
                project_name="Out Of Scope Project",
                project_nickname="OutScope",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.add(
            VaResearchProjects(
                project_id=cls.OUT_PROJECT_ID,
                project_code=cls.OUT_PROJECT_ID,
                project_name="Out Of Scope Project",
                project_nickname="OutScope",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSites(
                site_id=cls.OUT_SITE_ID,
                project_id=cls.OUT_PROJECT_ID,
                site_name="Out Of Scope Site",
                site_abbr=cls.OUT_SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSiteMaster(
                site_id=cls.OUT_SITE_ID,
                site_name="Out Of Scope Site",
                site_abbr=cls.OUT_SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaProjectSites(
                project_id=cls.OUT_PROJECT_ID,
                site_id=cls.OUT_SITE_ID,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
        )
        db.session.add(
            VaForms(
                form_id=cls.OUT_FORM_ID,
                project_id=cls.OUT_PROJECT_ID,
                site_id=cls.OUT_SITE_ID,
                odk_form_id="DM_OUT_FORM",
                odk_project_id="12",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSubmissions(
                va_sid=cls.OUT_SID,
                va_form_id=cls.OUT_FORM_ID,
                va_submission_date=now,
                va_odk_updatedat=now,
                va_odk_reviewstate="approved",
                va_data_collector="Collector",
                va_instance_name=cls.OUT_SID,
                va_uniqueid_real=cls.OUT_SID,
                va_uniqueid_masked="masked-out",
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=41,
                va_deceased_gender="female",
                va_data={"sid": cls.OUT_SID},
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.flush()
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=cls.OUT_SID,
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
        self.assertIn(b"ODK - Has Issues", response.data)
        self.assertIn(b"SmartVA Missing", response.data)
        self.assertIn(b"SmartVA", response.data)
        self.assertIn(b"ODK Sync", response.data)
        self.assertIn(b"Missing", response.data)
        self.assertIn(b"Flagged Not Codeable", response.data)
        self.assertIn(b"id=\"dm-view-flagged-btn\"", response.data)
        self.assertIn(b"id=\"dm-view-odk-issues-btn\"", response.data)
        self.assertIn(b"id=\"dm-view-smartva-missing-btn\"", response.data)
        self.assertIn(b"Edit", response.data)
        self.assertIn(b"Table Columns", response.data)
        self.assertIn(b"Optional Columns", response.data)
        self.assertIn(b"Project", response.data)
        self.assertIn(b"Data Collector", response.data)
        self.assertIn(b"Flagged At", response.data)
        self.assertIn(b"Needs correction from field team.", response.data)
        self.assertIn(b"Narrative answer is incomplete.", response.data)
        self.assertIn(b"Missing In ODK", response.data)
        self.assertIn(b"Sync Forms For a Project and Site", response.data)
        self.assertIn(b"Open Sync Modal", response.data)
        self.assertIn(b"Refresh", response.data)
        self.assertIn(b"Clear Filters", response.data)
        self.assertIn(b"All workflow states", response.data)
        self.assertIn(b"Not Codeable By Coder", response.data)
        self.assertIn(b"All ODK statuses", response.data)
        self.assertIn(b"All SmartVA statuses", response.data)
        self.assertIn(b"All ODK sync statuses", response.data)
        self.assertIn(b"Submitted From", response.data)
        self.assertIn(b"Submitted To", response.data)
        self.assertIn(b"ODK Sync", response.data)

    @patch("app.utils.va_odk_delta_count")
    @patch("app.utils.va_odk_fetch_instance_ids")
    @patch("app.utils.va_odk.va_odk_01_clientsetup.va_odk_clientsetup")
    def test_data_manager_can_load_sync_preview(
        self,
        mocked_clientsetup,
        mocked_fetch_instance_ids,
        mocked_delta_count,
    ):
        self._login(self.dm_user_id)
        headers = self._csrf_headers()
        mocked_clientsetup.return_value = object()
        mocked_fetch_instance_ids.return_value = ["uuid:data-manager-dashboard", "uuid:new-remote"]
        mocked_delta_count.return_value = 3

        response = self.client.post(
            "/vadashboard/data-manager/api/sync/preview",
            headers=headers,
            json={"project_ids": [self.BASE_PROJECT_ID], "site_ids": [self.BASE_SITE_ID]},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["totals"]["forms"], 1)
        self.assertEqual(payload["totals"]["new_fetch_candidates"], 2)
        self.assertEqual(payload["totals"]["missing_in_odk_flags"], 1)
        self.assertEqual(payload["totals"]["updated_candidates"], 3)
        self.assertEqual(payload["forms"][0]["preview_status"], "ok")

    def test_data_manager_can_load_recent_sync_runs(self):
        self._login(self.dm_user_id)
        run = VaSyncRun(
            triggered_by="data-manager",
            triggered_user_id=uuid.UUID(self.dm_user_id),
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            status="success",
            records_added=2,
            records_updated=1,
            progress_log='[{"ts":"2026-03-18T00:00:00+00:00","msg":"[BASE01BS0101] force-resync started"}]',
        )
        db.session.add(run)
        db.session.commit()

        response = self.client.get("/vadashboard/data-manager/api/sync/runs")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload["runs"]), 1)
        self.assertEqual(payload["runs"][0]["target"], self.FORM_ID)
        self.assertEqual(payload["runs"][0]["records_added"], 2)

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

    @patch("app.routes.va_main.va_odk_clientsetup")
    def test_data_manager_odk_edit_redirect_uses_scoped_submission_mapping(
        self, mocked_clientsetup
    ):
        self._login(self.dm_user_id)
        mocked_clientsetup.return_value = SimpleNamespace(
            session=SimpleNamespace(
                get=lambda *args, **kwargs: SimpleNamespace(
                    headers={
                        "Location": (
                            "https://minerva.example.org/-/edit/token123"
                            "?instance_id=uuid:data-manager-dashboard"
                        )
                    }
                )
            )
        )

        response = self.client.get(
            f"/vadashboard/data-manager/submissions/{self.SID}/odk-edit",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"],
            "https://minerva.example.org/-/edit/token123?instance_id=uuid:data-manager-dashboard",
        )

    def test_single_form_task_revalidates_scope_in_worker(self):
        from app.tasks.sync_tasks import run_single_form_sync

        with patch("app.tasks.sync_tasks._get_single_form_odk_client") as mocked_client:
            with self.assertRaises(PermissionError):
                run_single_form_sync.run(
                    form_id=self.OUT_FORM_ID,
                    triggered_by="manual",
                    user_id=self.dm_user_id,
                )

        mocked_client.assert_not_called()

    def test_single_submission_task_revalidates_scope_in_worker(self):
        from app.tasks.sync_tasks import run_single_submission_sync

        with patch("app.tasks.sync_tasks._get_single_form_odk_client") as mocked_client:
            with self.assertRaises(PermissionError):
                run_single_submission_sync.run(
                    va_sid=self.OUT_SID,
                    triggered_by="manual",
                    user_id=self.dm_user_id,
                )

        mocked_client.assert_not_called()
