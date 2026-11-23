"""Device sessions: sign-in, the account device cap, refresh rotation,
sign-out, profile deletion and access-token resolution. Part of
``device_auth_service``; names tests patch there are read through
``facade()``."""

from __future__ import annotations

import hmac
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from werkzeug.security import check_password_hash, generate_password_hash

from app import db
from app.models import AuthDevice, AuthDeviceSession, AuthSecurityEvent, VaUsers
from app.services.device import facade
from app.services.device.eligibility import _no_access_error
from app.services.device.registry import _get_device
from app.services.device.tokens import (
    ACCESS_TTL,
    DeviceAuthError,
    IssuedTokens,
    _new_secret,
    _now,
    _refresh_ttl,
    _session_max_age,
    hash_token,
    log,
)
from app.services.security_event_service import record_security_event
from app.services.user_account_service import find_sign_in_user, sign_in_identifier

#: Rotated-away refresh hashes kept per session for reuse detection.
RETIRED_REFRESH_KEEP = 5
#: A retry with the token rotated away less than this ago is treated as a lost
#: response (409 ``refresh_retry_race``), not as theft (401 ``refresh_reused``).
REFRESH_RETRY_GRACE = timedelta(seconds=60)
#: Revocation reasons that mean "the refresh token was replayed". They answer
#: refresh_reused / refresh_retry_race so the app keeps the interviewer's data;
#: every other reason answers session_revoked, on which the app wipes.
_REUSE_REASONS = frozenset({"refresh_reuse", "refresh_retry_race"})
#: Revocations that end the session but must not destroy unsent interviews:
#: an account change, device decommission or same-phone re-login. They answer
#: session_ended (sign in again, keep data). A revoked device, a worker left
#: with no active project, or a sign-out answers session_revoked (wipe).
_KEEP_DATA_REASONS = frozenset({"account_changed", "device_decommissioned", "signed_in_again"})
MAX_ACTIVE_USER_DEVICES = 3
DEVICE_LIMIT_MESSAGE = (
    "This account is already active on 3 phones. Open Profile to decommission one, "
    "or use another signed-in phone."
)


#: Throttle for last_seen_at writes, so a bearer request is not always a write.
LAST_SEEN_INTERVAL = timedelta(seconds=60)
_DUMMY_PASSWORD_HASH = generate_password_hash("digitva-device-timing-equaliser")


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
    # The enrolment project does not bound the device's life: a device serves
    # every project its worker is an interviewer in, so only a revoke ends it.
    if device.revoked_at is not None:
        # Before the credentials are checked: audited with no user.
        _sign_in_failed(device, None, "device_revoked")
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


def _refuse(device: AuthDevice, user: VaUsers, message: str, code: str, status_code: int) -> DeviceAuthError:
    """Audit a post-password refusal (reason = the contract code) and return
    the error to raise."""
    _sign_in_failed(device, user, code)
    return DeviceAuthError(message, code, status_code)


def _live_session(user: VaUsers):
    """The condition on ``AuthDeviceSession`` for a session of *user* that can
    still refresh. The device's own revocation is the caller's condition."""
    return sa.and_(
        AuthDeviceSession.user_id == user.user_id,
        AuthDeviceSession.revoked_at.is_(None),
        AuthDeviceSession.refresh_expires_at > _now(),
        # A password or factor reset ended it: it can never refresh again
        # (``_session_still_allowed``), so it holds no slot.
        AuthDeviceSession.user_session_version == (user.auth_session_version or 0),
    )


def check_device_slot(user: VaUsers, device_id=None, replace_device_id=None) -> None:
    """Lock *user* and refuse a new live device pair at the account cap.

    A device already holding a live session for this user is a re-login and
    does not consume another slot. Only native device sessions are counted;
    browser sessions have no ``AuthDeviceSession`` row, and a session a
    password or factor reset ended (older ``user_session_version``) is not.

    Every caller has verified the user's credential in this request, so the
    409 ``device_limit`` carries ``devices``: that account's live phones
    ``[{device_id, label, last_seen_at, unsent_count}]``. At the cap,
    *replace_device_id* (one of those phones; docs/policy/mobile-sign-in.md,
    replacing a phone at sign-in) is decommissioned as Profile does, actor the
    user, in the caller's transaction; any other value is 400
    ``invalid_request``. Below the cap it is ignored.
    """
    db.session.execute(
        sa.select(VaUsers.user_id).where(VaUsers.user_id == user.user_id).with_for_update()
    )
    if device_id is not None:
        try:
            device_id = uuid.UUID(str(device_id))
        except (ValueError, TypeError, AttributeError):
            device_id = None
    # One row per live session; a pair normally has one (re-login ends the older).
    rows = db.session.execute(
        sa.select(AuthDevice.device_id, AuthDevice.name, AuthDeviceSession.last_seen_at,
                  AuthDeviceSession.outstanding_count)
        .join(AuthDeviceSession, AuthDeviceSession.device_id == AuthDevice.device_id)
        .where(_live_session(user), AuthDevice.revoked_at.is_(None))
    ).all()
    live: dict[uuid.UUID, dict] = {}
    for row in rows:
        entry = live.setdefault(row.device_id, {"name": row.name, "last_seen_at": None, "unsent_count": None})
        if row.last_seen_at and (entry["last_seen_at"] is None or row.last_seen_at > entry["last_seen_at"]):
            entry["last_seen_at"] = row.last_seen_at
        if row.outstanding_count is not None:
            entry["unsent_count"] = max(entry["unsent_count"] or 0, row.outstanding_count)
    if device_id in live or len(live) < facade().MAX_ACTIVE_USER_DEVICES:
        return
    if replace_device_id is not None:
        try:
            replaced = uuid.UUID(str(replace_device_id))
        except (ValueError, TypeError, AttributeError):
            replaced = None
        # Not one of this account's live phones: another user's, revoked, ended or this one.
        if replaced is None or replaced not in live or replaced == device_id:
            raise DeviceAuthError("replace_device_id is not one of your signed-in phones.",
                                  "invalid_request", 400, fields=["replace_device_id"])
        # Only when that frees the slot: open_session commits a 409's audit.
        if len(live) - 1 < facade().MAX_ACTIVE_USER_DEVICES:
            decommission_account_device(user.user_id, replaced, user, reason="replaced_at_sign_in")
            return
    devices = sorted(live.items(), key=lambda item: item[1]["last_seen_at"] or datetime.min.replace(tzinfo=UTC),
                     reverse=True)
    raise DeviceAuthError(DEVICE_LIMIT_MESSAGE, "device_limit", 409, extra={"devices": [
        {
            "device_id": str(did),
            "label": entry["name"],
            "last_seen_at": entry["last_seen_at"].isoformat() if entry["last_seen_at"] else None,
            "unsent_count": entry["unsent_count"],
        }
        for did, entry in devices
    ]})


def _end_existing_pair_sessions(device: AuthDevice, user: VaUsers) -> None:
    """End older sessions for this user/device, retaining encrypted work."""
    sessions = db.session.scalars(
        sa.select(AuthDeviceSession)
        .where(
            AuthDeviceSession.device_id == device.device_id,
            AuthDeviceSession.user_id == user.user_id,
            AuthDeviceSession.revoked_at.is_(None),
        )
        .with_for_update()
    ).all()
    for session in sessions:
        _revoke(session, "signed_in_again")


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


def _sign_in_user(identifier: str) -> VaUsers | None:
    """The account an email, mobile number or (public demo) username names,
    read exactly as the web login reads it (``sign_in_identifier``,
    docs/policy/mobile-sign-in.md section 2): a number matches only a unique
    sign-in number, so a shared, unknown or malformed one matches no one."""
    return find_sign_in_user(*sign_in_identifier(identifier))


def _check_credentials(identifier: str, password) -> tuple[VaUsers | None, bool]:
    """The account *identifier* names and whether *password* signs it in:
    ``(user or None, valid)``. An unknown identifier spends a hash check
    anyway so it takes as long. A mobile-only account that never redeemed a
    code has no password of its own: refused exactly like a wrong password,
    as on the web."""
    password = password if isinstance(password, str) else ""
    user = _sign_in_user(identifier) if identifier else None
    if user is None:
        check_password_hash(_DUMMY_PASSWORD_HASH, password)
        return None, False
    unredeemed = user.is_mobile_only and not user.sign_in_verified
    return user, user.check_password(password) and user.is_active and not unredeemed


def _open_authorized_session(
    device: AuthDevice, user: VaUsers, replace_device_id=None
) -> tuple[IssuedTokens, VaUsers]:
    """Issue the normal device session after authentication and access checks;
    *replace_device_id* as ``check_device_slot``."""
    if not facade().has_device_access(user):
        error = _no_access_error(user)
        _sign_in_failed(device, user, error.code)
        raise error
    check_device_slot(user, device.device_id, replace_device_id)
    _end_existing_pair_sessions(device, user)
    return facade()._create_session(device, user)


def _create_session(device: AuthDevice, user: VaUsers) -> tuple[IssuedTokens, VaUsers]:
    """Issue tokens after the caller checks credentials, access and slots.

    Returns the issued session and user. Caller commits, so a newly enrolled
    device and its session remain one transaction if issuance fails.
    """
    session = AuthDeviceSession(
        device_id=device.device_id,
        user_id=user.user_id,
        user_session_version=user.auth_session_version or 0,
    )
    issued = _issue(session)
    db.session.add(session)
    device.last_seen_at = session.last_seen_at
    db.session.flush()
    user.mark_signed_in()
    record_security_event(
        user_id=user.user_id, event_type="device_session_opened",
        detail={"device_id": str(device.device_id)},
    )
    log.info(
        "device session opened | device=%s | session=%s | user=%s",
        device.device_id, session.session_id, user.user_id,
    )
    return issued, user


def live_session_clauses(now: datetime) -> tuple:
    """SQL clauses for a live phone sign-in: a device session not revoked,
    its refresh token unexpired, on a device not revoked (the caller joins
    ``AuthDevice`` to ``AuthDeviceSession``). The one rule behind the account
    devices list, the roster's ``phone_count`` and the sign-in-code refusal
    for someone already signed in (docs/policy/mobile-sign-in.md section 3)."""
    return (
        AuthDeviceSession.revoked_at.is_(None),
        AuthDeviceSession.refresh_expires_at > now,
        AuthDevice.revoked_at.is_(None),
    )


def list_account_devices(user_id, current_device_id=None) -> list[dict]:
    """List this account's live native device pairs, newest activity first."""
    rows = db.session.execute(
        sa.select(AuthDevice, AuthDeviceSession.last_seen_at)
        .join(AuthDeviceSession, AuthDeviceSession.device_id == AuthDevice.device_id)
        .where(AuthDeviceSession.user_id == user_id, *live_session_clauses(_now()))
    ).all()
    latest: dict[uuid.UUID, tuple[AuthDevice, datetime | None]] = {}
    for device, last_seen in rows:
        previous = latest.get(device.device_id)
        if previous is None or (last_seen or datetime.min.replace(tzinfo=UTC)) > (
            previous[1] or datetime.min.replace(tzinfo=UTC)
        ):
            latest[device.device_id] = (device, last_seen)
    devices = sorted(
        latest.values(),
        key=lambda pair: (pair[1] or pair[0].enrolled_at, pair[0].enrolled_at),
        reverse=True,
    )
    current = str(current_device_id) if current_device_id is not None else None
    return [
        {
            "device_id": str(device.device_id),
            "name": device.name,
            "platform": device.platform,
            "app_version": device.app_version,
            "enrolled_at": device.enrolled_at.isoformat(),
            "last_seen_at": last_seen.isoformat() if last_seen else None,
            "current": str(device.device_id) == current,
        }
        for device, last_seen in devices
    ]


def decommission_account_device(user_id, device_id, actor: VaUsers, reason: str | None = None) -> int:
    """End only *user_id*'s sessions on *device_id*, retaining all data.
    *reason* is a fixed code put in the audit detail (``replaced_at_sign_in``)."""
    try:
        parsed_device_id = uuid.UUID(str(device_id))
    except (ValueError, TypeError, AttributeError):
        return 0
    db.session.execute(
        sa.select(VaUsers.user_id).where(VaUsers.user_id == user_id).with_for_update()
    )
    sessions = db.session.scalars(
        sa.select(AuthDeviceSession)
        .where(
            AuthDeviceSession.user_id == user_id,
            AuthDeviceSession.device_id == parsed_device_id,
            AuthDeviceSession.revoked_at.is_(None),
        )
        .with_for_update()
    ).all()
    for session in sessions:
        _revoke(session, "device_decommissioned")
    record_security_event(
        user_id=user_id,
        actor_user_id=actor.user_id,
        event_type="device_decommissioned",
        detail={"device_id": str(parsed_device_id), "sessions_ended": len(sessions),
                **({"reason": reason} if reason else {})},
    )
    return len(sessions)


def record_profile_deletion(*, device_id, device_secret, user_id, unsent_count, loss_confirmed) -> bool:
    """Audit the phone deleting *user_id*'s profile and end their sessions on
    the device (docs/policy/mobile-sign-in.md section 10).

    Device-authenticated (a revoked device may still report). *unsent_count*
    is an int, or None when the phone could not count (locked profile);
    None needs *loss_confirmed* True. Returns False when a retry found the
    deletion already recorded and nothing live to end. Raises
    DeviceAuthError. Caller commits."""
    device = _device_by_secret(device_id, device_secret)
    try:
        user_uuid = uuid.UUID(str(user_id))
    except (ValueError, TypeError, AttributeError):
        raise DeviceAuthError("user_id is not valid.", "invalid_request", 400, fields=["user_id"])
    if unsent_count is not None and (
        isinstance(unsent_count, bool) or not isinstance(unsent_count, int) or not 0 <= unsent_count <= 100_000
    ):
        raise DeviceAuthError("unsent_count is not valid.", "invalid_request", 400, fields=["unsent_count"])
    if not isinstance(loss_confirmed, bool):
        raise DeviceAuthError("loss_confirmed must be true or false.", "invalid_request", 400, fields=["loss_confirmed"])
    if unsent_count:
        raise DeviceAuthError("Send this profile's work before deleting it.", "unsent_work", 409)
    if unsent_count is None and not loss_confirmed:
        raise DeviceAuthError("Confirm that unsent work will be lost.", "confirmation_required", 400)

    latest_session_at = db.session.scalar(
        sa.select(sa.func.max(AuthDeviceSession.created_at)).where(
            AuthDeviceSession.device_id == device.device_id,
            AuthDeviceSession.user_id == user_uuid,
        )
    )
    if latest_session_at is None:  # never signed in here: not this phone's profile
        raise DeviceAuthError("This profile is not on this device.", "profile_not_on_device", 403)

    sessions = db.session.scalars(
        sa.select(AuthDeviceSession)
        .where(
            AuthDeviceSession.device_id == device.device_id,
            AuthDeviceSession.user_id == user_uuid,
            AuthDeviceSession.revoked_at.is_(None),
        )
        .with_for_update()
    ).all()
    if not sessions:
        already = db.session.scalar(
            sa.select(AuthSecurityEvent.id).where(
                AuthSecurityEvent.user_id == user_uuid,
                AuthSecurityEvent.event_type == "device_profile_deleted",
                AuthSecurityEvent.occurred_at >= latest_session_at,
                AuthSecurityEvent.detail["device_id"].astext == str(device.device_id),
            ).limit(1)
        )
        if already is not None:
            return False
    for session in sessions:
        _revoke(session, "profile_deleted")
    record_security_event(
        user_id=user_uuid, event_type="device_profile_deleted",
        detail={
            "device_id": str(device.device_id),
            "unsent_count_known": unsent_count is not None,
            "unsent_count": unsent_count,
            "loss_confirmed": loss_confirmed,
            "sessions_ended": len(sessions),
        },
    )
    log.info("device profile deleted | device=%s | user=%s", device.device_id, user_uuid)
    return True


def open_session(*, device_id, device_secret, email, password, replace_device_id=None) -> tuple[IssuedTokens, VaUsers]:
    """Sign an interviewer in on an enrolled device (the web login's checks,
    with the device credential in place of the CAPTCHA). *email* is the
    contract's field name; it holds an email, a mobile number or a
    public-demo username. *replace_device_id*: the phone to sign out at the
    device cap (``check_device_slot``). Raises
    DeviceAuthError; a refused attempt is audited and committed. Caller
    commits a success."""
    device = _authenticate_device(device_id, device_secret)
    identifier = email.strip() if isinstance(email, str) else ""
    user, valid = _check_credentials(identifier, password)
    if not valid:
        _sign_in_failed(device, user if user and user.is_active else None, "invalid_credentials")
        raise DeviceAuthError("Invalid email or password.", "invalid_credentials", 401)
    if not user.sign_in_verified:
        raise _refuse(device, user, "Verify your email address before signing in.", "email_unverified", 403)
    # Pending terms do not refuse sign-in (onboarding policy 5.4): the
    # tokens carry ``terms_required`` and the device API answers 403
    # ``terms_required`` everywhere but sign-out and POST /terms until then.
    if not user.is_admin() and facade().should_block_non_admin_after_cutoff():
        raise _refuse(device, user, "Site is under maintenance.", "maintenance", 403)

    # ``no_interviewer_grant`` (or ``project_intake_off``) when there is no access.
    try:
        return _open_authorized_session(device, user, replace_device_id)
    except DeviceAuthError as exc:
        if exc.code == "device_limit":
            _sign_in_failed(device, user, "device_limit")
        raise


def _revoke(session: AuthDeviceSession, reason: str) -> None:
    session.revoked_at = _now()
    session.revoked_reason = reason
    record_security_event(
        user_id=session.user_id, event_type="device_session_revoked",
        detail={"device_id": str(session.device_id), "reason": reason},
    )
    log.warning("device session revoked | session=%s | reason=%s", session.session_id, reason)


def _session_still_allowed(session: AuthDeviceSession) -> tuple[bool, str]:
    """Whether a session may continue: device not revoked, account unchanged
    and at least one active project to collect or code in."""
    device = db.session.get(AuthDevice, session.device_id)
    if device is None or device.revoked_at is not None:
        return False, "device_revoked"
    user = db.session.get(VaUsers, session.user_id)
    if user is None or not user.is_active or (user.auth_session_version or 0) != session.user_session_version:
        return False, "account_changed"
    if not facade().has_device_access(user):
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
