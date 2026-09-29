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
(digitva-vzk.5).
This module only decides *which kind* of actor a transition needs.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from app import db
from app.models import (
    MapCaseTransition,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaStatuses,
    VaSubmissionWorkflow,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.va_web_intake import CASE_FLAGS
from app.services.org_grant_service import active_project_condition
from app.services.workflow.definition import CODING_BUCKET_CODED, coding_bucket

__all__ = [
    "WebIntakeError",
    "TRANSITIONS",
    "TERMINAL_STATES",
    "is_interview_supervisor_for",
    "supervised_case_condition",
    "identity_complete",
    "lock_case",
    "open_case",
    "transition",
    "flag_case",
    "resolve_flag",
    "reopen",
]


class WebIntakeError(ValueError):
    """A refused intake or case action; ``status_code`` is the HTTP answer."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


# Who may make a transition. ``team``: any interviewer in scope. ``starter`` /
# ``registrant``: the user who started / registered the case. ``supervisor``:
# ``is_interview_supervisor_for``. A supervisor may also do what a starter or
# registrant may.
TEAM, STARTER, REGISTRANT, SUPERVISOR = "team", "starter", "registrant", "supervisor"

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
    ("registered", "not_reachable"): TEAM,
    ("scheduled", "not_reachable"): TEAM,
    ("paused", "not_reachable"): TEAM,
    ("in_progress", "not_reachable"): TEAM,
    ("not_reachable", "scheduled"): TEAM,
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

#: Left only by a supervisor ``reopen``.
TERMINAL_STATES = frozenset({"submitted", "duplicate", "cancelled"})
#: States an interviewer may flag as a possible duplicate or for cancellation.
_FLAGGABLE = {
    "duplicate": frozenset({"registered", "scheduled", "in_progress", "paused", "submitted"}),
    "cancel": frozenset({"registered", "scheduled", "in_progress", "paused"}),
}
_REASON_MAX = 200


_SUPERVISING_ROLES = (VaAccessRoles.interview_supervisor, VaAccessRoles.data_manager)


def _case_scope_condition(user: VaUsers, roles: tuple[VaAccessRoles, ...]):
    """SQL condition on ``VaDeathRegister``: the case lies inside *roles*' reach.

    A unit grant of any of *roles* reaches its unit's subtree (same ltree join
    as ``org_grant_service.scope_unit_ids``, correlated on the case's unit and
    project); a ``data_manager`` project or project-site grant reaches that
    whole project or project-site. Active grants, units and projects only
    (closed-project dormancy via ``active_project_condition``).
    """
    granted = aliased(MasOrgUnit, name="sup_granted_unit")
    covered = aliased(MasOrgUnit, name="sup_covered_unit")
    conditions = [
        sa.exists(
            sa.select(1)
            .select_from(VaUserAccessGrants)
            .join(granted, granted.org_unit_id == VaUserAccessGrants.org_unit_id)
            .join(
                covered,
                sa.and_(
                    covered.project_id == granted.project_id,
                    sa.text("sup_covered_unit.path <@ sup_granted_unit.path"),
                ),
            )
            .where(
                VaUserAccessGrants.user_id == user.user_id,
                VaUserAccessGrants.role.in_(roles),
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
                VaUserAccessGrants.grant_status == VaStatuses.active,
                granted.is_active.is_(True),
                covered.is_active.is_(True),
                active_project_condition(granted.project_id),
                covered.org_unit_id == VaDeathRegister.org_unit_id,
                covered.project_id == VaDeathRegister.project_id,
            )
        )
    ]
    if VaAccessRoles.data_manager in roles:
        projects = sorted(user.get_data_manager_projects())
        pairs = sorted(user.get_data_manager_project_sites())
        if projects:
            conditions.append(VaDeathRegister.project_id.in_(projects))
        if pairs:
            conditions.append(sa.tuple_(VaDeathRegister.project_id, VaDeathRegister.site_id).in_(pairs))
    return sa.or_(*conditions)


def supervised_case_condition(user: VaUsers):
    """SQL condition on ``VaDeathRegister``: the cases *user* supervises.

    Decisions 15-17 (.tasks/2026-09-28-interviewer-worklist.md): an
    ``interview_supervisor`` unit grant reaches its unit's subtree on its own
    (no interviewer grant needed); a ``data_manager`` grant supervises through
    its own scope. No other role confers supervision. The listing and
    ``is_interview_supervisor_for`` share this one condition.
    """
    return _case_scope_condition(user, _SUPERVISING_ROLES)


def _case_matches(case: VaDeathRegister, condition) -> bool:
    if case.death_id is None:
        return False
    return db.session.scalar(
        sa.select(VaDeathRegister.death_id)
        .where(VaDeathRegister.death_id == case.death_id, condition)
        .limit(1)
    ) is not None


def is_interview_supervisor_for(user: VaUsers, case: VaDeathRegister) -> bool:
    """Whether *user* supervises interviews over *case* (``supervised_case_condition``).

    Every supervisor-only action in this module asks this one predicate.
    """
    return _case_matches(case, supervised_case_condition(user))


def _data_manager_covers(user: VaUsers, case: VaDeathRegister) -> bool:
    return _case_matches(case, _case_scope_condition(user, (VaAccessRoles.data_manager,)))


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


def _may_confirm(actor: VaUsers, case: VaDeathRegister, to_state: str) -> bool:
    """The data-manager rule on top of supervision; the caller checked supervision."""
    return not _needs_data_manager(case, to_state) or _data_manager_covers(actor, case)


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
           to_state: str, reason: str | None) -> None:
    db.session.add(
        MapCaseTransition(
            death_id=case.death_id,
            action=action,
            from_state=from_state,
            to_state=to_state,
            reason=reason,
            actor_user_id=actor.user_id,
        )
    )


def _require_actor(kind: str, actor: VaUsers, case: VaDeathRegister) -> None:
    if kind == TEAM:
        return
    if kind == STARTER and case.started_by_user_id == actor.user_id:
        return
    if kind == REGISTRANT and case.registered_by == actor.user_id:
        return
    if is_interview_supervisor_for(actor, case):
        return
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
    _require_actor(kind, actor, case)
    if not _may_confirm(actor, case, to_state):
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
    _audit(case, actor=actor, action=action, from_state=from_state, to_state=to_state, reason=reason)
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
    _audit(case, actor=actor, action=f"flag_{kind}", from_state=case.status,
           to_state=case.status, reason=reason)
    db.session.flush()
    # A supervisor's own flag is confirmed at once, unless the data-manager
    # rule stops them: then it waits like an interviewer's flag.
    target = "duplicate" if kind == "duplicate" else "cancelled"
    if is_interview_supervisor_for(actor, case) and _may_confirm(actor, case, target):
        resolve_flag(case, actor=actor, confirm=True, reason=reason)
    return case


def resolve_flag(case: VaDeathRegister, *, actor: VaUsers, confirm: bool,
                 reason: str | None = None) -> VaDeathRegister:
    """A supervisor confirms (state -> duplicate / cancelled) or rejects a flag."""
    if not is_interview_supervisor_for(actor, case):
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
           to_state=case.status, reason=reason)
    db.session.flush()
    return case


def reopen(case: VaDeathRegister, *, actor: VaUsers, reason: str | None = None) -> VaDeathRegister:
    """A supervisor reopens a terminal case to the state it was in before.

    The earlier state comes from the audit row that entered the terminal
    state; a case with no such row (migrated history) goes back to
    ``registered``, or ``draft_identity`` without identity. Undoing a duplicate
    clears its link.
    """
    lock_case(case)
    if case.status not in TERMINAL_STATES:
        raise WebIntakeError("Only a submitted, duplicate or cancelled case can be reopened.", 409)
    if not is_interview_supervisor_for(actor, case):
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
    case.status = previous
    _audit(case, actor=actor, action="reopen", from_state=from_state, to_state=previous, reason=reason)
    db.session.flush()
    return case

