"""Tests for data management service upstream-change resolution flow.

Critical behavior under test:
- dm_accept_upstream_change: deactivates artifacts, transitions to smartva_pending
- dm_reject_upstream_change: promotes new payload, restores finalized state, preserves artifacts
- Both functions require the submission to be in finalized_upstream_changed state
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
    VaReviewerFinalAssessments,
    VaSiteMaster,
    VaSites,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissionUpstreamChange,
    VaSubmissionWorkflowEvent,
    VaSubmissionWorkflow,
    VaSubmissions,
    VaUsers,
)
from app.models.va_submission_payload_versions import (
    PAYLOAD_VERSION_STATUS_ACTIVE,
    PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM,
    PAYLOAD_VERSION_STATUS_SUPERSEDED,
)
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_SMARTVA_PENDING,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
)
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    set_submission_workflow_state,
)
from app.services.data_management_service import (
    dm_accept_upstream_change,
    dm_reject_upstream_change,
)
from app.services.submission_payload_version_service import (
    create_or_update_pending_upstream_payload_version,
    ensure_active_payload_version,
)
from app.services.workflow.upstream_changes import record_protected_upstream_change
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

    def _create_revoked_submission(
        self,
        sid_suffix: str,
        *,
        workflow_state_before: str = WORKFLOW_CODER_FINALIZED,
        with_reviewer_final: bool = False,
    ) -> str:
        """Create a submission in finalized_upstream_changed state with artifacts."""
        now = datetime.now(timezone.utc)
        va_sid = f"uuid:dm-test-{sid_suffix}"
        active_payload = {
            "sid": va_sid,
            "form_def": self.FORM_ID,
            "SubmissionDate": now.isoformat(),
            "updatedAt": now.isoformat(),
            "SubmitterName": "tester",
            "ReviewState": None,
            "OdkReviewComments": [],
            "instanceName": va_sid,
            "unique_id": va_sid,
            "unique_id2": va_sid,
            "Id10013": "yes",
            "language": "English",
            "finalAgeInYears": "42",
            "Id10019": "male",
        }
        incoming_payload = {
            **active_payload,
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "finalAgeInYears": "47",
            "test": "updated-data",
        }

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
            va_data=active_payload,
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(submission)
        db.session.flush()

        active_version = ensure_active_payload_version(
            submission,
            payload_data=active_payload,
            source_updated_at=now,
            created_by_role="vasystem",
        )

        # Create workflow record (correct attribute names)
        db.session.add(VaSubmissionWorkflow(
            va_sid=va_sid,
            workflow_state=workflow_state_before,
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

        if with_reviewer_final:
            db.session.add(
                VaReviewerFinalAssessments(
                    va_sid=va_sid,
                    va_rfinassess_by=self.base_admin_id,
                    va_conclusive_cod="R55",
                    va_rfinassess_status=VaStatuses.active,
                )
            )
            db.session.flush()

        pending_version = create_or_update_pending_upstream_payload_version(
            submission,
            payload_data=incoming_payload,
            source_updated_at=now,
            created_by_role="vasystem",
        )
        record_protected_upstream_change(
            submission,
            incoming_payload,
            workflow_state_before=workflow_state_before,
            detected_odk_updatedat=now,
            previous_payload_version_id=active_version.payload_version_id,
            incoming_payload_version_id=pending_version.payload_version_id,
        )

        # Transition to finalized_upstream_changed
        set_submission_workflow_state(
            va_sid,
            WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
            reason="test_setup",
            by_user_id=self.base_admin_id,
            by_role="vaadmin",
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

    def test_transitions_to_smartva_pending(self):
        """Accept should transition submission to smartva_pending."""
        va_sid = self._create_revoked_submission("accept-1")
        dm_user = self._create_dm_user()

        dm_accept_upstream_change(dm_user, va_sid)
        db.session.commit()

        state = get_submission_workflow_state(va_sid)
        self.assertEqual(state, WORKFLOW_SMARTVA_PENDING)

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
            sa.select(VaSubmissionWorkflowEvent)
            .where(VaSubmissionWorkflowEvent.va_sid == va_sid)
            .where(
                VaSubmissionWorkflowEvent.transition_id == "upstream_change_accepted"
            )
        )
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor_user_id, dm_user.user_id)
        self.assertEqual(audit.actor_role, "data_manager")
        self.assertEqual(audit.previous_state, WORKFLOW_FINALIZED_UPSTREAM_CHANGED)
        self.assertEqual(audit.current_state, WORKFLOW_SMARTVA_PENDING)

    def test_admin_accept_records_admin_actor_role(self):
        """Admin accept should stamp vaadmin rather than data_manager."""
        va_sid = self._create_revoked_submission("accept-6-admin")

        dm_accept_upstream_change(self.base_admin_user, va_sid)
        db.session.commit()

        workflow = db.session.scalar(
            sa.select(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid == va_sid)
        )
        self.assertEqual(workflow.workflow_updated_by_role, "vaadmin")

        audit = db.session.scalar(
            sa.select(VaSubmissionWorkflowEvent)
            .where(VaSubmissionWorkflowEvent.va_sid == va_sid)
            .where(
                VaSubmissionWorkflowEvent.transition_id == "upstream_change_accepted"
            )
            .order_by(VaSubmissionWorkflowEvent.event_created_at.desc())
        )
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor_role, "vaadmin")

    def test_accept_promotes_pending_payload_version_and_updates_active_summary(self):
        va_sid = self._create_revoked_submission("accept-payload")
        dm_user = self._create_dm_user()

        previous_active = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == va_sid,
                VaSubmissionPayloadVersion.version_status == PAYLOAD_VERSION_STATUS_ACTIVE,
            )
        )
        pending = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == va_sid,
                VaSubmissionPayloadVersion.version_status
                == PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM,
            )
        )

        dm_accept_upstream_change(dm_user, va_sid)
        db.session.commit()

        refreshed_submission = db.session.get(VaSubmissions, va_sid)
        refreshed_previous = db.session.get(
            VaSubmissionPayloadVersion, previous_active.payload_version_id
        )
        refreshed_pending = db.session.get(
            VaSubmissionPayloadVersion, pending.payload_version_id
        )

        self.assertEqual(refreshed_pending.version_status, PAYLOAD_VERSION_STATUS_ACTIVE)
        self.assertEqual(
            refreshed_submission.active_payload_version_id,
            refreshed_pending.payload_version_id,
        )
        self.assertEqual(refreshed_previous.version_status, PAYLOAD_VERSION_STATUS_SUPERSEDED)
        self.assertEqual(refreshed_submission.va_data["test"], "updated-data")

    def test_accept_deactivates_reviewer_final_assessments(self):
        va_sid = self._create_revoked_submission(
            "accept-reviewer-final",
            workflow_state_before=WORKFLOW_REVIEWER_ELIGIBLE,
            with_reviewer_final=True,
        )
        dm_user = self._create_dm_user()

        dm_accept_upstream_change(dm_user, va_sid)
        db.session.commit()

        active_count = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(VaReviewerFinalAssessments)
            .where(VaReviewerFinalAssessments.va_sid == va_sid)
            .where(VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active)
        )
        self.assertEqual(active_count, 0)

    def test_raises_for_wrong_state(self):
        """Accept should raise ValueError if submission is not in revoked state."""
        va_sid = self._create_revoked_submission("accept-7")
        dm_user = self._create_dm_user()

        # First accept it (moves to smartva_pending)
        dm_accept_upstream_change(dm_user, va_sid)
        db.session.commit()

        # Try to accept again - should fail
        with self.assertRaises(ValueError) as ctx:
            dm_accept_upstream_change(dm_user, va_sid)

        self.assertIn("not finalized_upstream_changed", str(ctx.exception))

    def test_raises_for_non_dm_user(self):
        """Accept should raise for user without DM scope."""
        va_sid = self._create_revoked_submission("accept-8")
        # base_coder_user has no DM access to this project

        with self.assertRaises(PermissionError):
            dm_accept_upstream_change(self.base_coder_user, va_sid)

    def test_accept_requires_latest_pending_payload_timestamp(self):
        va_sid = self._create_revoked_submission("accept-stale")
        dm_user = self._create_dm_user()

        submission = db.session.get(VaSubmissions, va_sid)
        pending = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == va_sid,
                VaSubmissionPayloadVersion.version_status
                == PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM,
            )
        )
        submission.va_odk_updatedat = datetime(2026, 1, 1, tzinfo=timezone.utc)
        db.session.commit()

        with self.assertRaises(ValueError) as ctx:
            dm_accept_upstream_change(dm_user, va_sid)

        self.assertIn("Refresh the submission from ODK", str(ctx.exception))


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
        """Keep-current-ICD should create an explicit audit log entry."""
        va_sid = self._create_revoked_submission("reject-4")
        dm_user = self._create_dm_user()

        dm_reject_upstream_change(dm_user, va_sid)
        db.session.commit()

        audit = db.session.scalar(
            sa.select(VaSubmissionWorkflowEvent)
            .where(VaSubmissionWorkflowEvent.va_sid == va_sid)
            .where(
                VaSubmissionWorkflowEvent.transition_id
                == "upstream_change_kept_current_icd"
            )
        )
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor_user_id, dm_user.user_id)
        self.assertEqual(audit.actor_role, "data_manager")
        self.assertEqual(audit.previous_state, WORKFLOW_FINALIZED_UPSTREAM_CHANGED)
        self.assertEqual(audit.current_state, WORKFLOW_CODER_FINALIZED)

    def test_admin_reject_records_admin_actor_role(self):
        """Admin keep-current-ICD should stamp vaadmin rather than data_manager."""
        va_sid = self._create_revoked_submission("reject-4-admin")

        dm_reject_upstream_change(self.base_admin_user, va_sid)
        db.session.commit()

        workflow = db.session.scalar(
            sa.select(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid == va_sid)
        )
        self.assertEqual(workflow.workflow_updated_by_role, "vaadmin")

        audit = db.session.scalar(
            sa.select(VaSubmissionWorkflowEvent)
            .where(VaSubmissionWorkflowEvent.va_sid == va_sid)
            .where(
                VaSubmissionWorkflowEvent.transition_id
                == "upstream_change_kept_current_icd"
            )
            .order_by(VaSubmissionWorkflowEvent.event_created_at.desc())
        )
        self.assertIsNotNone(audit)
        self.assertEqual(audit.actor_role, "vaadmin")

    def test_reject_promotes_pending_payload_version_and_updates_active_summary(self):
        va_sid = self._create_revoked_submission("reject-payload")
        dm_user = self._create_dm_user()

        previous_active = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == va_sid,
                VaSubmissionPayloadVersion.version_status == PAYLOAD_VERSION_STATUS_ACTIVE,
            )
        )
        pending = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == va_sid,
                VaSubmissionPayloadVersion.version_status
                == PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM,
            )
        )

        dm_reject_upstream_change(dm_user, va_sid)
        db.session.commit()

        refreshed_submission = db.session.get(VaSubmissions, va_sid)
        refreshed_previous = db.session.get(
            VaSubmissionPayloadVersion, previous_active.payload_version_id
        )
        refreshed_pending = db.session.get(
            VaSubmissionPayloadVersion, pending.payload_version_id
        )

        self.assertEqual(
            refreshed_pending.version_status, PAYLOAD_VERSION_STATUS_ACTIVE
        )
        self.assertEqual(
            refreshed_submission.active_payload_version_id,
            refreshed_pending.payload_version_id,
        )
        self.assertEqual(
            refreshed_previous.version_status, PAYLOAD_VERSION_STATUS_SUPERSEDED
        )
        self.assertEqual(refreshed_submission.va_data["test"], "updated-data")

    def test_reject_records_kept_current_icd_resolution_status(self):
        va_sid = self._create_revoked_submission("reject-resolution")
        dm_user = self._create_dm_user()

        dm_reject_upstream_change(dm_user, va_sid)
        db.session.commit()

        resolved = db.session.scalar(
            sa.select(VaSubmissionUpstreamChange)
            .where(VaSubmissionUpstreamChange.va_sid == va_sid)
            .order_by(VaSubmissionUpstreamChange.created_at.desc())
        )
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.resolution_status, "kept_current_icd")

    def test_reject_restores_prior_finalized_state(self):
        va_sid = self._create_revoked_submission(
            "reject-reviewer-eligible",
            workflow_state_before=WORKFLOW_REVIEWER_ELIGIBLE,
        )
        dm_user = self._create_dm_user()

        dm_reject_upstream_change(dm_user, va_sid)
        db.session.commit()

        state = get_submission_workflow_state(va_sid)
        self.assertEqual(state, WORKFLOW_REVIEWER_ELIGIBLE)

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

        self.assertIn("not finalized_upstream_changed", str(ctx.exception))

    def test_reject_requires_latest_pending_payload_timestamp(self):
        va_sid = self._create_revoked_submission("reject-stale")
        dm_user = self._create_dm_user()

        submission = db.session.get(VaSubmissions, va_sid)
        pending = db.session.scalar(
            sa.select(VaSubmissionPayloadVersion).where(
                VaSubmissionPayloadVersion.va_sid == va_sid,
                VaSubmissionPayloadVersion.version_status
                == PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM,
            )
        )
        submission.va_odk_updatedat = datetime(2026, 1, 1, tzinfo=timezone.utc)
        db.session.commit()

        with self.assertRaises(ValueError) as ctx:
            dm_reject_upstream_change(dm_user, va_sid)

        self.assertIn("Refresh the submission from ODK", str(ctx.exception))
