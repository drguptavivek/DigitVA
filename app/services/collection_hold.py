"""Interviews uploaded outside the collection period: held, cleared, released, rejected.

Policy: docs/policy/project-clock-and-gates.md ("Uploads outside the
collection period are accepted and held"). Decided once, at the first upload
of a DigitVA interview (``web_intake_service.submit_draft``, the one funnel
for web and Collect app submits): its start date on the project clock
(recorded start time, else when the server first received it) is checked
against the site and unit gate as they stand then (``collection_gate.resolve``,
stricter wins). Switched off, or the start date before the start date or
after the end date, holds it; the daily limit never does.

The hold lives on the draft (``va_web_intake_drafts.collection_hold``); ODK
submissions have no draft and are never held. Every coding, analytics and
export reader keeps held and rejected interviews out through the shared
predicate (``duplicate_exclusion.not_confirmed_duplicate_condition``), so a
clear or release needs no trigger: the SmartVA sweep and allocation see the
row on their next read.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import sqlalchemy as sa

from app import db
from app.models import VaProjectMaster, VaSubmissionsAuditlog, VaWebIntakeDraft
from app.services import collection_gate
from app.services.authz import subtree_select
from app.services.project_clock import project_day

HELD = "held"
RELEASED = "released"
REJECTED = "rejected"

#: Rows read per batch when a gate save re-checks held interviews.
_CLEAR_BATCH = 500
#: Page size bounds of the data-manager list.
LIST_DEFAULT, LIST_MAX = 50, 200
NOTE_MAX = 500


def _hold_reason(gate: dict, start_day: date) -> str | None:
    """The gate reason code that holds an interview started on *start_day*, or None."""
    if not gate["enabled"]:
        return collection_gate.PAUSED
    if gate["start_date"] and start_day < date.fromisoformat(gate["start_date"]):
        return collection_gate.NOT_STARTED
    if gate["end_date"] and start_day > date.fromisoformat(gate["end_date"]):
        return collection_gate.ENDED
    return None


def _started_at(meta: dict | None, created_at: datetime) -> datetime:
    """The interview's recorded start (``meta.startedAt`` with an offset), else
    when the server first received it (the draft's ``created_at``)."""
    from app.services.web_intake_service import _device_time

    return _device_time((meta or {}).get("startedAt")) or created_at


def _timezone(project_id: str) -> str | None:
    return db.session.scalar(sa.select(VaProjectMaster.timezone).where(VaProjectMaster.project_id == project_id))


def _audit(va_sid: str, draft_id, action: str, *, role: str, by=None, note: str | None = None) -> None:
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid, va_audit_byrole=role, va_audit_by=by, va_audit_operation="u",
        va_audit_action=action, va_audit_entityid=draft_id, va_audit_note=note,
    ))


def hold_at_upload(user, draft: VaWebIntakeDraft, va_sid: str, now: datetime) -> bool:
    """Hold *draft* (just submitted as *va_sid*) when it started outside the
    collection period; returns whether it is held. Never refuses."""
    gate = collection_gate.resolve(user, [(draft.project_id, draft.site_id, draft.org_unit_id)], now=now, counts=False)[
        (draft.project_id, draft.site_id, uuid.UUID(str(draft.org_unit_id)) if draft.org_unit_id else None)]
    start_day = project_day(_timezone(draft.project_id), _started_at(draft.meta, draft.created_at)).today
    reason = _hold_reason(gate, start_day)
    if reason is None:
        return False
    draft.collection_hold, draft.collection_hold_reason, draft.collection_hold_at = HELD, reason, now
    _audit(va_sid, draft.draft_id, "collection_hold_held", role="vasystem")
    return True


def clear_covered(user, project_id: str, *, site_id: str | None = None, org_unit_id=None) -> int:
    """After a gate save: release every ``held`` interview of the saved site
    (or of the saved unit's subtree) whose start date the gates now cover.
    Keyset batches over the partial hold index; one gate resolve per batch.
    Returns how many cleared. Caller commits."""
    tz = _timezone(project_id)
    where = [VaWebIntakeDraft.project_id == project_id, VaWebIntakeDraft.collection_hold == HELD]
    if site_id is not None:
        where.append(VaWebIntakeDraft.site_id == site_id)
    if org_unit_id is not None:
        where.append(VaWebIntakeDraft.org_unit_id.in_(subtree_select([uuid.UUID(str(org_unit_id))])))
    now = datetime.now(UTC)
    cleared, after = 0, None
    while True:
        rows = db.session.execute(
            sa.select(VaWebIntakeDraft.draft_id, VaWebIntakeDraft.va_sid, VaWebIntakeDraft.site_id,
                      VaWebIntakeDraft.org_unit_id, VaWebIntakeDraft.meta["startedAt"].astext.label("started"),
                      VaWebIntakeDraft.created_at)
            .where(*where, *([VaWebIntakeDraft.draft_id > after] if after else []))
            .order_by(VaWebIntakeDraft.draft_id)
            .limit(_CLEAR_BATCH)
        ).all()
        if not rows:
            return cleared
        after = rows[-1].draft_id
        gates = collection_gate.resolve(user, {(project_id, r.site_id, r.org_unit_id) for r in rows}, now=now, counts=False)
        covered = [
            r for r in rows
            if _hold_reason(gates[(project_id, r.site_id, r.org_unit_id)],
                            project_day(tz, _started_at({"startedAt": r.started}, r.created_at)).today) is None
        ]
        if covered:
            db.session.execute(
                sa.update(VaWebIntakeDraft)
                .where(VaWebIntakeDraft.draft_id.in_([r.draft_id for r in covered]),
                       VaWebIntakeDraft.collection_hold == HELD)
                # A hold change is not an edit of the interview: keep updated_at.
                .values(collection_hold=RELEASED, collection_hold_at=now, updated_at=VaWebIntakeDraft.updated_at)
                .execution_options(synchronize_session=False)
            )
            for r in covered:
                _audit(r.va_sid, r.draft_id, "collection_hold_cleared", role="vasystem", by=user.user_id)
            cleared += len(covered)


def _clean_note(note) -> str | None:
    if note in (None, ""):
        return None
    if not isinstance(note, str) or len(note.strip()) > NOTE_MAX:
        raise ValueError(f"note must be text of at most {NOTE_MAX} characters.")
    return note.strip() or None


def decide(user, va_sid: str, action: str, note=None) -> VaWebIntakeDraft:
    """A data manager's ``release`` (held or rejected -> released: enters
    coding) or ``reject`` (held -> rejected: stays out, data kept). Scope is
    ``authz`` TRIAGE on the submission (PermissionError / ValueError for the
    route's 403 / 404); a wrong current status is LookupError (409). Audited
    with who, when and the note. Caller commits."""
    from app.services.data_management_service import _dm_submission_scope_check

    allowed_from = {"release": (HELD, REJECTED), "reject": (HELD,)}
    if action not in allowed_from:
        raise ValueError("action must be release or reject.")
    note = _clean_note(note)
    _dm_submission_scope_check(user, va_sid)
    draft = db.session.scalars(
        sa.select(VaWebIntakeDraft)
        .where(VaWebIntakeDraft.va_sid == va_sid, VaWebIntakeDraft.status == "submitted")
        .with_for_update()
    ).first()
    if draft is None or draft.collection_hold not in allowed_from[action]:
        raise LookupError("This interview is not held.")
    now = datetime.now(UTC)
    status = RELEASED if action == "release" else REJECTED
    db.session.execute(
        sa.update(VaWebIntakeDraft).where(VaWebIntakeDraft.draft_id == draft.draft_id)
        .values(collection_hold=status, collection_hold_at=now, updated_at=VaWebIntakeDraft.updated_at)
    )
    _audit(va_sid, draft.draft_id, f"collection_hold_{status}",
           role="admin" if user.is_admin() else "data_manager", by=user.user_id, note=note)
    return draft


def _parse_cursor(raw) -> tuple[datetime, uuid.UUID] | None:
    if not raw:
        return None
    try:
        at, draft_id = str(raw).split("|", 1)
        return datetime.fromisoformat(at), uuid.UUID(draft_id)
    except ValueError:
        raise ValueError("cursor is invalid.") from None


def list_held(user, *, status: str = HELD, project_id: str | None = None, site_id: str | None = None,
              limit=None, cursor=None) -> dict:
    """Held (or rejected) interviews in *user*'s data-manager scope
    (``dm_grant_scope``: project and project-site grants, unit subtrees;
    admin all), newest hold first, keyset paged. No personal data: ids,
    site, reason and times only. ``ValueError`` names a bad argument."""
    from app.services.data_management_service import dm_grant_scope

    if status not in (HELD, REJECTED):
        raise ValueError("status must be held or rejected.")
    try:
        limit = max(1, min(LIST_MAX, int(limit))) if limit not in (None, "") else LIST_DEFAULT
    except (TypeError, ValueError):
        raise ValueError("limit must be an integer.") from None
    after = _parse_cursor(cursor)
    scope = dm_grant_scope(user)
    clauses = []
    if scope.project_ids:
        clauses.append(VaWebIntakeDraft.project_id.in_(sorted(scope.project_ids)))
    if scope.pairs:
        clauses.append(sa.tuple_(VaWebIntakeDraft.project_id, VaWebIntakeDraft.site_id).in_(sorted(scope.pairs)))
    if scope.unit_grant_ids:
        clauses.append(VaWebIntakeDraft.org_unit_id.in_(scope.unit_subtree()))
    if not clauses:
        return {"items": [], "next_cursor": None}
    D = VaWebIntakeDraft
    stmt = sa.select(D.draft_id, D.va_sid, D.unique_id, D.project_id, D.site_id, D.org_unit_id,
                     D.collection_hold, D.collection_hold_reason, D.collection_hold_at, D.submitted_at,
                     D.meta["startedAt"].astext.label("started"), D.created_at
                     ).where(D.collection_hold == status, sa.or_(*clauses))
    if project_id:
        stmt = stmt.where(D.project_id == project_id)
    if site_id:
        stmt = stmt.where(D.site_id == site_id)
    if after:
        stmt = stmt.where(sa.tuple_(D.collection_hold_at, D.draft_id) < after)
    rows = db.session.execute(
        stmt.order_by(D.collection_hold_at.desc(), D.draft_id.desc()).limit(limit + 1)
    ).all()
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [{
            "va_sid": r.va_sid, "unique_id": r.unique_id, "project_id": r.project_id, "site_id": r.site_id,
            "org_unit_id": str(r.org_unit_id) if r.org_unit_id else None,
            "collection_hold": r.collection_hold, "reason": r.collection_hold_reason,
            "held_at": r.collection_hold_at.isoformat() if r.collection_hold_at else None,
            "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
            "started_at": _started_at({"startedAt": r.started}, r.created_at).isoformat(),
        } for r in rows],
        "next_cursor": f"{rows[-1].collection_hold_at.isoformat()}|{rows[-1].draft_id}" if more else None,
    }
