"""A supervisor chooses between two complete interviews (digitva-bqzm).

Part of the web intake service split (bead digitva-r8nh.12); the public
module is ``app.services.web_intake_service``, which re-exports every name.
Code that tests patch on that module is read back through ``facade()``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    VaDeathRegister,
    VaForms,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUsers,
    VaWebIntakeDraft,
)
from app.services import case_transition_service as cases
from app.services import (
    notification_service,
    smartva_service,
)
from app.services import web_intake_attachment_service as attachments
from app.services.authz import supervision
from app.services.case_transition_service import WebIntakeError
from app.services.coding_release_service import (
    SOURCE_SUPERVISOR_CHOICE,
    release_coding_for_changed_payload,
    reopen_coding_after_revision,
)
from app.services.submission_payload_version_service import (
    ensure_active_payload_version,
    get_active_payload_version,
    get_latest_pending_upstream_payload_version,
    opened_payload,
    reject_pending_upstream_payload_version,
)
from app.services.va_data_sync.va_data_sync_01_odkcentral import (
    apply_submission_projection,
    build_submission_projection,
    consent_is_valid,
    normalize_consent,
)
from app.services.web_intake import facade
from app.services.web_intake.common import (
    _device_time,
    _expression_now,
    log,
)
from app.services.web_intake.drafts import (
    _answers_of,
    _sync_case_identity,
)
from app.services.web_intake.submission import (
    build_final_payload,
)
from app.services.workflow.definition import (
    PROTECTED_WORKFLOW_STATES,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
)
from app.services.workflow.state_store import get_submission_workflow_state
from app.services.workflow.transitions import (
    INTERVIEW_CHOSEN_REASON,
    WorkflowTransitionError,
    admin_actor,
    data_manager_actor,
    interview_supervisor_actor,
    mark_attachment_sync_completed,
    mark_upstream_change_detected,
    system_actor,
)
from app.services.workflow.upstream_changes import (
    UPSTREAM_CHANGE_STATUS_REJECTED,
    resolve_pending_upstream_change,
)

#: Fixed reasons for a choice; no free text, so a reason carries no personal data.
CHOICE_REASONS = ("better_quality", "more_complete", "original_incorrect", "switch_back")


#: Most candidates one case detail lists (a case rarely has more than one).
CANDIDATES_MAX = 20


def _candidate_condition():
    """SQL condition on ``VaWebIntakeDraft``: a candidate for the case's
    interview, a ``superseded`` copy whose interview was complete. A ``replaced``
    row (history of a resend) and an incomplete copy never qualify."""
    return sa.and_(
        VaWebIntakeDraft.status == "superseded",
        VaWebIntakeDraft.meta["interviewOutcome"].astext == "completed",
    )


def _has_candidate():
    """Correlated EXISTS on ``VaDeathRegister``: the submitted case has a
    candidate, i.e. a second complete interview exists. One probe on
    ``ix_va_web_intake_drafts_death`` per case row."""
    return sa.exists().where(
        VaWebIntakeDraft.death_id == VaDeathRegister.death_id,
        _candidate_condition(),
        VaDeathRegister.status == "submitted",
        VaDeathRegister.va_sid.is_not(None),
    )


def list_candidates(death: VaDeathRegister, *, redact_names: bool = False) -> list[dict]:
    """The other complete interviews of a submitted case a supervisor may
    choose, newest first: ``{draft_id, interviewer_name, completed_at,
    outcome}``. Names are for supervisors only (staff identity, as the
    supervision list shows who registered a case); never serve this to an
    interviewer. *redact_names*: the viewer has no personal-data access in
    the case's project, so ``interviewer_name`` is null. One query, joined to
    the interviewer."""
    if death.status != "submitted" or not death.va_sid:
        return []
    rows = db.session.execute(
        sa.select(
            VaWebIntakeDraft.draft_id, VaUsers.name, VaWebIntakeDraft.submitted_at,
            VaWebIntakeDraft.meta["completedAt"].astext,
        )
        .join(VaUsers, VaUsers.user_id == VaWebIntakeDraft.user_id)
        .where(VaWebIntakeDraft.death_id == death.death_id, _candidate_condition())
        .order_by(VaWebIntakeDraft.submitted_at.desc())
        .limit(CANDIDATES_MAX)
    ).all()
    return [
        {
            "draft_id": str(draft_id), "interviewer_name": None if redact_names else name,
            "completed_at": completed or (submitted_at.isoformat() if submitted_at else None),
            "outcome": "completed",
        }
        for draft_id, name, submitted_at, completed in rows
    ]


def _candidate_completed_at(draft: VaWebIntakeDraft) -> datetime:
    """When *draft*'s interview was completed, in server time: the device's
    ``completedAt`` corrected by the clock skew recorded at upload and never
    later than the upload (``_completion_time``'s rule), else the upload."""
    meta = draft.meta or {}
    done = _device_time(meta.get("completedAt"))
    if done is None:
        return draft.submitted_at
    skew = meta.get("clockSkewSeconds")
    if isinstance(skew, (int, float)) and not isinstance(skew, bool):
        done += timedelta(seconds=skew)
    return min(done, draft.submitted_at)


def _supervising_actor(user: VaUsers, death: VaDeathRegister):
    """The workflow actor *user* chooses as: an admin, or a supervisor or data
    manager whose supervision reach covers *death* (audited as a data manager
    when the grant is data-manager shaped, as ``reopen_for_revision`` does);
    else 404, so an id outside the caller's reach is never confirmed."""
    if user.is_admin():
        return admin_actor(user.user_id)
    if not cases.is_interview_supervisor_for(user, death):
        raise WebIntakeError("Case not found.", 404)
    shaped = supervision.dm_shaped_grant(user.user_id, death)
    return data_manager_actor(user.user_id) if shaped else interview_supervisor_actor(user.user_id)


def choose_interview(user: VaUsers, death_id: object, candidate_draft_id: object, reason_code: object) -> VaDeathRegister:
    """A supervisor, data manager or admin chooses the *candidate_draft_id*
    interview (another interviewer's complete one, kept as a superseded copy)
    over the one the submitted case now holds; returns the case.

    The submission keeps its ``va_sid``. The candidate's answers become a new
    active payload version (reason ``supervisor_choice``, built by
    ``build_final_payload`` on the original submit time with the sid, key and
    non-answer values carried over), so ``va_data_collector`` and the
    projection follow the chosen interviewer; the identity answers sync onto
    the case. The drafts swap: the candidate becomes the ``submitted`` draft
    carrying the ``va_sid``, the former winner becomes ``superseded`` (sid
    cleared, ``meta.previousVaSid`` set) and stays a candidate, so the choice
    can be switched back, each time audited.

    Coding restarts as for any changed payload: a protected case (final COD
    given) moves through ``finalized_upstream_changed`` and
    ``reopen_coding_after_revision``, the earlier COD kept as inactive
    history; an unprotected one is released
    (``release_coding_for_changed_payload``); the submission is then re-routed.
    Both interviewers are notified (``INTERVIEW_CHOSEN``; the chosen one with
    the ``va_sid``).

    Done under the case lock, then a lock on the submission
    (``revise_submission``'s order). Refusals: 422 ``invalid_reason``; 404 an
    unknown or out-of-reach case, or a candidate that is not this case's; 409
    ``case_not_submitted``, ``not_web_submission``, ``not_a_candidate`` (not a
    superseded, complete interview), ``form_mismatch``, ``wrong_state`` (a
    reviewer session is live) and the form-changed refusal.
    """
    if reason_code not in CHOICE_REASONS:
        raise WebIntakeError("reason_code must be one of: " + ", ".join(CHOICE_REASONS) + ".", 422, "invalid_reason")
    try:
        death = db.session.get(VaDeathRegister, uuid.UUID(str(death_id)))
    except ValueError:
        death = None
    if death is None:
        raise WebIntakeError("Case not found.", 404)
    try:
        candidate_id = uuid.UUID(str(candidate_draft_id))
    except ValueError:
        raise WebIntakeError("draft_id must be a UUID.") from None
    actor = _supervising_actor(user, death)
    death = cases.lock_case(death)
    if death.status != "submitted" or not death.va_sid:
        raise WebIntakeError("Only a submitted case has an interview to choose.", 409, "case_not_submitted")
    va_sid = death.va_sid
    submission = db.session.get(VaSubmissions, va_sid, with_for_update=True)
    winner = db.session.scalar(sa.select(VaWebIntakeDraft).where(
        VaWebIntakeDraft.va_sid == va_sid, VaWebIntakeDraft.status == "submitted"))
    candidate = db.session.get(VaWebIntakeDraft, candidate_id)
    if submission is None or winner is None:
        raise WebIntakeError("Only a web or device interview can be chosen between here.", 409, "not_web_submission")
    if candidate is None or candidate.death_id != death.death_id:
        raise WebIntakeError("Interview not found.", 404)
    if candidate.status != "superseded" or (candidate.meta or {}).get("interviewOutcome") != "completed":
        raise WebIntakeError("Only another complete interview of this case can be chosen.", 409, "not_a_candidate")
    if candidate.form_id != winner.form_id:
        raise WebIntakeError("That interview was filled on another form.", 409, "form_mismatch")
    state = get_submission_workflow_state(va_sid)  # read under the lock
    if state == WORKFLOW_REVIEWER_CODING_IN_PROGRESS:
        raise WebIntakeError("A reviewer is coding this interview; try again when the session ends.", 409, "wrong_state")
    active = get_active_payload_version(va_sid)
    if active is None:
        raise WebIntakeError("This submission has no payload to replace.", 409, "wrong_state")
    prior = opened_payload(active)  # the carry: sealed fields joined back

    chosen_user = db.session.get(VaUsers, candidate.user_id)
    now = facade()._utcnow()
    meta = {k: v for k, v in (candidate.meta or {}).items() if k != "previousVaSid"}
    raw = {**_answers_of(candidate), "interview_outcome": "completed"}
    submitted_at = datetime.fromisoformat(prior["SubmissionDate"]) if prior.get("SubmissionDate") else winner.submitted_at
    expression_now = _device_time(meta.get("completedAt")) or _expression_now(chosen_user, candidate.submitted_at)
    payload, references, validation_err = build_final_payload(
        winner, chosen_user, raw, submitted_at=submitted_at, expression_now=expression_now, visit_note={},
        intake_source=prior.get("intake_source") or "web", meta=meta,
        carry={k: v for k, v in prior.items() if k != "SubmitterName"}, attachments_from=candidate,
    )
    payload["updatedAt"] = now.isoformat()
    fields = build_submission_projection(db.session.get(VaForms, winner.form_id), payload)
    if fields["va_sid"] != va_sid:
        raise WebIntakeError("This interview's form changed; it cannot be chosen.", 409, "form_mismatch")
    # All refusals are decided; writes start here.
    _sync_case_identity(death, raw, user)
    apply_submission_projection(submission, fields, payload)
    version = ensure_active_payload_version(
        submission, payload_data=payload, source_updated_at=fields["va_odk_updatedat"],
        created_by_role=actor.audit_role, created_by=user.user_id, validation_err=validation_err,
        revision_reason_code="supervisor_choice", answers_sha256=candidate.answers_sha256,
    )
    attachments.link_to_submission(va_sid, candidate.draft_id, payload)

    enters_coding = consent_is_valid(normalize_consent(raw.get("Id10013")))
    try:
        if state in PROTECTED_WORKFLOW_STATES:
            if state != WORKFLOW_FINALIZED_UPSTREAM_CHANGED:
                mark_upstream_change_detected(va_sid, reason=INTERVIEW_CHOSEN_REASON, actor=actor)
            # No pending upstream version may linger beside the chosen payload.
            pending = get_latest_pending_upstream_payload_version(va_sid)
            if pending is not None:
                reject_pending_upstream_payload_version(pending, reason="superseded_by_interview_choice")
            resolve_pending_upstream_change(
                va_sid, resolution_status=UPSTREAM_CHANGE_STATUS_REJECTED, resolved_by=user.user_id,
                resolved_by_role=actor.audit_role,
            )
            reopen_coding_after_revision(va_sid, audit_by=user.user_id, source=SOURCE_SUPERVISOR_CHOICE)
        else:
            release_coding_for_changed_payload(va_sid, source=SOURCE_SUPERVISOR_CHOICE, audit_by=user.user_id)
        facade().route_synced_submission(va_sid, consent_valid=enters_coding, reason=INTERVIEW_CHOSEN_REASON, actor=system_actor())
    except WorkflowTransitionError as exc:
        # A coder finalised or a reviewer started after the check; the route rolls back.
        raise WebIntakeError("The interview changed state; try again.", 409, "wrong_state") from exc
    if enters_coding and not references:
        mark_attachment_sync_completed(va_sid, reason="web_intake_no_attachments", actor=system_actor())
        smartva_service.queue_smartva_after_commit(va_sid, "supervisor_choice")

    # The swap. The former winner keeps its answers and its outcome, so it is a
    # candidate again (switch back); the sid moves with the submitted draft.
    winner.status = "superseded"
    winner.va_sid = None
    winner.meta = {**(winner.meta or {}), "previousVaSid": va_sid}
    candidate.status = "submitted"
    candidate.va_sid = va_sid
    candidate.meta = {
        **meta, "attachmentReferences": references, "interviewOutcome": "completed",
        "effectiveSavedAt": _candidate_completed_at(candidate).isoformat(),
    }
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid, va_audit_byrole=actor.audit_role, va_audit_by=user.user_id, va_audit_operation="u",
        va_audit_action=f"va_submission_interview_chosen_by_supervisor:{reason_code}",
        va_audit_entityid=version.payload_version_id,
    ))
    cases.record_action(death, actor=user, action="interview_chosen", reason=reason_code)
    if candidate.user_id != user.user_id:
        notification_service.notify(
            [candidate.user_id], notification_service.INTERVIEW_CHOSEN, project_id=candidate.project_id,
            death_id=death.death_id, draft_id=candidate.draft_id, va_sid=va_sid,
        )
    if winner.user_id not in (user.user_id, candidate.user_id):
        notification_service.notify(
            [winner.user_id], notification_service.INTERVIEW_CHOSEN, project_id=winner.project_id,
            death_id=death.death_id, draft_id=winner.draft_id,
        )
    db.session.flush()
    log.info("interview chosen | sid=%s | by=%s | reason=%s | chosen_draft=%s", va_sid, user.user_id, reason_code, candidate.draft_id)
    return death
