"""Deleting an account from the signed-in app or website (digitva-et16).

Policy: docs/policy/public-privacy-and-data-requests.md section 8, and
docs/policy/public-demo.md section 9a for demo accounts.

* Demo accounts delete themselves at once: ``public_demo_purge_service.
  delete_own_account`` (the route checks the password first).
* Every other (staff) account files a request here; an admin reviews it on the
  Users page and marks it handled. Deletion itself is manual for now.

Audit: ``account_deletion_requested`` and ``account_deletion_request_handled``
security events, never with a name, email or username in ``detail``.
"""

import logging
from datetime import UTC, datetime

import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import AuthAccountDeletionRequest, VaUsers
from app.services import email_service
from app.services.security_event_service import record_security_event

log = logging.getLogger(__name__)

REQUEST_EVENT = "account_deletion_requested"
HANDLED_EVENT = "account_deletion_request_handled"
#: Most pending requests one admin listing returns (oldest first).
LIST_LIMIT = 100


def _pending(user_id):
    return db.session.scalar(sa.select(AuthAccountDeletionRequest).where(
        AuthAccountDeletionRequest.user_id == user_id,
        AuthAccountDeletionRequest.handled_at.is_(None),
    ))


def request_deletion(user: VaUsers, *, via: str) -> tuple[AuthAccountDeletionRequest, bool]:
    """The caller's pending request, filing one if there is none:
    ``(request, created)``. A repeat while one is pending changes nothing. A
    concurrent duplicate loses on the partial unique index and gets the
    winner's row. The caller commits, then calls ``notify`` when created."""
    existing = _pending(user.user_id)
    if existing is not None:
        return existing, False
    row = AuthAccountDeletionRequest(user_id=user.user_id, requested_via=via)
    try:
        with db.session.begin_nested():
            db.session.add(row)
    except sa.exc.IntegrityError:
        return _pending(user.user_id), False
    record_security_event(user_id=user.user_id, event_type=REQUEST_EVENT, detail={"via": via})
    return row, True


def notify(user: VaUsers) -> None:
    """Tell ``PUBLIC_CONTACT_EMAIL`` a request is waiting, through the contact
    form's mail path, when that address is set and mail really goes out.
    Fixed text: the account's name, and its email as Reply-To when it has one."""
    to = (current_app.config.get("PUBLIC_CONTACT_EMAIL") or "").strip()
    if not to or not email_service.can_send_mail():
        return
    email_service.send_account_deletion_request_notice(to=to, name=user.name, email=user.email or None)


def pending_requests(limit: int = LIST_LIMIT) -> dict:
    """Pending requests, oldest first, at most *limit*, with the account's
    name and contact details for the admin: ``{requests, total}``."""
    pending = AuthAccountDeletionRequest.handled_at.is_(None)
    rows = db.session.execute(
        sa.select(AuthAccountDeletionRequest, VaUsers.name, VaUsers.email, VaUsers.phone)
        .join(VaUsers, VaUsers.user_id == AuthAccountDeletionRequest.user_id)
        .where(pending)
        .order_by(AuthAccountDeletionRequest.requested_at, AuthAccountDeletionRequest.id)
        .limit(limit)
    ).all()
    total = db.session.scalar(sa.select(sa.func.count()).select_from(AuthAccountDeletionRequest).where(pending))
    return {
        "requests": [{
            "id": str(req.id),
            "user_id": str(req.user_id),
            "name": name,
            "email": email,
            "phone": phone,
            "requested_via": req.requested_via,
            "requested_at": req.requested_at.isoformat(),
        } for req, name, email, phone in rows],
        "total": total,
    }


def mark_handled(request_id, admin: VaUsers) -> bool:
    """Mark one pending request handled by *admin*; False when there is no
    such pending request. The caller commits."""
    row = db.session.scalar(sa.select(AuthAccountDeletionRequest).where(
        AuthAccountDeletionRequest.id == request_id,
        AuthAccountDeletionRequest.handled_at.is_(None),
    ).with_for_update())
    if row is None:
        return False
    row.handled_at = datetime.now(UTC)
    row.handled_by = admin.user_id
    record_security_event(
        user_id=row.user_id, actor_user_id=admin.user_id, event_type=HANDLED_EVENT,
        detail={"request_id": str(row.id)},
    )
    return True
