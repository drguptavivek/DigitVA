"""Tests for data management service — accept/reject upstream change flow.

Critical behavior under test:
- dm_accept_upstream_change: deactivates artifacts, transitions to ready_for_coding
- dm_reject_upstream_change: restores coder_finalized, preserves artifacts
- Both functions require the submission to be in revoked_va_data_changed state
- Permission/scope checks are enforced
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import sqlalchemy as sa

from app import db
from app.models import (
    VaAllocations,
    VaCoderReview,
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaDataManagerReview,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUsers,
)
from app.services.submission_workflow_service import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVOKED_VA_DATA_CHANGED,
    get_submission_workflow_state,
    set_submission_workflow_state,
)
from app.services.data_management_service import (
    dm_accept_upstream_change,
    dm_reject_upstream_change,
)
from tests.base import BaseTestCase


class DataManagementAcceptRejectTests(BaseTestCase):
    """Tests for dm_accept_upstream_change and dm_reject_upstream_change."""

    FORM_ID = "DM01DM0101"
    PROJECT_ID = "DM01"
    SITE_ID = "DM01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)

        # Create project/site/form infrastructure
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID,
            project_code=cls.PROJECT_ID,
            project_name="DM Test Project",
            project_nickname="DMTest",
            project_status=VaStatuses.active,
            project_registered_at=now,
            project_updated_at=now,
        ))
        db.session.add(VaResearchProjects(
            project_id=cls.PROJECT_ID,
            project_code=cls.PROJECT_ID,
            project_name="DM Test Project",
            project_nickname="DMTest",
            project_status=VaStatuses.active,
            project_registered_at=now,
            project_updated_at=now,
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID,
            site_name="DM Test Site",
            site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active,
            site_registered_at=now,
            site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaSites(
            site_id=cls.SITE_ID,
            project_id=cls.PROJECT_ID,
            site_name="DM Test Site",
            site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active,
            site_registered_at=now,
            site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.PROJECT_ID,
            site_id=cls.SITE_ID,
            project_site_status=VaStatuses.active,
            project_site_registered_at=now,
            project_site_updated_at=now,
        ))
        db.session.add(VaForms(
            form_id=cls.FORM_ID,
            project_id=cls.PROJECT_ID,
            site_id=cls.SITE_ID,
            odk_form_id="DM_FORM",
            odk_project_id="99",
            form_type="WHO VA 2022",
            form_status=VaStatuses.active,
            form_registered_at=now,
            form_updated_at=now,
        ))
        db.session.commit()

    def _create_revoked_submission(self, sid_suffix: str) -> str:
        """Create a submission in revoked_va_data_changed state with artifacts."""
        now = datetime.now(timezone.utc)
        va_sid = f"uuid:dm-test-{sid_suffix}"

        # Create submission
        submission = VaSubmissions(
            va_sid=va_sid,
            va_form_id=self.FORM_ID,
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name=va_sid,
            va_uniqueid_real=None,
            va_uniqueid_masked=va_sid,
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=42,
            va_deceased_gender="male",
            va_data={"test": "data"},
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(submission)
        db.session.flush()

        # Create workflow record (correct attribute names)
        db.session.add(VaSubmissionWorkflow(
            va_sid=va_sid,
            workflow_state=WORKFLOW_CODER_FINALIZED,
            workflow_created_at=now,
            workflow_updated_at=now,
        ))

        # Create active artifacts (these should be deactivated on accept)
        # VaFinalAssessments requires va_finassess_by and va_conclusive_cod
        db.session.add(VaFinalAssessments(
            va_sid=va_sid,
            va_finassess_by=self.base_admin_id,
            va_conclusive_cod="A00",
            va_finassess_status=VaStatuses.active,
        ))
        # VaInitialAssessments requires va_iniassess_by, va_immediate_cod, va_antecedent_cod
        db.session.add(VaInitialAssessments(
            va_sid=va_sid,
            va_iniassess_by=self.base_admin_id,
            va_immediate_cod="A00",
            va_antecedent_cod="B00",
            va_iniassess_status=VaStatuses.active,
        ))
        # VaCoderReview requires va_creview_by and va_creview_reason
        db.session.add(VaCoderReview(
            va_sid=va_sid,
            va_creview_by=self.base_admin_id,
            va_creview_reason="completed",
            va_creview_status=VaStatuses.active,
        ))
        # VaSmartvaResults - only va_sid and va_smartva_status are required
        db.session.add(VaSmartvaResults(
            va_sid=va_sid,
            va_smartva_status=VaStatuses.active,
        ))
        db.session.flush()

        # Transition to revoked_va_data_changed
        set_submission_workflow_state(
            va_sid,
            WORKFLOW_REVOKED_VA_DATA_CHANGED,
            reason="test_setup",
            by_user_id=self.base_admin_id,
            by_role="admin",
        )
        db.session.commit()

        return va_sid

    def _create_dm_user(self) -> VaUsers:
        """Create a data manager user with access to the test project."""
        # Use unique email to avoid conflicts between tests
        unique_suffix = uuid.uuid4().hex[:8]
        user = VaUsers(
            name=f"DM Test User {unique_suffix}",
            email=f"dm_test_{unique_suffix}@example.com",
            vacode_language=["English"],
            permission={},
            landing_page="data_manager",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status=VaStatuses.active,
        )
        user.set_password("password")
        db.session.add(user)
        db.session.flush()

        # Grant data_manager role for the project
        from app.models import VaAccessRoles, VaUserAccessGrants, VaAccessScopeTypes
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.PROJECT_ID,
            grant_status=VaStatuses.active,
        ))
        db.session.commit()
        return user


class DmAcceptUpstreamChangeTests(DataManagementAcceptRejectTests):
    """Tests for dm_accept_upstream_change."""

    def test_transitions_to_ready_for_coding(self):
        """Accept should transition submission to ready_for_coding."""
        va_sid = self._create_revoked_submission("accept-1")
        dm_user = self._create_dm_user()

        dm_accept_upstream_change(dm_user, va_sid)
        db.session.commit()

        state = get_submission_workflow_state(va_sid)
        self.assertEqual(state, WORKFLOW_READY_FOR_CODING)

    def test_deactivates_final_assessments(self):
        """Accept should deactivate all active final assessments."""
        va_sid = self._create_revoked_submission("accept-2")
        dm_user = self._create_dm_user()

        dm_accept_upstream_change(dm_user, va_sid)
        db.session.commit()

        active_count = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaFinalAssessments)
            .where(VaFinalAssessments.va_sid == va_sid)
            .where(VaFinalAssessments.va_finassess_status == VaStatuses.active)
        )
        self.assertEqual(active_count, 0)

    def test_deactivates_initial_assessments(self):
        """Accept should deactivate all active initial assessments."""
        va_sid = self._create_revoked_submission("accept-3")
        dm_user = self._create_dm_user()

        dm_accept_upstream_change(dm_user, va_sid)
        db.session.commit()

        active_count = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaInitialAssessments)
            .where(VaInitialAssessments.va_sid == va_sid)
            .where(VaInitialAssessments.va_iniassess_status == VaStatuses.active)
        )
        self.assertEqual(active_count, 0)

    def test_deactivates_coder_reviews(self):
        """Accept should deactivate all active coder reviews."""
        va_sid = self._create_revoked_submission("accept-4")
        dm_user = self._create_dm_user()

        dm_accept_upstream_change(dm_user, va_sid)
        db.session.commit()

        active_count = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaCoderReview)
            .where(VaCoderReview.va_sid == va_sid)
            .where(VaCoderReview.va_creview_status == VaStatuses.active)
        )
        self.assertEqual(active_count, 0)

    def test_deactivates_smartva_results(self):
        """Accept should deactivate all active SmartVA results."""
        va_sid = self._create_revoked_submission("accept-5")
        dm_user = self._create_dm_user()

        dm_accept_upstream_change(dm_user, va_sid)
        db.session.commit()

        active_count = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaSmartvaResults)
            .where(VaSmartvaResults.va_sid == va_sid)
            .where(VaSmartvaResults.va_smartva_status == VaStatuses.active)
        )
        self.assertEqual(active_count, 0)

    def test_creates_audit_log_entry(self):
        """Accept should create an audit log entry."""
        va_sid = self._create_revoked_submission("accept-6")
        dm_user = self._create_dm_user()

        dm_accept_upstream_change(dm_user, va_sid)
        db.session.commit()

        audit = db.session.scalar(
            sa.select(VaSubmissionsAuditlog)
            .where(VaSubmissionsAuditlog.va_sid == va_sid)
            .where(VaSubmissionsAuditlog.va_audit_action == "data_manager_accepted_upstream_odk_change")
        )
        self.assertIsNotNone(audit)
        self.assertEqual(audit.va_audit_by, dm_user.user_id)
        self.assertEqual(audit.va_audit_byrole, "data_manager")

    def test_raises_for_wrong_state(self):
        """Accept should raise ValueError if submission is not in revoked state."""
        va_sid = self._create_revoked_submission("accept-7")
        dm_user = self._create_dm_user()

        # First accept it (moves to ready_for_coding)
        dm_accept_upstream_change(dm_user, va_sid)
        db.session.commit()

        # Try to accept again - should fail
        with self.assertRaises(ValueError) as ctx:
            dm_accept_upstream_change(dm_user, va_sid)

        self.assertIn("not revoked_va_data_changed", str(ctx.exception))

    def test_raises_for_non_dm_user(self):
        """Accept should raise for user without DM scope."""
        va_sid = self._create_revoked_submission("accept-8")
        # base_coder_user has no DM access to this project

        with self.assertRaises(PermissionError):
            dm_accept_upstream_change(self.base_coder_user, va_sid)


class DmRejectUpstreamChangeTests(DataManagementAcceptRejectTests):
    """Tests for dm_reject_upstream_change."""

    def test_transitions_to_coder_finalized(self):
        """Reject should restore submission to coder_finalized."""
        va_sid = self._create_revoked_submission("reject-1")
        dm_user = self._create_dm_user()

        dm_reject_upstream_change(dm_user, va_sid)
        db.session.commit()

        state = get_submission_workflow_state(va_sid)
        self.assertEqual(state, WORKFLOW_CODER_FINALIZED)

    def test_preserves_final_assessments(self):
        """Reject should keep final assessments active."""
        va_sid = self._create_revoked_submission("reject-2")
        dm_user = self._create_dm_user()

        dm_reject_upstream_change(dm_user, va_sid)
        db.session.commit()

        active_count = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaFinalAssessments)
            .where(VaFinalAssessments.va_sid == va_sid)
            .where(VaFinalAssessments.va_finassess_status == VaStatuses.active)
        )
        self.assertEqual(active_count, 1)  # Still active

    def test_preserves_smartva_results(self):
        """Reject should keep SmartVA results active."""
        va_sid = self._create_revoked_submission("reject-3")
        dm_user = self._create_dm_user()

        dm_reject_upstream_change(dm_user, va_sid)
        db.session.commit()

        active_count = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaSmartvaResults)
            .where(VaSmartvaResults.va_sid == va_sid)
            .where(VaSmartvaResults.va_smartva_status == VaStatuses.active)
        )
        self.assertEqual(active_count, 1)  # Still active

    def test_creates_audit_log_entry(self):
        """Reject should create an audit log entry."""
        va_sid = self._create_revoked_submission("reject-4")
        dm_user = self._create_dm_user()

        dm_reject_upstream_change(dm_user, va_sid)
        db.session.commit()

        audit = db.session.scalar(
            sa.select(VaSubmissionsAuditlog)
            .where(VaSubmissionsAuditlog.va_sid == va_sid)
            .where(VaSubmissionsAuditlog.va_audit_action == "data_manager_rejected_upstream_odk_change")
        )
        self.assertIsNotNone(audit)
        self.assertEqual(audit.va_audit_by, dm_user.user_id)
        self.assertEqual(audit.va_audit_byrole, "data_manager")

    def test_raises_for_wrong_state(self):
        """Reject should raise ValueError if submission is not in revoked state."""
        va_sid = self._create_revoked_submission("reject-5")
        dm_user = self._create_dm_user()

        # First reject it (moves to coder_finalized)
        dm_reject_upstream_change(dm_user, va_sid)
        db.session.commit()

        # Try to reject again - should fail
        with self.assertRaises(ValueError) as ctx:
            dm_reject_upstream_change(dm_user, va_sid)

        self.assertIn("not revoked_va_data_changed", str(ctx.exception))

    @patch("app.services.odk_review_service.post_dm_rejection_comment")
    def test_posts_odk_comment(self, mock_post_comment):
        """Reject should post a comment to ODK Central."""
        mock_post_comment.return_value = MagicMock(success=True)

        va_sid = self._create_revoked_submission("reject-6")
        dm_user = self._create_dm_user()

        dm_reject_upstream_change(dm_user, va_sid)
        db.session.commit()

        mock_post_comment.assert_called_once_with(va_sid)

    @patch("app.services.odk_review_service.post_dm_rejection_comment")
    def test_continues_on_odk_failure(self, mock_post_comment):
        """Reject should complete even if ODK comment post fails."""
        mock_post_comment.return_value = MagicMock(
            success=False,
            error_message="ODK unavailable"
        )

        va_sid = self._create_revoked_submission("reject-7")
        dm_user = self._create_dm_user()

        # Should not raise - ODK failure is non-blocking
        dm_reject_upstream_change(dm_user, va_sid)
        db.session.commit()

        state = get_submission_workflow_state(va_sid)
        self.assertEqual(state, WORKFLOW_CODER_FINALIZED)
