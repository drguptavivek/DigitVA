"""Public-demo device enrolment without a code (docs/policy/public-demo.md
section 10). Part of ``device_auth_service``."""

from __future__ import annotations

from datetime import timedelta

import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import AuthDevice, AuthDeviceEnrolmentCode, AuthDeviceSession, VaUsers
from app.services.device.eligibility import _project_active
from app.services.device.registry import _add_device, _device_fields
from app.services.device.sessions import _check_credentials, _live_session, check_device_slot
from app.services.device.tokens import DeviceAuthError, _now, hash_token
from app.services.security_event_service import record_security_event


def _demo_code_hash(user: VaUsers) -> str:
    return hash_token(f"public_demo:{user.user_id}")


def enrol_demo_device(
    *, username, password, device_name, platform, app_version, client_device_uuid=None,
    replace_device_id=None,
) -> tuple[AuthDevice, str]:
    """Enrol a device on the public demo project for a public-demo account,
    without an enrolment code (docs/policy/public-demo.md section 10). The
    username and password are checked exactly as device sign-in checks them
    (same resolver, same uniform ``invalid_credentials`` answer), and an
    account that is not a public-demo account gets that same answer. The
    caller has checked ``PUBLIC_DEMO_ENABLED`` and the main-database guard.

    Devices carry no user column, so each demo account owns one hidden,
    already-revoked ``auth_device_enrolment_codes`` row (``created_by`` the
    account, a hash no one can present) that its devices name in
    ``enrolled_via``. Both the three active-device limit (409
    ``device_limit``) and ``PUBLIC_DEMO_DEVICES_PER_ACCOUNT`` (429
    ``demo_limit``, unopened devices included) are checked before a device
    row is created; no older device is silently evicted. At the first cap the
    409 lists the account's phones and *replace_device_id* signs one out
    (``check_device_slot``); that phone has no live session afterwards, so it
    no longer counts toward ``demo_limit``, and a ``demo_limit`` refusal rolls
    the sign-out back with the request.
    Raises DeviceAuthError; a refused credential is audited and committed.
    Caller commits a success."""
    from app.services import public_demo_service as demo

    name, version = _device_fields(device_name, platform, app_version)
    identifier = username.strip() if isinstance(username, str) else ""
    user, valid = _check_credentials(identifier, password)
    if not valid or not user.is_public_demo:
        record_security_event(
            user_id=user.user_id if user and user.is_active else None,
            event_type="demo_device_enrol_failed", detail={"reason": "invalid_credentials"},
        )
        db.session.commit()
        raise DeviceAuthError("Invalid username or password.", "invalid_credentials", 401)
    project_id = demo.demo_project_id()
    if not _project_active(project_id):
        raise DeviceAuthError(demo.WRONG_DATABASE_MESSAGE, "project_missing", 503)
    demo._lock_account(user)
    check_device_slot(user, replace_device_id=replace_device_id)
    digest = _demo_code_hash(user)
    code_id = db.session.scalar(
        sa.select(AuthDeviceEnrolmentCode.id).where(AuthDeviceEnrolmentCode.code_hash == digest)
    )
    if code_id is None:
        now = _now()
        row = AuthDeviceEnrolmentCode(
            project_id=project_id, code_hash=digest, expires_at=now, max_uses=1, use_count=1,
            created_by=user.user_id, revoked_at=now,
        )
        db.session.add(row)
        db.session.flush()
        code_id = row.id
    _check_demo_device_cap(user, code_id)
    return _add_device(project_id, name, platform, version, code_id, client_device_uuid)


def _check_demo_device_cap(user: VaUsers, code_id) -> None:
    """Refuse a new demo device (429 ``demo_limit``) once the account holds
    ``PUBLIC_DEMO_DEVICES_PER_ACCOUNT`` unrevoked devices that count: those it
    has a live session on, plus those its demo code *code_id* enrolled in the
    last 24 hours that never had a session. ``check_device_slot`` counts only
    signed-in devices, so without the second part an enrolment that never signs
    in is unbounded; the 24 hour window keeps reinstalls from locking the
    account out for good. The caller holds the account lock."""
    now_live = sa.select(AuthDeviceSession.device_id).where(_live_session(user))
    any_session = sa.select(AuthDeviceSession.device_id)
    count = db.session.scalar(
        sa.select(sa.func.count()).select_from(AuthDevice).where(
            AuthDevice.revoked_at.is_(None),
            sa.or_(
                AuthDevice.device_id.in_(now_live),
                sa.and_(
                    AuthDevice.enrolled_via == code_id,
                    AuthDevice.enrolled_at > _now() - timedelta(hours=24),
                    AuthDevice.device_id.not_in(any_session),
                ),
            ),
        )
    ) or 0
    if count >= int(current_app.config["PUBLIC_DEMO_DEVICES_PER_ACCOUNT"]):
        raise DeviceAuthError("This demo account has reached its device limit.", "demo_limit", 429)
