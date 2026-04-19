import uuid
import re
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa
from app import cache, db
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
    VaSubmissionUpstreamChange,
    VaSubmissionsAuditlog,
    VaSubmissions,
    VaSyncRun,
    VaUserAccessGrants,
    VaUsers,
    VaFinalAssessments,
    VaSmartvaResults,
    VaSubmissionWorkflow,
)
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_READY_FOR_CODING,
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
                workflow_state=WORKFLOW_NOT_CODEABLE_BY_CODER,
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
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.flush()
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=cls.OUT_SID,
                workflow_state=WORKFLOW_READY_FOR_CODING,
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

    @patch(
        "app.routes.data_management.get_dm_kpi_from_mv",
        return_value={
            "total_submissions": 1,
            "flagged_submissions": 1,
            "odk_has_issues_submissions": 1,
            "smartva_missing_submissions": 1,
        },
    )
    def test_dashboard_shows_odk_state_and_sync_issue(self, _mocked_kpi):
        self._login(self.dm_user_id)

        response = self.client.get("/data-management/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Has Issues", response.data)
        self.assertIn(b"SmartVA Missing", response.data)
        self.assertIn(b"Needs Field Attention", response.data)
        self.assertIn(b"Not Codeable (DM)", response.data)
        self.assertIn(b"Refresh Dashboard", response.data)
        self.assertIn(b"Submissions by Project / Site", response.data)
        self.assertIn(b"Age Groups", response.data)
        self.assertIn(b"Sex Distribution", response.data)
        self.assertIn(b"dm-project-site-submissions-chart", response.data)

    @patch(
        "app.routes.data_management.get_dm_kpi_from_mv",
        return_value={
            "total_submissions": 1,
            "flagged_submissions": 1,
            "odk_has_issues_submissions": 1,
            "smartva_missing_submissions": 1,
        },
    )
    @patch(
        "app.routes.data_management.va_render_serialisedates",
        side_effect=AssertionError(
            "dashboard should not serialise preloaded submission rows"
        ),
        create=True,
    )
    @patch(
        "app.routes.data_management.dm_scoped_forms",
        side_effect=AssertionError(
            "dashboard should not preload scoped forms for the infinite grid"
        ),
        create=True,
    )
    def test_dashboard_does_not_preload_submission_table_data(
        self,
        _mocked_scoped_forms,
        _mocked_render_rows,
        _mocked_kpi,
    ):
        self._login(self.dm_user_id)

        response = self.client.get("/data-management/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"id=\"dm-table\"", response.data)

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
            "/data-management/api/sync/preview",
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

        response = self.client.get("/api/v1/data-management/sync/runs")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload["runs"]), 1)
        self.assertEqual(payload["runs"][0]["target"], self.FORM_ID)
        self.assertEqual(payload["runs"][0]["records_added"], 2)

    def test_data_manager_recent_sync_runs_resolve_submission_sid_to_form_target(self):
        self._login(self.dm_user_id)
        run = VaSyncRun(
            triggered_by="data-manager",
            triggered_user_id=uuid.UUID(self.dm_user_id),
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            status="error",
            records_added=0,
            records_updated=0,
            progress_log=(
                f'[{{"ts":"2026-03-18T00:00:00+00:00","msg":"[{self.SID}] '
                'refreshed from ODK: +0 added, 0 updated"}}]'
            ),
        )
        db.session.add(run)
        db.session.commit()

        response = self.client.get("/api/v1/data-management/sync/runs")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(len(payload["runs"]), 1)
        self.assertEqual(payload["runs"][0]["target"], self.FORM_ID)

    def test_data_manager_can_load_project_site_submission_stats(self):
        self._login(self.dm_user_id)

        response = self.client.get("/data-management/api/project-site-submissions")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["stats"])
        self.assertEqual(payload["stats"][0]["project_id"], self.BASE_PROJECT_ID)
        self.assertEqual(payload["stats"][0]["site_id"], self.BASE_SITE_ID)
        self.assertIn("total_submissions", payload["stats"][0])
        self.assertIn("this_week_submissions", payload["stats"][0])
        self.assertIn("today_submissions", payload["stats"][0])

    def test_coded_submissions_api_includes_coded_on_and_coded_by(self):
        self._login(self.dm_user_id)
        now = datetime.now(timezone.utc)
        coded_sid = f"uuid:coded-{uuid.uuid4().hex[:8]}"
        db.session.add(
            VaSubmissions(
                va_sid=coded_sid,
                va_form_id=self.FORM_ID,
                va_submission_date=now,
                va_odk_updatedat=now,
                va_odk_reviewstate="approved",
                va_data_collector="Collector",
                va_instance_name=coded_sid,
                va_uniqueid_real=coded_sid,
                va_uniqueid_masked="coded-masked-id",
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=50,
                va_deceased_gender="male",
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.flush()
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=coded_sid,
                workflow_state=WORKFLOW_CODER_FINALIZED,
                workflow_reason="test_seed",
                workflow_updated_by_role="vasystem",
            )
        )
        db.session.add(
            VaFinalAssessments(
                va_sid=coded_sid,
                va_finassess_by=uuid.UUID(self.dm_user_id),
                va_conclusive_cod="A41",
                va_finassess_status=VaStatuses.active,
                va_finassess_createdat=now,
                va_finassess_updatedat=now,
            )
        )
        db.session.commit()

        response = self.client.get("/api/v1/data-management/submissions?workflow=coded")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        coded_row = next(row for row in payload["data"] if row["va_sid"] == coded_sid)
        self.assertEqual(coded_row["coded_by"], self.dm_user.name)
        self.assertRegex(coded_row["coded_on"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")

    @patch(
        "app.routes.api.data_management.get_dm_kpi_from_mv",
        return_value={
            "total_submissions": 1,
            "coded_submissions": 0,
            "pending_submissions": 1,
            "flagged_submissions": 0,
            "odk_has_issues_submissions": 0,
            "smartva_missing_submissions": 0,
            "revoked_submissions": 0,
            "consent_refused_submissions": 0,
            "smartva_pending_submissions": 0,
            "workflow_counts": {},
        },
    )
    def test_data_manager_kpi_endpoint_uses_cache(self, mocked_get_kpi):
        self._login(self.dm_user_id)
        cache.clear()

        first = self.client.get("/api/v1/data-management/kpi")
        second = self.client.get("/api/v1/data-management/kpi")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(mocked_get_kpi.call_count, 1)

    def test_upstream_change_details_endpoint_returns_changed_fields(self):
        self._login(self.dm_user_id)
        now = datetime.now(timezone.utc)
        db.session.add(
            VaSubmissionUpstreamChange(
                va_sid=self.SID,
                workflow_state_before="coder_finalized",
                previous_va_data={
                    "Id10120": 10.0,
                    "updatedAt": "2026-03-01T00:00:00Z",
                    "OdkReviewComments": None,
                },
                incoming_va_data={
                    "Id10120": "12",
                    "updatedAt": "2026-03-02T00:00:00Z",
                    "OdkReviewComments": [],
                },
                detected_odk_updatedat=now,
                resolution_status="pending",
            )
        )
        db.session.commit()

        response = self.client.get(
            f"/api/v1/data-management/submissions/{self.SID}/upstream-change-details"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["changed_field_count"], 1)
        self.assertTrue(payload["has_substantive_changes"])
        self.assertEqual(payload["changed_fields"][0]["field_id"], "Id10120")
        self.assertEqual(payload["changed_fields"][0]["previous_value_display"], "10")
        self.assertEqual(payload["changed_fields"][0]["current_value_display"], "12")
        self.assertEqual(payload["non_substantive_change_count"], 1)
        self.assertEqual(
            [row["field_id"] for row in payload["non_substantive_changed_fields"]],
            ["updatedAt"],
        )

    def test_upstream_change_details_endpoint_ignores_metadata_only_churn(self):
        self._login(self.dm_user_id)
        now = datetime.now(timezone.utc)
        db.session.add(
            VaSubmissionUpstreamChange(
                va_sid=self.SID,
                workflow_state_before="coder_finalized",
                previous_va_data={
                    "Id10120": 10.0,
                    "updatedAt": "2026-03-01T00:00:00Z",
                    "OdkReviewComments": None,
                },
                incoming_va_data={
                    "Id10120": "10",
                    "updatedAt": "2026-03-02T00:00:00Z",
                    "OdkReviewComments": [],
                },
                detected_odk_updatedat=now,
                resolution_status="pending",
            )
        )
        db.session.commit()

        response = self.client.get(
            f"/api/v1/data-management/submissions/{self.SID}/upstream-change-details"
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["changed_field_count"], 0)
        self.assertFalse(payload["has_substantive_changes"])
        self.assertEqual(payload["changed_fields"], [])
        self.assertEqual(payload["formatting_only_change_count"], 1)
        self.assertEqual(
            [row["field_id"] for row in payload["formatting_only_changed_fields"]],
            ["Id10120"],
        )
        self.assertEqual(payload["non_substantive_change_count"], 1)
        self.assertEqual(
            [row["field_id"] for row in payload["non_substantive_changed_fields"]],
            ["updatedAt"],
        )

    @patch("app.services.coder_workflow_service.is_upstream_recode", return_value=True)
    def test_data_manager_view_includes_inline_upstream_change_panel(self, _mocked_upstream):
        self._login(self.dm_user_id)

        response = self.client.get(f"/data-management/view/{self.SID}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Changed Fields", response.data)
        self.assertIn(b"dm-upstream-change-panel", response.data)
        self.assertIn(b"/api/v1/data-management/submissions/", response.data)

    def test_data_manager_can_trigger_scoped_form_sync(self):
        self._login(self.dm_user_id)
        headers = self._csrf_headers()

        with patch(
            "app.tasks.sync_tasks.run_single_form_sync.delay"
        ) as mocked_delay:
            mocked_delay.return_value.id = "task-form-sync"

            response = self.client.post(
                f"/data-management/api/forms/{self.FORM_ID}/sync",
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
                f"/data-management/api/submissions/{self.SID}/sync",
                headers=headers,
            )

        self.assertEqual(response.status_code, 202)
        mocked_delay.assert_called_once()
        audit_row = db.session.scalar(
            sa.select(VaSubmissionsAuditlog)
            .where(VaSubmissionsAuditlog.va_sid == self.SID)
            .order_by(VaSubmissionsAuditlog.va_audit_createdat.desc())
        )
        self.assertIsNotNone(audit_row)
        self.assertEqual(
            audit_row.va_audit_action,
            "data_manager_requested_submission_refresh",
        )
        self.assertEqual(audit_row.va_audit_byrole, "data_manager")

    @patch("app.routes.va_form.sync_not_codeable_review_state")
    @patch("app.routes.va_form.get_category_rendering_service")
    def test_dm_not_codeable_posts_odk_review_state_update(
        self,
        mocked_category_service,
        mocked_sync_not_codeable,
    ):
        self._login(self.dm_user_id)
        headers = self._csrf_headers()
        workflow = db.session.scalar(
            sa.select(VaSubmissionWorkflow).where(
                VaSubmissionWorkflow.va_sid == self.SID
            )
        )
        workflow.workflow_state = WORKFLOW_READY_FOR_CODING
        db.session.commit()

        mocked_sync_not_codeable.return_value = SimpleNamespace(
            success=True,
            review_state="hasIssues",
            comment="DigitVA data manager marked this submission as not codeable.",
            error_message=None,
        )
        mocked_category_service.return_value = SimpleNamespace(
            is_category_enabled=lambda *args, **kwargs: True,
            get_category_neighbours=lambda *args, **kwargs: (None, None),
            get_category_config=lambda *args, **kwargs: {},
        )

        response = self.client.post(
            f"/vaform/{self.SID}/vadmtriage?action=vadata&actiontype=vaview",
            data={
                "va_dmreview_reason": "duplicate_submission",
                "va_dmreview_other": "Duplicate in site register.",
                "va_mark_not_codeable": "1",
            },
            headers={**headers, "HX-Request": "true"},
        )

        self.assertEqual(response.status_code, 200)
        mocked_sync_not_codeable.assert_called_once_with(
            self.SID,
            "duplicate_submission",
            "Duplicate in site register.",
            actor_role="data_manager",
        )
        audit_row = db.session.scalar(
            sa.select(VaSubmissionsAuditlog)
            .where(VaSubmissionsAuditlog.va_sid == self.SID)
            .where(
                VaSubmissionsAuditlog.va_audit_action
                == "odk review state set to hasIssues"
            )
            .order_by(VaSubmissionsAuditlog.va_audit_createdat.desc())
        )
        self.assertIsNotNone(audit_row)
        self.assertEqual(audit_row.va_audit_byrole, "data_manager")

    @patch("app.routes.va_form.get_category_rendering_service")
    def test_data_manager_triage_partial_shows_smartva_results_card(
        self,
        mocked_category_service,
    ):
        self._login(self.dm_user_id)
        mocked_category_service.return_value = SimpleNamespace(
            is_category_enabled=lambda *args, **kwargs: True,
            get_category_neighbours=lambda *args, **kwargs: (None, None),
            get_category_config=lambda *args, **kwargs: {},
        )
        now = datetime.now(timezone.utc)
        db.session.add(
            VaSmartvaResults(
                va_sid=self.SID,
                va_smartva_status=VaStatuses.active,
                va_smartva_outcome=VaSmartvaResults.OUTCOME_SUCCESS,
                va_smartva_cause1="Acute myocardial infarction",
                va_smartva_likelihood1="0.78",
                va_smartva_updatedat=now,
            )
        )
        db.session.commit()

        response = self.client.get(
            f"/vaform/{self.SID}/vadmtriage?action=vadata&actiontype=vaview",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"SmartVA Results", response.data)
        self.assertIn(b"Acute myocardial infarction", response.data)
        self.assertIn(b"Secondary Cause", response.data)

    @patch("app.routes.va_form.get_category_rendering_service")
    def test_data_manager_triage_reconciles_stale_smartva_pending_to_ready_for_coding(
        self,
        mocked_category_service,
    ):
        self._login(self.dm_user_id)
        mocked_category_service.return_value = SimpleNamespace(
            is_category_enabled=lambda *args, **kwargs: True,
            get_category_neighbours=lambda *args, **kwargs: (None, None),
            get_category_config=lambda *args, **kwargs: {},
        )
        now = datetime.now(timezone.utc)
        workflow = db.session.scalar(
            sa.select(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid == self.SID)
        )
        self.assertIsNotNone(workflow)
        workflow.workflow_state = "smartva_pending"
        db.session.add(
            VaSmartvaResults(
                va_sid=self.SID,
                va_smartva_status=VaStatuses.active,
                va_smartva_outcome=VaSmartvaResults.OUTCOME_SUCCESS,
                va_smartva_cause1="Acute myocardial infarction",
                va_smartva_likelihood1="0.78",
                va_smartva_updatedat=now,
            )
        )
        db.session.commit()

        response = self.client.get(
            f"/vaform/{self.SID}/vadmtriage?action=vadata&actiontype=vaview",
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            b"can no longer be triaged by a data manager",
            response.data,
        )
        workflow = db.session.scalar(
            sa.select(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid == self.SID)
        )
        self.assertIsNotNone(workflow)
        self.assertEqual(workflow.workflow_state, "ready_for_coding")

    def test_data_manager_odk_edit_redirect_uses_scoped_submission_mapping(
        self
    ):
        self._login(self.dm_user_id)

        response = self.client.get(
            f"/data-management/submissions/{self.SID}/odk-edit",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers["Location"],
            "https://minerva.example.org/projects/11/forms/"
            "DM_DASHBOARD_FORM/submissions/uuid%3Adata-manager-dashboard",
        )
        audit_row = db.session.scalar(
            sa.select(VaSubmissionsAuditlog)
            .where(VaSubmissionsAuditlog.va_sid == self.SID)
            .order_by(VaSubmissionsAuditlog.va_audit_createdat.desc())
        )
        self.assertIsNotNone(audit_row)
        self.assertEqual(
            audit_row.va_audit_action,
            "data_manager_opened_odk_edit_link",
        )

    def test_data_manager_read_only_view_writes_audit_row(self):
        self._login(self.dm_user_id)

        response = self.client.get(f"/vacta/vadata/vaview/{self.SID}")

        self.assertEqual(response.status_code, 200)
        audit_row = db.session.scalar(
            sa.select(VaSubmissionsAuditlog)
            .where(VaSubmissionsAuditlog.va_sid == self.SID)
            .order_by(VaSubmissionsAuditlog.va_audit_createdat.desc())
        )
        self.assertIsNotNone(audit_row)
        self.assertEqual(
            audit_row.va_audit_action,
            "data_manager_viewed_submission_read_only",
        )
        self.assertEqual(audit_row.va_audit_byrole, "data_manager")

    @patch("app.routes.api.analytics.refresh_submission_analytics_mv")
    def test_data_manager_can_refresh_analytics_mv(self, refresh_mv):
        self._login(self.dm_user_id)

        response = self.client.post(
            "/api/v1/analytics/mv/refresh",
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(
            response.get_json(),
            {"message": "Analytics data refreshed successfully."},
        )
        refresh_mv.assert_called_once_with(concurrently=True)

    def test_submissions_export_csv_includes_payload_and_current_state_fields(self):
        db.session.add(
            VaFinalAssessments(
                va_sid=self.SID,
                va_finassess_by=uuid.UUID(self.dm_user_id),
                va_conclusive_cod="I21",
                va_finassess_remark="Final coder decision",
                va_finassess_status=VaStatuses.active,
            )
        )
        db.session.commit()
        self._login(self.dm_user_id)

        response = self.client.get("/api/v1/data-management/submissions/export.csv")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        self.assertIn("attachment; filename=", response.headers["Content-Disposition"])
        body = response.get_data(as_text=True)
        self.assertIn("final_conclusive_cod", body)
        self.assertIn("workflow_state", body)
        self.assertIn("sid", body)
        self.assertIn("uuid:data-manager-dashboard", body)
        self.assertIn("I21", body)

    @patch(
        "app.routes.api.data_management.dm_smartva_input_export_csv",
        return_value="sid,result\nuuid:data-manager-dashboard,ok\n",
    )
    def test_smartva_input_export_csv_route_returns_excel_safe_csv(
        self,
        mocked_export,
    ):
        self._login(self.dm_user_id)

        response = self.client.get(
            "/api/v1/data-management/submissions/export-smartva-input.csv"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        self.assertIn("attachment; filename=", response.headers["Content-Disposition"])
        self.assertTrue(response.get_data(as_text=True).startswith("\ufeffsid,result"))
        mocked_export.assert_called_once()

    @patch(
        "app.routes.api.data_management.dm_smartva_results_export_csv",
        return_value="va_sid,va_smartva_cause1\nuuid:data-manager-dashboard,Heart attack\n",
    )
    def test_smartva_results_export_csv_route_returns_excel_safe_csv(
        self,
        mocked_export,
    ):
        self._login(self.dm_user_id)

        response = self.client.get(
            "/api/v1/data-management/submissions/export-smartva-results.csv"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        self.assertIn("attachment; filename=", response.headers["Content-Disposition"])
        self.assertTrue(
            response.get_data(as_text=True).startswith(
                "\ufeffva_sid,va_smartva_cause1"
            )
        )
        mocked_export.assert_called_once()

    @patch(
        "app.routes.api.data_management.dm_smartva_likelihoods_export_csv",
        return_value="va_sid,output_row_index,likelihood\nuuid:data-manager-dashboard,1,0.95\n",
    )
    def test_smartva_likelihoods_export_csv_route_returns_excel_safe_csv(
        self,
        mocked_export,
    ):
        self._login(self.dm_user_id)

        response = self.client.get(
            "/api/v1/data-management/submissions/export-smartva-likelihoods.csv"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/csv")
        self.assertIn("attachment; filename=", response.headers["Content-Disposition"])
        self.assertTrue(
            response.get_data(as_text=True).startswith(
                "\ufeffva_sid,output_row_index,likelihood"
            )
        )
        mocked_export.assert_called_once()

    @patch(
        "app.routes.api.data_management.dm_smartva_input_export_csv",
        side_effect=[
            "sid,result\nuuid:data-manager-dashboard,first\n",
            "sid,result\nuuid:data-manager-dashboard,second\n",
        ],
    )
    def test_export_route_reuses_disk_cache_for_same_filters(self, mocked_export):
        self._login(self.dm_user_id)
        with tempfile.TemporaryDirectory() as tmpdir:
            old_app_data = self.app.config.get("APP_DATA")
            old_ttl = self.app.config.get("DM_EXPORT_CACHE_TTL_SECONDS")
            self.app.config["APP_DATA"] = tmpdir
            self.app.config["DM_EXPORT_CACHE_TTL_SECONDS"] = 300
            try:
                response_first = self.client.get(
                    "/api/v1/data-management/submissions/export-smartva-input.csv"
                    "?project=ICMR01&site=ICMR01OD0101"
                )
                response_second = self.client.get(
                    "/api/v1/data-management/submissions/export-smartva-input.csv"
                    "?project=ICMR01&site=ICMR01OD0101"
                )
            finally:
                self.app.config["APP_DATA"] = old_app_data
                self.app.config["DM_EXPORT_CACHE_TTL_SECONDS"] = old_ttl

        self.assertEqual(response_first.status_code, 200)
        self.assertEqual(response_first.headers.get("X-Export-Cache"), "MISS")
        self.assertEqual(response_second.status_code, 200)
        self.assertEqual(response_second.headers.get("X-Export-Cache"), "HIT")
        self.assertEqual(mocked_export.call_count, 1)

    @patch(
        "app.routes.api.data_management.dm_smartva_input_export_csv",
        side_effect=[
            "sid,result\nuuid:data-manager-dashboard,first\n",
            "sid,result\nuuid:data-manager-dashboard,second\n",
        ],
    )
    def test_export_cache_ignores_sort_query_params(self, mocked_export):
        self._login(self.dm_user_id)
        with tempfile.TemporaryDirectory() as tmpdir:
            old_app_data = self.app.config.get("APP_DATA")
            old_ttl = self.app.config.get("DM_EXPORT_CACHE_TTL_SECONDS")
            self.app.config["APP_DATA"] = tmpdir
            self.app.config["DM_EXPORT_CACHE_TTL_SECONDS"] = 300
            try:
                response_first = self.client.get(
                    "/api/v1/data-management/submissions/export-smartva-input.csv"
                    "?project=ICMR01&sort[0][field]=coded_on&sort[0][dir]=asc"
                )
                response_second = self.client.get(
                    "/api/v1/data-management/submissions/export-smartva-input.csv"
                    "?project=ICMR01&sort[0][field]=va_submission_date&sort[0][dir]=desc"
                )
            finally:
                self.app.config["APP_DATA"] = old_app_data
                self.app.config["DM_EXPORT_CACHE_TTL_SECONDS"] = old_ttl

        self.assertEqual(response_first.status_code, 200)
        self.assertEqual(response_first.headers.get("X-Export-Cache"), "MISS")
        self.assertEqual(response_second.status_code, 200)
        self.assertEqual(response_second.headers.get("X-Export-Cache"), "HIT")
        self.assertEqual(mocked_export.call_count, 1)

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
