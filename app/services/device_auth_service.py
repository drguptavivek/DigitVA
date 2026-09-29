"""Device enrolment, interviewer device sessions and bearer-token resolution.

Baseline: docs/policy/field-data-collection.md ("Path B design"); design and
API contract: .tasks/2026-09-30-android-collection-app.md. Routes:
app/routes/api/device.py (device API) and app/routes/admin_devices.py
(enrolment codes, device list, revoke).

Credentials. Enrolment codes, device secrets and access/refresh tokens are
``secrets.token_urlsafe(32)`` (256 bits). Only their SHA-256 hex digest is
stored: a slow hash buys nothing against a 256-bit random value, and a
digest lets every lookup be an indexed equality. The device secret is
compared with ``hmac.compare_digest``.

Sessions. One row per (device, interviewer) sign-in. The access token lives
``ACCESS_TTL``; the refresh token rotates on every use and its lifetime
slides (``DEVICE_REFRESH_TTL_DAYS``, proposed decision C1: 30 days), capped
at ``DEVICE_SESSION_MAX_DAYS`` from sign-in. A refresh must also present the
session's device id and secret. Presenting any of the last
``RETIRED_REFRESH_KEEP`` rotated-away refresh tokens is reuse and revokes the
session; the refusal code (``refresh_reused``, or ``refresh_retry_race``
inside ``REFRESH_RETRY_GRACE`` of the rotation) is distinct from
``session_revoked``, which the app treats as "wipe this interviewer's store"
and so is reserved for an administrative revoke, a withdrawn grant or a
changed account. Grant, device, project and account checks run at
sign-in and at every refresh; the per-request access-token check covers the
account (active, session version) and the device, so a withdrawn interviewer
grant ends the session at the next refresh, within ``ACCESS_TTL``.

Second factor. Failed device second-factor attempts are counted per account
from the audit trail (``SECOND_FACTOR_MAX_FAILURES`` in
``SECOND_FACTOR_WINDOW`` since the last successful device sign-in); the fifth
records ``second_factor_lockout`` and sign-in is refused, 429
``second_factor_locked``, until the window passes.

Nothing here logs a token, secret, code, email or password.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import sqlalchemy as sa
from flask import current_app
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.models import (
    AuthDevice,
    AuthDeviceEnrolmentCode,
    AuthDeviceSession,
    AuthSecurityEvent,
    VaProjectMaster,
    VaStatuses,
    VaUsers,
)
from app.services import totp_service
from app.services.security_event_service import record_security_event
from app.services.site_maintenance_service import should_block_non_admin_after_cutoff

log = logging.getLogger(__name__)

DEVICE_API_PREFIX = "/api/v1/device/"
ACCESS_TTL = timedelta(minutes=15)
DEFAULT_REFRESH_TTL_DAYS = 30
DEFAULT_SESSION_MAX_DAYS = 90
#: Rotated-away refresh hashes kept per session for reuse detection.
RETIRED_REFRESH_KEEP = 5
#: A retry with the token rotated away less than this ago is treated as a lost
#: response (409 ``refresh_retry_race``), not as theft (401 ``refresh_reused``).
REFRESH_RETRY_GRACE = timedelta(seconds=60)
SECOND_FACTOR_MAX_FAILURES = 5
SECOND_FACTOR_WINDOW = timedelta(minutes=15)
#: Revocation reasons that mean "the refresh token was replayed". They answer
#: refresh_reused / refresh_retry_race so the app keeps the interviewer's data;
#: every other reason answers session_revoked, on which the app wipes.
_REUSE_REASONS = frozenset({"refresh_reuse", "refresh_retry_race"})
#: Revocations that end the session but must not destroy unsent interviews:
#: a password or factor reset, a deactivated account, a closed project. They
#: answer session_ended (sign in again, keep data). Only a deliberate revoke
#: of the device, a withdrawn grant or a sign-out answers session_revoked.
_KEEP_DATA_REASONS = frozenset({"account_changed", "project_inactive"})
#: Hosts an http:// DEVICE_PUBLIC_URL may name outside debug/testing.
_PLAIN_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1", "10.0.2.2"})
ENROLMENT_DEFAULT_MINUTES = 60
ENROLMENT_MAX_MINUTES = 7 * 24 * 60
ENROLMENT_MAX_USES = 200
#: Throttle for last_seen_at writes, so a bearer request is not always a write.
LAST_SEEN_INTERVAL = timedelta(seconds=60)
OUTSTANDING_MAX_IDS = 1000
_DEVICE_NAME_MAX = 64
_APP_VERSION_MAX = 32
_PLATFORMS = frozenset({"android"})
_DUMMY_PASSWORD_HASH = generate_password_hash("digitva-device-timing-equaliser")


class DeviceAuthError(Exception):
    """A refused device call: ``code`` is the contract's machine code."""

    def __init__(self, message: str, code: str, status_code: int):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass
class IssuedTokens:
    access_token: str
    refresh_token: str
    session: AuthDeviceSession


def _now() -> datetime:
    return datetime.now(UTC)


def _new_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _refresh_ttl() -> timedelta:
    return timedelta(days=int(current_app.config.get("DEVICE_REFRESH_TTL_DAYS") or DEFAULT_REFRESH_TTL_DAYS))


def _session_max_age() -> timedelta:
    return timedelta(days=int(current_app.config.get("DEVICE_SESSION_MAX_DAYS") or DEFAULT_SESSION_MAX_DAYS))


def _insecure_device_url_allowed() -> bool:
    """Debug and test builds may put any URL in an enrolment QR."""
    return bool(current_app.debug or current_app.testing)


def device_public_url_problem(url: str | None, *, allow_insecure: bool) -> str | None:
    """Why *url* must not go into an enrolment QR, or None. Outside debug and
    testing it must be https, except http to a local development host (an
    emulator reaches the dev server as 10.0.2.2): the interviewer's password
    is sent to it."""
    parsed = urlsplit((url or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "DEVICE_PUBLIC_URL is not an http(s) URL."
    if parsed.scheme == "http" and not allow_insecure and parsed.hostname not in _PLAIN_HTTP_HOSTS:
        return "DEVICE_PUBLIC_URL must use https outside development."
    return None


def _project_active(project_id: str) -> bool:
    project = db.session.get(VaProjectMaster, project_id)
    return project is not None and project.project_status == VaStatuses.active


def has_interviewer_access(user: VaUsers, project_id: str) -> bool:
    """An active interviewer grant (any scope) reaching *project_id*, through
    the same resolution the intake bootstrap serves (``interviewer_context``),
    so a session is never open for a project the app would get no scope in.
    That resolution skips a project whose ``web_intake_mode`` is ``off``."""
    from app.services.web_intake_service import interviewer_context

    return any(entry["project_id"] == project_id for entry in interviewer_context(user))


# ---------------------------------------------------------------------------
# Enrolment
# ---------------------------------------------------------------------------


def _bounded_int(value, *, default: int, low: int, high: int, name: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise DeviceAuthError(f"{name} must be a whole number from {low} to {high}.", "invalid_request", 400)
    return value


def create_enrolment_code(project_id: str, *, actor: VaUsers, expires_in_minutes=None, max_uses=None) -> tuple[AuthDeviceEnrolmentCode, str]:
    """Issue an enrolment code for *project_id*. Returns (row, plaintext code);
    the code is shown once and only its hash is stored. Refused (503
    ``device_url_insecure``) when DEVICE_PUBLIC_URL, which the QR carries,
    is plain http outside development. Caller commits."""
    problem = device_public_url_problem(
        current_app.config.get("DEVICE_PUBLIC_URL"), allow_insecure=_insecure_device_url_allowed()
    )
    if problem:
        log.error("enrolment code refused | %s", problem)
        raise DeviceAuthError("Device enrolment is not configured on this server.", "device_url_insecure", 503)
    if not _project_active(project_id):
        raise DeviceAuthError("Project not found.", "not_found", 404)
    minutes = _bounded_int(expires_in_minutes, default=ENROLMENT_DEFAULT_MINUTES, low=5,
                           high=ENROLMENT_MAX_MINUTES, name="expires_in_minutes")
    uses = _bounded_int(max_uses, default=1, low=1, high=ENROLMENT_MAX_USES, name="max_uses")
    code = _new_secret()
    row = AuthDeviceEnrolmentCode(
        project_id=project_id,
        code_hash=hash_token(code),
        expires_at=_now() + timedelta(minutes=minutes),
        max_uses=uses,
        created_by=actor.user_id,
    )
    db.session.add(row)
    db.session.flush()
    record_security_event(
        user_id=None, actor_user_id=actor.user_id, event_type="device_enrolment_code_created",
        detail={"project_id": project_id, "max_uses": uses, "expires_in_minutes": minutes},
    )
    return row, code


def _clean_text(value, *, limit: int, name: str, required: bool) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise DeviceAuthError(f"{name} is required.", "invalid_request", 400)
        return None
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise DeviceAuthError(f"{name} must be text of at most {limit} characters.", "invalid_request", 400)
    return value.strip()


def enrol_device(code, *, device_name, platform, app_version) -> tuple[AuthDevice, str]:
    """Consume one use of an enrolment code and register a device. Returns
    (device, plaintext device secret). An unknown, expired, revoked or used-up
    code is one answer, 404 ``enrolment_invalid``. Caller commits."""
    name = _clean_text(device_name, limit=_DEVICE_NAME_MAX, name="device_name", required=True)
    version = _clean_text(app_version, limit=_APP_VERSION_MAX, name="app_version", required=False)
    if platform not in _PLATFORMS:
        raise DeviceAuthError("platform must be android.", "invalid_request", 400)
    if not isinstance(code, str) or not code.strip():
        raise DeviceAuthError("Enrolment code is invalid or expired.", "enrolment_invalid", 404)

    table = AuthDeviceEnrolmentCode.__table__
    # Atomic: two phones scanning a single-use code cannot both consume it.
    consumed = db.session.execute(
        sa.update(table)
        .where(
            table.c.code_hash == hash_token(code.strip()),
            table.c.revoked_at.is_(None),
            table.c.expires_at > _now(),
            table.c.use_count < table.c.max_uses,
        )
        .values(use_count=table.c.use_count + 1)
        .returning(table.c.id, table.c.project_id)
    ).first()
    if consumed is None or not _project_active(consumed.project_id):
        raise DeviceAuthError("Enrolment code is invalid or expired.", "enrolment_invalid", 404)

    secret = _new_secret()
    device = AuthDevice(
        project_id=consumed.project_id,
        name=name,
        platform=platform,
        app_version=version,
        secret_hash=hash_token(secret),
        enrolled_via=consumed.id,
    )
    db.session.add(device)
    db.session.flush()
    record_security_event(
        user_id=None, event_type="device_enrolled",
        detail={"device_id": str(device.device_id), "project_id": device.project_id},
    )
    log.info("device enrolled | device=%s | project=%s", device.device_id, device.project_id)
    return device, secret


def revoke_device(device: AuthDevice, *, actor: VaUsers) -> int:
    """Revoke a device and every session on it. Returns the number of sessions
    ended. Idempotent. Caller commits."""
    now = _now()
    if device.revoked_at is None:
        device.revoked_at = now
        device.revoked_by = actor.user_id
    ended = db.session.execute(
        sa.update(AuthDeviceSession)
        .where(AuthDeviceSession.device_id == device.device_id, AuthDeviceSession.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason="device_revoked")
    ).rowcount
    record_security_event(
        user_id=None, actor_user_id=actor.user_id, event_type="device_revoked",
        detail={"device_id": str(device.device_id), "sessions_ended": ended},
    )
    return ended


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def _get_device(device_id) -> AuthDevice | None:
    try:
        return db.session.get(AuthDevice, uuid.UUID(str(device_id)))
    except (ValueError, TypeError, AttributeError):
        return None


def _device_by_secret(device_id, device_secret) -> AuthDevice:
    """The device named by id whose secret matches (constant-time), else 401
    ``device_invalid``. Revocation is the caller's check."""
    device = _get_device(device_id)
    presented = device_secret if isinstance(device_secret, str) else ""
    if device is None or not hmac.compare_digest(hash_token(presented), device.secret_hash):
        raise DeviceAuthError("Device is not recognised.", "device_invalid", 401)
    return device


def _authenticate_device(device_id, device_secret) -> AuthDevice:
    device = _device_by_secret(device_id, device_secret)
    if device.revoked_at is not None or not _project_active(device.project_id):
        raise DeviceAuthError("This device has been revoked.", "device_revoked", 403)
    return device


def _sign_in_failed(device: AuthDevice, user: VaUsers | None, reason: str) -> None:
    """Audit a refused sign-in: device id and reason only, never the email."""
    record_security_event(
        user_id=user.user_id if user else None, event_type="device_session_failed",
        detail={"device_id": str(device.device_id), "reason": reason},
    )
    db.session.commit()
    log.warning("device sign-in refused | device=%s | reason=%s", device.device_id, reason)


def _second_factor_failures(user: VaUsers) -> int:
    """Failed device second-factor attempts for *user* in the window, counted
    since their last successful device sign-in (a success resets the count,
    as the web flow's pre-auth state does)."""
    since = _now() - SECOND_FACTOR_WINDOW
    last_success = db.session.scalar(
        sa.select(sa.func.max(AuthSecurityEvent.occurred_at)).where(
            AuthSecurityEvent.user_id == user.user_id,
            AuthSecurityEvent.event_type == "device_session_opened",
            AuthSecurityEvent.occurred_at > since,
        )
    )
    return db.session.scalar(
        sa.select(sa.func.count()).select_from(AuthSecurityEvent).where(
            AuthSecurityEvent.user_id == user.user_id,
            AuthSecurityEvent.event_type == "device_session_failed",
            AuthSecurityEvent.occurred_at > max(since, last_success or since),
            AuthSecurityEvent.detail["reason"].astext == "second_factor_invalid",
        )
    ) or 0


def _refuse(device: AuthDevice, user: VaUsers, message: str, code: str, status_code: int) -> DeviceAuthError:
    """Audit a post-password refusal (reason = the contract code) and return
    the error to raise."""
    _sign_in_failed(device, user, code)
    return DeviceAuthError(message, code, status_code)


def _issue(session: AuthDeviceSession) -> IssuedTokens:
    access, refresh = _new_secret(), _new_secret()
    now = _now()
    session.access_hash = hash_token(access)
    session.access_expires_at = now + ACCESS_TTL
    session.refresh_hash = hash_token(refresh)
    # Sliding, but never past the absolute cap from sign-in.
    session.refresh_expires_at = min(now + _refresh_ttl(), (session.created_at or now) + _session_max_age())
    session.last_seen_at = now
    return IssuedTokens(access_token=access, refresh_token=refresh, session=session)


def open_session(*, device_id, device_secret, email, password, otp=None) -> tuple[IssuedTokens, VaUsers]:
    """Sign an interviewer in on an enrolled device (the web login's checks,
    with the device credential in place of the CAPTCHA). Raises
    DeviceAuthError; a refused attempt is audited and committed. Caller
    commits a success."""
    device = _authenticate_device(device_id, device_secret)
    email = email.strip().lower() if isinstance(email, str) else ""
    password = password if isinstance(password, str) else ""
    user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email)) if email else None
    if user is None:
        # Spend a hash check anyway so unknown emails take as long.
        check_password_hash(_DUMMY_PASSWORD_HASH, password)
    if user is None or not user.check_password(password) or not user.is_active:
        _sign_in_failed(device, user if user and user.is_active else None, "invalid_credentials")
        raise DeviceAuthError("Invalid email or password.", "invalid_credentials", 401)
    if not user.email_verified:
        raise _refuse(device, user, "Verify your email address before signing in.", "email_unverified", 403)
    if not user.pw_reset_t_and_c:
        raise _refuse(device, user, "Change your password on the website before signing in.",
                      "password_change_required", 403)
    if not user.is_admin() and should_block_non_admin_after_cutoff():
        raise _refuse(device, user, "Site is under maintenance.", "maintenance", 403)

    if totp_service.needs_second_factor(user):
        # Checked before the code is: a locked account gets no more guesses.
        if _second_factor_failures(user) >= SECOND_FACTOR_MAX_FAILURES:
            raise _refuse(device, user, "Too many wrong codes. Try again later.", "second_factor_locked", 429)
        code = otp.strip() if isinstance(otp, str) else ""
        if not code:
            raise _refuse(device, user, "A TOTP or recovery code is required.", "second_factor_required", 401)
        by_totp = totp_service.has_confirmed_totp(user.user_id) and totp_service.verify(user, code)
        by_recovery = (not by_totp) and totp_service.verify_recovery_code(user, code)
        if not (by_totp or by_recovery):
            db.session.rollback()
            _sign_in_failed(device, user, "second_factor_invalid")
            if _second_factor_failures(user) == SECOND_FACTOR_MAX_FAILURES:
                record_security_event(
                    user_id=user.user_id, event_type="second_factor_lockout",
                    detail={"device_id": str(device.device_id), "channel": "device"},
                )
                db.session.commit()
            raise DeviceAuthError("A TOTP or recovery code is required.", "second_factor_required", 401)
        if by_recovery:
            record_security_event(
                user_id=user.user_id, event_type="recovery_code_used",
                detail={"remaining": totp_service.remaining_recovery_code_count(user.user_id)},
            )

    if not has_interviewer_access(user, device.project_id):
        _sign_in_failed(device, user, "no_interviewer_grant")
        raise DeviceAuthError("You have no interviewer access in this device's project.", "no_interviewer_grant", 403)

    session = AuthDeviceSession(
        device_id=device.device_id,
        user_id=user.user_id,
        user_session_version=user.auth_session_version or 0,
    )
    issued = _issue(session)
    db.session.add(session)
    device.last_seen_at = session.last_seen_at
    db.session.flush()
    record_security_event(
        user_id=user.user_id, event_type="device_session_opened",
        detail={"device_id": str(device.device_id)},
    )
    log.info("device session opened | device=%s | session=%s | user=%s", device.device_id, session.session_id, user.user_id)
    return issued, user


def _revoke(session: AuthDeviceSession, reason: str) -> None:
    session.revoked_at = _now()
    session.revoked_reason = reason
    record_security_event(
        user_id=session.user_id, event_type="device_session_revoked",
        detail={"device_id": str(session.device_id), "reason": reason},
    )
    log.warning("device session revoked | session=%s | reason=%s", session.session_id, reason)


def _session_still_allowed(session: AuthDeviceSession) -> tuple[bool, str]:
    """Whether a session may continue: device, project, account and grant."""
    device = db.session.get(AuthDevice, session.device_id)
    if device is None or device.revoked_at is not None:
        return False, "device_revoked"
    if not _project_active(device.project_id):
        return False, "project_inactive"
    user = db.session.get(VaUsers, session.user_id)
    if user is None or not user.is_active or (user.auth_session_version or 0) != session.user_session_version:
        return False, "account_changed"
    if not has_interviewer_access(user, device.project_id):
        return False, "grant_withdrawn"
    return True, ""


def _revoked_error(session: AuthDeviceSession) -> DeviceAuthError:
    """The refusal for a revoked session, by why it was revoked: a replayed
    refresh token keeps the app's data (``refresh_reused`` /
    ``refresh_retry_race``); anything else is ``session_revoked``."""
    if session.revoked_reason == "refresh_retry_race":
        return DeviceAuthError("Sign in again.", "refresh_retry_race", 409)
    if session.revoked_reason in _REUSE_REASONS:
        return DeviceAuthError("This refresh token was already used; sign in again.", "refresh_reused", 401)
    if session.revoked_reason in _KEEP_DATA_REASONS:
        return DeviceAuthError("This session has ended; sign in again.", "session_ended", 401)
    return DeviceAuthError("This session has been revoked.", "session_revoked", 401)


def refresh_session(refresh_token, *, device_id, device_secret) -> tuple[IssuedTokens, VaUsers]:
    """Rotate a refresh token presented with its device's id and secret.

    Refusals, none of which asks the app to wipe except ``session_revoked``:
    - 401 ``device_invalid``: device id/secret missing, wrong, or not the
      session's device. Revokes nothing, so a leaked token without the device
      secret can neither refresh nor end the session.
    - a retired refresh token (one of the last ``RETIRED_REFRESH_KEEP``)
      revokes the session: 409 ``refresh_retry_race`` when it is the token
      rotated away less than ``REFRESH_RETRY_GRACE`` ago (a lost response;
      the app holds no newer token, so revoking costs it nothing and cuts off
      anyone who does), else 401 ``refresh_reused``. Later refreshes on that
      session keep answering the same code.
    - 401 ``session_ended``: the account changed (password or factor reset,
      deactivated) or the project closed; revoked, but the app keeps data.
    - 401 ``session_revoked``: revoked for any other reason (device or admin
      revoke, grant withdrawn, signed out); the app wipes that store.
    - 401 ``session_expired``: past its sliding expiry or the absolute cap.
    - 401 ``refresh_invalid``: unknown token.
    Revocations are committed here. Caller commits a success."""
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise DeviceAuthError("refresh_token is required.", "invalid_request", 400)
    device = _device_by_secret(device_id, device_secret)
    digest = hash_token(refresh_token.strip())
    session = db.session.scalar(
        sa.select(AuthDeviceSession).where(AuthDeviceSession.refresh_hash == digest).with_for_update()
    )
    retired = False
    if session is None:
        session = db.session.scalar(
            sa.select(AuthDeviceSession)
            .where(sa.or_(
                AuthDeviceSession.previous_refresh_hash == digest,
                AuthDeviceSession.retired_refresh_hashes.contains([digest]),
            ))
            .with_for_update()
        )
        retired = session is not None
    if session is None:
        raise DeviceAuthError("Refresh token is not valid.", "refresh_invalid", 401)
    if session.device_id != device.device_id:
        raise DeviceAuthError("Device is not recognised.", "device_invalid", 401)
    if session.revoked_at is not None:
        raise _revoked_error(session)
    now = _now()
    if retired:
        lost_response = (
            digest == session.previous_refresh_hash
            and session.refreshed_at is not None
            and now - session.refreshed_at < REFRESH_RETRY_GRACE
        )
        _revoke(session, "refresh_retry_race" if lost_response else "refresh_reuse")
        db.session.commit()
        raise _revoked_error(session)
    if session.refresh_expires_at <= now or session.created_at + _session_max_age() <= now:
        raise DeviceAuthError("This session has expired; sign in again.", "session_expired", 401)
    allowed, reason = _session_still_allowed(session)
    if not allowed:
        _revoke(session, reason)
        db.session.commit()
        raise _revoked_error(session)

    session.previous_refresh_hash = session.refresh_hash
    session.retired_refresh_hashes = [session.refresh_hash, *(session.retired_refresh_hashes or [])][
        :RETIRED_REFRESH_KEEP
    ]
    session.refreshed_at = now
    issued = _issue(session)
    device.last_seen_at = session.last_seen_at
    db.session.flush()
    return issued, db.session.get(VaUsers, session.user_id)


def end_session(session: AuthDeviceSession) -> None:
    """Sign-out: revoke this session. Caller commits."""
    if session.revoked_at is None:
        _revoke(session, "signed_out")


def resolve_access_token(token: str) -> tuple[AuthDeviceSession, VaUsers] | None:
    """The live session and its user for a bearer access token, else None:
    unknown, expired or revoked token, revoked device, inactive account, or a
    bumped session version. Touches last_seen_at at most once a minute."""
    now = _now()
    row = db.session.execute(
        sa.select(AuthDeviceSession, AuthDevice)
        .join(AuthDevice, AuthDevice.device_id == AuthDeviceSession.device_id)
        .where(
            AuthDeviceSession.access_hash == hash_token(token),
            AuthDeviceSession.revoked_at.is_(None),
            AuthDeviceSession.access_expires_at > now,
            AuthDevice.revoked_at.is_(None),
        )
    ).first()
    if row is None:
        return None
    session, device = row
    user = db.session.get(VaUsers, session.user_id)
    if user is None or not user.is_active or (user.auth_session_version or 0) != session.user_session_version:
        return None
    if session.last_seen_at is None or now - session.last_seen_at > LAST_SEEN_INTERVAL:
        session.last_seen_at = now
        device.last_seen_at = now
        db.session.commit()
    return session, user


def _uuid_list(values, name: str) -> list[str]:
    """*values* (None, or a list of at most OUTSTANDING_MAX_IDS UUID strings)
    sorted and normalised, else 400."""
    if values is None:
        return []
    try:
        if (
            not isinstance(values, list)
            or len(values) > OUTSTANDING_MAX_IDS
            or not all(isinstance(value, str) for value in values)
        ):
            raise ValueError
        return sorted({str(uuid.UUID(value)) for value in values})
    except ValueError:
        raise DeviceAuthError(
            f"{name} must be a list of at most {OUTSTANDING_MAX_IDS} UUIDs.", "invalid_request", 400
        ) from None


def record_outstanding(session: AuthDeviceSession, count, unique_ids, client_draft_ids=None,
                       client_death_ids=None) -> None:
    """Store the device's report of unsent work for this interviewer.
    ``count`` a whole number >= 0 (unsent interviews); ``unique_ids`` a list
    of case ids (text, at most 64 characters each, at most
    OUTSTANDING_MAX_IDS); ``client_draft_ids`` the app's draft UUIDs and
    ``client_death_ids`` its offline registrations not yet uploaded (UUIDs,
    same bound). Caller commits."""
    if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 100_000:
        raise DeviceAuthError("count must be a whole number of at least 0.", "invalid_request", 400)
    if unique_ids is None:
        unique_ids = []
    if (
        not isinstance(unique_ids, list)
        or len(unique_ids) > OUTSTANDING_MAX_IDS
        or not all(isinstance(u, str) and 0 < len(u) <= 64 for u in unique_ids)
    ):
        raise DeviceAuthError(
            f"unique_ids must be a list of at most {OUTSTANDING_MAX_IDS} ids.", "invalid_request", 400
        )
    draft_ids = _uuid_list(client_draft_ids, "client_draft_ids")
    death_ids = _uuid_list(client_death_ids, "client_death_ids")
    session.outstanding_count = count
    session.outstanding_unique_ids = sorted(set(unique_ids))
    session.outstanding_client_draft_ids = draft_ids
    session.outstanding_client_death_ids = death_ids
    session.outstanding_reported_at = _now()


def serialize_tokens(issued: IssuedTokens, user: VaUsers) -> dict:
    return {
        "access_token": issued.access_token,
        "access_expires_at": issued.session.access_expires_at.isoformat(),
        "refresh_token": issued.refresh_token,
        "refresh_expires_at": issued.session.refresh_expires_at.isoformat(),
        "user": {"user_id": str(user.user_id), "name": user.name, "email": user.email},
    }


# ---------------------------------------------------------------------------
# Admin listing
# ---------------------------------------------------------------------------


def list_project_devices(project_id: str) -> list[dict]:
    """Every device enrolled in *project_id* with its live sessions: the
    interviewer's name and the outstanding-work report. Two queries."""
    devices = db.session.scalars(
        sa.select(AuthDevice)
        .where(AuthDevice.project_id == project_id)
        .order_by(AuthDevice.revoked_at.is_not(None), AuthDevice.enrolled_at.desc())
        .limit(500)
    ).all()
    sessions_by_device: dict = {}
    if devices:
        rows = db.session.execute(
            sa.select(AuthDeviceSession, VaUsers.name)
            .join(VaUsers, VaUsers.user_id == AuthDeviceSession.user_id)
            .where(
                AuthDeviceSession.device_id.in_([d.device_id for d in devices]),
                AuthDeviceSession.revoked_at.is_(None),
            )
            .order_by(AuthDeviceSession.created_at)
        ).all()
        for session, user_name in rows:
            sessions_by_device.setdefault(session.device_id, []).append({
                "session_id": str(session.session_id),
                "user_name": user_name,
                "last_seen_at": session.last_seen_at.isoformat() if session.last_seen_at else None,
                "outstanding_count": session.outstanding_count,
                "outstanding_unique_ids": session.outstanding_unique_ids or [],
                "outstanding_client_draft_ids": session.outstanding_client_draft_ids or [],
                "outstanding_client_death_ids": session.outstanding_client_death_ids or [],
            })

    def iso(value):
        return value.isoformat() if value else None

    return [
        {
            "device_id": str(d.device_id),
            "name": d.name,
            "platform": d.platform,
            "app_version": d.app_version,
            "enrolled_at": iso(d.enrolled_at),
            "last_seen_at": iso(d.last_seen_at),
            "revoked_at": iso(d.revoked_at),
            "sessions": sessions_by_device.get(d.device_id, []),
        }
        for d in devices
    ]
