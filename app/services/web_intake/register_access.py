"""Who may write a case's registration numbers, and the register detail edits (digitva-kzyp).

Part of the web intake service split (bead digitva-r8nh.12); the public
module is ``app.services.web_intake_service``, which re-exports every name.
Code that tests patch on that module is read back through ``facade()``.
"""
from __future__ import annotations

import uuid
from datetime import date

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgUnit,
    VaAccessRoles,
    VaDeathRegister,
    VaUsers,
    VaWebIntakeDraft,
)
from app.services import case_transition_service as cases
from app.services import death_identifier_service as death_identifiers
from app.services import (
    register_pii_accessor,
)
from app.services.authz import resolve_grants, supervision
from app.services.case_transition_service import WebIntakeError
from app.services.duplicate_exclusion import DUPLICATE_CASE_STATUS
from app.services.web_intake import facade
from app.services.web_intake.common import (
    draft_is_stale,
)
from app.services.web_intake.register import (
    _PHONE_FIELDS,
    LOCATION_FIELDS,
    REGISTER_FIELDS,
    _clean_death_fields,
    _project_today,
    _reporter_reaches,
    _require_age_info,
    get_death,
)
from app.services.web_intake.scope import (
    _DEATH_REPORTER,
    _decode_cursor,
    _encode_cursor,
    _worklist_scope,
)
from app.services.web_intake.serializers import (
    serialize_death,
)

#: A case in one of these states is closed: cancelled, or a confirmed duplicate.
IDENTIFIER_CLOSED_STATES = ("cancelled", DUPLICATE_CASE_STATUS)


#: The supervising roles that may still write numbers on a closed case.
#: ``data_manager`` supervises but is read-only there, so it is left out.
_CLOSED_WRITER_ROLES = (VaAccessRoles.interview_supervisor, VaAccessRoles.site_pi, VaAccessRoles.project_pi)


CASE_CLOSED_MESSAGE = "This case is closed; only a supervisor can change its registration numbers."


IDENTIFIER_FORBIDDEN_MESSAGE = "You may not change this case's registration numbers."


def identifier_field_scopes(user: VaUsers) -> tuple:
    """``(interviewer, reporter)``: the SQL reach of *user*'s ASSIGNED
    interviewer grants and of the death_reporter grants (own registrations
    only), each None without any. The coder's implied self-coding interviewer
    grant is not one of them, so it neither shows values nor writes numbers."""
    interviewer = _worklist_scope(user, assigned_only=True)
    reporter = _worklist_scope(user, None, _DEATH_REPORTER, assigned_only=True)
    if reporter is not None:
        reporter = sa.and_(reporter, VaDeathRegister.registered_by == user.user_id)
    return interviewer, reporter


def _interviewed_condition(user: VaUsers):
    """The cases *user* registered, started or has an interview of (a draft
    that is not discarded): not every case of their unit subtree. The
    registrant clause lets an interviewer who registered a death correct its
    numbers before the first interview, as the death_reporter can."""
    return sa.or_(
        VaDeathRegister.registered_by == user.user_id,
        VaDeathRegister.started_by_user_id == user.user_id,
        sa.exists().where(
            VaWebIntakeDraft.death_id == VaDeathRegister.death_id,
            VaWebIntakeDraft.user_id == user.user_id,
            VaWebIntakeDraft.status != "discarded",
        ),
    )


def identifier_write_parts(user: VaUsers, scopes: tuple | None = None) -> tuple:
    """``(open_ok, closed_ok)``: SQL conditions on ``VaDeathRegister`` for the
    cases *user* may change registration numbers of, ignoring closed cases
    (``open_ok``) and including them (``closed_ok``).

    Admin: every case. A supervisor, In-charge, project PI or data manager
    (``supervised_case_condition``; under a device credential only an
    explicit interview supervisor) and the death_reporter on a death they reported, and the
    interviewer on a case they registered, started or interviewed, write open cases; only
    a supervisor, In-charge, project PI or admin write closed ones. *scopes*:
    ``identifier_field_scopes(user)``, when the caller already has it.
    """
    if resolve_grants(user).is_admin:
        return sa.true(), sa.true()
    interviewer, reporter = scopes if scopes is not None else identifier_field_scopes(user)
    ways = [supervision.supervised_case_condition(user)]
    if reporter is not None:
        ways.append(reporter)
    if interviewer is not None:
        ways.append(sa.and_(interviewer, _interviewed_condition(user)))
    return sa.or_(*ways), supervision.supervised_case_condition(user, _CLOSED_WRITER_ROLES)


def identifier_edit_condition(user: VaUsers, scopes: tuple | None = None):
    """SQL on ``VaDeathRegister``: *user* may change this case's numbers now
    (``can_edit_identifiers``): ``closed_ok`` or an open case and ``open_ok``."""
    open_ok, closed_ok = identifier_write_parts(user, scopes)
    return sa.or_(closed_ok, sa.and_(VaDeathRegister.status.not_in(IDENTIFIER_CLOSED_STATES), open_ok))


def identifier_write_flags(user: VaUsers, deaths) -> dict:
    """``{death_id: (open_ok, closed_ok)}`` for *deaths* (anything with
    ``death_id``), one query however many."""
    ids = [d.death_id for d in deaths]
    if not ids:
        return {}
    open_ok, closed_ok = identifier_write_parts(user)
    rows = db.session.execute(
        sa.select(VaDeathRegister.death_id, open_ok.label("open_ok"), closed_ok.label("closed_ok"))
        .where(VaDeathRegister.death_id.in_(ids))
    ).all()
    return {row.death_id: (bool(row.open_ok), bool(row.closed_ok)) for row in rows}


def can_edit_identifiers(user: VaUsers, deaths) -> dict:
    """``{death_id: bool}``: whether *user* may change each case's numbers now
    (the ``can_edit_identifiers`` of a detail or a list row). One query."""
    deaths = list(deaths)
    flags = identifier_write_flags(user, deaths)
    out = {}
    for death in deaths:
        open_ok, closed_ok = flags.get(death.death_id, (False, False))
        out[death.death_id] = closed_ok or (open_ok and death.status not in IDENTIFIER_CLOSED_STATES)
    return out


def identifier_write_status(user: VaUsers, death: VaDeathRegister) -> str:
    """``"ok"`` when *user* may change *death*'s numbers now, ``"closed"``
    when only the case being closed stops them, else ``"denied"``."""
    open_ok, closed_ok = identifier_write_flags(user, [death]).get(death.death_id, (False, False))
    if closed_ok or (open_ok and death.status not in IDENTIFIER_CLOSED_STATES):
        return "ok"
    return "closed" if open_ok else "denied"


def require_identifier_write(user: VaUsers, death: VaDeathRegister) -> None:
    """Return when *user* may change *death*'s numbers now
    (``identifier_write_status``, the rule of ``can_edit_identifiers`` and of
    ``PUT /cases/<id>/identifiers``); else 409 ``case_closed`` when only the
    case being cancelled or a confirmed duplicate stops them (decision 12),
    else 403. The id is a claim: reaching a case to correct its details is
    not permission to change its numbers (decisions 11 and 12)."""
    status = identifier_write_status(user, death)
    if status == "closed":
        raise WebIntakeError(CASE_CLOSED_MESSAGE, 409, "case_closed")
    if status != "ok":
        raise WebIntakeError(IDENTIFIER_FORBIDDEN_MESSAGE, 403)


#: Page size of a reporter's list, as the worklist's.
REPORTED_PAGE_DEFAULT = 50


REPORTED_PAGE_MAX = 200


def reported_deaths_page(user: VaUsers, args) -> dict:
    """``GET /api/v1/intake/deaths`` for a death_reporter: the deaths *user*
    registered that their death_reporter grants reach, newest activity first,
    keyset-paged on (updated_at, death_id): ``{"deaths": [...],
    "next_cursor": str | None}``.

    *args* is the query string: ``project_id`` and ``site_id`` (optional
    narrowing; one the caller has no reach in is 403), ``limit`` (clamped to
    1..200, default 50), ``cursor`` (from ``next_cursor``; malformed is 400).
    Rows are ``serialize_death`` without the submission id (a reporter has no
    business with the interview) plus ``unit_name`` (the case's unit, one
    query for the page; null when unrouted, digitva-grf9) and ``identifiers``
    (``death_identifier_service.identifier_payloads``, one query for the page). Each row is the caller's own registration,
    so each carries its GPS fix (``shows_gps``).
    """
    try:
        limit = max(1, min(int(args.get("limit") or REPORTED_PAGE_DEFAULT), REPORTED_PAGE_MAX))
    except ValueError:
        raise WebIntakeError("limit must be a whole number.") from None
    context = facade().interviewer_context(user, _DEATH_REPORTER)
    project_id, site_id = args.get("project_id") or None, args.get("site_id") or None
    if project_id is not None or site_id is not None:
        context = [e for e in context if project_id in (None, e["project_id"]) and site_id in (None, e["site_id"])]
        if not context:
            raise WebIntakeError("You do not have access to that project and site.", 403)
    scope = _worklist_scope(user, context, _DEATH_REPORTER)
    if scope is None:
        return {"deaths": [], "next_cursor": None}
    stmt = sa.select(VaDeathRegister).where(scope, VaDeathRegister.registered_by == user.user_id)
    if args.get("cursor"):
        at, death_id = _decode_cursor(args["cursor"])
        stmt = stmt.where(sa.tuple_(VaDeathRegister.updated_at, VaDeathRegister.death_id) < (at, death_id))
    rows = list(db.session.scalars(
        stmt.order_by(VaDeathRegister.updated_at.desc(), VaDeathRegister.death_id.desc()).limit(limit + 1)
    ))
    page = rows[:limit]
    next_cursor = _encode_cursor(page[-1].updated_at, page[-1].death_id) if len(rows) > limit else None
    # Every row is the caller's own registration, so it keeps its GPS fix
    # (``shows_gps``): the edit form shows the location its reporter captured.
    # The registration numbers ride along for the edit form's prefill.
    identifiers = death_identifiers.identifier_payloads(user, page)
    editable = can_edit_identifiers(user, page)
    opened = register_pii_accessor.open_register_pii(page)
    unit_ids = {d.org_unit_id for d in page if d.org_unit_id}
    unit_names = dict(db.session.execute(
        sa.select(MasOrgUnit.org_unit_id, MasOrgUnit.unit_name).where(MasOrgUnit.org_unit_id.in_(unit_ids))
    ).all()) if unit_ids else {}
    return {"deaths": [dict(serialize_death(d, show_gps=True, register=opened[d.death_id]), va_sid=None,
                            unit_name=unit_names.get(d.org_unit_id), identifiers=identifiers[d.death_id],
                            can_edit_identifiers=editable[d.death_id])
                       for d in page],
            "next_cursor": next_cursor}


def flag_death(user: VaUsers, death_id: object, *, kind: str, reason: str | None = None,
               duplicate_of: object | None = None) -> VaDeathRegister:
    """Flag a case in scope as a possible duplicate of another case in scope, or
    for cancellation. A supervisor confirms or rejects it later."""
    death = get_death(user, death_id)
    target = get_death(user, duplicate_of) if kind == "duplicate" and duplicate_of else None
    return cases.flag_case(death, actor=user, kind=kind, reason=reason, duplicate_of=target)


#: Audit actions of a correction and of an interview overwriting registered
#: details; ``reason`` names the fields, never their values.
DETAILS_EDITED = "details_edited"


IDENTITY_FROM_INTERVIEW = "identity_from_interview"


def _json_value(value: object) -> object:
    return value.isoformat() if isinstance(value, date) else value


def _audit_details_change(death: VaDeathRegister, actor: VaUsers, action: str, before: dict, after: dict) -> None:
    """One case audit row for details that moved from *before* to *after*
    (same keys). The reason holds the field names only (their count past the
    reason cap); the old and new values, personal data, go in ``changes``.
    Neither is ever logged."""
    names = ", ".join(before)
    reason = names if len(names) <= cases.REASON_MAX else f"{len(before)} fields"
    changes = {name: {"old": _json_value(before[name]), "new": _json_value(after[name])} for name in before}
    cases.record_action(death, actor=actor, action=action, reason=reason, changes=changes)


def _interview_completed(death: VaDeathRegister) -> bool:
    """Whether a completed interview of the case exists: the winning one
    (``va_sid``), or a complete copy kept apart on a shared case."""
    return death.va_sid is not None or bool(db.session.scalar(sa.select(sa.exists().where(
        VaWebIntakeDraft.death_id == death.death_id,
        VaWebIntakeDraft.status.in_(("submitted", "superseded")),
        VaWebIntakeDraft.meta["interviewOutcome"].astext == "completed",
    ))))


def update_death(user: VaUsers, death_id: object, changes: dict, *, if_updated_at: object | None = None,
                 identifiers: dict | None = None, warnings: list | None = None,
                 station_roster: bool = False, consent=None) -> VaDeathRegister:
    """Correct the register fields of a case, until an interview of it is completed.

    *changes* holds only the fields to change, named as ``register_death``'s
    are; the result is validated by the same ``_clean_death_fields`` over the
    case as it would stand. Allowed to whoever sees the case (``get_death``)
    or supervises it, or is the death_reporter who registered it
    (``_reporter_reaches``). Refused: 404 out of reach; 409 ``details_pending`` (a
    direct start's identity comes from its interview), ``case_completed``
    (the completed interview holds the better data, docs/policy/web-intake.md
    "Correcting a registered death"), ``death_stale`` when *if_updated_at* is
    not the case's ``updated_at`` (400 if malformed); 400 on a bad value.
    One audit row names the changed fields in ``reason`` (their count when
    the names exceed the cap) and keeps each one's old and new value in
    ``changes``; values are personal data and never go in the reason or a log. A stored value that no longer validates must be corrected in
    the same edit (400, naming the field).

    *identifiers* (``{type code: text | None}``) change only the listed
    registration numbers (``death_identifier_service.set_identifiers``; None
    clears); they may be the only change. Their
    ``identifier_in_use`` warnings are appended to *warnings*. On a cancelled
    or confirmed-duplicate case they are a supervisor's only: any other caller
    gets 409 ``case_closed`` for the whole request; the register fields of a
    closed case are edited as before. The numbers need the write permission of
    ``PUT /cases/<id>/identifiers`` (``require_identifier_write``): anyone else
    who may correct the details gets 403 for the whole request. After an
    interview is completed the numbers go through
    ``death_identifier_write.put_identifiers`` instead.

    *station_roster*: a station supervisor's correction from a bundle
    (offline-api-contract.md 4.1, 4.2). The caller has authorized *user*
    from the station's signed roster, so the reach and number-writer gates
    are skipped; a cancelled or confirmed-duplicate case is 409
    ``case_closed`` for any change (stricter than the web).
    """
    if station_roster:
        try:
            death = db.session.get(VaDeathRegister, uuid.UUID(str(death_id)))
        except ValueError:
            death = None
        if death is None:
            raise WebIntakeError("Death entry not found.", 404)
    else:
        try:
            death = get_death(user, death_id)
        except WebIntakeError:
            try:
                death = db.session.get(VaDeathRegister, uuid.UUID(str(death_id)))
            except ValueError:
                death = None
            if death is None or not (cases.is_interview_supervisor_for(user, death) or _reporter_reaches(user, death)):
                raise
    death = cases.lock_case(death)
    from app.services import consent_service
    if consent_service.interview_refused(death=death, client_draft_id=None, answers={}, consent=consent):
        if any(v not in (None, "") for v in changes.values()) or identifiers:
            raise WebIntakeError("Consent was refused; do not add registration details.", 422, "consent_refused")
    if station_roster and death.status in IDENTIFIER_CLOSED_STATES:
        raise WebIntakeError("This case is closed; correct it on the web.", 409, "case_closed")
    if not changes and not identifiers:
        raise WebIntakeError("Nothing to change.")
    unknown = set(changes) - set(REGISTER_FIELDS)
    if unknown:
        raise WebIntakeError("Unknown field: " + ", ".join(sorted(unknown)) + ".")
    if death.status == "draft_identity":
        raise WebIntakeError("Record the details in the interview first.", 409, "details_pending")
    if facade()._interview_completed(death):
        raise WebIntakeError("An interview of this case is completed; its answers are the case details.", 409, "case_completed")
    if identifiers and not station_roster:
        # Register-field edits of a closed case are unchanged; the numbers
        # have the any-time write's own gate.
        require_identifier_write(user, death)
    if if_updated_at is not None and draft_is_stale(death, if_updated_at):
        raise WebIntakeError("This death was changed since you opened it; reload it.", 409, "death_stale")
    if changes:
        _correct_register_fields(user, death, changes)
    if identifiers:
        _, found = death_identifiers.set_identifiers(
            death, user, identifiers, reason_context="correction", enforce_required=False)
        if warnings is not None:
            warnings.extend(found)
    db.session.flush()
    return death


def _correct_register_fields(user: VaUsers, death: VaDeathRegister, changes: dict) -> None:
    """The register-field half of ``update_death``: validate the case as it
    would stand and audit the changed fields (nothing when none changed)."""
    opened = register_pii_accessor.current_values(death)
    current = {name: opened[name] if name in opened else getattr(death, name) for name in REGISTER_FIELDS}
    # A phone is validated only when this edit changes it.
    keep_phones = frozenset(n for n in _PHONE_FIELDS if changes.get(n, current[n]) == current[n])
    today = _project_today(death.project_id)
    try:
        cleaned = _clean_death_fields({**current, **changes}, keep_phones=keep_phones, today=today)
    except WebIntakeError as exc:
        # The whole record is re-validated, so a stored value that is no
        # longer valid (older free-text phone) must be corrected in this edit.
        if exc.status_code != 400:
            raise
        try:
            _clean_death_fields(current, keep_phones=frozenset(_PHONE_FIELDS), today=today)
        except WebIntakeError as stored:
            if str(stored) == str(exc):
                raise WebIntakeError(f"{exc} The stored value is no longer valid; correct it in this edit.") from None
        raise
    _require_age_info(cleaned, current)
    changed = [name for name in changes if cleaned[name] != current[name]]
    if not changed:
        return
    values = {name: cleaned[name] for name in changed}
    if "date_of_death" in values:
        # An edited date is exact (the form takes no year-only date); not audited.
        values["date_of_death_year_only"] = False
    register_pii_accessor.write_fields(death, values)
    if any(name in LOCATION_FIELDS for name in changed):
        death.captured_at = facade()._utcnow() if cleaned["latitude"] is not None else None
    _audit_details_change(death, user, DETAILS_EDITED,
                          {name: current[name] for name in changed}, {name: cleaned[name] for name in changed})
    db.session.flush()
