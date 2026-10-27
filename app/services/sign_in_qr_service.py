"""Sign-in QR for data collectors and death reporters (digitva-3g19, digitva-5bzf.15).

Baseline: docs/policy/mobile-sign-in.md section 8. One scan enrols a device
and opens that one user's normal device session, with no password typed.

Token: ``secrets.token_urlsafe(32)``, stored only as its SHA-256 digest
(``device_auth_service.hash_token``), single use, 6 hours, bound to the first
device that redeems it and to the user's ``auth_session_version`` at issue. At most one is pending per user; a new issue voids it.
Eligibility (checked at issue and again at redeem): an active ``interviewer``
or ``death_reporter`` grant that reaches an active project (a coder grant, or a
self-coding grant, alone is not enough: owner 2026-10-27, those users sign in
on the web) and no other active grant of any kind, in any project; a coder
grant held beside a collector grant is tolerated. Issuer: an admin, or anyone who may manage every active grant the
person holds (``authz.grant_list_filter``, the section 3 ``can_grant`` rule).

Audit: ``sign_in_qr_issued`` / ``_redeemed`` / ``_expired`` / ``_revoked`` / ``_refused``,
never the token. Expiry is noticed lazily (at the next issue, revoke or
redeem attempt); no sweep runs. Nothing here logs a token.
"""

from __future__ import annotations

import base64
import json
import logging
import secrets
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import (
    AuthSignInToken,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import authz, email_service, web_intake_service
from app.services import device_auth_service as devices
from app.services.security_event_service import record_security_event
from app.services.site_maintenance_service import should_block_non_admin_after_cutoff
from app.services.totp_service import provisioning_qr_png

log = logging.getLogger(__name__)

TOKEN_TTL = timedelta(hours=6)
DELIVERIES = ("show", "email")
COLLECTOR_ROLES = frozenset({VaAccessRoles.interviewer, VaAccessRoles.death_reporter})
ELIGIBLE_ROLES = COLLECTOR_ROLES | {VaAccessRoles.coder}
_TOKEN_MAX = 256
INVALID_MESSAGE = "Sign-in QR is invalid or expired."

_G = VaUserAccessGrants


class SignInQrError(Exception):
    """A refused issue/revoke: *status* is the HTTP status, *code* the machine code."""

    def __init__(self, message: str, status: int = 400, code: str | None = None):
        super().__init__(message)
        self.status = status
        self.code = code


def _now() -> datetime:
    return datetime.now(UTC)


def _not_found() -> SignInQrError:
    return SignInQrError("User not found.", 404, "not_found")


def _invalid() -> devices.DeviceAuthError:
    # One answer for every redeem failure (unknown, used, expired, revoked,
    # ineligible, inactive): nothing tells a guesser which.
    return devices.DeviceAuthError(INVALID_MESSAGE, "sign_in_qr_invalid", 404)


# ---------------------------------------------------------------------------
# Eligibility and issuer rule
# ---------------------------------------------------------------------------


def eligible_project(user: VaUsers) -> str | None:
    """The project a sign-in QR would enrol *user*'s device under, or None
    when they are not eligible: active account, at least one active
    interviewer or death_reporter grant on an active project that opens
    the app (``has_device_access``), and no other active grant of any kind or
    global scope anywhere."""
    if user.user_status != VaStatuses.active:
        return None
    rows = db.session.execute(
        sa.select(_G.role, _G.scope_type).where(_G.user_id == user.user_id, _G.grant_status == VaStatuses.active)
    ).all()
    if not rows or any(
        r.role not in ELIGIBLE_ROLES or r.scope_type == VaAccessScopeTypes.global_scope for r in rows
    ):
        return None
    resolved = authz.resolve_grants(user)
    if resolved.is_admin:
        return None
    # Only a project where the person can interview or register a death
    # counts, so a closed project is never picked for the enrolment.
    context = web_intake_service.interviewer_context(user, _grants=resolved)
    reach = context + web_intake_service.register_death_context(user, context, _grants=resolved)
    projects = sorted({pid for pid in (e["project_id"] for e in reach) if devices._project_active(pid)})
    return projects[0] if projects else None


def may_issue(actor, user_id) -> bool:
    """Admin, or an actor who may manage **every** active grant of the target
    (and the target holds at least one). Partial authority is not enough: the
    QR signs in as the whole person."""
    grants = authz.resolve_grants(actor)
    if grants.is_admin:
        return True
    active = (_G.user_id == user_id, _G.grant_status == VaStatuses.active)
    managed = sa.func.coalesce(authz.grant_list_filter(actor, _grants=grants), sa.false())
    return bool(db.session.scalar(sa.select(sa.and_(
        sa.exists().where(*active),
        sa.not_(sa.exists().where(*active, sa.not_(managed))),
    ))))


# ---------------------------------------------------------------------------
# Issue, revoke, status
# ---------------------------------------------------------------------------


def qr_payload(token: str) -> str:
    """The JSON the sign-in QR carries (the app's ``parseEnrolmentQr`` reads
    ``sign_in`` as it reads ``enroll``)."""
    return json.dumps(
        {"v": 1, "server": current_app.config["DEVICE_PUBLIC_URL"], "sign_in": token},
        separators=(",", ":"),
    )


def _void_pending(user_id, *, actor_id, reason: str) -> list:
    """Void the user's pending token(s) in one UPDATE (a token redeemed a
    moment earlier is never touched, so it is never marked revoked); audits
    only the rows it voided. An expired one is audited as expired, once.
    Returns the voided rows."""
    now = _now()
    t = AuthSignInToken.__table__
    rows = db.session.execute(
        sa.update(t)
        .where(t.c.user_id == user_id, t.c.redeemed_at.is_(None), t.c.revoked_at.is_(None))
        .values(revoked_at=now)
        .returning(t.c.id, t.c.expires_at)
    ).all()
    for row in rows:
        if row.expires_at > now:
            record_security_event(
                user_id=user_id, actor_user_id=actor_id, event_type="sign_in_qr_revoked",
                detail={"reason": reason},
            )
            continue
        noted = db.session.execute(
            sa.update(t).where(t.c.id == row.id, t.c.expiry_noted_at.is_(None))
            .values(expiry_noted_at=now).returning(t.c.id)
        ).first()
        if noted:
            record_security_event(user_id=user_id, actor_user_id=actor_id, event_type="sign_in_qr_expired")
    return rows


def issue(actor, user_id, delivery) -> dict:
    """Issue a sign-in QR for *user_id* (see module doc). ``delivery`` ``show``
    returns the token, payload and QR PNG once; ``email`` sends them to the
    user's verified address and returns ``{"emailed": True, ...}`` only.
    Commits. Raises SignInQrError."""
    if delivery not in DELIVERIES:
        raise SignInQrError("delivery must be show or email.")
    user = db.session.get(VaUsers, user_id)
    if user is None or not may_issue(actor, user.user_id):
        raise _not_found()
    if eligible_project(user) is None:
        raise SignInQrError(
            "A sign-in QR is only for an active data collector or death reporter with no other role.",
            400, "not_eligible",
        )
    if delivery == "email" and not (user.email and user.email_verified):
        raise SignInQrError("This user has no verified email; show the QR instead.", 400, "no_verified_email")
    if delivery == "email" and not email_service.can_deliver_to(user.email):
        raise SignInQrError("Email could not be sent.", 502, "email_failed")
    problem = devices.device_public_url_problem(
        current_app.config.get("DEVICE_PUBLIC_URL"), allow_insecure=devices._insecure_device_url_allowed()
    )
    if problem:
        log.error("sign-in QR refused | %s", problem)
        raise SignInQrError("Device enrolment is not configured on this server.", 503, "device_url_insecure")

    # Serialise issuers for this person (the partial unique index is the backstop).
    db.session.execute(sa.select(VaUsers.user_id).where(VaUsers.user_id == user.user_id).with_for_update())
    _void_pending(user.user_id, actor_id=actor.user_id, reason="reissued")
    token = secrets.token_urlsafe(32)
    now = _now()
    row = AuthSignInToken(
        user_id=user.user_id, token_hash=devices.hash_token(token), issued_by=actor.user_id,
        issued_at=now, expires_at=now + TOKEN_TTL,
        user_session_version=user.auth_session_version or 0,
    )
    db.session.add(row)
    db.session.flush()
    record_security_event(
        user_id=user.user_id, actor_user_id=actor.user_id, event_type="sign_in_qr_issued",
        detail={"delivery": delivery},
    )
    db.session.commit()

    payload = qr_payload(token)
    png = provisioning_qr_png(payload)
    expires_at = row.expires_at.isoformat()
    if delivery == "email":
        try:
            email_service.send_sign_in_qr_email(user, code=token, qr_png=png)
        except Exception as exc:  # SMTP text can carry the address: log the type only
            log.warning("sign-in QR email failed: %s | user_id=%s", type(exc).__name__, user.user_id)
            _void_pending(user.user_id, actor_id=actor.user_id, reason="email_failed")
            db.session.commit()
            raise SignInQrError("Email could not be sent.", 502, "email_failed") from None
        return {"emailed": True, "expires_at": expires_at}
    return {
        "code": token,
        "qr_payload": payload,
        "qr_png": base64.b64encode(png).decode("ascii"),
        "expires_at": expires_at,
    }


def revoke(actor, user_id) -> bool:
    """Void the user's pending sign-in QR. Returns whether one was pending.
    Same issuer rule as issuing; commits. Raises SignInQrError (404)."""
    user = db.session.get(VaUsers, user_id)
    if user is None or not may_issue(actor, user.user_id):
        raise _not_found()
    voided = _void_pending(user.user_id, actor_id=actor.user_id, reason="revoked")
    db.session.commit()
    return bool(voided)


def _status(row: AuthSignInToken, now) -> str:
    if row.redeemed_at is not None:
        return "redeemed"
    if row.revoked_at is not None:
        return "revoked"
    return "expired" if row.expires_at <= now else "pending"


def list_for_user(actor, user_id, *, limit: int = 5) -> list[dict]:
    """The user's latest sign-in QRs, newest first: status and times only,
    never the token. Same visibility rule as issuing (404 otherwise)."""
    if db.session.get(VaUsers, user_id) is None or not may_issue(actor, user_id):
        raise _not_found()
    now = _now()
    rows = db.session.scalars(
        sa.select(AuthSignInToken).where(AuthSignInToken.user_id == user_id)
        .order_by(AuthSignInToken.issued_at.desc()).limit(max(1, min(limit, 20)))
    ).all()
    return [
        {
            "status": _status(r, now),
            "issued_at": r.issued_at.isoformat(),
            "expires_at": r.expires_at.isoformat(),
            "redeemed_at": r.redeemed_at.isoformat() if r.redeemed_at else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Redeem (public, from the phone)
# ---------------------------------------------------------------------------


def token_limit_key(token) -> str:
    """Rate-limit key for a presented token: its digest, never the token."""
    text = token.strip()[:_TOKEN_MAX] if isinstance(token, str) else ""
    return f"sign-in-qr:{devices.hash_token(text)}" if text else "sign-in-qr:"


def _burn(token_id, user_id, reason: str) -> devices.DeviceAuthError:
    """Kill a claimed token that cannot be used (the holder is no longer
    eligible, or their sessions were reset since issue), committing at once and
    auditing ``sign_in_qr_refused`` (no token); returns the one public error."""
    db.session.execute(
        sa.update(AuthSignInToken).where(AuthSignInToken.id == token_id)
        .values(redeemed_at=None, revoked_at=_now())
    )
    record_security_event(user_id=user_id, event_type="sign_in_qr_refused", detail={"reason": reason})
    db.session.commit()
    log.warning("sign-in QR refused at redeem | reason=%s", reason)
    return _invalid()


def redeem(token, *, device_name, platform, app_version, client_device_uuid=None):
    """Consume a sign-in QR: enrol a device and open the user's normal device
    session. Returns ``(device, device_secret, IssuedTokens, user)``. Every
    failure is one 404 ``sign_in_qr_invalid``. Caller commits a success."""
    name, version = devices._device_fields(device_name, platform, app_version)
    if not isinstance(token, str) or not token.strip() or len(token) > _TOKEN_MAX:
        raise _invalid()
    digest = devices.hash_token(token.strip())
    now = _now()
    table = AuthSignInToken.__table__
    claimed = db.session.execute(
        sa.update(table)
        .where(
            table.c.token_hash == digest, table.c.redeemed_at.is_(None),
            table.c.revoked_at.is_(None), table.c.expires_at > now,
        )
        .values(redeemed_at=now)
        .returning(table.c.id, table.c.user_id, table.c.user_session_version)
    ).first()
    if claimed is None:
        stale = db.session.scalar(sa.select(AuthSignInToken).where(
            AuthSignInToken.token_hash == digest, AuthSignInToken.redeemed_at.is_(None),
            AuthSignInToken.revoked_at.is_(None), AuthSignInToken.expiry_noted_at.is_(None),
        ))
        if stale is not None:
            stale.expiry_noted_at = now
            record_security_event(user_id=stale.user_id, event_type="sign_in_qr_expired")
            db.session.commit()
        raise _invalid()

    user = db.session.get(VaUsers, claimed.user_id)
    project_id = eligible_project(user) if user is not None else None
    if project_id is None:
        raise _burn(claimed.id, claimed.user_id, "not_eligible")
    # Sign out everywhere, a password or factor reset: the QR dies with them.
    if (user.auth_session_version or 0) != claimed.user_session_version:
        raise _burn(claimed.id, claimed.user_id, "session_changed")
    # Transient: the plain rollback in the error handler un-claims the token.
    if not user.is_admin() and should_block_non_admin_after_cutoff():
        raise _invalid()

    device, secret = devices._add_device(project_id, name, platform, version, None, client_device_uuid)
    device.enrolled_via_sign_in_token = claimed.id
    db.session.execute(
        sa.update(table).where(table.c.id == claimed.id).values(redeemed_device_id=device.device_id)
    )
    issued, user = devices._open_authorized_session(device, user)
    record_security_event(
        user_id=user.user_id, event_type="sign_in_qr_redeemed",
        detail={"device_id": str(device.device_id)},
    )
    return device, secret, issued, user
