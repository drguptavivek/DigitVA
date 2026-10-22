"""Device Ed25519 bundle-signing keys: enrolment, lookup and verification.

Baseline: docs/policy/offline-bundle-and-transfer.md section 3.2 (bead
digitva-gb8w.5); contract docs/policy/offline-api-contract.md 3.1 and 3.8.
A station generates its own Ed25519 key pair and sends the raw 32-byte
public key as base64url. It is stored raw (``auth_devices.signing_public_key``
holds the current key, ``auth_device_signing_keys`` every key the device has
held). ``signing_key_id`` is the first 16 lowercase hex characters of the
key's SHA-256, the same as ``compute_signing_key_id`` in
desktop/crates/digitva-bundle/src/lib.rs.

Three ways a key arrives: ``POST /auth/enroll`` (optional
``signing_public_key``), ``POST /auth/devices/current/signing-key`` (device
bearer, set once) and the admin paste of a never-online station's enrolment
file (``register_pasted_station``). Bundle ingest (digitva-gb8w.2) calls
``bundle_signing_key`` and ``verify_bundle_signature``.

Nothing here logs a key; audit rows carry the 16-hex key id only.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import AuthDevice, AuthDeviceSigningKey, VaUsers
from app.services.device_auth_service import (
    _APP_VERSION_MAX,
    _DEVICE_NAME_MAX,
    DeviceAuthError,
    _clean_text,
    _project_active,
)
from app.services.security_event_service import record_security_event

log = logging.getLogger(__name__)

#: Domain prefix of a bundle manifest signature (Rust ``BUNDLE_SIG_DOMAIN``).
BUNDLE_SIG_DOMAIN = b"digitva-bundle-v1\x00"
#: Platform recorded for a station registered from its enrolment file.
STATION_PLATFORM = "desktop"
#: Stored as the secret hash of a pasted station. ``hash_token`` yields
#: lowercase hex, so no presented secret can ever match it: no bearer
#: session can open on that device.
UNUSABLE_SECRET_HASH = "!" * 64
_B64URL = re.compile(r"[A-Za-z0-9_-]*")
_ENROLMENT_FILE_KEYS = frozenset({"device_id", "signing_public_key", "app_version"})

# Ed25519 curve constants (RFC 8032 section 5.1).
_P = 2**255 - 19
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


class SigningKeyRefusal(Exception):
    """Why a bundle's signing key is refused: ``code`` is ``device_unknown``,
    ``device_revoked`` or ``signing_key_unknown`` (bundle spec 5.2)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _now() -> datetime:
    return datetime.now(UTC)


def decode_b64url(text) -> bytes | None:
    """Strict base64url (RFC 4648 section 5) with optional padding, else None.
    Mirrors ``b64u_decode`` in the Rust crate."""
    if not isinstance(text, str) or len(text) > 512:
        return None
    trimmed = text.rstrip("=")
    if len(text) - len(trimmed) > 2 or not _B64URL.fullmatch(trimmed):
        return None
    try:
        return base64.b64decode(
            trimmed + "=" * (-len(trimmed) % 4), altchars=b"-_", validate=True
        )
    except (binascii.Error, ValueError):
        return None


def _is_curve_point(raw: bytes) -> bool:
    """True when *raw* decodes to a point on Ed25519 (RFC 8032 5.1.3).
    ``cryptography`` checks only the length, so an off-curve key would enrol
    and then never verify a bundle."""
    y = int.from_bytes(raw, "little") & ((1 << 255) - 1)
    sign = raw[31] >> 7
    if y >= _P:
        return False
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return sign == 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    return (x * x - x2) % _P == 0


def parse_public_key(value) -> bytes:
    """The raw 32-byte Ed25519 public key from its base64url text, else 400
    ``invalid_request`` with ``fields: ["signing_public_key"]``."""
    raw = decode_b64url(value)
    if raw is None or len(raw) != 32 or not _is_curve_point(raw):
        raise DeviceAuthError(
            "signing_public_key must be a base64url Ed25519 public key (32 bytes).",
            "invalid_request", 400, fields=["signing_public_key"],
        )
    return raw


def compute_signing_key_id(public_key: bytes) -> str:
    """First 16 lowercase hex characters of SHA-256 of the raw key."""
    return hashlib.sha256(public_key).digest()[:8].hex()


def set_signing_key(device: AuthDevice, public_key: bytes, *, via: str,
                    actor_user_id: uuid.UUID | None = None) -> str:
    """Give *device* its first signing key; returns the key id. Set once:
    a device that has one already is 409 ``conflict`` (a re-key is not built).
    *via* names the path for the audit row. Caller commits."""
    if device.signing_public_key is not None:
        raise DeviceAuthError("This device already has a signing key.", "conflict", 409)
    now = _now()
    key_id = compute_signing_key_id(public_key)
    device.signing_public_key = public_key
    device.signing_key_id = key_id
    device.signing_key_set_at = now
    db.session.add(AuthDeviceSigningKey(
        device_id=device.device_id, signing_public_key=public_key, signing_key_id=key_id, set_at=now,
    ))
    db.session.flush()
    record_security_event(
        user_id=None, actor_user_id=actor_user_id, event_type="device_signing_key_set",
        detail={"device_id": str(device.device_id), "signing_key_id": key_id, "via": via},
    )
    log.info("device signing key set | device=%s | key=%s | via=%s", device.device_id, key_id, via)
    return key_id


def set_current_device_key(device_id: uuid.UUID, signing_public_key) -> str:
    """``POST /auth/devices/current/signing-key``: *device_id* comes from the
    caller's bearer session, never the body. The row is locked so two
    concurrent calls cannot both set a key. Caller commits."""
    public_key = parse_public_key(signing_public_key)
    device = db.session.scalar(
        sa.select(AuthDevice).where(AuthDevice.device_id == device_id).with_for_update()
    )
    if device is None:
        raise DeviceAuthError("Device is not recognised.", "device_invalid", 401)
    if device.revoked_at is not None:
        raise DeviceAuthError("This device has been revoked.", "device_revoked", 403)
    return set_signing_key(device, public_key, via="device")


def register_pasted_station(project_id: str, enrolment_file, *, name, actor: VaUsers) -> AuthDevice:
    """Register a never-online station from its enrolment file
    ``{device_id, signing_public_key, app_version}`` into *project_id*. The
    device gets no secret (``UNUSABLE_SECRET_HASH``), so it never signs in;
    it only signs bundles. Refusals: 400 malformed file or bad key, 404
    project, 409 ``conflict`` for a device id already registered. Audited
    as ``device_registered_from_file``. Caller commits."""
    if not isinstance(enrolment_file, dict) or set(enrolment_file) - _ENROLMENT_FILE_KEYS:
        raise DeviceAuthError(
            "enrolment_file must be an object with device_id, signing_public_key and app_version.",
            "invalid_request", 400, fields=["enrolment_file"],
        )
    try:
        device_id = uuid.UUID(enrolment_file.get("device_id"))
    except (ValueError, TypeError, AttributeError):
        raise DeviceAuthError("device_id must be a UUID.", "invalid_request", 400,
                              fields=["enrolment_file.device_id"]) from None
    public_key = parse_public_key(enrolment_file.get("signing_public_key"))
    device_name = _clean_text(name, limit=_DEVICE_NAME_MAX, name="name", required=True)
    version = _clean_text(enrolment_file.get("app_version"), limit=_APP_VERSION_MAX,
                          name="app_version", required=False)
    if not _project_active(project_id):
        raise DeviceAuthError("Project not found.", "not_found", 404)
    if db.session.get(AuthDevice, device_id) is not None:
        raise DeviceAuthError("A device with this device_id is already registered.", "conflict", 409)

    device = AuthDevice(
        device_id=device_id, project_id=project_id, name=device_name, platform=STATION_PLATFORM,
        app_version=version, secret_hash=UNUSABLE_SECRET_HASH,
    )
    try:
        with db.session.begin_nested():
            db.session.add(device)
            db.session.flush()
    except IntegrityError:  # a concurrent paste of the same file
        raise DeviceAuthError("A device with this device_id is already registered.", "conflict", 409) from None
    key_id = set_signing_key(device, public_key, via="enrolment_file", actor_user_id=actor.user_id)
    record_security_event(
        user_id=None, actor_user_id=actor.user_id, event_type="device_registered_from_file",
        detail={"device_id": str(device_id), "project_id": project_id, "signing_key_id": key_id},
    )
    return device


def bundle_signing_key(device_id, signing_key_id, created_at: datetime) -> bytes:
    """The raw public key a bundle from *device_id* signed with
    *signing_key_id* must verify against: the device's current key or an
    earlier one. *created_at* is the manifest's (timezone-aware); its age
    bound is the caller's. Raises ``SigningKeyRefusal``: ``device_unknown``;
    ``device_revoked`` for a compromised device, or a revoked one when
    *created_at* is not before ``revoked_at``; ``signing_key_unknown``."""
    if created_at.tzinfo is None:
        raise ValueError("created_at must be timezone-aware")
    try:
        device = db.session.get(AuthDevice, uuid.UUID(str(device_id)))
    except ValueError:
        device = None
    if device is None:
        raise SigningKeyRefusal("device_unknown")
    if device.revoked_at is not None and (device.revoked_compromised or created_at >= device.revoked_at):
        raise SigningKeyRefusal("device_revoked")
    key = db.session.scalar(
        sa.select(AuthDeviceSigningKey.signing_public_key).where(
            AuthDeviceSigningKey.device_id == device.device_id,
            AuthDeviceSigningKey.signing_key_id == signing_key_id,
        )
    )
    if key is None:
        raise SigningKeyRefusal("signing_key_unknown")
    return bytes(key)


def verify_bundle_signature(public_key: bytes, manifest_line: bytes, signature: bytes) -> bool:
    """Ed25519 check of ``b"digitva-bundle-v1\\x00" || manifest_line`` (line 1
    of the bundle without its LF) against the 64-byte *signature*."""
    if len(signature) != 64 or len(public_key) != 32:
        return False
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, BUNDLE_SIG_DOMAIN + manifest_line)
    except (InvalidSignature, ValueError):
        return False
    return True
