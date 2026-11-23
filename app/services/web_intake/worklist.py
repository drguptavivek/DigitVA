"""The interviewer worklist and its filters.

Part of the web intake service split (bead digitva-r8nh.12); the public
module is ``app.services.web_intake_service``, which re-exports every name.
Code that tests patch on that module is read back through ``facade()``.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from app import db
from app.models import (
    MapCaseContactAttempt,
    MapCaseTransition,
    MasOrgUnit,
    VaDeathRegister,
    VaSubmissionWorkflow,
    VaUsers,
    VaWebIntakeDraft,
)
from app.models.va_web_intake import (
    CASE_STATES,
)
from app.services import death_identifier_service as death_identifiers
from app.services import (
    org_grant_service,
    register_duplicate_service,
    register_pii_accessor,
)
from app.services.case_transition_service import WebIntakeError
from app.services.duplicate_exclusion import DUPLICATE_CASE_STATUS
from app.services.web_intake import facade
from app.services.web_intake.drafts import (
    _SUPERSEDED_CASE_STATES,
    PREFILL_ANSWER_FIELDS,
    PREFILL_LOCKED_FIELDS,
    _prefill_from_death,
)
from app.services.web_intake.interview_choice import (
    _has_candidate,
)
from app.services.web_intake.register_access import (
    can_edit_identifiers,
)
from app.services.web_intake.scope import (
    _DEATH_REPORTER,
    _EPOCH,
    _decode_cursor,
    _encode_cursor,
    _unit_prefill_parts,
    _worklist_scope,
    reachable_unit_ids,
)
from app.services.web_intake.serializers import (
    serialize_worklist_row,
)
from app.services.workflow.definition import (
    WORKFLOW_READY_FOR_CODING,
)

WORKLIST_PAGE_DEFAULT = 50


WORKLIST_PAGE_MAX = 200


# ``sort``: the default next-visit order the device app and the older page use,
# or ``reported`` (newest reported first, the page's "Recent" chip).
WORKLIST_SORTS = ("next_visit", "reported")


def _micros(at: datetime) -> int:
    return (at - _EPOCH) // timedelta(microseconds=1)


def _encode_worklist_cursor(case: VaDeathRegister) -> str:
    visit = str(_micros(case.next_visit_at)) if case.next_visit_at else "-"
    return f"{visit}_{_micros(case.updated_at)}_{case.death_id}"


def _after_reported_cursor(raw: str):
    """Keyset condition for rows after *raw* in the reported order: newest
    registration first. ``_decode_cursor`` refuses a next-visit cursor (its
    remainder is not a uuid), so a cursor cannot cross the two orders."""
    at, death_uuid = _decode_cursor(raw)
    return sa.tuple_(VaDeathRegister.created_at, VaDeathRegister.death_id) < (at, death_uuid)


def _after_worklist_cursor(raw: str):
    """Keyset condition for rows after *raw* in the worklist order: next visit
    ascending with undated cases last, then last activity newest first."""
    try:
        visit, updated, death_id = raw.split("_", 2)
        visit_at = None if visit == "-" else _EPOCH + timedelta(microseconds=int(visit))
        at, death_uuid = _EPOCH + timedelta(microseconds=int(updated)), uuid.UUID(death_id)
    except (ValueError, OverflowError):
        raise WebIntakeError("Invalid cursor.") from None
    older = sa.tuple_(VaDeathRegister.updated_at, VaDeathRegister.death_id) < (at, death_uuid)
    if visit_at is None:
        return sa.and_(VaDeathRegister.next_visit_at.is_(None), older)
    return sa.or_(
        VaDeathRegister.next_visit_at.is_(None),
        VaDeathRegister.next_visit_at > visit_at,
        sa.and_(VaDeathRegister.next_visit_at == visit_at, older),
    )


def _mine_condition(user: VaUsers):
    """Registered, started or otherwise worked on (any audited action or
    contact attempt) by *user*."""
    return sa.or_(
        VaDeathRegister.registered_by == user.user_id,
        VaDeathRegister.started_by_user_id == user.user_id,
        sa.exists().where(
            MapCaseTransition.death_id == VaDeathRegister.death_id,
            MapCaseTransition.actor_user_id == user.user_id,
        ),
        sa.exists().where(
            MapCaseContactAttempt.death_id == VaDeathRegister.death_id,
            MapCaseContactAttempt.by_user_id == user.user_id,
        ),
    )


def _worklist_select(user: VaUsers):
    """``SELECT (case, unit_name, my_draft_id, other_draft_started_at,
    my_submission, other_complete_interview, ready_for_coding,
    other_draft_started_by)``: a worklist row, with the
    caller's own resumable web draft (at most one,
    ``uq_va_web_intake_drafts_user_death_open``, so the join never repeats a
    case), when the earliest other interviewer's open draft started (None
    without one), whether the caller's draft is the case's submission,
    whether a second complete interview exists (``_has_candidate``),
    whether the case's submission is ``ready_for_coding`` (None without one)
    and the name of the interviewer whose open draft is that earliest one
    (owner, 2026-11-05). One query for all of them. The caller adds the
    scope."""
    my_draft = aliased(VaWebIntakeDraft)
    other = aliased(VaWebIntakeDraft)
    won = aliased(VaWebIntakeDraft)
    other_started = (
        sa.select(sa.func.min(other.created_at))
        .where(
            other.death_id == VaDeathRegister.death_id, other.status == "draft", other.user_id != user.user_id,
            # A closed case has no live other interview to warn about.
            VaDeathRegister.status.not_in(tuple(_SUPERSEDED_CASE_STATES)),
        )
        .scalar_subquery()
    )
    # Same drafts as other_started; the earliest one's interviewer. Correlated
    # per row like other_started, probing the case's drafts by death_id.
    other_started_by = (
        sa.select(VaUsers.name)
        .select_from(other)
        .join(VaUsers, VaUsers.user_id == other.user_id)
        .where(
            other.death_id == VaDeathRegister.death_id, other.status == "draft", other.user_id != user.user_id,
            VaDeathRegister.status.not_in(tuple(_SUPERSEDED_CASE_STATES)),
        )
        .order_by(other.created_at, other.draft_id)
        .limit(1)
        .scalar_subquery()
    )
    return (
        sa.select(
            VaDeathRegister, MasOrgUnit.unit_name, my_draft.draft_id,
            other_started.label("other_draft_started_at"), (won.draft_id.is_not(None)).label("my_submission"),
            _has_candidate().label("other_complete_interview"),
            # A confirmed duplicate is never offered for coding; the register
            # row carries that status, so no correlated subquery is needed.
            sa.and_(
                VaSubmissionWorkflow.workflow_state == WORKFLOW_READY_FOR_CODING,
                VaDeathRegister.status != DUPLICATE_CASE_STATUS,
                VaDeathRegister.consent_withdrawn_at.is_(None),
            ).label("ready_for_coding"),
            other_started_by.label("other_draft_started_by"),
        )
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == VaDeathRegister.org_unit_id)
        .outerjoin(
            my_draft,
            sa.and_(
                my_draft.death_id == VaDeathRegister.death_id,
                my_draft.status == "draft",
                my_draft.user_id == user.user_id,
            ),
        )
        # A join, not EXISTS: PostgreSQL hashes an EXISTS into one scan of all
        # the caller's submitted drafts, a join probes ``death_id`` per case.
        # Matches at most one row: a submission belongs to one draft.
        .outerjoin(
            won,
            sa.and_(
                won.death_id == VaDeathRegister.death_id,
                won.user_id == user.user_id,
                won.status == "submitted",
                won.va_sid == VaDeathRegister.va_sid,
            ),
        )
        # One row per va_sid (uq_va_submission_workflow_sid).
        .outerjoin(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaDeathRegister.va_sid)
    )


def list_worklist(user: VaUsers, *, mine: bool = False, states: list[str] | None = None,
                  cursor: str | None = None, limit: int = WORKLIST_PAGE_DEFAULT,
                  project_id: str | None = None, context: list[dict] | None = None,
                  sort: str = "next_visit") -> dict:
    """Team cases in the interviewer's scope, soonest next visit first.

    Returns ``{"cases": [(case, unit_name, my_draft_id, other_draft_started_at,
    my_submission, other_complete_interview, ready_for_coding,
    other_draft_started_by), ...], "counts":
    {state: n}, "next_cursor": str | None, "possible_duplicates": {death_id:
    [{"death_id", "unique_id"}, ...]}}``; the last is the page's possible
    duplicates (up to three a case) from one query. ``counts`` cover the scope and
    the *mine* filter but not *states*, so tabs can show their totals. Sorted
    by next visit (overdue first, undated last), then last activity newest
    first. Keyset-paged on (next_visit_at, updated_at, death_id).
    *project_id* narrows the scope to one project, counts included (the
    device list); possible duplicates still come from the whole scope.
    ``sort="reported"`` orders by registration instead (newest first), keyset
    on (created_at, death_id); the cursor then comes from that order.
    ``context``: the caller's ``interviewer_context``, if already computed.

    A death_reporter also gets the deaths they registered that their
    death_reporter grants still reach (``reported_deaths_page``'s scope, so
    no case they could not already list). ``reporter_only`` is the set of
    the page's death ids reached that way alone, not by an interviewer
    grant: their rows carry the reporter's shape (``worklist_page``).
    ``coding_status`` is ``{death_id: str | None}`` for the page (``_CODING_STATUS``).
    """
    for state in states or []:
        if state not in CASE_STATES:
            raise WebIntakeError(f"Unknown state {state!r}.")
    if sort not in WORKLIST_SORTS:
        raise WebIntakeError("sort must be next_visit or reported.")
    limit = max(1, min(int(limit), WORKLIST_PAGE_MAX))
    interviewer_scope = _worklist_scope(user, context)
    reporter_scope = _worklist_scope(user, None, _DEATH_REPORTER)
    if reporter_scope is not None:
        reporter_scope = sa.and_(reporter_scope, VaDeathRegister.registered_by == user.user_id)
    scopes = [s for s in (interviewer_scope, reporter_scope) if s is not None]
    if not scopes:
        return {"cases": [], "counts": {}, "next_cursor": None, "possible_duplicates": {}, "reporter_only": set(),
                "coding_status": {}}
    scope = scopes[0] if len(scopes) == 1 else sa.or_(*scopes)
    # A consent-withdrawn case is sealed (docs/policy/consent-withdrawal.md).
    base = [scope, VaDeathRegister.consent_withdrawn_at.is_(None)]
    if project_id is not None:
        base.append(VaDeathRegister.project_id == project_id)
    if mine:
        base.append(_mine_condition(user))

    counts = dict(
        db.session.execute(
            sa.select(VaDeathRegister.status, sa.func.count())
            .where(*base)
            .group_by(VaDeathRegister.status)
        ).all()
    )

    filters = list(base)
    if states:
        filters.append(VaDeathRegister.status.in_(states))
    if sort == "reported":
        order_by = (VaDeathRegister.created_at.desc(), VaDeathRegister.death_id.desc())
        if cursor:
            filters.append(_after_reported_cursor(cursor))
    else:
        order_by = (
            VaDeathRegister.next_visit_at.asc().nulls_last(),
            VaDeathRegister.updated_at.desc(),
            VaDeathRegister.death_id.desc(),
        )
        if cursor:
            filters.append(_after_worklist_cursor(cursor))
    # Lazy: case_list_service imports this module.
    from app.services.case_list_service import combined_status_case

    via_interviewer = interviewer_scope if interviewer_scope is not None else sa.false()
    rows = db.session.execute(
        _worklist_select(user)
        .add_columns(combined_status_case().label("combined_status"), via_interviewer.label("via_interviewer"))
        .where(*filters)
        .order_by(*order_by)
        .limit(limit + 1)
    ).all()
    reporter_only = {row[0].death_id for row in rows[:limit] if not row[-1]}
    coding_status = {row[0].death_id: _CODING_STATUS.get(row[-2]) for row in rows[:limit]}
    page = [tuple(row)[:-2] for row in rows[:limit]]
    if len(rows) > limit:
        last = page[-1][0]
        next_cursor = (_encode_cursor(last.created_at, last.death_id) if sort == "reported"
                       else _encode_worklist_cursor(last))
    else:
        next_cursor = None
    duplicates = register_duplicate_service.possible_duplicate_rows([row[0].death_id for row in page], scope, per_case=3)
    possible = {}
    for row in duplicates:
        possible.setdefault(row.subject_id, []).append(
            {"death_id": str(row.death_id), "unique_id": row.unique_id}
        )
    return {"cases": page, "counts": counts, "next_cursor": next_cursor, "possible_duplicates": possible,
            "reporter_only": reporter_only, "coding_status": coding_status}


_TRUE, _FALSE = ("1", "true", "yes"), ("", "0", "false", "no")


#: A worklist row's ``coding_status`` from the case list's combined status
#: (``case_list_service.combined_status_case``); any other status (no
#: submission, refused, duplicate, cancelled) is None.
_CODING_STATUS = {"submitted_awaiting_coding": "awaiting_coding", "in_coding": "in_coding",
                  "coded": "coded", "not_codeable": "not_codeable"}


def worklist_page(user: VaUsers, args, *, project_id: str | None = None,
                  context: list[dict] | None = None) -> dict:
    """The worklist response ``GET /api/v1/intake/cases`` serves:
    ``{"cases": [row + possible_duplicates], "counts", "next_cursor"}``.

    *args* is the request's query string: ``mine`` (true/false), ``state``
    (comma-separated case states), ``limit`` (clamped to 1..200), ``cursor``
    (from ``next_cursor``), ``sort`` (``next_visit`` default, or ``reported``);
    a malformed one is a 400 WebIntakeError. Each row's ``can_interview`` is
    False for a case reached only as its reporter (``list_worklist``).
    ``latitude`` / ``longitude`` (the death-site GPS fix, for the card's map
    link) only in organization projects (``projects_with_org_tree``, the
    notion ``_require_scope`` uses), and there only where the case detail
    would show the household address: a caller with personal-data access
    in the row's project (``pii_scope``), or the death's own reporter. A sites-mode
    project's rows never carry them (owner, 2026-10-20). Each row carries
    ``identifiers`` (``death_identifier_service.identifier_payloads``, loaded
    once for the page) and ``can_edit_identifiers`` (``can_edit_identifiers``,
    one query for the page). ``coding_status``: ``awaiting_coding``,
    ``in_coding``, ``coded``, ``not_codeable`` or None (no submission, or
    refused / duplicate / cancelled), from the same select.
    *project_id* and *context* as ``list_worklist``.
    """
    mine = (args.get("mine") or "").lower()
    if mine not in _TRUE + _FALSE:
        raise WebIntakeError("mine must be true or false.")
    sort = args.get("sort") or "next_visit"
    if sort not in WORKLIST_SORTS:
        raise WebIntakeError("sort must be next_visit or reported.")
    try:
        limit = int(args.get("limit") or WORKLIST_PAGE_DEFAULT)
    except ValueError:
        raise WebIntakeError("limit must be a whole number.") from None
    result = list_worklist(
        user,
        mine=mine in _TRUE,
        states=[s for s in (args.get("state") or "").split(",") if s],
        cursor=args.get("cursor") or None,
        limit=limit,
        project_id=project_id,
        context=context,
        sort=sort,
    )
    possible = result["possible_duplicates"]
    # One grant read and one org-tree read per page, not per row.
    pii = facade().pii_scope(user)
    org_projects = org_grant_service.projects_with_org_tree(
        {row[0].project_id for row in result["cases"]}) if result["cases"] else set()
    identifiers = death_identifiers.identifier_payloads(user, [row[0] for row in result["cases"]])
    editable = can_edit_identifiers(user, [row[0] for row in result["cases"]])
    # Names of the page opened once (one unwrap a sealed row); the GPS fix
    # only for rows that carry it and may show it, so nothing else opens.
    deaths = [row[0] for row in result["cases"]]
    names = register_pii_accessor.open_register_pii(deaths, only=("deceased_name",))
    shows_fix = [d for d in deaths if d.has_location and d.project_id in org_projects
                 and (pii.sees(d.project_id) or d.registered_by == user.user_id)]
    fixes = register_pii_accessor.open_register_pii(shows_fix, only=("latitude", "longitude"))
    rows = []
    for row in result["cases"]:
        serialized = serialize_worklist_row(user, *row, register=names[row[0].death_id])
        serialized["identifiers"] = identifiers[row[0].death_id]
        serialized["can_edit_identifiers"] = editable[row[0].death_id]
        if row[0].project_id in org_projects and (pii.sees(row[0].project_id) or serialized["registered_by_me"]):
            fix = fixes.get(row[0].death_id) or {}
            serialized["latitude"] = fix.get("latitude")
            serialized["longitude"] = fix.get("longitude")
        serialized["possible_duplicates"] = possible.get(row[0].death_id, [])
        serialized["coding_status"] = result["coding_status"][row[0].death_id]
        # A case reached only as its reporter: no interview here, so nothing
        # about other interviewers' drafts (as _case_body, digitva-t6q).
        serialized["can_interview"] = row[0].death_id not in result["reporter_only"]
        if not serialized["can_interview"]:
            serialized.pop("other_draft_active")
            serialized.pop("other_draft_started_at")
            serialized.pop("other_draft_started_by")
        rows.append(serialized)
    return {"cases": rows, "counts": result["counts"], "next_cursor": result["next_cursor"]}


def get_case_detail(user: VaUsers, death_id: object, *, context: list[dict] | None = None) -> tuple:
    """One case as a ``_worklist_select`` row, visible exactly when the
    worklist would list it (``_worklist_scope``, every project of the
    caller's), in any state. Unknown, out of scope or a malformed id: 404.
    ``context``: the caller's ``interviewer_context``, if already computed."""
    try:
        death_uuid = uuid.UUID(str(death_id))
    except ValueError:
        raise WebIntakeError("Case not found.", 404) from None
    scope = _worklist_scope(user, context)
    if scope is None:
        raise WebIntakeError("Case not found.", 404)
    row = db.session.execute(
        _worklist_select(user).where(scope, VaDeathRegister.death_id == death_uuid).limit(1)
    ).first()
    if row is None:
        raise WebIntakeError("Case not found.", 404)
    return tuple(row)


def prefill_policy(user: VaUsers, project_id: str) -> dict:
    """The offline prefill the server applies in *project_id*, for an app that
    builds a draft before it can reach the server. Derived from
    ``_prefill_from_death``, which stays the authority: an upload's locked
    answers are recomputed server-side whatever the app sent.

    ``direct``: the prefill of a direct start with no unit (interviewer and
    its locked questions). ``units``: ``{org_unit_id: {answers,
    lockedQuestionNames}}``, the area part a direct start in that unit adds,
    for every unit the caller may pick (``reachable_unit_ids``; None means
    every active unit). ``answer_fields``/``locked_fields``: which register
    columns become which answers. Name, sex, dates and age go to
    ``prefill.deceased`` and the package maps them; the registered age lock,
    the partial birth date and the place-of-death matching are conditional,
    so they arrive per case in the case detail's ``prefill``, not here.

    ponytail: ``units`` grows with the reachable tree, as ``/units`` does.
    """
    direct = _prefill_from_death(None, user)
    reachable = reachable_unit_ids(user, project_id)
    if reachable is None:
        reachable = set(db.session.scalars(
            sa.select(MasOrgUnit.org_unit_id).where(
                MasOrgUnit.project_id == project_id, MasOrgUnit.is_active.is_(True)
            )
        ).all())
    parts = _unit_prefill_parts(reachable)
    interviewer_locked = set(direct["lockedQuestionNames"])
    units = {}
    for unit_id, unit_parts in parts.items():
        prefill = _prefill_from_death(None, user, unit_id, unit_parts)
        units[str(unit_id)] = {
            "answers": prefill["answers"],
            "lockedQuestionNames": sorted(set(prefill["lockedQuestionNames"]) - interviewer_locked),
        }
    return {
        "direct": direct,
        "units": units,
        "answer_fields": dict(PREFILL_ANSWER_FIELDS),
        "locked_fields": list(PREFILL_LOCKED_FIELDS),
    }
