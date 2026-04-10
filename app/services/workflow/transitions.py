"""Named workflow-transition execution for submissions.

This is the process-execution layer over the declarative workflow definition.
Callers should use these transition functions instead of writing workflow state
directly.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Iterable
from uuid import UUID

from app import db
from app.models import VaCodingEpisode
from app.services.workflow import definition as wd
from app.services.workflow.events import record_workflow_event
from app.services.workflow.state_store import (
    infer_workflow_state_after_coding_release,
    get_submission_workflow_record,
    set_submission_workflow_state,
)

log = logging.getLogger(__name__)


class WorkflowTransitionError(ValueError):
    """Raised when a requested workflow transition is not allowed."""


ACTOR_SYSTEM = "system"
ACTOR_ADMIN = "admin"
ACTOR_CODER = "coder"
ACTOR_DATA_MANAGER = "data_manager"
ACTOR_REVIEWER = "reviewer"

SYSTEM_ACTOR_KINDS = frozenset({ACTOR_SYSTEM, ACTOR_ADMIN})
CODING_ACTOR_KINDS = frozenset({ACTOR_CODER, ACTOR_ADMIN})
DATA_MANAGER_ACTOR_KINDS = frozenset({ACTOR_DATA_MANAGER, ACTOR_ADMIN})
REVIEWER_ACTOR_KINDS = frozenset({ACTOR_REVIEWER})
ADMIN_ACTOR_KINDS = frozenset({ACTOR_ADMIN})
SYNC_SOURCE_STATES = (
    None,
    wd.WORKFLOW_CONSENT_REFUSED,
    wd.WORKFLOW_SCREENING_PENDING,
    wd.WORKFLOW_ATTACHMENT_SYNC_PENDING,
    wd.WORKFLOW_SMARTVA_PENDING,
    wd.WORKFLOW_READY_FOR_CODING,
    wd.WORKFLOW_CODING_IN_PROGRESS,
    wd.WORKFLOW_CODER_STEP1_SAVED,
    wd.WORKFLOW_NOT_CODEABLE_BY_CODER,
    wd.WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
)


@dataclass(frozen=True)
class TransitionResult:
    va_sid: str
    transition_id: str
    previous_state: str | None
    current_state: str


@dataclass(frozen=True)
class WorkflowActor:
    kind: str
    audit_role: str
    user_id: UUID | None = None


def system_actor() -> WorkflowActor:
    return WorkflowActor(kind=ACTOR_SYSTEM, audit_role="vasystem")


def admin_actor(user_id: UUID | None) -> WorkflowActor:
    return WorkflowActor(kind=ACTOR_ADMIN, audit_role="vaadmin", user_id=user_id)


def coder_actor(user_id: UUID | None) -> WorkflowActor:
    return WorkflowActor(kind=ACTOR_CODER, audit_role="vacoder", user_id=user_id)


def data_manager_actor(user_id: UUID | None) -> WorkflowActor:
    return WorkflowActor(
        kind=ACTOR_DATA_MANAGER,
        audit_role="data_manager",
        user_id=user_id,
    )


def reviewer_actor(user_id: UUID | None) -> WorkflowActor:
    return WorkflowActor(kind=ACTOR_REVIEWER, audit_role="reviewer", user_id=user_id)


def _apply_transition(
    va_sid: str,
    *,
    transition_id: str,
    target_state: str,
    allowed_from: Iterable[str] | None = None,
    allowed_actor_kinds: Iterable[str] | None = None,
    reason: str,
    actor: WorkflowActor | None = None,
) -> TransitionResult:
    workflow_record = get_submission_workflow_record(va_sid, for_update=True)
    previous_state = workflow_record.workflow_state if workflow_record else None
    normalized_actor = actor or system_actor()
    if allowed_from is not None and previous_state not in set(allowed_from):
        raise WorkflowTransitionError(
            f"Transition {transition_id} not allowed from state {previous_state!r}."
        )
    if (
        allowed_actor_kinds is not None
        and normalized_actor.kind not in set(allowed_actor_kinds)
    ):
        raise WorkflowTransitionError(
            f"Transition {transition_id} not allowed for actor kind "
            f"{normalized_actor.kind!r}."
        )

    set_submission_workflow_state(
        va_sid,
        target_state,
        reason=reason,
        by_user_id=normalized_actor.user_id,
        by_role=normalized_actor.audit_role,
        record=workflow_record,
        emit_event=False,
    )
    record_workflow_event(
        va_sid,
        transition_id=transition_id,
        previous_state=previous_state,
        current_state=target_state,
        actor_kind=normalized_actor.kind,
        actor_role=normalized_actor.audit_role,
        actor_user_id=normalized_actor.user_id,
        reason=reason,
    )
    log.info(
        "workflow transition=%s va_sid=%s previous_state=%s current_state=%s by_role=%s by_user=%s reason=%s",
        transition_id,
        va_sid,
        previous_state,
        target_state,
        normalized_actor.audit_role,
        normalized_actor.user_id,
        reason,
    )
    return TransitionResult(
        va_sid=va_sid,
        transition_id=transition_id,
        previous_state=previous_state,
        current_state=target_state,
    )


def _has_active_recode_episode(va_sid: str) -> bool:
    return bool(
        db.session.scalar(
            db.select(VaCodingEpisode.episode_id).where(
                VaCodingEpisode.va_sid == va_sid,
                VaCodingEpisode.episode_type == "recode",
                VaCodingEpisode.episode_status == "active",
            )
        )
    )


def _apply_release_reset_transition(
    va_sid: str,
    *,
    transition_id: str,
    allowed_from: Iterable[str] | None,
    allowed_actor_kinds: Iterable[str] | None,
    reason: str,
    actor: WorkflowActor | None,
) -> TransitionResult:
    workflow_record = get_submission_workflow_record(va_sid, for_update=True)
    previous_state = workflow_record.workflow_state if workflow_record else None
    normalized_actor = actor or system_actor()
    if allowed_from is not None and previous_state not in set(allowed_from):
        raise WorkflowTransitionError(
            f"Transition {transition_id} not allowed from state {previous_state!r}."
        )
    if (
        allowed_actor_kinds is not None
        and normalized_actor.kind not in set(allowed_actor_kinds)
    ):
        raise WorkflowTransitionError(
            f"Transition {transition_id} not allowed for actor kind "
            f"{normalized_actor.kind!r}."
        )

    target_state = infer_workflow_state_after_coding_release(va_sid)
    set_submission_workflow_state(
        va_sid,
        target_state,
        reason=reason,
        by_user_id=normalized_actor.user_id,
        by_role=normalized_actor.audit_role,
        record=workflow_record,
        emit_event=False,
    )
    record_workflow_event(
        va_sid,
        transition_id=transition_id,
        previous_state=previous_state,
        current_state=target_state,
        actor_kind=normalized_actor.kind,
        actor_role=normalized_actor.audit_role,
        actor_user_id=normalized_actor.user_id,
        reason=reason,
    )
    log.info(
        "workflow transition=%s va_sid=%s previous_state=%s current_state=%s by_role=%s by_user=%s reason=%s",
        transition_id,
        va_sid,
        previous_state,
        target_state,
        normalized_actor.audit_role,
        normalized_actor.user_id,
        reason,
    )
    return TransitionResult(
        va_sid=va_sid,
        transition_id=transition_id,
        previous_state=previous_state,
        current_state=target_state,
    )


def route_synced_submission(
    va_sid: str,
    *,
    consent_valid: bool,
    reason: str = "submission_synced",
    actor: WorkflowActor | None = None,
) -> TransitionResult:
    target_state = (
        wd.WORKFLOW_ATTACHMENT_SYNC_PENDING
        if consent_valid
        else wd.WORKFLOW_CONSENT_REFUSED
    )
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_SYNC_NEW_PAYLOAD,
        target_state=target_state,
        allowed_from=SYNC_SOURCE_STATES,
        allowed_actor_kinds=SYSTEM_ACTOR_KINDS,
        reason=reason,
        actor=actor or system_actor(),
    )


def mark_attachment_sync_completed(
    va_sid: str,
    *,
    reason: str = "attachments_synced_for_current_payload",
    actor: WorkflowActor | None = None,
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_ATTACHMENTS_SYNCED,
        target_state=wd.WORKFLOW_SMARTVA_PENDING,
        allowed_from=(wd.WORKFLOW_ATTACHMENT_SYNC_PENDING,),
        allowed_actor_kinds=SYSTEM_ACTOR_KINDS,
        reason=reason,
        actor=actor or system_actor(),
    )


def mark_upstream_change_detected(
    va_sid: str,
    *,
    reason: str = "upstream_odk_data_changed",
    actor: WorkflowActor | None = None,
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_UPSTREAM_CHANGE_DETECTED,
        target_state=wd.WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
        allowed_from=(
            wd.WORKFLOW_CODER_FINALIZED,
            wd.WORKFLOW_REVIEWER_ELIGIBLE,
            wd.WORKFLOW_REVIEWER_FINALIZED,
            wd.WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
        ),
        allowed_actor_kinds=SYSTEM_ACTOR_KINDS,
        reason=reason,
        actor=actor or system_actor(),
    )


def mark_smartva_completed(
    va_sid: str,
    *,
    reason: str = "smartva_completed_for_current_payload",
    actor: WorkflowActor | None = None,
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_SMARTVA_COMPLETED,
        target_state=wd.WORKFLOW_READY_FOR_CODING,
        allowed_from=(wd.WORKFLOW_SMARTVA_PENDING,),
        allowed_actor_kinds=SYSTEM_ACTOR_KINDS,
        reason=reason,
        actor=actor or system_actor(),
    )


def mark_smartva_failed_recorded(
    va_sid: str,
    *,
    reason: str = "smartva_failed_for_current_payload",
    actor: WorkflowActor | None = None,
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_SMARTVA_FAILED_RECORDED,
        target_state=wd.WORKFLOW_READY_FOR_CODING,
        allowed_from=(wd.WORKFLOW_SMARTVA_PENDING,),
        allowed_actor_kinds=SYSTEM_ACTOR_KINDS,
        reason=reason,
        actor=actor or system_actor(),
    )


def mark_screening_passed(
    va_sid: str,
    *,
    actor: WorkflowActor,
    reason: str = "screening_passed",
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_SCREENING_PASSED,
        target_state=wd.WORKFLOW_SMARTVA_PENDING,
        allowed_from=(wd.WORKFLOW_SCREENING_PENDING,),
        allowed_actor_kinds=DATA_MANAGER_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def mark_screening_rejected(
    va_sid: str,
    *,
    actor: WorkflowActor,
    reason: str = "screening_rejected",
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_SCREENING_REJECTED,
        target_state=wd.WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
        allowed_from=(wd.WORKFLOW_SCREENING_PENDING,),
        allowed_actor_kinds=DATA_MANAGER_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def mark_coding_started(
    va_sid: str,
    *,
    actor: WorkflowActor,
    reason: str = "coding_started",
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_CODING_STARTED,
        target_state=wd.WORKFLOW_CODING_IN_PROGRESS,
        allowed_from=(wd.WORKFLOW_READY_FOR_CODING,),
        allowed_actor_kinds=CODING_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def mark_recode_started(
    va_sid: str,
    *,
    actor: WorkflowActor,
    reason: str = "recode_started",
) -> TransitionResult:
    if not _has_active_recode_episode(va_sid):
        raise WorkflowTransitionError(
            "Transition recode_started requires an active recode episode."
        )
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_RECODE_STARTED,
        target_state=wd.WORKFLOW_CODING_IN_PROGRESS,
        allowed_from=(
            wd.WORKFLOW_CODER_FINALIZED,
            wd.WORKFLOW_READY_FOR_CODING,
        ),
        allowed_actor_kinds=CODING_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def mark_coder_step1_saved(
    va_sid: str,
    *,
    actor: WorkflowActor,
    reason: str = "initial_cod_submitted",
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_CODER_STEP1_SAVED,
        target_state=wd.WORKFLOW_CODER_STEP1_SAVED,
        allowed_from=(
            wd.WORKFLOW_CODING_IN_PROGRESS,
            wd.WORKFLOW_READY_FOR_CODING,  # session timed out mid-coding
        ),
        allowed_actor_kinds=CODING_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def mark_coder_finalized(
    va_sid: str,
    *,
    actor: WorkflowActor,
    reason: str = "final_cod_submitted",
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_CODER_FINALIZED,
        target_state=wd.WORKFLOW_CODER_FINALIZED,
        allowed_from=(
            wd.WORKFLOW_CODER_STEP1_SAVED,
            wd.WORKFLOW_CODING_IN_PROGRESS,
        ),
        allowed_actor_kinds=CODING_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def mark_recode_finalized(
    va_sid: str,
    *,
    actor: WorkflowActor,
    reason: str = "recode_finalized",
) -> TransitionResult:
    if not _has_active_recode_episode(va_sid):
        raise WorkflowTransitionError(
            "Transition recode_finalized requires an active recode episode."
        )
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_RECODE_FINALIZED,
        target_state=wd.WORKFLOW_CODER_FINALIZED,
        allowed_from=(
            wd.WORKFLOW_CODER_STEP1_SAVED,
            wd.WORKFLOW_CODING_IN_PROGRESS,
        ),
        allowed_actor_kinds=CODING_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def mark_coder_not_codeable(
    va_sid: str,
    *,
    actor: WorkflowActor,
    reason: str = "coder_marked_not_codeable",
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_CODER_NOT_CODEABLE,
        target_state=wd.WORKFLOW_NOT_CODEABLE_BY_CODER,
        allowed_from=(
            wd.WORKFLOW_CODING_IN_PROGRESS,
            wd.WORKFLOW_CODER_STEP1_SAVED,
        ),
        allowed_actor_kinds=CODING_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def mark_data_manager_not_codeable(
    va_sid: str,
    *,
    actor: WorkflowActor,
    reason: str = "data_manager_marked_not_codeable",
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_DM_NOT_CODEABLE,
        target_state=wd.WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
        allowed_from=(
            wd.WORKFLOW_SCREENING_PENDING,
            wd.WORKFLOW_SMARTVA_PENDING,
            wd.WORKFLOW_READY_FOR_CODING,
            wd.WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
        ),
        allowed_actor_kinds=DATA_MANAGER_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def mark_admin_override_to_recode(
    va_sid: str,
    *,
    actor: WorkflowActor,
    reason: str = "admin_override_to_recode",
) -> TransitionResult:
    # Admin may reset from coder_finalized or reviewer_eligible. Both are
    # post-finalization protected states where no active session exists and
    # the submission can safely be returned to the coder pool.
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_ADMIN_OVERRIDE_TO_RECODE,
        target_state=wd.WORKFLOW_READY_FOR_CODING,
        allowed_from=(
            wd.WORKFLOW_CODER_FINALIZED,
            wd.WORKFLOW_REVIEWER_ELIGIBLE,
        ),
        allowed_actor_kinds=ADMIN_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def accept_upstream_change(
    va_sid: str,
    *,
    actor: WorkflowActor,
    reason: str = "upstream_change_accepted",
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_UPSTREAM_CHANGE_ACCEPTED,
        target_state=wd.WORKFLOW_SMARTVA_PENDING,
        allowed_from=(wd.WORKFLOW_FINALIZED_UPSTREAM_CHANGED,),
        allowed_actor_kinds=DATA_MANAGER_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def reject_upstream_change(
    va_sid: str,
    *,
    actor: WorkflowActor,
    target_state: str = wd.WORKFLOW_CODER_FINALIZED,
    reason: str = "upstream_change_rejected",
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_UPSTREAM_CHANGE_REJECTED,
        target_state=target_state,
        allowed_from=(wd.WORKFLOW_FINALIZED_UPSTREAM_CHANGED,),
        allowed_actor_kinds=DATA_MANAGER_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def keep_current_icd_on_upstream_change(
    va_sid: str,
    *,
    actor: WorkflowActor,
    target_state: str = wd.WORKFLOW_CODER_FINALIZED,
    reason: str = "upstream_change_kept_current_icd",
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_UPSTREAM_CHANGE_KEPT_CURRENT_ICD,
        target_state=target_state,
        allowed_from=(wd.WORKFLOW_FINALIZED_UPSTREAM_CHANGED,),
        allowed_actor_kinds=DATA_MANAGER_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def mark_demo_started(
    va_sid: str,
    *,
    actor: WorkflowActor,
    reason: str = "demo_coder_allocation_created",
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_DEMO_STARTED,
        target_state=wd.WORKFLOW_CODING_IN_PROGRESS,
        allowed_from=(wd.WORKFLOW_READY_FOR_CODING,),
        allowed_actor_kinds=CODING_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def reset_incomplete_first_pass(
    va_sid: str,
    *,
    actor: WorkflowActor | None = None,
    reason: str = "allocation_timeout_release",
) -> TransitionResult:
    return _apply_release_reset_transition(
        va_sid,
        transition_id=wd.TRANSITION_INCOMPLETE_FIRST_PASS_RESET,
        allowed_from=(
            None,
            wd.WORKFLOW_CODING_IN_PROGRESS,
            wd.WORKFLOW_CODER_STEP1_SAVED,
            wd.WORKFLOW_READY_FOR_CODING,  # allocation deactivated before reset; state already correct
        ),
        allowed_actor_kinds=SYSTEM_ACTOR_KINDS,
        reason=reason,
        actor=actor or system_actor(),
    )


def reset_incomplete_recode(
    va_sid: str,
    *,
    actor: WorkflowActor | None = None,
    reason: str = "allocation_timeout_release",
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_INCOMPLETE_RECODE_RESET,
        target_state=wd.WORKFLOW_CODER_FINALIZED,
        allowed_from=(
            None,
            wd.WORKFLOW_CODING_IN_PROGRESS,
            wd.WORKFLOW_CODER_STEP1_SAVED,
        ),
        allowed_actor_kinds=SYSTEM_ACTOR_KINDS,
        reason=reason,
        actor=actor or system_actor(),
    )


def mark_reviewer_eligible_after_recode_window(
    va_sid: str,
    *,
    actor: WorkflowActor | None = None,
    reason: str = "reviewer_eligible_after_recode_window",
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_REVIEWER_ELIGIBLE_AFTER_RECODE_WINDOW,
        target_state=wd.WORKFLOW_REVIEWER_ELIGIBLE,
        allowed_from=(wd.WORKFLOW_CODER_FINALIZED,),
        allowed_actor_kinds=SYSTEM_ACTOR_KINDS,
        reason=reason,
        actor=actor or system_actor(),
    )


def mark_reviewer_coding_started(
    va_sid: str,
    *,
    actor: WorkflowActor,
    reason: str = "reviewer_allocation_created",
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_REVIEWER_CODING_STARTED,
        target_state=wd.WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
        allowed_from=(wd.WORKFLOW_REVIEWER_ELIGIBLE,),
        allowed_actor_kinds=REVIEWER_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def reset_incomplete_reviewer_session(
    va_sid: str,
    *,
    actor: WorkflowActor | None = None,
    reason: str = "reviewer_allocation_timeout_release",
) -> TransitionResult:
    """Revert a timed-out reviewer session to reviewer_eligible.

    Reviewer sessions follow first-pass coder behaviour: the final COD
    submission is the only terminal action. If the session times out before
    that, all intermediate artifacts (VaReviewerReview, VaNarrativeAssessment,
    VaSocialAutopsyAnalysis filled by the reviewer) must be deactivated by the
    caller before invoking this transition. The case returns to
    reviewer_eligible so a reviewer may start a fresh session.
    """
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_INCOMPLETE_REVIEWER_RESET,
        target_state=wd.WORKFLOW_REVIEWER_ELIGIBLE,
        allowed_from=(wd.WORKFLOW_REVIEWER_CODING_IN_PROGRESS,),
        allowed_actor_kinds=SYSTEM_ACTOR_KINDS,
        reason=reason,
        actor=actor or system_actor(),
    )


def mark_reviewer_finalized(
    va_sid: str,
    *,
    actor: WorkflowActor,
    reason: str = "reviewer_final_cod_submitted",
) -> TransitionResult:
    return _apply_transition(
        va_sid,
        transition_id=wd.TRANSITION_REVIEWER_FINALIZED,
        target_state=wd.WORKFLOW_REVIEWER_FINALIZED,
        allowed_from=(wd.WORKFLOW_REVIEWER_CODING_IN_PROGRESS,),
        allowed_actor_kinds=REVIEWER_ACTOR_KINDS,
        reason=reason,
        actor=actor,
    )


def reset_demo_state(
    va_sid: str,
    *,
    actor: WorkflowActor | None = None,
    reason: str = "demo_retention_cleanup",
) -> TransitionResult:
    return _apply_release_reset_transition(
        va_sid,
        transition_id=wd.TRANSITION_DEMO_RESET,
        allowed_from=(
            wd.WORKFLOW_CODING_IN_PROGRESS,
            wd.WORKFLOW_CODER_STEP1_SAVED,
            wd.WORKFLOW_CODER_FINALIZED,
            wd.WORKFLOW_NOT_CODEABLE_BY_CODER,
        ),
        allowed_actor_kinds=SYSTEM_ACTOR_KINDS,
        reason=reason,
        actor=actor or system_actor(),
    )
