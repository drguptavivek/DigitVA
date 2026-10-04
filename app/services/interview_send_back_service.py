"""A coder or reviewer sends a submitted web or device interview back for
revision; a supervisor, data manager or admin reopens it after final COD
(docs/policy/interview-revisions.md, rules 3 and 4).

Both move the submission to ``finalized_upstream_changed`` through
``mark_upstream_change_detected`` with the transition reason
``sent_back_for_revision`` / ``reopened_for_revision``; that event is what
``revision_unlocked`` reads, and what a data manager's reject cancels. Coding
artifacts and the final COD are left active until the interviewer's revision
arrives (``reopen_coding_after_revision``), so the earlier COD stays visible
meanwhile. ODK submissions are refused: ODK has its own needs-revision path.
The caller commits.
"""
from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaDeathRegister,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaWebIntakeDraft,
)
from app.services import case_transition_service as cases
from app.services import notification_service
from app.services.authz import Action, Reason, can, supervision
from app.services.case_transition_service import WebIntakeError
from app.services.coding_allocation_service import release_reviewer_session_for_send_back
from app.services.duplicate_exclusion import is_confirmed_duplicate
from app.services.final_cod_authority_service import get_authoritative_final_assessment
from app.services.reviewer_final_assessment_service import (
    get_latest_active_reviewer_final_assessment,
)
from app.services.workflow.definition import (
    PROTECTED_WORKFLOW_STATES,
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
)
from app.services.workflow.state_store import get_submission_workflow_state
from app.services.workflow.transitions import (
    WorkflowActor,
    WorkflowTransitionError,
    admin_actor,
    coder_actor,
    data_manager_actor,
    interview_supervisor_actor,
    mark_upstream_change_detected,
    reviewer_actor,
)

#: Fixed reasons, no free text: a reason carries no personal data.
SEND_BACK_REASONS = ("missing_information", "inconsistent_answers", "wrong_respondent_or_case", "needs_clarification")
REOPEN_REASONS = ("cod_review_requested", "new_information", "data_correction")

#: Every protected state but ``finalized_upstream_changed`` (already open).
_SEND_BACK_STATES = PROTECTED_WORKFLOW_STATES - {WORKFLOW_FINALIZED_UPSTREAM_CHANGED}
#: The states holding a final COD. An active reviewer session is not one: the
#: reviewer sends it back, or the session ends first.
_REOPEN_STATES = frozenset({WORKFLOW_CODER_FINALIZED, WORKFLOW_REVIEWER_ELIGIBLE, WORKFLOW_REVIEWER_FINALIZED})

SENT_BACK = "sent_back_for_revision"
REOPENED = "reopened_for_revision"


def _check_reason(reason_code: object, allowed: tuple[str, ...]) -> None:
    if reason_code not in allowed:
        raise WebIntakeError("reason_code must be one of: " + ", ".join(allowed) + ".", 422, "invalid_reason")


def _web_draft(va_sid: str) -> VaWebIntakeDraft | None:
    """The submitted web or device draft behind *va_sid* (one lookup on the
    partial ``va_sid`` index); None for an ODK submission."""
    return db.session.scalar(
        sa.select(VaWebIntakeDraft).where(VaWebIntakeDraft.va_sid == va_sid, VaWebIntakeDraft.status == "submitted")
    )


def _scope(user, va_sid: str):
    """The caller's coding and reviewing decisions on *va_sid*; 404 when it
    does not exist for them, 403 when neither scope reaches it. Asked before
    any lock, so an outsider holds nothing."""
    coding, reviewing = can(user, Action.RECODE, va_sid), can(user, Action.REVIEW, va_sid)
    if coding or reviewing:
        return coding, reviewing
    if Reason.NOT_FOUND in (coding.reason, reviewing.reason):
        raise WebIntakeError("Submission not found.", 404)
    raise WebIntakeError("You may not send this interview back.", 403)


def _sender(user, va_sid: str, state: str | None, coding, reviewing) -> WorkflowActor:
    """The workflow actor *user* sends *va_sid* back as, else 403.

    A coder in their coding scope who authored the authoritative final COD
    (``coder_finalized``, ``reviewer_eligible``); a reviewer in their
    reviewing scope on a ``reviewer_eligible`` submission, on the one whose
    session they hold (``reviewer_coding_in_progress``), or on the one they
    finalised (``reviewer_finalized``). An allocation held by a coder exists
    only in states the interviewer can already revise, so it grants nothing
    here.
    """
    if coding and state in (WORKFLOW_CODER_FINALIZED, WORKFLOW_REVIEWER_ELIGIBLE):
        final = get_authoritative_final_assessment(va_sid)
        if final is not None and final.va_finassess_by == user.user_id:
            return coder_actor(user.user_id)
    if reviewing:
        if state == WORKFLOW_REVIEWER_ELIGIBLE:
            return reviewer_actor(user.user_id)
        if state == WORKFLOW_REVIEWER_CODING_IN_PROGRESS and db.session.scalar(
            sa.select(sa.exists().where(
                VaAllocations.va_sid == va_sid,
                VaAllocations.va_allocated_to == user.user_id,
                VaAllocations.va_allocation_for == VaAllocation.reviewing,
                VaAllocations.va_allocation_status == VaStatuses.active,
            ))
        ):
            return reviewer_actor(user.user_id)
        if state == WORKFLOW_REVIEWER_FINALIZED:
            final = get_latest_active_reviewer_final_assessment(va_sid)
            if final is not None and final.va_rfinassess_by == user.user_id:
                return reviewer_actor(user.user_id)
    raise WebIntakeError("You may not send this interview back.", 403)


def _open_for_revision(user, va_sid: str, draft: VaWebIntakeDraft, actor: WorkflowActor, *, transition_reason: str, reason_code: str) -> dict:
    """The transition, its audit row and the interviewer's nudge, under the
    submission lock."""
    try:
        mark_upstream_change_detected(va_sid, reason=transition_reason, actor=actor)
    except WorkflowTransitionError as exc:
        raise WebIntakeError("The interview changed state; try again.", 409, "wrong_state") from exc
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid,
        va_audit_byrole=actor.audit_role,
        va_audit_by=user.user_id,
        va_audit_operation="u",
        va_audit_action=f"{transition_reason}:{reason_code}",
    ))
    db.session.flush()
    if draft.user_id != user.user_id:
        notification_service.notify(
            [draft.user_id], notification_service.REVISION_REQUESTED, project_id=draft.project_id,
            death_id=draft.death_id, draft_id=draft.draft_id, va_sid=va_sid,
        )
    return {"va_sid": va_sid, "workflow_state": WORKFLOW_FINALIZED_UPSTREAM_CHANGED, "reason_code": reason_code}


def send_back_for_revision(user, va_sid: str, *, reason_code: str) -> dict:
    """Send the web or device interview *va_sid* back to its interviewer;
    returns ``{va_sid, workflow_state, reason_code}``.

    Refusals: 422 ``invalid_reason``; 404 unknown or out of the caller's
    scope; 403 in scope but not the coder who finalised it nor a reviewer
    working on or eligible for it (``_sender``); 409 ``not_web_submission``
    (an ODK submission), ``case_closed`` (a confirmed duplicate), ``wrong_state``
    (not a protected state, or already sent back). A reviewer's unfinished session is released first.
    """
    _check_reason(reason_code, SEND_BACK_REASONS)
    coding, reviewing = _scope(user, va_sid)
    db.session.get(VaSubmissions, va_sid, with_for_update=True)
    state = get_submission_workflow_state(va_sid)  # read under the lock
    draft = _web_draft(va_sid)
    if draft is None:
        raise WebIntakeError("Only a web or device interview can be sent back here; ODK has its own needs-revision path.", 409, "not_web_submission")
    if is_confirmed_duplicate(va_sid):
        raise WebIntakeError("This case is closed.", 409, "case_closed")
    if state not in _SEND_BACK_STATES:
        raise WebIntakeError("This interview is not in a state that can be sent back.", 409, "wrong_state")
    actor = _sender(user, va_sid, state, coding, reviewing)
    if state == WORKFLOW_REVIEWER_CODING_IN_PROGRESS:
        try:
            release_reviewer_session_for_send_back(va_sid)
        except WorkflowTransitionError as exc:
            # The reviewer finalised or the session timed out meanwhile.
            raise WebIntakeError("The interview changed state; try again.", 409, "wrong_state") from exc
    return _open_for_revision(user, va_sid, draft, actor, transition_reason=SENT_BACK, reason_code=reason_code)


def reopen_for_revision(user, va_sid: str, *, reason_code: str) -> dict:
    """Reopen the finalised web or device interview *va_sid* for its
    interviewer; returns ``{va_sid, workflow_state, reason_code}``.

    Who: an admin; a supervisor or data manager whose supervision reach
    covers the interview's case (``is_interview_supervisor_for``), or, for an
    interview with no case, a data manager of its scope (``TRIAGE``).
    Refusals: 422 ``invalid_reason``; 404 unknown or out of reach; 409
    ``not_web_submission``, ``case_closed`` (a confirmed duplicate), ``wrong_state`` (no final COD yet, a reviewer
    session live, or already open for revision).
    """
    _check_reason(reason_code, REOPEN_REASONS)
    if db.session.get(VaSubmissions, va_sid) is None:
        raise WebIntakeError("Submission not found.", 404)
    draft = _web_draft(va_sid)
    death = db.session.get(VaDeathRegister, draft.death_id) if draft is not None and draft.death_id else None
    if user.is_admin():
        actor = admin_actor(user.user_id)
    elif death is not None and cases.is_interview_supervisor_for(user, death):
        # Audited as what they are: a data-manager shaped grant (data manager,
        # In-charge, project PI) reads data_manager, an interview_supervisor grant supervisor.
        shaped = supervision.dm_shaped_grant(user.user_id, death)
        actor = data_manager_actor(user.user_id) if shaped else interview_supervisor_actor(user.user_id)
    elif death is None and can(user, Action.TRIAGE, va_sid):
        actor = data_manager_actor(user.user_id)
    else:
        raise WebIntakeError("Submission not found.", 404)
    if draft is None:
        raise WebIntakeError("Only a web or device interview can be reopened here; ODK has its own reopen path.", 409, "not_web_submission")
    db.session.get(VaSubmissions, va_sid, with_for_update=True)
    if is_confirmed_duplicate(va_sid):
        raise WebIntakeError("This case is closed.", 409, "case_closed")
    if get_submission_workflow_state(va_sid) not in _REOPEN_STATES:
        raise WebIntakeError("Only an interview with a final COD can be reopened.", 409, "wrong_state")
    return _open_for_revision(user, va_sid, draft, actor, transition_reason=REOPENED, reason_code=reason_code)
