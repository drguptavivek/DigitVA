"""Supervisor view (digitva-vzk.5).

Part of the web intake service split (bead digitva-r8nh.12); the public
module is ``app.services.web_intake_service``, which re-exports every name.
Code that tests patch on that module is read back through ``facade()``.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from app import db
from app.models import (
    MasOrgUnit,
    VaDeathRegister,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaUsers,
    VaWebIntakeDraft,
)
from app.models.va_web_intake import (
    CASE_STATES,
)
from app.services import case_transition_service as cases
from app.services import (
    training_scope,
)
from app.services.case_transition_service import WebIntakeError
from app.services.duplicate_exclusion import DUPLICATE_CASE_STATUS
from app.services.visit_note import has_visit_note_condition
from app.services.web_intake import facade
from app.services.web_intake.interview_choice import (
    _has_candidate,
)
from app.services.web_intake.scope import (
    _decode_cursor,
    _encode_cursor,
)
from app.services.web_intake.worklist import (
    WORKLIST_PAGE_DEFAULT,
    WORKLIST_PAGE_MAX,
)


def get_supervised_case(user: VaUsers, death_id: object) -> VaDeathRegister:
    """A case *user* supervises, else 404: an id is not proof the case exists."""
    try:
        death = db.session.get(VaDeathRegister, uuid.UUID(str(death_id)))
    except ValueError:
        death = None
    # An admin may open any case here, as the choose action allows (they find
    # the case id in the admin panels; the supervision list stays grant-scoped).
    if death is None or not training_scope.keeps_project(death.project_id) or not (
        user.is_admin() or cases.is_interview_supervisor_for(user, death)
    ):
        raise WebIntakeError("Case not found.", 404)
    # A consent-withdrawn case is sealed: admin only (docs/policy/consent-withdrawal.md).
    if death.consent_withdrawn_at is not None and not user.is_admin():
        raise WebIntakeError("Case not found.", 404)
    return death


def get_case_for_supervisor(user: VaUsers, death_id: object) -> VaDeathRegister:
    """A case *user* supervises (``is_interview_supervisor_for``: no admin
    bypass) in a project where they see personal data (``pii_scope``), for
    ``GET /cases/<id>``'s death-report edit form; else 404. A
    consent-withdrawn case is sealed; a training case stays in training
    mode."""
    try:
        death = db.session.get(VaDeathRegister, uuid.UUID(str(death_id)))
    except ValueError:
        death = None
    if (death is None or death.consent_withdrawn_at is not None
            or not training_scope.keeps_project(death.project_id)
            or not facade().pii_scope(user).sees(death.project_id)
            or not cases.is_interview_supervisor_for(user, death)):
        raise WebIntakeError("Case not found.", 404)
    return death


def supervised_row_facts(user: VaUsers, deaths: list[VaDeathRegister]) -> dict:
    """``{death_id: {last_edited_by_name, last_edited_at, can_edit_death}}``
    for a page of supervision rows, in two queries whatever its size.

    ``last_edited_*``: who made the case submission's active payload version
    and when, when that version is a revision (``revision_reason_code`` set);
    else null. The name is null where *user* has no personal-data access in
    the case's project, like ``registered_by_name``. ``can_edit_death``: the
    death report edit (``update_death``) is open now: not ``draft_identity``,
    not cancelled, duplicate or consent-withdrawn, and no interview of the
    case completed (``_interview_completed``)."""
    if not deaths:
        return {}
    pii = facade().pii_scope(user)
    sids = {d.va_sid for d in deaths if d.va_sid}
    edited = {}
    if sids:
        edited = {row.va_sid: row for row in db.session.execute(
            sa.select(VaSubmissionPayloadVersion.va_sid, VaSubmissionPayloadVersion.version_created_at,
                      VaUsers.name)
            .outerjoin(VaUsers, VaUsers.user_id == VaSubmissionPayloadVersion.created_by)
            .where(VaSubmissionPayloadVersion.va_sid.in_(sids),
                   VaSubmissionPayloadVersion.version_status == "active",
                   VaSubmissionPayloadVersion.revision_reason_code.is_not(None))
        )}
    open_ids = [d.death_id for d in deaths if not d.va_sid]
    completed = set(db.session.scalars(sa.select(VaWebIntakeDraft.death_id).distinct().where(
        VaWebIntakeDraft.death_id.in_(open_ids),
        VaWebIntakeDraft.status.in_(("submitted", "superseded")),
        VaWebIntakeDraft.meta["interviewOutcome"].astext == "completed",
    ))) if open_ids else set()
    facts = {}
    for death in deaths:
        version = edited.get(death.va_sid)
        facts[death.death_id] = {
            "last_edited_by_name": version.name if version is not None and pii.sees(death.project_id) else None,
            "last_edited_at": version.version_created_at.isoformat() if version is not None else None,
            "can_edit_death": (
                death.status not in ("draft_identity", "cancelled", DUPLICATE_CASE_STATUS)
                and death.consent_withdrawn_at is None
                and not death.va_sid and death.death_id not in completed
            ),
        }
    return facts


def supervised_case_row(death: VaDeathRegister) -> tuple:
    """``(case, unit_name, registered_by_name, started_by_name,
    other_complete_interview)`` for a case the caller supervises
    (``list_supervised_cases``' row, for an action's reply), without
    re-running the list query."""
    unit = db.session.get(MasOrgUnit, death.org_unit_id) if death.org_unit_id else None
    registrant = db.session.get(VaUsers, death.registered_by) if death.registered_by else None
    starter = db.session.get(VaUsers, death.started_by_user_id) if death.started_by_user_id else None
    return (
        death,
        unit.unit_name if unit else None,
        registrant.name if registrant else None,
        starter.name if starter else None,
        bool(db.session.scalar(sa.select(_has_candidate()).where(VaDeathRegister.death_id == death.death_id))),
    )


_SUPERVISION_OPEN_STATES = ("registered", "scheduled", "in_progress", "paused", "not_reachable")


SUPERVISION_STUCK_DAYS = 30


SUPERVISION_SORTS = ("newest", "oldest")


def supervision_attention_conditions() -> dict:
    """The supervisor's three attention predicates, shared by the list filters
    and the tiles/Home counts so they never disagree: ``needs_decision`` (a
    flag waits, or a second complete interview is there to choose), ``overdue``
    (open and the revisit date has passed) and ``stuck`` (open, untouched for
    ``SUPERVISION_STUCK_DAYS``)."""
    now = datetime.now(UTC)
    open_case = VaDeathRegister.status.in_(_SUPERVISION_OPEN_STATES)
    return {
        "needs_decision": sa.or_(VaDeathRegister.pending_flag.is_not(None), _has_candidate()),
        "overdue": sa.and_(open_case, VaDeathRegister.next_visit_at < now),
        "stuck": sa.and_(open_case, VaDeathRegister.updated_at < now - timedelta(days=SUPERVISION_STUCK_DAYS)),
    }


def supervision_tiles(scope) -> dict:
    """``{needs_decision, overdue, stuck, total}`` over the cases *scope*
    (a ``VaDeathRegister`` condition) selects: one aggregate query, shared by
    the supervision list and the case list's tiles."""
    attention = supervision_attention_conditions()
    row = db.session.execute(
        sa.select(
            sa.func.count().filter(attention["needs_decision"]),
            sa.func.count().filter(attention["overdue"]),
            sa.func.count().filter(attention["stuck"]),
            sa.func.count(),
        ).where(scope)
    ).one()
    return dict(zip(("needs_decision", "overdue", "stuck", "total"), row))


def list_supervised_cases(user: VaUsers, *, states: list[str] | None = None, flagged: bool = False,
                          candidates: bool = False, visit_note: bool = False,
                          needs_decision: bool = False, overdue: bool = False, stuck: bool = False,
                          sort: str = "newest",
                          cursor: str | None = None, limit: int = WORKLIST_PAGE_DEFAULT) -> dict:
    """Every case in the supervisor's scope, "details pending" included.

    Returns ``{"cases": [(case, unit_name, registered_by_name,
    started_by_name, other_complete_interview), ...], "counts": {state: n},
    "next_cursor": ...}``; *flagged* keeps cases with a flag waiting for a
    supervisor, *candidates* those with a second complete interview to choose
    (``_has_candidate``), *visit_note* those whose submission holds a visit
    note (one EXISTS, no extra query); *needs_decision*, *overdue* and *stuck*
    are ``supervision_attention_conditions``. ``counts`` and ``tiles``
    (``{needs_decision, overdue, stuck, total}``, one aggregate query) ignore
    every filter. *sort*: ``newest`` (updated_at desc, default) or ``oldest``.
    Keyset-paged like ``list_worklist``.
    """
    for state in states or []:
        if state not in CASE_STATES:
            raise WebIntakeError(f"Unknown state {state!r}.")
    if sort not in SUPERVISION_SORTS:
        raise WebIntakeError(f"Unknown sort {sort!r}.")
    limit = max(1, min(int(limit), WORKLIST_PAGE_MAX))
    scope = sa.and_(cases.supervised_case_condition(user), VaDeathRegister.consent_withdrawn_at.is_(None),
                    *training_scope.conditions(VaDeathRegister.project_id))
    counts = dict(
        db.session.execute(
            sa.select(VaDeathRegister.status, sa.func.count()).where(scope).group_by(VaDeathRegister.status)
        ).all()
    )
    attention = supervision_attention_conditions()
    tiles = supervision_tiles(scope)
    filters = [scope]
    for name, wanted in (("needs_decision", needs_decision), ("overdue", overdue), ("stuck", stuck)):
        if wanted:
            filters.append(attention[name])
    if states:
        filters.append(VaDeathRegister.status.in_(states))
    if flagged:
        filters.append(VaDeathRegister.pending_flag.is_not(None))
    if candidates:
        filters.append(_has_candidate())
    if visit_note:
        # The note's predicate reads VaSubmissions, so it is correlated here.
        filters.append(sa.exists(sa.select(1).where(
            VaSubmissions.va_sid == VaDeathRegister.va_sid, has_visit_note_condition(),
        )))
    if cursor:
        at, death_id = _decode_cursor(cursor)
        keyset = sa.tuple_(VaDeathRegister.updated_at, VaDeathRegister.death_id)
        filters.append(keyset > (at, death_id) if sort == "oldest" else keyset < (at, death_id))
    registrant = aliased(VaUsers)
    starter = aliased(VaUsers)
    ordering = (
        (VaDeathRegister.updated_at.asc(), VaDeathRegister.death_id.asc())
        if sort == "oldest"
        else (VaDeathRegister.updated_at.desc(), VaDeathRegister.death_id.desc())
    )
    rows = db.session.execute(
        sa.select(VaDeathRegister, MasOrgUnit.unit_name, registrant.name, starter.name,
                  _has_candidate().label("other_complete_interview"))
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == VaDeathRegister.org_unit_id)
        .outerjoin(registrant, registrant.user_id == VaDeathRegister.registered_by)
        .outerjoin(starter, starter.user_id == VaDeathRegister.started_by_user_id)
        .where(*filters)
        .order_by(*ordering)
        .limit(limit + 1)
    ).all()
    page = [tuple(row) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = page[-1][0]
        next_cursor = _encode_cursor(last.updated_at, last.death_id)
    return {"cases": page, "counts": counts, "tiles": tiles, "next_cursor": next_cursor}
