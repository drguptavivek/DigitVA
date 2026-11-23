"""Device rows: validated fields, insert, home project, revoke and the admin
list. Part of ``device_auth_service``."""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from app import db
from app.models import (
    AuthDevice,
    AuthDeviceSession,
    AuthDeviceSigningKey,
    AuthStationConfig,
    AuthStationCustodian,
    VaBundleIngest,
    VaUsers,
)
from app.services.device.eligibility import eligible_device_projects
from app.services.device.tokens import DeviceAuthError, _new_secret, _now, hash_token, log
from app.services.security_event_service import record_security_event

_DEVICE_NAME_MAX = 64
_APP_VERSION_MAX = 32
#: "desktop" is the offline PHC station (docs/policy/offline-bundle-and-transfer.md).
_PLATFORMS = frozenset({"android", "ios", "desktop"})


def _clean_text(value, *, limit: int, name: str, required: bool) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise DeviceAuthError(f"{name} is required.", "invalid_request", 400)
        return None
    if not isinstance(value, str) or len(value.strip()) > limit:
        raise DeviceAuthError(f"{name} must be text of at most {limit} characters.", "invalid_request", 400)
    return value.strip()


def record_app_version(session, app_version) -> None:
    """The app version a device reports at sign-in or refresh (it changes with
    every app update; enrolment alone went stale). Absent: left as it is."""
    if app_version is None:
        return
    version = _clean_text(app_version, limit=_APP_VERSION_MAX, name="app_version", required=False)
    device = db.session.get(AuthDevice, session.device_id)
    if device is not None and version and device.app_version != version:
        device.app_version = version


def _device_fields(device_name, platform, app_version) -> tuple[str, str | None]:
    """Validated (name, app version) for a new device; raises 400
    ``invalid_request``."""
    name = _clean_text(device_name, limit=_DEVICE_NAME_MAX, name="device_name", required=True)
    version = _clean_text(app_version, limit=_APP_VERSION_MAX, name="app_version", required=False)
    if not isinstance(platform, str) or platform not in _PLATFORMS:
        raise DeviceAuthError("platform must be android, ios or desktop.", "invalid_request", 400)
    return name, version


def parse_client_device_uuid(value) -> uuid.UUID | None:
    """The optional Collect Plus install UUID an enrolment request carries:
    None when absent, else the parsed UUID or 400 ``invalid_request``. Routes
    call it before a code or QR token is consumed."""
    if value is None:
        return None
    try:
        if not isinstance(value, str):
            raise ValueError
        return uuid.UUID(value)
    except ValueError:
        raise DeviceAuthError("client_device_uuid must be a UUID.", "invalid_request", 400) from None


def device_for_client_uuid(session: AuthDeviceSession, client_device_uuid) -> AuthDevice | None:
    """The session's own device when it was enrolled with *client_device_uuid*,
    else None. Never another device's row: the UUID is a claim, the session
    is the proof (offline-api-contract.md section 17)."""
    claimed = parse_client_device_uuid(client_device_uuid)
    device = db.session.get(AuthDevice, session.device_id)
    if claimed is None or device is None or device.client_device_uuid != claimed:
        return None
    return device


def _add_device(
    project_id: str, name: str, platform: str, version: str | None, via, client_device_uuid=None
) -> tuple[AuthDevice, str]:
    """Insert a device, optionally through code row *via*; returns (device,
    plaintext secret). Caller commits."""
    secret = _new_secret()
    device = AuthDevice(
        # The enrolment project: the device's admin home (listed and
        # revoked there). It does not limit which
        # projects the device serves; every request names its project.
        project_id=project_id,
        name=name,
        platform=platform,
        app_version=version,
        secret_hash=hash_token(secret),
        enrolled_via=via,
        client_device_uuid=client_device_uuid,
    )
    db.session.add(device)
    db.session.flush()
    record_security_event(
        user_id=None, event_type="device_enrolled",
        detail={"device_id": str(device.device_id), "project_id": device.project_id},
    )
    log.info("device enrolled | device=%s | project=%s", device.device_id, device.project_id)
    return device, secret


def _station_state(device: AuthDevice) -> bool:
    """True when *device* holds offline-station trust or work bound to its
    project: a signing key, a station config or custodian, an ingested or
    held bundle, or outstanding work reported by a session."""
    did = device.device_id
    if device.signing_public_key is not None or device.signing_key_id is not None:
        return True
    exists = lambda *where: db.session.scalar(sa.select(sa.exists().where(*where)))  # noqa: E731
    return bool(
        exists(AuthDeviceSigningKey.device_id == did)
        or exists(AuthStationConfig.device_id == did)
        or exists(AuthStationCustodian.device_id == did)
        or exists(VaBundleIngest.device_id == did)
        or exists(AuthDeviceSession.device_id == did, AuthDeviceSession.outstanding_count > 0)
    )


def set_device_project(device_id: uuid.UUID, user: VaUsers, project_id) -> AuthDevice:
    """``POST /auth/devices/current/project``: make *project_id* the home of
    the caller's device (*device_id* from the bearer session). Refused 403
    ``project_not_eligible`` unless it is one of the session user's
    eligible projects, and 409 ``device_project_locked`` when the device holds
    station state (``_station_state``) and the project would change: its
    project binds offline-station trust. Audited as ``device_project_changed``.
    Caller commits."""
    if not isinstance(project_id, str) or not project_id.strip():
        raise DeviceAuthError("project_id is required.", "invalid_request", 400, fields=["project_id"])
    project_id = project_id.strip()
    if project_id not in {p["project_id"] for p in eligible_device_projects(user)}:
        raise DeviceAuthError("You cannot use this project on a phone.", "project_not_eligible", 403)
    device = db.session.scalar(
        sa.select(AuthDevice).where(AuthDevice.device_id == device_id).with_for_update()
    )
    if device is None:
        raise DeviceAuthError("Device is not recognised.", "device_invalid", 401)
    if device.revoked_at is not None:
        raise DeviceAuthError("This device has been revoked.", "device_revoked", 403)
    previous = device.project_id
    if previous != project_id:
        if _station_state(device):
            raise DeviceAuthError("This device is a registered station; its project cannot change.",
                                  "device_project_locked", 409)
        device.project_id = project_id
        record_security_event(
            user_id=user.user_id, event_type="device_project_changed",
            detail={"device_id": str(device.device_id), "from": previous, "project_id": project_id},
        )
    return device


def revoke_device(device: AuthDevice, *, actor: VaUsers, compromised: bool = False, reason: str | None = None) -> int:
    """Revoke a device and every session on it. Returns the number of sessions
    ended. Idempotent. *compromised* (lost or stolen) refuses every bundle the
    device signed, not only those created after the revoke; a later revoke
    may raise it on an already revoked device, never clear it. *reason* is a
    fixed code put in the audit detail. Caller commits."""
    now = _now()
    if device.revoked_at is None:
        device.revoked_at = now
        device.revoked_by = actor.user_id
    if compromised:
        device.revoked_compromised = True
    ended = db.session.execute(
        sa.update(AuthDeviceSession)
        .where(AuthDeviceSession.device_id == device.device_id, AuthDeviceSession.revoked_at.is_(None))
        .values(revoked_at=now, revoked_reason="device_revoked")
    ).rowcount
    record_security_event(
        user_id=None, actor_user_id=actor.user_id, event_type="device_revoked",
        detail={"device_id": str(device.device_id), "sessions_ended": ended,
                "compromised": bool(device.revoked_compromised), **({"reason": reason} if reason else {})},
    )
    return ended


def _get_device(device_id) -> AuthDevice | None:
    try:
        return db.session.get(AuthDevice, uuid.UUID(str(device_id)))
    except (ValueError, TypeError, AttributeError):
        return None


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
            "revoked_compromised": d.revoked_compromised,
            "signing_key_id": d.signing_key_id,
            "sessions": sessions_by_device.get(d.device_id, []),
        }
        for d in devices
    ]
