"""Enrolment codes and their QR, code enrolment and password enrolment.
Part of ``device_auth_service``; names tests patch there are read through
``facade()``."""

from __future__ import annotations

import json
from datetime import timedelta
from urllib.parse import urlsplit

import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import AuthDevice, AuthDeviceEnrolmentCode, VaUsers
from app.services.authz import resolve_grants
from app.services.device import facade
from app.services.device.eligibility import (
    _default_home_project,
    _eligible_projects,
    _no_access_error,
    _project_active,
)
from app.services.device.registry import _add_device, _device_fields, parse_client_device_uuid
from app.services.device.sessions import _check_credentials, check_device_slot
from app.services.device.tokens import (
    DeviceAuthError,
    IssuedTokens,
    _new_secret,
    _now,
    hash_token,
    log,
)
from app.services.security_event_service import record_security_event

#: Hosts an http:// DEVICE_PUBLIC_URL may name outside debug/testing.
_PLAIN_HTTP_HOSTS = frozenset({"localhost", "127.0.0.1", "10.0.2.2"})
ENROLMENT_DEFAULT_MINUTES = 60
ENROLMENT_MAX_MINUTES = 7 * 24 * 60
ENROLMENT_MAX_USES = 200


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


def _bounded_int(value, *, default: int, low: int, high: int, name: str) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise DeviceAuthError(f"{name} must be a whole number from {low} to {high}.", "invalid_request", 400)
    return value


def create_enrolment_code(project_id: str, *, actor: VaUsers, expires_in_minutes=None, max_uses=None,
                          subject_user_id=None) -> tuple[AuthDeviceEnrolmentCode, str]:
    """Issue an enrolment code for *project_id*. Returns (row, plaintext code);
    the code is shown once and only its hash is stored. *subject_user_id*,
    when the code is issued for one person (enrolment email, Users page),
    is the audit event's user. Refused (503 ``device_url_insecure``) when
    DEVICE_PUBLIC_URL, which the QR carries, is plain http outside
    development. Caller commits."""
    problem = device_public_url_problem(
        current_app.config.get("DEVICE_PUBLIC_URL"), allow_insecure=facade()._insecure_device_url_allowed()
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
        user_id=subject_user_id, actor_user_id=actor.user_id, event_type="device_enrolment_code_created",
        detail={"project_id": project_id, "code_id": str(row.id), "max_uses": uses,
                "expires_in_minutes": minutes},
    )
    return row, code


def enrolment_qr_payload(row: AuthDeviceEnrolmentCode, code: str) -> str:
    """The JSON the enrolment QR carries, as the app's parseEnrolmentQr reads
    it. One builder for the Devices page and the enrolment email, so both
    show the same QR."""
    return json.dumps(
        {"v": 1, "server": current_app.config["DEVICE_PUBLIC_URL"], "enroll": code, "project": row.project_id},
        separators=(",", ":"),
    )


def enrol_device(
    code, *, device_name, platform, app_version, client_device_uuid=None
) -> tuple[AuthDevice, str]:
    """Consume one use of an enrolment code and register a device. Returns
    (device, plaintext device secret). An unknown, expired, revoked or used-up
    code is one answer, 404 ``enrolment_invalid``. Caller commits."""
    name, version = _device_fields(device_name, platform, app_version)
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
    return _add_device(consumed.project_id, name, platform, version, consumed.id, client_device_uuid)


def enrol_with_password(
    *, identifier, password, device_name, platform, app_version, client_device_uuid=None,
    replace_device_id=None,
) -> tuple[AuthDevice, str, IssuedTokens, VaUsers]:
    """Authenticate, enrol and open one native session; caller commits.
    *replace_device_id*: the phone to sign out at the device cap
    (``check_device_slot``), in this transaction.

    The optional install UUID is parsed before writes. The home is the first
    accessible collection project, otherwise the first native coding/review
    project (``_default_home_project``). Raises DeviceAuthError before
    creating rows on credential, eligibility or device-cap refusal. Session issuance never commits, so a
    later failure rolls the new device back with it. Invalid credentials
    commit only their audit event before any device/session is created.
    """
    from app.services.web_intake_service import interviewer_context, register_death_context

    name, version = _device_fields(device_name, platform, app_version)
    client_uuid = parse_client_device_uuid(client_device_uuid)
    identifier = identifier.strip() if isinstance(identifier, str) else ""
    user, valid = _check_credentials(identifier, password)
    if not valid or user.is_public_demo:
        record_security_event(
            user_id=user.user_id if user and user.is_active else None,
            event_type="device_password_enrol_failed", detail={"reason": "invalid_credentials"},
        )
        db.session.commit()
        raise DeviceAuthError("Invalid email or password.", "invalid_credentials", 401)
    if not user.sign_in_verified:
        raise DeviceAuthError("Verify your email address before signing in.", "email_unverified", 403)
    if not user.is_admin() and facade().should_block_non_admin_after_cutoff():
        raise DeviceAuthError("Site is under maintenance.", "maintenance", 403)

    resolved = resolve_grants(user)
    context = interviewer_context(user, _grants=resolved)
    register_context = register_death_context(user, context, _grants=resolved)
    if not facade().has_device_access(user, context, register_context, _grants=resolved):
        raise _no_access_error(user, resolved)
    project_id = _default_home_project(
        context, register_context, resolved, _eligible_projects(context, register_context, resolved))
    # Hold the account lock through creation and issuance; a phone is signed
    # out only when the user named it (replace_device_id).
    check_device_slot(user, replace_device_id=replace_device_id)
    device, secret = _add_device(project_id, name, platform, version, None, client_uuid)
    issued, user = facade()._create_session(device, user)
    return device, secret, issued, user
