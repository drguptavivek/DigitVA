import uuid
from datetime import datetime, timezone

from app import db
from app.models import (
    VaAllocations,
    VaAllocation,
    VaCoderReview,
    VaDataManagerReview,
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflowEvent,
    VaSubmissionWorkflow,
    VaSubmissions,
)
from app.services.workflow.definition import (
    ALL_WORKFLOW_STATES,
    PROTECTED_WORKFLOW_STATES,
    SMARTVA_BLOCKED_WORKFLOW_STATES,
    WORKFLOW_CONSENT_REFUSED,
    WORKFLOW_ATTACHMENT_SYNC_PENDING,
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
    WORKFLOW_SCREENING_PENDING,
    WORKFLOW_SMARTVA_PENDING,
    TRANSITIONS,
    TRANSITION_ATTACHMENTS_SYNCED,
    TRANSITION_REVIEWER_ELIGIBLE_AFTER_RECODE_WINDOW,
)
from app.services.workflow.state_store import (
    infer_workflow_state_from_legacy_records,
    set_submission_workflow_state,
    sync_submission_workflow_from_legacy_records,
)
from app.services.workflow.transitions import (
    WorkflowTransitionError,
    admin_actor,
    accept_upstream_change,
    coder_actor,
    data_manager_actor,
    mark_admin_override_to_recode,
    mark_attachment_sync_completed,
    mark_coder_finalized,
    mark_coder_step1_saved,
    mark_coding_started,
    mark_data_manager_not_codeable,
    mark_recode_finalized,
    mark_recode_started,
    mark_reviewer_eligible_after_recode_window,
    mark_reviewer_coding_started,
    mark_reviewer_finalized,
    reviewer_actor,
    mark_screening_passed,
    mark_screening_rejected,
    mark_smartva_failed_recorded,
    mark_smartva_completed,
    reset_demo_state,
    reset_incomplete_first_pass,
    reset_incomplete_recode,
    system_actor,
)
from app.services.final_cod_authority_service import start_recode_episode
from tests.base import BaseTestCase


_RUN_SUFFIX = uuid.uuid4().hex[:4].upper()


class TestSubmissionWorkflowService(BaseTestCase):
    BASE_PROJECT_ID = f"WF{_RUN_SUFFIX}"
    BASE_SITE_ID = f"S{_RUN_SUFFIX[:3]}"
    FORM_ID = f"W{_RUN_SUFFIX}000001"
    USER_EMAIL_SUFFIX = f"+workflow{_RUN_SUFFIX.lower()}"

    @classmethod
    def _make_user(cls, email, password):
        local_part, domain = email.split("@", 1)
        return super()._make_user(
            f"{local_part}{cls.USER_EMAIL_SUFFIX}@{domain}",
            password,
        )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db.session.add(
            VaResearchProjects(
                project_id=cls.BASE_PROJECT_ID,
                project_code=cls.BASE_PROJECT_ID,
                project_name="Workflow Project",
                project_nickname="WorkflowProject",
                project_status=VaStatuses.active,
            )
        )
        db.session.commit()
        db.session.add(
            VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="Workflow Site",
                site_abbr=cls.BASE_SITE_ID,
                site_status=VaStatuses.active,
            )
        )
        db.session.commit()
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="WORKFLOW_FORM",
                odk_project_id="1",
                form_type="WHO_2022_VA",
                form_status=VaStatuses.active,
            )
        )
        db.session.commit()

    def _add_submission(self, sid: str) -> None:
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id=self.FORM_ID,
                va_submission_date=datetime.now(timezone.utc),
                va_odk_updatedat=datetime.now(timezone.utc),
                va_data_collector="tester",
                va_odk_reviewstate=None,
                va_instance_name=sid,
                va_uniqueid_real=None,
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
        db.session.commit()

    def test_infer_ready_for_coding_when_no_active_workflow_records(self):
        sid = "uuid:wf-ready"
        self._add_submission(sid)

        inferred = infer_workflow_state_from_legacy_records(sid)

        self.assertEqual(inferred, WORKFLOW_READY_FOR_CODING)

    def test_reviewer_eligible_is_registered_as_canonical_protected_state(self):
        self.assertIn(WORKFLOW_REVIEWER_ELIGIBLE, ALL_WORKFLOW_STATES)
        self.assertIn(WORKFLOW_REVIEWER_ELIGIBLE, PROTECTED_WORKFLOW_STATES)
        self.assertEqual(
            TRANSITIONS[
                TRANSITION_REVIEWER_ELIGIBLE_AFTER_RECODE_WINDOW
            ].target_state,
            WORKFLOW_REVIEWER_ELIGIBLE,
        )

    def test_consent_refused_is_smartva_blocked_but_not_finalized_protected(self):
        self.assertIn(WORKFLOW_CONSENT_REFUSED, ALL_WORKFLOW_STATES)
        self.assertNotIn(WORKFLOW_CONSENT_REFUSED, PROTECTED_WORKFLOW_STATES)
        self.assertIn(WORKFLOW_CONSENT_REFUSED, SMARTVA_BLOCKED_WORKFLOW_STATES)

    def test_attachment_sync_pending_is_registered_before_smartva(self):
        self.assertIn(WORKFLOW_ATTACHMENT_SYNC_PENDING, ALL_WORKFLOW_STATES)
        self.assertEqual(
            TRANSITIONS[TRANSITION_ATTACHMENTS_SYNCED].target_state,
            WORKFLOW_SMARTVA_PENDING,
        )

    def test_mark_attachment_sync_completed_advances_to_smartva_pending(self):
        sid = "uuid:wf-attachments"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_ATTACHMENT_SYNC_PENDING,
            by_role="vasystem",
            reason="test_seed",
        )
        db.session.commit()

        result = mark_attachment_sync_completed(sid, actor=system_actor())

        self.assertEqual(result.current_state, WORKFLOW_SMARTVA_PENDING)

    def test_infer_coding_in_progress_from_active_allocation(self):
        sid = "uuid:wf-alloc"
        self._add_submission(sid)
        db.session.add(
            VaAllocations(
                va_sid=sid,
                va_allocated_to=self.base_coder_user.user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
            )
        )
        db.session.commit()

        inferred = infer_workflow_state_from_legacy_records(sid)

        self.assertEqual(inferred, WORKFLOW_CODING_IN_PROGRESS)

    def test_infer_step1_saved_from_active_initial_assessment(self):
        sid = "uuid:wf-step1"
        self._add_submission(sid)
        db.session.add(
            VaInitialAssessments(
                va_sid=sid,
                va_iniassess_by=self.base_coder_user.user_id,
                va_immediate_cod="R99",
                va_antecedent_cod="R99",
                va_other_conditions=None,
                va_iniassess_status=VaStatuses.active,
            )
        )
        db.session.commit()

        inferred = infer_workflow_state_from_legacy_records(sid)

        self.assertEqual(inferred, WORKFLOW_CODER_STEP1_SAVED)

    def test_infer_finalized_and_not_codeable_precedence(self):
        sid_final = "uuid:wf-final"
        self._add_submission(sid_final)
        db.session.add(
            VaFinalAssessments(
                va_sid=sid_final,
                va_finassess_by=self.base_coder_user.user_id,
                va_conclusive_cod="R99",
                va_finassess_status=VaStatuses.active,
            )
        )

        sid_error = "uuid:wf-error"
        self._add_submission(sid_error)
        db.session.add(
            VaCoderReview(
                va_sid=sid_error,
                va_creview_by=self.base_coder_user.user_id,
                va_creview_reason="form_is_empty",
                va_creview_other=None,
                va_creview_status=VaStatuses.active,
            )
        )
        db.session.commit()

        self.assertEqual(
            infer_workflow_state_from_legacy_records(sid_final),
            WORKFLOW_CODER_FINALIZED,
        )
        self.assertEqual(
            infer_workflow_state_from_legacy_records(sid_error),
            WORKFLOW_NOT_CODEABLE_BY_CODER,
        )

    def test_infer_data_manager_not_codeable_before_coder_pool(self):
        sid = "uuid:wf-dm"
        self._add_submission(sid)
        db.session.add(
            VaDataManagerReview(
                va_sid=sid,
                va_dmreview_by=self.base_admin_user.user_id,
                va_dmreview_reason="submission_incomplete",
                va_dmreview_other=None,
                va_dmreview_status=VaStatuses.active,
            )
        )
        db.session.commit()

        self.assertEqual(
            infer_workflow_state_from_legacy_records(sid),
            WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
        )

    def test_sync_submission_workflow_creates_and_updates_record(self):
        sid = "uuid:wf-sync"
        self._add_submission(sid)

        workflow = sync_submission_workflow_from_legacy_records(
            sid,
            reason="initial_backfill",
            by_role="vasystem",
        )
        db.session.commit()

        self.assertIsNotNone(workflow.workflow_id)
        self.assertEqual(workflow.workflow_state, WORKFLOW_READY_FOR_CODING)

        updated = set_submission_workflow_state(
            sid,
            WORKFLOW_CODING_IN_PROGRESS,
            reason="manual_transition",
            by_user_id=self.base_coder_user.user_id,
            by_role="vacoder",
        )
        db.session.commit()

        stored = db.session.scalar(
            db.select(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid == sid)
        )
        events = db.session.scalars(
            db.select(VaSubmissionWorkflowEvent)
            .where(VaSubmissionWorkflowEvent.va_sid == sid)
            .order_by(VaSubmissionWorkflowEvent.event_created_at.asc())
        ).all()
        self.assertEqual(updated.workflow_id, stored.workflow_id)
        self.assertEqual(stored.workflow_state, WORKFLOW_CODING_IN_PROGRESS)
        self.assertEqual(stored.workflow_reason, "manual_transition")
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].transition_id, "state_set_direct")
        self.assertIsNone(events[0].previous_state)
        self.assertEqual(events[0].current_state, WORKFLOW_READY_FOR_CODING)
        self.assertEqual(events[1].transition_id, "state_set_direct")
        self.assertEqual(events[1].previous_state, WORKFLOW_READY_FOR_CODING)
        self.assertEqual(events[1].current_state, WORKFLOW_CODING_IN_PROGRESS)

    def test_mark_coding_started_records_structured_workflow_event(self):
        sid = "uuid:wf-event-coding-started"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_READY_FOR_CODING,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        mark_coding_started(
            sid,
            actor=coder_actor(self.base_coder_user.user_id),
        )
        db.session.commit()

        event = db.session.scalar(
            db.select(VaSubmissionWorkflowEvent)
            .where(
                VaSubmissionWorkflowEvent.va_sid == sid,
                VaSubmissionWorkflowEvent.transition_id == "coding_started",
            )
            .order_by(VaSubmissionWorkflowEvent.event_created_at.desc())
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.previous_state, WORKFLOW_READY_FOR_CODING)
        self.assertEqual(event.current_state, WORKFLOW_CODING_IN_PROGRESS)
        self.assertEqual(event.actor_kind, "coder")
        self.assertEqual(event.actor_role, "vacoder")
        self.assertEqual(event.actor_user_id, self.base_coder_user.user_id)

    def test_mark_coding_started_rejects_non_coder_roles(self):
        sid = "uuid:wf-role-coding"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_READY_FOR_CODING,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        with self.assertRaises(WorkflowTransitionError):
            mark_coding_started(
                sid,
                actor=data_manager_actor(self.base_admin_user.user_id),
            )

    def test_mark_smartva_completed_rejects_non_system_roles(self):
        sid = "uuid:wf-role-smartva"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_SMARTVA_PENDING,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        with self.assertRaises(WorkflowTransitionError):
            mark_smartva_completed(
                sid,
                actor=coder_actor(self.base_coder_user.user_id),
            )

    def test_mark_smartva_failed_recorded_moves_pending_to_ready(self):
        sid = "uuid:wf-smartva-failed"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_SMARTVA_PENDING,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        mark_smartva_failed_recorded(
            sid,
            actor=system_actor(),
        )
        db.session.commit()

        self.assertEqual(
            db.session.scalar(
                db.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == sid
                )
            ),
            WORKFLOW_READY_FOR_CODING,
        )

    def test_mark_screening_passed_moves_submission_to_smartva_pending(self):
        sid = "uuid:wf-screen-pass"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_SCREENING_PENDING,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        mark_screening_passed(
            sid,
            actor=data_manager_actor(self.base_admin_user.user_id),
        )
        db.session.commit()

        self.assertEqual(
            db.session.scalar(
                db.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == sid
                )
            ),
            WORKFLOW_SMARTVA_PENDING,
        )

    def test_mark_screening_rejected_moves_submission_to_dm_not_codeable(self):
        sid = "uuid:wf-screen-reject"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_SCREENING_PENDING,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        mark_screening_rejected(
            sid,
            actor=admin_actor(self.base_admin_user.user_id),
        )
        db.session.commit()

        self.assertEqual(
            db.session.scalar(
                db.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == sid
                )
            ),
            WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
        )

    def test_accept_upstream_change_rejects_coder_role(self):
        sid = "uuid:wf-role-upstream"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        with self.assertRaises(WorkflowTransitionError):
            accept_upstream_change(
                sid,
                actor=coder_actor(self.base_coder_user.user_id),
            )

    def test_mark_data_manager_not_codeable_allows_admin_role(self):
        sid = "uuid:wf-role-dm"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_READY_FOR_CODING,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        mark_data_manager_not_codeable(
            sid,
            actor=admin_actor(self.base_admin_user.user_id),
        )
        db.session.commit()

        self.assertEqual(
            db.session.scalar(
                db.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == sid
                )
            ),
            WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
        )

    def test_mark_coder_finalized_allows_admin_role(self):
        sid = "uuid:wf-role-admin-finalize"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_CODING_IN_PROGRESS,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        mark_coder_finalized(
            sid,
            actor=admin_actor(self.base_admin_user.user_id),
        )
        db.session.commit()

        self.assertEqual(
            db.session.scalar(
                db.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == sid
                )
            ),
            WORKFLOW_CODER_FINALIZED,
        )

    def test_mark_recode_started_moves_submission_to_coding_in_progress(self):
        sid = "uuid:wf-role-recode-start"
        self._add_submission(sid)
        start_recode_episode(sid, self.base_admin_user.user_id)
        set_submission_workflow_state(
            sid,
            WORKFLOW_CODER_FINALIZED,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        mark_recode_started(
            sid,
            actor=admin_actor(self.base_admin_user.user_id),
        )
        db.session.commit()

        self.assertEqual(
            db.session.scalar(
                db.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == sid
                )
            ),
            WORKFLOW_CODING_IN_PROGRESS,
        )

    def test_mark_recode_finalized_returns_submission_to_coder_finalized(self):
        sid = "uuid:wf-role-recode-finalized"
        self._add_submission(sid)
        start_recode_episode(sid, self.base_coder_user.user_id)
        set_submission_workflow_state(
            sid,
            WORKFLOW_CODING_IN_PROGRESS,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        mark_recode_finalized(
            sid,
            actor=coder_actor(self.base_coder_user.user_id),
        )
        db.session.commit()

        self.assertEqual(
            db.session.scalar(
                db.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == sid
                )
            ),
            WORKFLOW_CODER_FINALIZED,
        )

    def test_reset_incomplete_recode_returns_submission_to_coder_finalized(self):
        sid = "uuid:wf-role-recode-reset"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_CODING_IN_PROGRESS,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        reset_incomplete_recode(
            sid,
            actor=system_actor(),
            reason="allocation_timeout_release",
        )
        db.session.commit()

        self.assertEqual(
            db.session.scalar(
                db.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == sid
                )
            ),
            WORKFLOW_CODER_FINALIZED,
        )

    def test_admin_override_to_recode_returns_submission_to_ready_for_coding(self):
        sid = "uuid:wf-role-admin-override"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_CODER_FINALIZED,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        mark_admin_override_to_recode(
            sid,
            actor=admin_actor(self.base_admin_user.user_id),
        )
        db.session.commit()

        self.assertEqual(
            db.session.scalar(
                db.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == sid
                )
            ),
            WORKFLOW_READY_FOR_CODING,
        )

    def test_mark_reviewer_eligible_after_recode_window_moves_submission_post_window(self):
        sid = "uuid:wf-role-reviewer-eligible"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_CODER_FINALIZED,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        mark_reviewer_eligible_after_recode_window(
            sid,
            actor=system_actor(),
        )
        db.session.commit()

        self.assertEqual(
            db.session.scalar(
                db.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == sid
                )
            ),
            WORKFLOW_REVIEWER_ELIGIBLE,
        )

    def test_mark_reviewer_coding_started_moves_submission_to_reviewer_in_progress(self):
        sid = "uuid:wf-reviewer-start"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_REVIEWER_ELIGIBLE,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        mark_reviewer_coding_started(
            sid,
            actor=reviewer_actor(self.base_admin_user.user_id),
        )
        db.session.commit()

        self.assertEqual(
            db.session.scalar(
                db.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == sid
                )
            ),
            WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
        )

    def test_mark_reviewer_finalized_moves_submission_to_reviewer_finalized(self):
        sid = "uuid:wf-reviewer-finalized"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        mark_reviewer_finalized(
            sid,
            actor=reviewer_actor(self.base_admin_user.user_id),
        )
        db.session.commit()

        self.assertEqual(
            db.session.scalar(
                db.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == sid
                )
            ),
            WORKFLOW_REVIEWER_FINALIZED,
        )

    def test_accept_upstream_change_allows_admin_role(self):
        sid = "uuid:wf-role-upstream-admin"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        accept_upstream_change(
            sid,
            actor=admin_actor(self.base_admin_user.user_id),
        )
        db.session.commit()

        self.assertEqual(
            db.session.scalar(
                db.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == sid
                )
            ),
            WORKFLOW_SMARTVA_PENDING,
        )

    def test_reset_demo_state_rejects_illegal_source_state(self):
        sid = "uuid:wf-role-demo-reset"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_SMARTVA_PENDING,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        with self.assertRaises(WorkflowTransitionError):
            reset_demo_state(
                sid,
                actor=system_actor(),
            )

    def test_mark_coder_step1_saved_from_ready_for_coding_session_timeout(self):
        """Step 1 save must succeed when allocation timed out (state = ready_for_coding).

        This covers the race where release_stale_coding_allocations resets the
        workflow state back to ready_for_coding while the coder's browser is still
        open. The submission should be accepted rather than returning a 500.
        """
        sid = "uuid:wf-step1-timeout"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_READY_FOR_CODING,
            reason="test_setup_timeout_simulation",
            by_role="vasystem",
        )
        db.session.commit()

        result = mark_coder_step1_saved(
            sid,
            actor=coder_actor(self.base_coder_user.user_id),
        )
        db.session.commit()

        self.assertEqual(result.previous_state, WORKFLOW_READY_FOR_CODING)
        self.assertEqual(result.current_state, WORKFLOW_CODER_STEP1_SAVED)
        stored_state = db.session.scalar(
            db.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == sid
            )
        )
        self.assertEqual(stored_state, WORKFLOW_CODER_STEP1_SAVED)

    def test_reset_incomplete_first_pass_tolerates_ready_for_coding_state(self):
        """release_stale_coding_allocations deactivates the allocation record
        before calling reset_incomplete_first_pass, so by the time the reset
        runs, infer_workflow_state_after_coding_release returns ready_for_coding
        (no active allocation found). The reset must succeed idempotently when
        the recorded state is already ready_for_coding.
        """
        sid = "uuid:wf-reset-ready"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_READY_FOR_CODING,
            reason="test_setup_inconsistent_state",
            by_role="vasystem",
        )
        db.session.commit()

        result = reset_incomplete_first_pass(sid, actor=system_actor())
        db.session.commit()

        self.assertEqual(result.previous_state, WORKFLOW_READY_FOR_CODING)
        self.assertEqual(result.current_state, WORKFLOW_READY_FOR_CODING)
        stored_state = db.session.scalar(
            db.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == sid
            )
        )
        self.assertEqual(stored_state, WORKFLOW_READY_FOR_CODING)

    def test_reset_incomplete_first_pass_tolerates_coder_finalized_state(self):
        """Timeout release can race with finalization and should remain idempotent."""
        sid = "uuid:wf-reset-finalized"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_CODER_FINALIZED,
            reason="test_setup_inconsistent_state",
            by_role="vasystem",
        )
        db.session.add(
            VaFinalAssessments(
                va_sid=sid,
                va_finassess_by=self.base_coder_user.user_id,
                va_conclusive_cod="I21",
                va_finassess_status=VaStatuses.active,
            )
        )
        db.session.commit()

        result = reset_incomplete_first_pass(sid, actor=system_actor())
        db.session.commit()

        self.assertEqual(result.previous_state, WORKFLOW_CODER_FINALIZED)
        self.assertEqual(result.current_state, WORKFLOW_CODER_FINALIZED)
        stored_state = db.session.scalar(
            db.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == sid
            )
        )
        self.assertEqual(stored_state, WORKFLOW_CODER_FINALIZED)
        transition_events = db.session.scalars(
            db.select(VaSubmissionWorkflowEvent).where(
                VaSubmissionWorkflowEvent.va_sid == sid,
                VaSubmissionWorkflowEvent.transition_id
                == "incomplete_first_pass_reset",
            )
        ).all()
        self.assertEqual(len(transition_events), 0)
