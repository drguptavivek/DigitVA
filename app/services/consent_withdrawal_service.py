"""Record, undo and seal a respondent's consent withdrawal on a submitted case.

Policy: docs/policy/consent-withdrawal.md (digitva-4gu7, DPDP s6(4)/(6)).
Recording sets ``VaDeathRegister.consent_withdrawn_at``; the shared rule in
``duplicate_exclusion`` then drops the case from every reader. Who may act:
an admin, or a data-manager shaped grant over the case
(``authz.supervision.dm_shaped_grant``: data manager, In-charge, project PI).
A project-scope data manager is covered by that rule on tree and non-tree
projects alike (``_covering_grants``, depth -1). Undo is admin only. Every step writes one ``map_case_transitions`` row
(state unchanged); ``requested_by`` and the note never go into its reason.
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import sqlalchemy as sa

from app import db
from app.models import VaConsentWithdrawal, VaDeathRegister, VaProjectMaster, VaUsers
from app.models.va_consent import WITHDRAWAL_CHANNELS
from app.services import case_transition_service as case_svc
from app.services import training_scope
from app.services.authz import supervision
from app.services.case_transition_service import WebIntakeError

REQUESTED_BY_MAX = 200
CONTACT_REFERENCE_MAX = 100
NOTE_MAX = 2000
UNDO_REASON_MAX = case_svc.REASON_MAX  # the audit row's reason limit


def can_record(user: VaUsers, case: VaDeathRegister) -> bool:
    """Admin, or a data-manager shaped grant over *case*."""
    return user.is_admin() or supervision.dm_shaped_grant(user.user_id, case) is not None


def recordable_ids(user: VaUsers, death_ids: list) -> set:
    """Which of *death_ids* *user* may record a withdrawal on: one query for a
    list page (the same grants as ``can_record``)."""
    if not death_ids:
        return set()
    if user.is_admin():
        return set(death_ids)
    return set(db.session.scalars(sa.select(VaDeathRegister.death_id).where(
        VaDeathRegister.death_id.in_(death_ids),
        supervision.supervised_case_condition(user, roles=supervision.DM_SHAPED_ROLES),
    )))


def get_case(user: VaUsers, death_id: object) -> VaDeathRegister:
    """The case *user* may record a withdrawal on, else 404 (an id is a claim)."""
    try:
        case = db.session.get(VaDeathRegister, uuid.UUID(str(death_id)))
    except ValueError:
        case = None
    if case is None or not training_scope.keeps_project(case.project_id) or not can_record(user, case):
        raise WebIntakeError("Case not found.", 404)
    if case.consent_withdrawn_at is not None and not user.is_admin():
        raise WebIntakeError("Case not found.", 404)
    return case


def active_withdrawal(case: VaDeathRegister) -> VaConsentWithdrawal | None:
    return db.session.scalar(sa.select(VaConsentWithdrawal).where(
        VaConsentWithdrawal.death_id == case.death_id, VaConsentWithdrawal.undone_at.is_(None),
    ))


def _text(payload: dict, key: str, limit: int, *, required: bool = False) -> str | None:
    value = payload.get(key)
    if value is not None and not isinstance(value, str):
        raise WebIntakeError(f"{key} must be text.", 422, code="invalid_request")
    value = (value or "").strip()
    if not value:
        if required:
            raise WebIntakeError(f"{key} is required.", 422, code="invalid_request")
        return None
    if len(value) > limit:
        raise WebIntakeError(f"{key} must be at most {limit} characters.", 422, code="invalid_request")
    return value


def _requested_on(raw) -> date:
    try:
        value = date.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        value = None
    if value is None or value > datetime.now(UTC).date():
        raise WebIntakeError("requested_on must be a date (YYYY-MM-DD), not in the future.", 422,
                             code="invalid_request")
    return value


def record(user: VaUsers, case: VaDeathRegister, payload: dict) -> VaConsentWithdrawal:
    """Record the withdrawal on a submitted *case*; revoke any active coding
    or review allocation. 409 when the case is not submitted or already
    withdrawn; 422 on a bad field."""
    requested_by = _text(payload, "requested_by", REQUESTED_BY_MAX, required=True)
    requested_on = _requested_on(payload.get("requested_on"))
    channel = payload.get("channel")
    if channel not in WITHDRAWAL_CHANNELS:
        raise WebIntakeError("channel is not one of the allowed values.", 422, code="invalid_request")
    contact_reference = _text(payload, "contact_reference", CONTACT_REFERENCE_MAX)
    note = _text(payload, "note", NOTE_MAX)

    case_svc.lock_case(case)
    if case.status != "submitted":
        raise WebIntakeError("Consent withdrawal is recorded on a submitted case.", 409)
    if case.consent_withdrawn_at is not None:
        raise WebIntakeError("A consent withdrawal is already recorded on this case.", 409)
    now = datetime.now(UTC)
    row = VaConsentWithdrawal(
        death_id=case.death_id, requested_by=requested_by, requested_on=requested_on, channel=channel,
        contact_reference=contact_reference, note=note, recorded_by=user.user_id, recorded_at=now,
    )
    db.session.add(row)
    case.consent_withdrawn_at = now
    if case.va_sid:
        # As a duplicate confirmation: the allocation in flight is released;
        # finished coding is kept (sealed with the case).
        from app.services.coding_allocation_service import revoke_active_allocations
        from app.services.workflow.transitions import WorkflowTransitionError

        try:
            revoke_active_allocations(case.va_sid)
        except WorkflowTransitionError as exc:
            raise WebIntakeError(
                "The submission's coding state does not match its active allocation, so the "
                "withdrawal cannot be recorded yet. Ask a data manager to repair it.", 409,
            ) from exc
    case_svc.record_action(case, actor=user, action="consent_withdrawn", reason=channel)
    db.session.flush()
    return row


def undo(user: VaUsers, case: VaDeathRegister, reason) -> VaConsentWithdrawal:
    """Admin only: undo a mistaken withdrawal record; the case comes back."""
    if not user.is_admin():
        raise WebIntakeError("Only an administrator may undo a consent withdrawal.", 403)
    reason = _text({"reason": reason}, "reason", UNDO_REASON_MAX, required=True)
    case_svc.lock_case(case)
    row = active_withdrawal(case)
    if row is None:
        raise WebIntakeError("No consent withdrawal is recorded on this case.", 409)
    row.undone_by, row.undone_at, row.undo_reason = user.user_id, datetime.now(UTC), reason
    case.consent_withdrawn_at = None
    case_svc.record_action(case, actor=user, action="consent_withdrawal_undone", reason=reason)
    db.session.flush()
    return row


def record_admin_view(user: VaUsers, case: VaDeathRegister) -> None:
    """Audit an admin opening a sealed (withdrawn) case."""
    if case.consent_withdrawn_at is not None and user.is_admin():
        case_svc.record_action(case, actor=user, action="consent_withdrawn_case_viewed")


def serialize(row: VaConsentWithdrawal | None) -> dict | None:
    if row is None:
        return None
    return {
        "withdrawal_id": str(row.withdrawal_id),
        "requested_by": row.requested_by,
        "requested_on": row.requested_on.isoformat(),
        "channel": row.channel,
        "contact_reference": row.contact_reference,
        "note": row.note,
        "recorded_at": row.recorded_at.isoformat(),
    }


LIST_LIMIT_MAX = 100


def parse_cursor(raw: str) -> tuple[datetime, uuid.UUID]:
    """``<recorded_at iso>|<withdrawal_id>`` as ``list_withdrawals`` returns it; ValueError if malformed."""
    when, _, withdrawal_id = raw.partition("|")
    return datetime.fromisoformat(when), uuid.UUID(withdrawal_id)


def list_withdrawals(*, project_id: str | None = None, include_undone: bool = False,
                     cursor: str | None = None, limit: int = LIST_LIMIT_MAX) -> dict:
    """Admin list, newest recorded first, keyset-paged (limit clamped to
    ``LIST_LIMIT_MAX``). One join query: case id, project, dates, channel and
    the recorder's name; never ``requested_by``, the note or the reference
    (person text, shown only on the sealed case). ``next_cursor`` is null on
    the last page."""
    limit = max(1, min(limit, LIST_LIMIT_MAX))
    query = (
        sa.select(VaConsentWithdrawal, VaDeathRegister.unique_id, VaDeathRegister.project_id,
                  VaProjectMaster.project_name, VaUsers.name)
        .join(VaDeathRegister, VaDeathRegister.death_id == VaConsentWithdrawal.death_id)
        .join(VaProjectMaster, VaProjectMaster.project_id == VaDeathRegister.project_id)
        .join(VaUsers, VaUsers.user_id == VaConsentWithdrawal.recorded_by)
        .order_by(VaConsentWithdrawal.recorded_at.desc(), VaConsentWithdrawal.withdrawal_id.desc())
        .limit(limit + 1)
    )
    if project_id:
        query = query.where(VaDeathRegister.project_id == project_id)
    if not include_undone:
        query = query.where(VaConsentWithdrawal.undone_at.is_(None))
    if cursor:
        when, last_id = parse_cursor(cursor)
        query = query.where(sa.tuple_(VaConsentWithdrawal.recorded_at, VaConsentWithdrawal.withdrawal_id)
                            < sa.tuple_(when, last_id))
    found = db.session.execute(query).all()
    rows = [
        {
            "withdrawal_id": str(w.withdrawal_id),
            "death_id": str(w.death_id),
            "unique_id": unique_id,
            "project_id": pid,
            "project_name": project_name,
            "requested_on": w.requested_on.isoformat(),
            "recorded_at": w.recorded_at.isoformat(),
            "channel": w.channel,
            "recorded_by_name": recorder,
            "undone": w.undone_at is not None,
        }
        for w, unique_id, pid, project_name, recorder in found[:limit]
    ]
    more = len(found) > limit
    return {"withdrawals": rows, "next_cursor": f"{rows[-1]['recorded_at']}|{rows[-1]['withdrawal_id']}" if more else None}
