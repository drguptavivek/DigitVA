"""Case state machine: the only writer of ``VaDeathRegister.status``.

Policy: docs/policy/web-intake.md, "Case worklist and interview states";
plan: .tasks/2026-09-28-interviewer-worklist.md (bead digitva-vzk.4).

Every state change goes through ``open_case`` (creation), ``transition``,
``resolve_flag`` or ``reopen``, each of which checks the transition table and
who may make it, then writes one ``map_case_transitions`` audit row. Flags
(``flag_case``) change no state but are audited the same way.

Scope is the caller's job: ``team`` transitions trust that the caller already
confirmed the actor may reach the case (``web_intake_service.get_death``).
Supervisor-only moves check scope here, through ``is_interview_supervisor_for``
(digitva-vzk.5), and their audit rows name the grant and cadre relied on
(``supervising_grant``, decision 15; digitva-vzk.8). The supervision rule
itself is ``authz.supervision`` (``Action.SUPERVISE_INTAKE``).
This module only decides *which kind* of actor a transition needs.
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import db
from app.models import (
    MapCaseTransition,
    VaDeathRegister,
    VaSubmissionWorkflow,
    VaUsers,
)
from app.models.va_web_intake import CASE_FLAGS, VaWebIntakeDraft
from app.services import notification_service
from app.services.authz import supervision
from app.services.workflow.definition import CODING_BUCKET_CODED, coding_bucket

__all__ = [
    "WebIntakeError",
    "TRANSITIONS",
    "TERMINAL_STATES",
    "is_interview_supervisor_for",
    "supervised_case_condition",
    "supervising_grant",
    "identity_complete",
    "lock_case",
    "open_case",
    "transition",
    "flag_case",
    "resolve_flag",
    "reopen",
]


log = logging.getLogger(__name__)


class WebIntakeError(ValueError):
    """A refused intake or case action; ``status_code`` is the HTTP answer,
    ``code`` an optional machine code that replaces the status's generic one."""

    def __init__(self, message: str, status_code: int = 400, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code


# Who may make a transition. ``team``: any interviewer in scope. ``starter`` /
# ``registrant``: the user who started / registered the case. ``supervisor``:
# ``is_interview_supervisor_for``. A supervisor may also do what a starter or
# registrant may.
TEAM, STARTER, REGISTRANT, SUPERVISOR = "team", "starter", "registrant", "supervisor"
# ``submitter``: only the interviewer whose interview is the case's submission
# (its draft carries ``case.va_sid``); no supervisor fallback.
SUBMITTER = "submitter"

#: (from_state, to_state) -> who may make it.
TRANSITIONS: dict[tuple[str, str], str] = {
    # Direct start: identity captured by the form, or the start abandoned.
    ("draft_identity", "in_progress"): STARTER,
    ("draft_identity", "cancelled"): STARTER,
    # Appointments (phase 5 drives these).
    ("registered", "scheduled"): TEAM,
    ("scheduled", "registered"): TEAM,
    # Start, resume, restart (refused is soft: decision 9).
    ("registered", "in_progress"): TEAM,
    ("scheduled", "in_progress"): TEAM,
    ("paused", "in_progress"): TEAM,
    ("not_reachable", "in_progress"): TEAM,
    ("refused", "in_progress"): TEAM,
    ("in_progress", "paused"): TEAM,
    # The draft was discarded: the case waits for a new interview.
    ("in_progress", "registered"): TEAM,
    ("in_progress", "submitted"): TEAM,
    ("paused", "submitted"): TEAM,
    # The interviewer's latest completed version is a partial or a refusal
    # (docs/policy/interview-revisions.md "Latest completed version wins"):
    # the case leaves coding and waits for a new complete interview.
    ("submitted", "paused"): SUBMITTER,
    ("submitted", "refused"): SUBMITTER,
    ("submitted", "not_reachable"): SUBMITTER,
    ("registered", "not_reachable"): TEAM,
    ("scheduled", "not_reachable"): TEAM,
    ("paused", "not_reachable"): TEAM,
    ("in_progress", "not_reachable"): TEAM,
    ("not_reachable", "scheduled"): TEAM,
    ("not_reachable", "refused"): TEAM,
    ("registered", "refused"): TEAM,
    ("scheduled", "refused"): TEAM,
    ("in_progress", "refused"): TEAM,
    ("paused", "refused"): TEAM,
    # Duplicate: only a supervisor confirms (decisions 6, 10).
    ("registered", "duplicate"): SUPERVISOR,
    ("scheduled", "duplicate"): SUPERVISOR,
    ("in_progress", "duplicate"): SUPERVISOR,
    ("paused", "duplicate"): SUPERVISOR,
    ("submitted", "duplicate"): SUPERVISOR,
    # Cancel: the registrant until an interview starts (decision 12 of
    # 2026-09-30), a supervisor after.
    ("registered", "cancelled"): REGISTRANT,
    ("scheduled", "cancelled"): REGISTRANT,
    ("in_progress", "cancelled"): SUPERVISOR,
    ("paused", "cancelled"): SUPERVISOR,
}

#: Left by a supervisor ``reopen``, or (``submitted`` only) by the
#: submitter's own later partial or refused version (``SUBMITTER`` rows).
TERMINAL_STATES = frozenset({"submitted", "duplicate", "cancelled"})
#: States an interviewer may flag as a possible duplicate or for cancellation.
_FLAGGABLE = {
    "duplicate": frozenset({"registered", "scheduled", "in_progress", "paused", "submitted"}),
    "cancel": frozenset({"registered", "scheduled", "in_progress", "paused"}),
}
_REASON_MAX = 200


def supervised_case_condition(user: VaUsers):
    """SQL condition on ``VaDeathRegister``: the cases *user* supervises.

    The rule is ``authz.supervision`` (``Action.SUPERVISE_INTAKE``); the
    listing, ``is_interview_supervisor_for`` and ``supervising_grant`` all
    ask it.
    """
    return supervision.supervised_case_condition(user)


def supervising_grant(user: VaUsers, case: VaDeathRegister):
    """The grant *user* supervises *case* through, as ``(grant_id, cadre_id)``,
    or None (an unsaved case). What a supervisor action's audit row names
    (decision 15)."""
    if case.death_id is None:
        return None
    return supervision.supervising_grant(user.user_id, case)


def is_interview_supervisor_for(user: VaUsers, case: VaDeathRegister) -> bool:
    """Whether *user* supervises interviews over *case* (``authz``
    ``SUPERVISE_INTAKE``).

    Every supervisor-only action in this module asks this one predicate.
    """
    return supervising_grant(user, case) is not None


def _needs_data_manager(case: VaDeathRegister, to_state: str) -> bool:
    """Confirming a duplicate whose submission is already coded (decisions 10, 14).

    "Coded" is the area dashboard's coded bucket (a final COD exists). A
    submitted case whose workflow row cannot be found counts as coded: the
    rule fails closed.
    """
    if to_state != "duplicate" or case.status != "submitted":
        return False
    state = None
    if case.va_sid:
        state = db.session.scalar(
            sa.select(VaSubmissionWorkflow.workflow_state).where(VaSubmissionWorkflow.va_sid == case.va_sid)
        )
    return state is None or coding_bucket(state) == CODING_BUCKET_CODED


def _data_manager_grant(actor: VaUsers, case: VaDeathRegister):
    """The actor's narrowest data-manager shaped grant over *case*, or None:
    what confirming an already coded duplicate relies on (decisions 10, 14;
    ``authz.supervision.dm_shaped_grant``)."""
    if case.death_id is None:
        return None
    return supervision.dm_shaped_grant(actor.user_id, case)


def identity_complete(case: VaDeathRegister) -> bool:
    """The minimum identity (decision 4): name, date of death and sex."""
    return bool(case.deceased_name and case.date_of_death and case.deceased_sex)


def lock_case(case: VaDeathRegister) -> VaDeathRegister:
    """Take the case's row lock and re-read it, before any state decision.

    Pending changes are flushed first (they are this transaction's own, e.g.
    identity copied from a draft), then ``SELECT ... FOR UPDATE`` waits for any
    other transaction on the row and refreshes the object from the database.
    So a teammate's move cannot overwrite a concurrent ``submitted``, and two
    interviewers cannot both open an active draft for one case. Held until
    the request's transaction ends.
    """
    db.session.flush()
    return db.session.execute(
        sa.select(VaDeathRegister)
        .where(VaDeathRegister.death_id == case.death_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()


def _clean_reason(reason: str | None) -> str | None:
    value = (reason or "").strip()
    if not value:
        return None
    if len(value) > _REASON_MAX:
        raise WebIntakeError(f"The reason must be at most {_REASON_MAX} characters.")
    return value


def _audit(case: VaDeathRegister, *, actor: VaUsers, action: str, from_state: str | None,
           to_state: str, reason: str | None, grant=None) -> None:
    """One audit row; *grant* (``(grant_id, cadre_id)``) is the supervisor
    grant relied on, None for a team, starter or registrant move."""
    db.session.add(
        MapCaseTransition(
            death_id=case.death_id,
            action=action,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            actor_user_id=actor.user_id,
            authorizing_grant_id=grant.grant_id if grant else None,
            authorizing_cadre_id=grant.cadre_id if grant else None,
        )
    )


def _require_actor(kind: str, actor: VaUsers, case: VaDeathRegister):
    """Refuse (403) an actor who may not make a *kind* move; return the
    supervisor grant relied on, or None when no supervision was needed."""
    if kind == TEAM:
        return None
    if kind == SUBMITTER:
        if case.va_sid and db.session.scalar(sa.select(sa.exists().where(
            VaWebIntakeDraft.va_sid == case.va_sid, VaWebIntakeDraft.user_id == actor.user_id,
            VaWebIntakeDraft.status == "submitted",
        ))):
            return None
        raise WebIntakeError("Only the interviewer whose interview was submitted may do that.", 403)
    if kind == STARTER and case.started_by_user_id == actor.user_id:
        return None
    if kind == REGISTRANT and case.registered_by == actor.user_id:
        return None
    grant = supervising_grant(actor, case)
    if grant is not None:
        return grant
    if kind == SUPERVISOR:
        raise WebIntakeError("Only an interview supervisor may do that.", 403)
    raise WebIntakeError("Only the person who started or registered this case may do that.", 403)


def open_case(case: VaDeathRegister, *, actor: VaUsers) -> VaDeathRegister:
    """Add a new case in its first state and audit its creation.

    A registered death starts ``registered`` with its identity; a direct start
    starts ``draft_identity`` and is filled in by its draft.
    """
    initial = "registered" if case.source == "register" else "draft_identity"
    if initial == "registered" and not identity_complete(case):
        raise WebIntakeError("Name, date of death and sex are required.")
    case.status = initial
    db.session.add(case)
    db.session.flush()
    _audit(case, actor=actor, action="created", from_state=None, to_state=initial, reason=None)
    return case


_KPI_RECOUNT_SIDS = "duplicate_kpi_recount_sids"


def _recompute_kpi_rows_after_commit(va_sid: str) -> None:
    """Queue the stored daily KPI recount for *va_sid* once this transaction commits.

    Confirming or undoing a duplicate, or an interviewer's revision that
    moves the submission's ``updatedAt``, changes what the daily aggregates
    count (app/services/duplicate_exclusion.py); the worker must see the
    committed status, so the sid waits in ``session.info`` and is queued by
    ``_queue_kpi_recounts`` on commit, or dropped on rollback.
    """
    db.session().info.setdefault(_KPI_RECOUNT_SIDS, set()).add(va_sid)


@sa.event.listens_for(Session, "after_commit")
def _queue_kpi_recounts(session):
    va_sids = session.info.pop(_KPI_RECOUNT_SIDS, None)
    if not va_sids:
        return
    from app.tasks.kpi_tasks import recompute_kpi_days_for_submission

    for va_sid in sorted(va_sids):
        try:
            recompute_kpi_days_for_submission.delay(va_sid)
        except Exception:
            # The case change is committed; a missed recount only leaves
            # stored rows stale until the next snapshot or backfill.
            log.warning("Could not queue the KPI recount after a duplicate change", exc_info=True)


@sa.event.listens_for(Session, "after_soft_rollback")
def _drop_kpi_recounts(session, previous_transaction):
    if previous_transaction.parent is None:
        session.info.pop(_KPI_RECOUNT_SIDS, None)


def transition(case: VaDeathRegister, to_state: str, *, actor: VaUsers, action: str,
               reason: str | None = None) -> VaDeathRegister:
    """Move *case* to *to_state*, or raise ``WebIntakeError`` (409 / 403).

    ``action`` is a short code for the audit row ("interview_started",
    "identity_captured", "submitted", ...). Leaving ``draft_identity`` for any
    state but ``cancelled`` needs the minimum identity. Locks the case row
    first (``lock_case``), so ``from_state`` is the current committed state.
    """
    lock_case(case)
    from_state = case.status
    kind = TRANSITIONS.get((from_state, to_state))
    if kind is None:
        raise WebIntakeError(f"A case cannot move from {from_state} to {to_state}.", 409)
    grant = _require_actor(kind, actor, case)
    if _needs_data_manager(case, to_state):
        grant = _data_manager_grant(actor, case)
        if grant is None:
            raise WebIntakeError(
                "This case is already coded: only a supervisor who is also its data manager "
                "may confirm it as a duplicate.", 403
            )
    if from_state == "draft_identity" and to_state != "cancelled" and not identity_complete(case):
        raise WebIntakeError(
            "Record the name, date of death and sex of the deceased first.", 409
        )
    reason = _clean_reason(reason)
    case.status = to_state
    if to_state in ("duplicate", "cancelled"):
        case.pending_flag = None
    if to_state == "duplicate" and case.va_sid:
        # The submission leaves every coding reader through the shared
        # predicate (app/services/duplicate_exclusion.py); an allocation in
        # flight is revoked like a timed-out one; finished coding is kept;
        # stored daily KPI rows are recounted after commit.
        # Lazy import: the allocation service pulls in the coding stack.
        from app.services.coding_allocation_service import revoke_active_allocations
        from app.services.workflow.transitions import WorkflowTransitionError

        try:
            revoke_active_allocations(case.va_sid)
        except WorkflowTransitionError as exc:
            # An allocation whose workflow state does not match it cannot be
            # released safely; refuse the confirmation (the caller rolls back)
            # instead of a 500, and leave the repair to a data manager.
            raise WebIntakeError(
                "The submission's coding state does not match its active allocation, "
                "so the duplicate cannot be confirmed yet. Ask a data manager to repair it.",
                409,
            ) from exc
        _recompute_kpi_rows_after_commit(case.va_sid)
    _audit(case, actor=actor, action=action, from_state=from_state, to_state=to_state, reason=reason,
           grant=grant)
    db.session.flush()
    return case


def flag_case(case: VaDeathRegister, *, actor: VaUsers, kind: str, reason: str | None = None,
              duplicate_of: VaDeathRegister | None = None) -> VaDeathRegister:
    """Flag *case* as a possible duplicate (of *duplicate_of*) or for cancellation.

    Any team member may flag (decision 6); the flag waits for a supervisor's
    ``resolve_flag``. A supervisor's own flag is confirmed at once. The caller
    has checked the actor may reach both cases.
    """
    if kind not in CASE_FLAGS:
        raise WebIntakeError("Flag must be duplicate or cancel.")
    lock_case(case)
    if case.status not in _FLAGGABLE[kind]:
        raise WebIntakeError(f"A {case.status} case cannot be flagged that way.", 409)
    reason = _clean_reason(reason)
    if kind == "duplicate":
        if duplicate_of is None:
            raise WebIntakeError("Name the case this one duplicates.")
        if duplicate_of.death_id == case.death_id or duplicate_of.project_id != case.project_id:
            raise WebIntakeError("A case can only duplicate another case of the same project.")
        # The kept case must be a live one, and two cases may not name each other.
        if duplicate_of.status in ("duplicate", "cancelled"):
            raise WebIntakeError("The case named as the original is itself closed.", 409)
        if duplicate_of.duplicate_of_death_id == case.death_id:
            raise WebIntakeError("That case is already flagged as a duplicate of this one.", 409)
        case.duplicate_of_death_id = duplicate_of.death_id
    elif not reason:
        raise WebIntakeError("Give a reason for cancelling.")
    else:
        case.duplicate_of_death_id = None
    case.pending_flag = kind
    # The flag row names the supervisor grant when the actor supervises the
    # case, else NULL (a team member's flag).
    grant = supervising_grant(actor, case)
    _audit(case, actor=actor, action=f"flag_{kind}", from_state=case.status,
           to_state=case.status, reason=reason, grant=grant)
    db.session.flush()
    # A supervisor's own flag is confirmed at once, unless the data-manager
    # rule stops them: then it waits like an interviewer's flag.
    target = "duplicate" if kind == "duplicate" else "cancelled"
    if grant is not None and (
        not _needs_data_manager(case, target) or _data_manager_grant(actor, case) is not None
    ):
        resolve_flag(case, actor=actor, confirm=True, reason=reason)
    return case


def resolve_flag(case: VaDeathRegister, *, actor: VaUsers, confirm: bool,
                 reason: str | None = None) -> VaDeathRegister:
    """A supervisor confirms (state -> duplicate / cancelled) or rejects a flag."""
    grant = supervising_grant(actor, case)
    if grant is None:
        raise WebIntakeError("Only an interview supervisor may do that.", 403)
    lock_case(case)
    kind = case.pending_flag
    if kind is None:
        raise WebIntakeError("This case has no flag to resolve.", 409)
    if confirm:
        target = "duplicate" if kind == "duplicate" else "cancelled"
        return transition(case, target, actor=actor, action=f"confirm_{kind}", reason=reason)
    reason = _clean_reason(reason)
    case.pending_flag = None
    if kind == "duplicate":
        case.duplicate_of_death_id = None
    _audit(case, actor=actor, action=f"reject_{kind}", from_state=case.status,
           to_state=case.status, reason=reason, grant=grant)
    db.session.flush()
    return case


def reopen(case: VaDeathRegister, *, actor: VaUsers, reason: str | None = None) -> VaDeathRegister:
    """A supervisor reopens a terminal case to the state it was in before.

    The earlier state comes from the audit row that entered the terminal
    state; a case with no such row (migrated history) goes back to
    ``registered``, or ``draft_identity`` without identity. Undoing a duplicate
    clears its link, and its submission returns to every coding reader in the
    workflow state it kept (an allocation revoked on confirmation stays
    released), and the stored daily KPI rows it touched are recounted.
    """
    lock_case(case)
    if case.status not in TERMINAL_STATES:
        raise WebIntakeError("Only a submitted, duplicate or cancelled case can be reopened.", 409)
    grant = supervising_grant(actor, case)
    if grant is None:
        raise WebIntakeError("Only an interview supervisor may do that.", 403)
    reason = _clean_reason(reason)
    if not reason:
        raise WebIntakeError("Give a reason for reopening.")
    previous = db.session.scalar(
        sa.select(MapCaseTransition.from_state)
        .where(
            MapCaseTransition.death_id == case.death_id,
            MapCaseTransition.to_state == case.status,
            MapCaseTransition.from_state.is_not(None),
            MapCaseTransition.from_state != case.status,
        )
        .order_by(MapCaseTransition.created_at.desc())
        .limit(1)
    )
    if previous is None:
        previous = "registered" if identity_complete(case) else "draft_identity"
    from_state = case.status
    if from_state == "duplicate":
        case.duplicate_of_death_id = None
        if case.va_sid:
            _recompute_kpi_rows_after_commit(case.va_sid)
    case.status = previous
    _audit(case, actor=actor, action="reopen", from_state=from_state, to_state=previous, reason=reason,
           grant=grant)
    db.session.flush()
    # The starter and anyone holding an open draft learn the case is open again.
    holders = notification_service.open_draft_holders(case.death_id, exclude_user_id=actor.user_id)
    recipients = list(holders)
    if case.started_by_user_id not in (None, actor.user_id, *recipients):
        recipients.insert(0, case.started_by_user_id)  # first, so the fan-out cap never drops it
    notification_service.notify(
        recipients, notification_service.CASE_REOPENED, project_id=case.project_id,
        death_id=case.death_id, draft_id=holders,
    )
    return case

