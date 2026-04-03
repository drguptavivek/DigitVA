from datetime import datetime, timezone
from unittest.mock import patch

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaForms,
    VaProjectSites,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissionWorkflowEvent,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUserAccessGrants,
)
from app.services.workflow.definition import (
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_ELIGIBLE,
)
from tests.base import BaseTestCase


class ReviewingRoutesTests(BaseTestCase):
    BASE_PROJECT_ID = "RR01"
    BASE_SITE_ID = "RS01"
    FORM_ID = "RRTFORM001"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)

        db.session.add(
            VaResearchProjects(
                project_id=cls.BASE_PROJECT_ID,
                project_code=cls.BASE_PROJECT_ID,
                project_name="Reviewer Route Project",
                project_nickname="ReviewerRoute",
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
                site_name="Reviewer Route Site",
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
                odk_form_id="REVIEWER_ROUTE_FORM",
                odk_project_id="1",
                form_type="WHO_2022_VA",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.flush()

        project_site_id = db.session.scalar(
            db.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == cls.BASE_PROJECT_ID,
                VaProjectSites.site_id == cls.BASE_SITE_ID,
            )
        )
        cls.base_reviewer_user = cls._make_user(
            "base.reviewer.routes@test.local",
            "BaseReviewerRoutes123",
        )
        cls.base_reviewer_user.landing_page = "reviewer"
        db.session.add(
            VaUserAccessGrants(
                user_id=cls.base_reviewer_user.user_id,
                role=VaAccessRoles.reviewer,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site_id,
                notes="reviewer route grant",
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()
        cls.base_reviewer_id = str(cls.base_reviewer_user.user_id)

    def _add_submission(self, sid: str, workflow_state: str) -> None:
        now = datetime.now(timezone.utc)
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id=self.FORM_ID,
                va_submission_date=now,
                va_odk_updatedat=now,
                va_data_collector="reviewer-route",
                va_instance_name=sid,
                va_uniqueid_real=sid,
                va_uniqueid_masked=sid,
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=42,
                va_deceased_gender="male",
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.flush()
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=sid,
                workflow_state=workflow_state,
                workflow_reason="test_seed",
                workflow_updated_by_role="vasystem",
            )
        )
        db.session.commit()

    def test_reviewing_start_uses_canonical_reviewer_transition_path(self):
        sid = "uuid:reviewer-route-start"
        self._add_submission(sid, WORKFLOW_REVIEWER_ELIGIBLE)
        self._login(self.base_reviewer_id)

        with patch(
            "app.routes.reviewing.render_va_coding_page",
            return_value="reviewer-page",
        ) as render_page:
            response = self.client.get(f"/reviewing/start/{sid}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "reviewer-page")
        render_page.assert_called_once()

        allocation = db.session.scalar(
            db.select(VaAllocations).where(
                VaAllocations.va_sid == sid,
                VaAllocations.va_allocation_for == VaAllocation.reviewing,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        )
        self.assertIsNotNone(allocation)

        workflow_state = db.session.scalar(
            db.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == sid
            )
        )
        self.assertEqual(workflow_state, WORKFLOW_REVIEWER_CODING_IN_PROGRESS)

        event = db.session.scalar(
            db.select(VaSubmissionWorkflowEvent).where(
                VaSubmissionWorkflowEvent.va_sid == sid,
                VaSubmissionWorkflowEvent.transition_id == "reviewer_coding_started",
            )
        )
        self.assertIsNotNone(event)

        legacy_audit = db.session.scalar(
            db.select(VaSubmissionsAuditlog).where(
                VaSubmissionsAuditlog.va_sid == sid,
                VaSubmissionsAuditlog.va_audit_action
                == "form allocated to reviewer for coding",
            )
        )
        self.assertIsNotNone(legacy_audit)

    def test_admin_revoked_stats_uses_canonical_workflow_state(self):
        sid = "uuid:admin-revoked-stats"
        self._add_submission(sid, WORKFLOW_FINALIZED_UPSTREAM_CHANGED)
        self._login(self.base_admin_id)

        response = self.client.get("/admin/api/sync/revoked-stats")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["totals"]["revoked"], 1)

        projects = payload["projects"]
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["project_id"], self.BASE_PROJECT_ID)
        self.assertEqual(projects[0]["revoked"], 1)
        self.assertEqual(projects[0]["sites"][0]["site_id"], self.BASE_SITE_ID)
        self.assertEqual(projects[0]["sites"][0]["revoked"], 1)
        self.assertEqual(
            projects[0]["sites"][0]["forms"][self.FORM_ID]["form_id"],
            self.FORM_ID,
        )
        self.assertEqual(
            projects[0]["sites"][0]["forms"][self.FORM_ID]["revoked"],
            1,
        )
