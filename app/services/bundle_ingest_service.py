"""Offline bundle (.dvb) ingest: verify, decrypt in memory, apply each
record through the HTTPS services, report, sign a receipt (bead
digitva-gb8w.2).

Policy: docs/policy/offline-bundle-and-transfer.md 2 (format), 3 (signature,
replay, age, keys), 4 (idempotency), 5.1-5.6 (ingest); contract
docs/policy/offline-api-contract.md 4, 4.1, 4.2, 5, 7, 8. The writer is
``build_bundle`` in desktop/crates/digitva-bundle/src/lib.rs; the receipt is
read by its ``verify_and_plan_receipt``.

Order. Whole-bundle checks first, nothing written and nothing decrypted:
container limits, manifest and signature lines, uploader, device and
signing key, onboarding, signature, body hash, replay, age, KEM key, and
only then the record lines; the bundle DEK is unwrapped once, under the
bundle's ingest lock (``_ingest_lock``). Records are processed by type in the spec order (within
a type in the writer's signed line order, which ``build_bundle`` sorts by
``recorded_at``), each decrypted just before it is used and in its own
savepoint, so one rejection never rolls back another. A
``death_registration`` naming ``consent_client_id`` is applied with that
consent in one savepoint.

Actors. A record's ``actor_user_id`` is a roster ``user_id``
(``va_users.user_number``) of the station config the manifest names; the
user must be active on it with the record's ``acting_role`` in scope, still
hold the server grant behind that role, and (an online-enrolled station
only) have signed in on the station at or before ``created_at``. The
services then run under the device projection of the actor's grants, as a
device bearer request would, whatever the uploader's credential.

Plaintext lives only in local variables of one record's processing; it is
never logged, written to disk or put in the report (ids, codes, hashes and
field names only). Python cannot wipe a ``bytes`` object, so "released"
means dropped for the collector.
"""
from __future__ import annotations

import base64
import binascii
import contextlib
import hashlib
import hmac
import json
import logging
import re
import unicodedata
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import current_app, g
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (
    AuthDevice,
    AuthDeviceSession,
    AuthStationConfig,
    AuthStationCustodian,
    MapBundleRecord,
    MasOrgUnit,
    VaAccessRoles,
    VaBundleIngest,
    VaBundlePendingCoding,
    VaConsentRecord,
    VaDeathRegister,
    VaProjectMaster,
    VaStatuses,
    VaSubmissionWorkflow,
    VaUsers,
    VaWebIntakeDraft,
)
from app.services import case_transition_service as cases
from app.services import coder_cod_service as coder_cod
from app.services import coder_workflow_service as coder_workflow
from app.services import consent_service, smartva_service
from app.services import death_identifier_service as identifiers_svc
from app.services import death_identifier_write as identifier_write
from app.services import device_auth_service as devices
from app.services import offline_coding_import_service as offline_coding_import
from app.services import station_config_service as station_config
from app.services import web_intake_attachment_service as intake_attachments
from app.services import web_intake_service as intake
from app.services.authz import resolve_grants
from app.services.cod_entry_mode import is_masked, project_mode
from app.services.device_signing_service import (
    UNUSABLE_SECRET_HASH,
    SigningKeyRefusal,
    bundle_signing_key,
    decode_b64url,
    verify_bundle_signature,
)
from app.services.security_event_service import record_security_event
from app.utils import pii_crypto

log = logging.getLogger(__name__)

BUNDLE_FORMAT_VERSION = 1
MEDIA_TYPE = "application/vnd.digitva.bundle"
RECEIPT_MEDIA_TYPE = "application/vnd.digitva.receipt"
#: Rust ``RECEIPT_SIG_DOMAIN``.
RECEIPT_SIG_DOMAIN = b"digitva-receipt-v1\x00"
#: Rust ``BUNDLE_AAD_TABLE`` (bundle spec 2.3, 3.1).
AAD_TABLE = "digitva_bundle"
#: Spec 2.1 limits (Rust ``BUNDLE_MAX_*``).
MAX_BYTES = 50 * 1024 * 1024
MAX_RECORDS = 5_000
MAX_LINE_BYTES = 2 * 1024 * 1024 + 64 * 1024
MAX_MANIFEST_BYTES = 256 * 1024
#: Contract 4.2 limits.
MAX_CORRECTIONS = 500
CORRECTION_MAX_BYTES = 16 * 1024
#: ``created_at`` may run ahead of the server clock by this much (spec 3.3).
FUTURE_SKEW = timedelta(days=1)
#: Stored ingests per device per hour (spec 5.1; the uploader's own limit is the route's).
DEVICE_HOURLY_LIMIT = 10
#: Longest ``missing_seq`` list a report carries, and largest forward jump a station's ``bundle_seq`` may make.
MISSING_SEQ_MAX = 100
MAX_BUNDLE_SEQ_GAP = 10_000

#: Processing order (spec 5.3). ``attachment_chunk`` is reserved, not built.
RECORD_ORDER = (
    "death_registration", "consent", "death_correction", "interview_submission",
    "identifiers_set", "attachment_chunk", "coding_result",
)
_ORDER = {name: index for index, name in enumerate(RECORD_ORDER)}
#: Which roster role may send which record (contract 4.1, 4.2; Rust ``validate_actor_on_roster``).
ROLES_FOR_TYPE = {
    "death_registration": frozenset({"death_reporter", "interviewer"}),
    "consent": frozenset({"death_reporter", "interviewer"}),
    "death_correction": frozenset({"station_supervisor"}),
    "identifiers_set": frozenset({"station_supervisor"}),
    "interview_submission": frozenset({"interviewer"}),
    "coding_result": frozenset({"coder"}),
}
#: Applied outcomes: the station deletes the record on a receipt naming one (spec 5.6).
APPLIED = frozenset({"accepted", "duplicate", "superseded"})
OUTCOMES = ("accepted", "duplicate", "superseded", "pending", "rejected")
#: A refused content check per record type when the service names no code.
_CONTENT_CODES = {
    "death_registration": "invalid_registration",
    "death_correction": "invalid_death",
    "interview_submission": "invalid_interview",
    "identifiers_set": "invalid_request",
    "coding_result": "invalid_cod",
}
_STATUS_CODES = {403: "forbidden", 404: "not_found", 409: "conflict", 429: "rate_limited"}

MANIFEST_KEYS = frozenset({
    "app_version", "body_sha256", "bundle_format_version", "bundle_id", "bundle_seq", "crate_version",
    "created_at", "dek_wrapped", "device_id", "instrument_versions", "kem_key_id", "project_ids",
    "record_counts", "signing_key_id", "station_config_id",
})
_ENVELOPE_KEYS = frozenset({"record_type", "client_id", "project_id", "actor_user_id", "acting_role", "recorded_at"})
#: Keys of a consent record that are not the 5.3 consent object's.
_CONSENT_ENVELOPE_ONLY = ("record_type", "project_id", "actor_user_id", "acting_role", "death_ref")
_CONSENT_BODY = frozenset(consent_service.CONSENT_KEYS - {"client_id", "recorded_at"}) | {"death_ref"}
_TYPE_KEYS = {
    "death_registration": frozenset({"site_id", "org_unit_id", "identifiers", "consent_client_id",
                                     *intake.REGISTER_FIELDS}),
    "consent": _CONSENT_BODY,
    "death_correction": frozenset({"death_ref", "reason", "if_updated_at", "base_client_id", "changes"}),
    "identifiers_set": frozenset({"death_ref", "reason", "if_updated_at", "base_client_id", "identifiers"}),
    "interview_submission": frozenset({"site_id", "org_unit_id", "death_ref", "draft", "completion",
                                       "answers_json", "answers_sha256", "consent_client_id"}),
    "coding_result": frozenset({"client_draft_id", "coded_answers_sha256", "kind", "initial", "final",
                                "not_codeable", "coding_mode"}),
}
#: Contract 5.5: informant fields of a station registration need its granted consent.
INFORMANT_FIELDS = ("informant_name", "informant_phone", "informant_phone_2", "address",
                    "address_house_street", "address_village_ward", "address_landmark")
_UPLOADER_ROLES = frozenset({VaAccessRoles.data_manager, VaAccessRoles.interview_supervisor})

_CREATED_AT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
_HEX64_RE = re.compile(r"[0-9a-f]{64}")
_HEX16_RE = re.compile(r"[0-9a-f]{16}")
_B64URL_RE = re.compile(r"[A-Za-z0-9_-]*")


class BundleRefusal(Exception):
    """A whole-bundle refusal: nothing was written. ``code`` is the contract
    code (section 8); the message is safe to show."""

    def __init__(self, message: str, code: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.status = status


class RecordRejected(Exception):
    """One record's rejection: ``code`` per contract section 8, ``fields``
    names inputs (never values)."""

    def __init__(self, code: str, fields: list[str] | None = None):
        super().__init__(code)
        self.code = code
        self.fields = fields


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate key")
        out[key] = value
    return out


def _no_float(_text):
    raise ValueError("numbers are integers only")


def _loads(raw: bytes):
    """Strict JSON: no duplicate keys, integers only (JCS integer rule)."""
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates,
                      parse_float=_no_float, parse_constant=_no_float)


def _canonical_line(raw: bytes) -> dict:
    """A line that is a JSON object in exactly its canonical (JCS, NFC) form."""
    value = _loads(raw)
    if not isinstance(value, dict) or station_config.canonical_json(value) != raw:
        raise ValueError("not canonical")
    return value


def _check_text(value) -> None:
    """``record_invalid`` when any string in *value* (keys included) holds a
    NUL or a lone surrogate: JSON escapes (``\\u0000``, ``\\ud800``) parse,
    but neither survives a UTF-8 encode or a Postgres text column."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            if "\x00" in item:
                raise RecordRejected("record_invalid")
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                raise RecordRejected("record_invalid") from None
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


#: A report entry names at most this many fields, each cut to this length:
#: unknown keys are the sender's text, and the receipt is signed.
FIELDS_MAX = 5
FIELD_NAME_MAX = 64


def _capped(fields: list[str] | None) -> list[str] | None:
    return [str(name)[:FIELD_NAME_MAX] for name in fields[:FIELDS_MAX]] if fields else None


def _uuid(value, *, v4: bool = False) -> uuid.UUID | None:
    """*value* as a UUID when it is lowercase hyphenated UUID text, else None."""
    if not isinstance(value, str):
        return None
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return None
    if str(parsed) != value or (v4 and parsed.version != 4):
        return None
    return parsed


def _b64u(text: str) -> bytes | None:
    if not _B64URL_RE.fullmatch(text):
        return None
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (binascii.Error, ValueError):
        return None


@dataclass
class _Line:
    index: int
    client_id: uuid.UUID
    record_type: str
    ct: str


@dataclass
class _Container:
    manifest_line: bytes
    manifest: dict
    signature: bytes
    #: The upload and where its record lines start (line 3).
    raw: bytes
    body_start: int
    bundle_id: uuid.UUID
    device_id: uuid.UUID
    station_config_id: uuid.UUID
    created_at: datetime
    #: Filled by ``_parse_records`` after the signature and body hash.
    lines: list[_Line] = field(default_factory=list)
    _body_sha256: str | None = None

    @property
    def body_sha256(self) -> str:
        """SHA-256 of the record lines, hashed through a view (no copy)."""
        if self._body_sha256 is None:
            self._body_sha256 = hashlib.sha256(memoryview(self.raw)[self.body_start:]).hexdigest()
        return self._body_sha256


def _bad_manifest(message: str) -> BundleRefusal:
    return BundleRefusal(message, "manifest_invalid")


def _parse_manifest(raw: bytes) -> dict:
    if len(raw) + 1 > MAX_MANIFEST_BYTES:
        raise BundleRefusal("The manifest line is too long.", "payload_too_large", 413)
    try:
        manifest = _canonical_line(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise _bad_manifest("Line 1 is not a canonical JSON manifest.") from None
    if manifest.get("bundle_format_version") != BUNDLE_FORMAT_VERSION or isinstance(
            manifest.get("bundle_format_version"), bool):
        raise BundleRefusal("This bundle format version is not supported.", "bundle_version_unsupported")
    if set(manifest) != MANIFEST_KEYS:
        raise _bad_manifest("The manifest has missing or unknown keys.")
    checks = (
        _uuid(manifest["bundle_id"], v4=True) is not None,
        type(manifest["bundle_seq"]) is int and 1 <= manifest["bundle_seq"] <= 2_147_483_647,
        _uuid(manifest["device_id"]) is not None,
        isinstance(manifest["signing_key_id"], str) and _HEX16_RE.fullmatch(manifest["signing_key_id"]),
        _sorted_unique_text(manifest["project_ids"]) and len(manifest["project_ids"]) >= 1,
        isinstance(manifest["created_at"], str) and _CREATED_AT_RE.fullmatch(manifest["created_at"]),
        all(isinstance(manifest[k], str) and 0 < len(manifest[k]) <= 64 for k in ("app_version", "crate_version")),
        _sorted_unique_text(manifest["instrument_versions"]),
        _uuid(manifest["station_config_id"]) is not None,
        isinstance(manifest["kem_key_id"], str) and pii_crypto.KEY_ID_RE.fullmatch(manifest["kem_key_id"]),
        isinstance(manifest["dek_wrapped"], str)
        and manifest["dek_wrapped"].startswith(f"{pii_crypto.WRAP_PREFIX}{manifest['kem_key_id']}:"),
        isinstance(manifest["record_counts"], dict) and all(
            k in _ORDER and type(v) is int and v >= 1 for k, v in manifest["record_counts"].items()),
        isinstance(manifest["body_sha256"], str) and _HEX64_RE.fullmatch(manifest["body_sha256"]),
    )
    if not all(checks):
        raise _bad_manifest("A manifest field is malformed.")
    try:
        datetime.strptime(manifest["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise _bad_manifest("created_at is not a valid time.") from None
    return manifest


def _sorted_unique_text(value) -> bool:
    return (isinstance(value, list) and all(isinstance(v, str) and v for v in value)
            and value == sorted(set(value)))


def _parse_signature(raw: bytes, manifest: dict) -> bytes:
    try:
        line = _canonical_line(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise _bad_manifest("Line 2 is not a canonical JSON signature.") from None
    if set(line) != {"alg", "sig", "signing_key_id"} or line["alg"] != "ed25519":
        raise BundleRefusal("The bundle signature line is malformed.", "signature_invalid")
    signature = decode_b64url(line["sig"])
    if line["signing_key_id"] != manifest["signing_key_id"] or signature is None or len(signature) != 64:
        raise BundleRefusal("The bundle signature line is malformed.", "signature_invalid")
    return signature


def _parse_record_line(index: int, raw: bytes) -> _Line:
    if len(raw) + 1 > MAX_LINE_BYTES:
        raise BundleRefusal("A record line is too long.", "payload_too_large", 413)
    try:
        line = _canonical_line(raw)
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise _bad_manifest(f"Record line {index + 3} is not canonical JSON.") from None
    client_id = _uuid(line.get("client_id"))
    if (set(line) != {"client_id", "ct", "record_type"} or client_id is None
            or line["record_type"] not in _ORDER or not isinstance(line["ct"], str)
            or not line["ct"].startswith(pii_crypto.DATA_PREFIX)):
        raise _bad_manifest(f"Record line {index + 3} is malformed.")
    return _Line(index, client_id, line["record_type"], line["ct"])


def _parse_head(raw: bytes) -> _Container:
    """The container's form and limits and its first two lines (spec
    2.1-2.3, 5.2 step 1); the record lines are only counted, so an unsigned
    upload costs one scan before the uploader and signature are checked.
    Raises ``BundleRefusal``."""
    if len(raw) > MAX_BYTES:
        raise BundleRefusal("The bundle is too large.", "payload_too_large", 413)
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise _bad_manifest("A bundle is UTF-8 lines ending in LF, without BOM or CR.")
    first = raw.find(b"\n")
    second = raw.find(b"\n", first + 1)
    if second < 0 or second + 1 == len(raw):
        raise _bad_manifest("A bundle has a manifest, a signature and at least one record.")
    if raw.count(b"\n", second + 1) > MAX_RECORDS:
        raise BundleRefusal(f"A bundle holds at most {MAX_RECORDS} records.", "payload_too_large", 413)
    manifest = _parse_manifest(raw[:first])
    signature = _parse_signature(raw[first + 1:second], manifest)
    return _Container(
        manifest_line=raw[:first], manifest=manifest, signature=signature, raw=raw, body_start=second + 1,
        bundle_id=uuid.UUID(manifest["bundle_id"]), device_id=uuid.UUID(manifest["device_id"]),
        station_config_id=uuid.UUID(manifest["station_config_id"]),
        created_at=datetime.strptime(manifest["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC),
    )


def _parse_records(container: _Container) -> None:
    """Each record line's form (spec 2.2), walked with ``find`` (one line's
    bytes at a time, no split list); then ``record_counts``. Run only after
    the signature and body hash verify. Raises ``BundleRefusal``."""
    raw, start, lines = container.raw, container.body_start, []
    while start < len(raw):
        end = raw.find(b"\n", start)  # raw ends with LF (``_parse_head``)
        lines.append(_parse_record_line(len(lines), raw[start:end]))
        start = end + 1
    counts: dict[str, int] = {}
    for line in lines:
        counts[line.record_type] = counts.get(line.record_type, 0) + 1
    if counts != container.manifest["record_counts"]:
        raise _bad_manifest("record_counts does not match the records.")
    container.lines = lines


def parse_container(raw: bytes) -> _Container:
    """The whole container parsed (head and record lines); nothing verified
    or decrypted. The fixture tests' entry point; the ingest runs the
    stages itself, verifying between them. Raises ``BundleRefusal``."""
    container = _parse_head(raw)
    _parse_records(container)
    return container


# ---------------------------------------------------------------------------
# Whole-bundle checks (spec 5.2)
# ---------------------------------------------------------------------------


def may_upload_for(user: VaUsers, project_id: str) -> bool:
    """A browser uploader of *project_id*'s bundles and reader of their
    reports: admin, or a data manager or interview supervisor with a grant
    in the project (spec 5.1, decision Q1). Full browser grants."""
    resolved = resolve_grants(user, native=False)
    return resolved.is_admin or any(gr.project_id == project_id for gr in resolved.of(_UPLOADER_ROLES))


def _authorize_uploader(container: _Container, uploader: VaUsers, bearer_device_id: uuid.UUID | None) -> None:
    if bearer_device_id is not None:
        if bearer_device_id != container.device_id:
            raise BundleRefusal("A station uploads only its own bundles.", "forbidden", 403)
        return
    if not all(may_upload_for(uploader, p) for p in container.manifest["project_ids"]):
        raise BundleRefusal("You may not upload bundles for this project.", "forbidden", 403)


@dataclass
class _Verified:
    container: _Container
    device: AuthDevice
    config: AuthStationConfig
    custodian: AuthStationCustodian
    project_id: str
    manifest_sha256: str
    received_at: datetime


def _verify(container: _Container, received_at: datetime) -> _Verified:
    """Spec 5.2 steps 2-4 before any decryption; raises ``BundleRefusal``.
    The replay check is the caller's (it may answer the stored report)."""
    manifest = container.manifest
    # A backdated claim cannot slip under revoked_at: the earlier of the claim
    # and the receipt time is what the revocation is compared with.
    try:
        public_key = bundle_signing_key(container.device_id, manifest["signing_key_id"],
                                        min(container.created_at, received_at))
    except SigningKeyRefusal as refusal:
        status = 403 if refusal.code == "device_revoked" else 422
        raise BundleRefusal({
            "device_unknown": "This station is not registered.",
            "device_revoked": "This station has been revoked.",
            "signing_key_unknown": "This station's signing key is not registered.",
        }[refusal.code], refusal.code, status) from None
    device = db.session.get(AuthDevice, container.device_id)
    if manifest["project_ids"] != [device.project_id]:
        raise BundleRefusal("The bundle names a project this station is not enrolled in.", "forbidden", 403)
    custodian = db.session.get(AuthStationCustodian, device.device_id)
    config = db.session.scalar(sa.select(AuthStationConfig).where(
        AuthStationConfig.config_id == container.station_config_id,
        AuthStationConfig.device_id == device.device_id,
    ))
    if custodian is None or config is None:
        raise BundleRefusal("This station is not onboarded: no custodian, or the station config "
                            "the bundle names was not issued to it.", "station_not_onboarded")
    if not verify_bundle_signature(public_key, container.manifest_line, container.signature):
        raise BundleRefusal("The bundle signature does not verify.", "signature_invalid")
    if not hmac.compare_digest(container.body_sha256, manifest["body_sha256"]):
        raise BundleRefusal("The bundle body does not match its manifest.", "body_hash_invalid")
    # After the signature, so the signed created_at decides. Strict, as the
    # station writer's own check (now > expires_at); no skew allowance.
    if container.created_at > config.expires_at:
        raise BundleRefusal("The station configuration had expired when this bundle was made; import a "
                            "renewed station configuration and export again.", "station_config_expired")
    existing_max_seq = db.session.scalar(
        sa.select(sa.func.max(VaBundleIngest.bundle_seq)).where(
            VaBundleIngest.device_id == device.device_id
        )
    ) or 0
    if manifest["bundle_seq"] > existing_max_seq + MAX_BUNDLE_SEQ_GAP:
        raise _bad_manifest("bundle_seq exceeds the allowed sequence gap for this station.")
    return _Verified(
        container=container, device=device, config=config, custodian=custodian,
        project_id=device.project_id, received_at=received_at,
        manifest_sha256=hashlib.sha256(container.manifest_line).hexdigest(),
    )


def _check_age_and_key(verified: _Verified) -> None:
    created, now = verified.container.created_at, verified.received_at
    if created < now - timedelta(days=current_app.config["BUNDLE_MAX_AGE_DAYS"]):
        raise BundleRefusal("This bundle is too old to ingest.", "bundle_too_old")
    if created > now + FUTURE_SKEW:
        raise BundleRefusal("This bundle is dated in the future; check the station clock.", "bundle_from_future")
    if verified.container.manifest["kem_key_id"] not in pii_crypto._keyring().private:
        raise BundleRefusal("Bundle sealed to a retired server key; import the current station "
                            "configuration and export again.", "bundle_key_unknown")


def _check_device_rate(verified: _Verified) -> None:
    recent = db.session.scalar(sa.select(sa.func.count()).select_from(VaBundleIngest).where(
        VaBundleIngest.device_id == verified.device.device_id,
        VaBundleIngest.received_at > verified.received_at - timedelta(hours=1),
    ))
    if recent >= DEVICE_HOURLY_LIMIT:
        raise BundleRefusal("Too many bundles from this station in the last hour.", "rate_limited", 429)


def _stored(container: _Container, manifest_sha256: str) -> VaBundleIngest | None:
    """The earlier ingest of this ``bundle_id``, re-read from the database:
    None when new, else the row (``processed``, or ``processing`` when an
    ingest of it was interrupted or is running); 409 ``bundle_id_reused``
    when it held other bytes."""
    row = db.session.get(VaBundleIngest, container.bundle_id, populate_existing=True)
    if row is None:
        return None
    if not hmac.compare_digest(row.manifest_sha256, manifest_sha256) or row.device_id != container.device_id:
        raise BundleRefusal("This bundle_id was already used for another bundle.", "bundle_id_reused", 409)
    return row


#: ``pg_try_advisory_lock`` class id of bundle ingests (one lock per bundle_id).
_INGEST_LOCK_CLASS = 184731


@contextmanager
def _ingest_lock(bundle_id: uuid.UUID):
    """Hold the ingest of *bundle_id* for this request: a session-level
    advisory lock on a connection of its own, since the ingest commits
    midway (coding results) and a transaction lock would end there. A dead
    worker's connection closes and Postgres frees the lock, so a resend
    resumes the interrupted ingest. 409 ``conflict`` while another request
    holds it."""
    with db.engine.connect() as connection:
        params = {"cls": _INGEST_LOCK_CLASS, "name": f"bundle_ingest:{bundle_id}"}
        locked = connection.scalar(sa.text("SELECT pg_try_advisory_lock(:cls, hashtext(:name))"), params)
        connection.commit()
        if not locked:
            raise BundleRefusal("This bundle is being ingested; ask for its report shortly.", "conflict", 409)
        try:
            yield
        finally:
            # A pooled connection keeps a session lock past ROLLBACK: release it here.
            connection.scalar(sa.text("SELECT pg_advisory_unlock(:cls, hashtext(:name))"), params)
            connection.commit()


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@contextmanager
def _device_projection(on: bool):
    """Resolve grants as a device bearer would (``on``) or in full, for the
    calls inside, whatever this request's own credential."""
    previous = g.get("bearer_auth")
    g.bearer_auth = on
    try:
        yield
    finally:
        g.bearer_auth = previous


@dataclass
class _Outcome:
    line: _Line
    outcome: str
    code: str | None = None
    fields: list[str] | None = None
    received_sha256: str | None = None
    death_id: uuid.UUID | None = None
    unique_id: str | None = None

    def as_report(self, dry_run: bool) -> dict:
        outcome = "not_processed" if dry_run and self.outcome != "rejected" else self.outcome
        # A dry run rolls back: a case it "created" never exists, so no ids.
        entry = {
            "client_id": str(self.line.client_id), "record_type": self.line.record_type,
            "outcome": outcome, "code": self.code, "received_sha256": self.received_sha256,
            "death_id": str(self.death_id) if self.death_id and not dry_run else None,
            "unique_id": None if dry_run else self.unique_id,
        }
        if self.fields:
            entry["fields"] = _capped(self.fields)
        return entry


@dataclass
class _Ingest:
    verified: _Verified
    dek: bytes
    dry_run: bool
    outcomes: dict = field(default_factory=dict)  # client_id -> _Outcome
    roster: dict = field(default_factory=dict)  # user_number -> roster member
    users: dict = field(default_factory=dict)  # user_number -> VaUsers
    signed_in: set | None = None  # user ids with a prior device session; None: paste-enrolled
    reach: dict = field(default_factory=dict)
    lines_by_id: dict = field(default_factory=dict)

    # -- setup ---------------------------------------------------------------

    def load_actors(self) -> None:
        """The roster of the named config (the signed file's line 1) and its
        users, one query each; the prior-session set for an online station."""
        payload = json.loads(self.verified.config.signed_text.split("\n", 1)[0])
        self.roster = {m["user_id"]: m for m in payload.get("roster", [])}
        if self.roster:
            self.users = {u.user_number: u for u in db.session.scalars(
                sa.select(VaUsers).where(VaUsers.user_number.in_(list(self.roster))))}
        device = self.verified.device
        if device.secret_hash != UNUSABLE_SECRET_HASH:
            self.signed_in = set(db.session.scalars(sa.select(AuthDeviceSession.user_id).where(
                AuthDeviceSession.device_id == device.device_id,
                AuthDeviceSession.created_at <= self.verified.container.created_at,
            ).distinct()))

    # -- opening -------------------------------------------------------------

    def open(self, line: _Line) -> tuple[dict, str]:
        """The record's plaintext object (checked envelope) and the SHA-256
        of its bytes. ``record_invalid`` when it does not open or parse."""
        raw = _b64u(line.ct[len(pii_crypto.DATA_PREFIX):])
        if raw is None or len(raw) < 12 + 16:
            raise RecordRejected("record_invalid")
        aad = pii_crypto.record_aad(AAD_TABLE, f"{line.record_type}/{line.client_id}",
                                    self.verified.container.bundle_id.bytes)
        try:
            plaintext = AESGCM(self.dek).decrypt(raw[:12], raw[12:], aad)
        except InvalidTag:
            raise RecordRejected("record_invalid") from None
        digest = hashlib.sha256(plaintext).hexdigest()
        if line.record_type in ("death_correction", "identifiers_set") and len(plaintext) > CORRECTION_MAX_BYTES:
            raise RecordRejected("record_invalid")
        try:
            record = _loads(plaintext)
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise RecordRejected("record_invalid") from None
        finally:
            del plaintext
        _check_text(record)
        self._check_envelope(line, record)
        return record, digest

    def _check_envelope(self, line: _Line, record) -> None:
        if not isinstance(record, dict) or not _ENVELOPE_KEYS <= set(record):
            raise RecordRejected("record_invalid")
        unknown = set(record) - _ENVELOPE_KEYS - _TYPE_KEYS.get(line.record_type, frozenset())
        actor = record["actor_user_id"]
        if (unknown or record["record_type"] != line.record_type or record["client_id"] != str(line.client_id)
                or record["project_id"] != self.verified.project_id
                or type(actor) is not int or intake._device_time(record["recorded_at"]) is None
                or not isinstance(record["acting_role"], str)):
            raise RecordRejected("record_invalid", sorted(unknown) or None)

    # -- actors (spec 5.3 "Actor trust", contract 4.1) -----------------------

    def actor(self, record: dict, *, site_id: str, org_unit_id, unroled: str = "forbidden") -> VaUsers:
        """The server user behind *record*, checked against the roster and
        their grants for *site_id* / *org_unit_id* (the record's or the case's).
        *unroled* is the code when the roster names no role of the acting
        role there, or its server grant has gone."""
        role = record["acting_role"]
        if role not in ROLES_FOR_TYPE[record["record_type"]]:
            raise RecordRejected("forbidden")
        member = self.roster.get(record["actor_user_id"])
        user = self.users.get(record["actor_user_id"])
        if (member is None or not member.get("active") or user is None
                or user.user_status != VaStatuses.active
                or (self.signed_in is not None and user.user_id not in self.signed_in)):
            raise RecordRejected("actor_unknown_on_device")
        unit = str(org_unit_id) if org_unit_id else None
        roles = [r for r in member["roles"] if r["role"] == role and r["project_id"] == self.verified.project_id
                 and r["site_id"] == site_id and _unit_within(unit, r["org_unit_id"])]
        if not roles or not any(self._still_granted(user, r) for r in roles):
            raise RecordRejected(unroled)
        return user

    def _still_granted(self, user: VaUsers, role: dict) -> bool:
        """The server grant behind a roster role, re-checked at ingest with
        the full grants (``station_supervisor`` rests on a supervising grant,
        decision 10, which the device projection lacks)."""
        key = (user.user_id, role["role"], role["site_id"], role["org_unit_id"])
        if key not in self.reach:
            with _device_projection(False):
                self.reach[key] = station_config._role_reaches(
                    user, role["role"], role["project_id"], role["site_id"], role["org_unit_id"])
        return self.reach[key]

    # -- shared lookups ------------------------------------------------------

    def depends(self, client_id: uuid.UUID) -> None:
        """``depends_on_rejected`` when *client_id* is a record of this bundle
        that was rejected."""
        earlier = self.outcomes.get(client_id)
        if earlier is not None and earlier.outcome == "rejected":
            raise RecordRejected("depends_on_rejected", [str(client_id)])

    def death(self, ref) -> VaDeathRegister:
        if not isinstance(ref, dict) or len(ref) != 1:
            raise RecordRejected("record_invalid", ["death_ref"])
        (key, value), = ref.items()
        ref_id = _uuid(value)
        if ref_id is None or key not in ("client_death_id", "death_id"):
            raise RecordRejected("record_invalid", ["death_ref"])
        if key == "client_death_id":
            self.depends(ref_id)
            found = db.session.scalar(sa.select(VaDeathRegister).where(VaDeathRegister.client_death_id == ref_id))
        else:
            found = db.session.get(VaDeathRegister, ref_id)
        if found is None or found.project_id != self.verified.project_id:
            raise RecordRejected("not_found", ["death_ref"])
        return found

    def replayed(self, line: _Line, digest: str) -> MapBundleRecord | None:
        """The applied record of an earlier bundle with this client id: same
        content is a duplicate (returned), other content ``conflict``."""
        row = db.session.get(MapBundleRecord, line.client_id)
        if row is None:
            return None
        if row.record_type != line.record_type or not hmac.compare_digest(row.content_sha256, digest):
            raise RecordRejected("conflict")
        return row

    def applied(self, line: _Line, digest: str, death_id: uuid.UUID | None) -> None:
        if self.dry_run or db.session.get(MapBundleRecord, line.client_id) is not None:
            return
        db.session.add(MapBundleRecord(
            client_id=line.client_id, bundle_id=self.verified.container.bundle_id,
            record_type=line.record_type, content_sha256=digest, death_id=death_id,
        ))
        db.session.flush()

    def station_audit(self, death: VaDeathRegister, actor: VaUsers, line: _Line, record: dict) -> None:
        """One case audit row per newly applied station record, beside the
        service's own rows (spec 5.6): which station, config, bundle and
        custodian, and the roster role acted on; no record values. A
        correction (contract 4.2) is ``station_correction`` with
        ``authorized_by`` and its reason text (kept only here); every other
        record ``station_record``."""
        changes = _station_changes(
            record["acting_role"], record["actor_user_id"], line.record_type, self.verified.device.device_id,
            self.verified.config.config_id, self.verified.container.bundle_id, line.client_id,
            self.verified.custodian)
        action = "station_record"
        if line.record_type in ("death_correction", "identifiers_set"):
            action = "station_correction"
            changes["authorized_by"] = "station_roster"
            changes["reason"] = unicodedata.normalize("NFC", record["reason"]).strip()
        cases.record_action(death, actor=actor, action=action, changes=changes)


def _station_changes(acting_role, actor_number, record_type, device_id, config_id, bundle_id, client_id,
                     custodian: AuthStationCustodian | None) -> dict:
    """The ``changes`` of a station audit row (spec 5.6): ids and roles, no
    record values."""
    return {
        "acting_role": acting_role, "actor_user_id": actor_number, "record_type": record_type,
        "device_id": str(device_id), "station_config_id": str(config_id), "bundle_id": str(bundle_id),
        "client_id": str(client_id),
        "custodian": {"name": custodian.name, "designation": custodian.designation} if custodian else None,
    }


def _unit_within(unit: str | None, roster_unit: str | None) -> bool:
    """Whether a record's unit lies in a roster role's unit (None: the whole site)."""
    if roster_unit is None:
        return True
    if unit is None:
        return False
    if unit == roster_unit:
        return True
    inner_id, outer_id = _uuid(unit), _uuid(roster_unit)
    if inner_id is None or outer_id is None:
        return False
    paths = dict(db.session.execute(sa.select(MasOrgUnit.org_unit_id, MasOrgUnit.path).where(
        MasOrgUnit.org_unit_id.in_([inner_id, outer_id]))).all())
    inner, outer = paths.get(inner_id), paths.get(outer_id)
    return bool(inner and outer and str(inner).startswith(f"{outer}."))


def _service_code(exc, record_type: str) -> RecordRejected:
    """A service refusal as a record rejection: its own code, else the
    content code of the record type (400/422) or the status's."""
    code = getattr(exc, "code", None)
    status = getattr(exc, "status_code", None) or 400
    fields = list(getattr(exc, "fields", None) or []) or None
    if code and code != "invalid_request":
        return RecordRejected(code, fields)
    if status in (400, 422):
        return RecordRejected(_CONTENT_CODES.get(record_type, "record_invalid"), fields)
    return RecordRejected(_STATUS_CODES.get(status, "conflict"), fields)


_SERVICE_ERRORS = (
    intake.WebIntakeError, consent_service.ConsentError, devices.DeviceAuthError,
    coder_cod.CoderCodingError, coder_workflow.AllocationError,
)


def _text_fields(record: dict, names) -> dict:
    values = {name: record.get(name) for name in names}
    if any(isinstance(v, (dict, list, bool)) for v in values.values()):
        raise RecordRejected("record_invalid")
    return values


def _registration(ingest: _Ingest, line: _Line, record: dict, digest: str) -> _Outcome:
    """Bundle spec 2.4 / contract 5.5: the ``POST /intake/deaths`` path."""
    site_id = record.get("site_id")
    if not isinstance(site_id, str) or not site_id.strip():
        raise RecordRejected("record_invalid", ["site_id"])
    org_unit_id = record.get("org_unit_id")
    if org_unit_id is not None and _uuid(org_unit_id) is None:
        raise RecordRejected("record_invalid", ["org_unit_id"])
    fields = _text_fields(record, intake.REGISTER_FIELDS)
    identifiers = record.get("identifiers")
    actor = ingest.actor(record, site_id=site_id.strip(), org_unit_id=org_unit_id)
    # A bundle registration applied before: other bytes are a ``conflict``.
    ingest.replayed(line, digest)
    existing = db.session.scalar(sa.select(VaDeathRegister).where(VaDeathRegister.client_death_id == line.client_id))
    if existing is not None:
        # ponytail: a case registered over HTTPS has no content hash to compare,
        # so the same client_death_id by the same registrant is a duplicate
        # whatever the fields (spec 9: HTTPS then bundle is a duplicate);
        # comparing register fields would need the sealed values opened.
        if existing.registered_by != actor.user_id or existing.project_id != ingest.verified.project_id:
            raise RecordRejected("conflict")
        ingest.applied(line, digest, existing.death_id)
        return _Outcome(line, "duplicate", death_id=existing.death_id, unique_id=existing.unique_id)

    consent_line = None
    consent_ref = record.get("consent_client_id")
    if consent_ref is not None:
        consent_id = _uuid(consent_ref)
        consent_line = ingest.lines_by_id.get(consent_id)
        if consent_line is None or consent_line.record_type != "consent":
            raise RecordRejected("consent_required", ["consent_client_id"])
        consent_record, _ = ingest.open(consent_line)
        if consent_record.get("decision") == "refused":
            raise RecordRejected("consent_refused", ["consent_client_id"])
    if consent_line is None and consent_service.has_covered_data(fields, INFORMANT_FIELDS):
        raise RecordRejected("consent_required", ["consent_client_id"])

    try:
        if identifiers is not None:
            identifiers_svc.check_limits(identifiers)
        death = intake.register_death(
            actor, project_id=ingest.verified.project_id, site_id=site_id.strip(), org_unit_id=org_unit_id,
            client_death_id=line.client_id, identifiers=identifiers, warnings=[], **fields)
        db.session.flush()
    except intake.WebIntakeError as exc:
        raise _service_code(exc, line.record_type) from None
    ingest.station_audit(death, actor, line, record)
    if consent_line is not None:
        _registration_consent(ingest, consent_line, line, death, fields)
    ingest.applied(line, digest, death.death_id)
    return _Outcome(line, "accepted", death_id=death.death_id, unique_id=death.unique_id)


def _registration_consent(ingest: _Ingest, consent_line: _Line, reg_line: _Line, death, fields: dict) -> None:
    """The named consent, in the registration's savepoint: recorded under
    its own actor, then the gate for the register fields (contract 5.5). Its
    outcome follows the registration's (set by the caller on rejection)."""
    try:
        consent, consent_digest = ingest.open(consent_line)
    except RecordRejected as exc:
        raise RecordRejected("consent_invalid", exc.fields) from None
    if consent.get("death_ref") != {"client_death_id": str(reg_line.client_id)} or consent.get("client_draft_id"):
        raise RecordRejected("consent_invalid", ["consent_client_id"])
    consent_actor = ingest.actor(consent, site_id=death.site_id, org_unit_id=death.org_unit_id)
    body = {k: v for k, v in consent.items() if k not in _CONSENT_ENVELOPE_ONLY}
    stored, created = consent_service.record_consent(
        consent_actor, project_id=ingest.verified.project_id, death=death, consent=body,
        client_draft_id=None, channel="bundle")
    if consent_service.has_covered_data(fields, INFORMANT_FIELDS) and stored.event != "granted":
        raise RecordRejected("consent_required", ["consent_client_id"])
    if created:
        ingest.station_audit(death, consent_actor, consent_line, consent)
    consent_service.apply_registration_consent(consent_actor, death, None, fields=fields, channel="bundle")
    ingest.applied(consent_line, consent_digest, death.death_id)
    ingest.outcomes[consent_line.client_id] = _Outcome(consent_line, "accepted", death_id=death.death_id,
                                                       unique_id=death.unique_id)


def _consent(ingest: _Ingest, line: _Line, record: dict, digest: str) -> _Outcome:
    """A standalone consent record (``consent_service.record_consent``)."""
    death = ingest.death(record.get("death_ref"))
    actor = ingest.actor(record, site_id=death.site_id, org_unit_id=death.org_unit_id)
    with _device_projection(True):
        if not (intake.interviewer_reaches(actor, death) or intake._reporter_reaches(actor, death)):
            raise RecordRejected("forbidden")
    if ingest.replayed(line, digest) is not None:
        return _Outcome(line, "duplicate", death_id=death.death_id, unique_id=death.unique_id)
    draft_id = record.get("client_draft_id")
    death = cases.lock_case(death)
    if record.get("decision") == "refused":
        submitted = sa.select(sa.exists().where(
            VaWebIntakeDraft.death_id == death.death_id,
            VaWebIntakeDraft.status.in_(("submitted", "superseded")),
            *([VaWebIntakeDraft.client_draft_id == _uuid(draft_id)] if draft_id is not None else []),
        ))
        if db.session.scalar(submitted):
            raise RecordRejected("consent_refused", ["client_draft_id"])
        open_drafts = list(db.session.scalars(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.death_id == death.death_id, VaWebIntakeDraft.status == "draft",
            *([sa.or_(VaWebIntakeDraft.client_draft_id == _uuid(draft_id),
                      VaWebIntakeDraft.meta["lastSync"]["clientDraftId"].astext == str(draft_id))]
              if draft_id is not None else []),
        ).with_for_update()))
        if draft_id is None and open_drafts:
            raise RecordRejected("consent_refused", ["client_draft_id"])
        if len(open_drafts) > 1:
            raise RecordRejected("conflict", ["client_draft_id"])
        for draft in open_drafts:
            if draft.user_id != actor.user_id:
                raise RecordRejected("forbidden")
            intake.clear_direct_identity_for_refusal(draft, actor)
            intake.scrub_refused_draft(draft)
    body = {k: v for k, v in record.items() if k not in _CONSENT_ENVELOPE_ONLY}
    stored, created = consent_service.record_consent(
        actor, project_id=ingest.verified.project_id, death=death, consent=body,
        client_draft_id=_uuid(draft_id) if draft_id is not None else None, channel="bundle")
    if created:
        ingest.station_audit(death, actor, line, record)
    ingest.applied(line, digest, death.death_id)
    return _Outcome(line, "accepted" if created else "duplicate", death_id=death.death_id, unique_id=death.unique_id)


#: The station writes a ``base_client_id`` names (contract 4.2: the
#: registration or an earlier death correction). ``identifiers_set`` is not
#: in the chain: it is processed after the corrections (spec 5.3), so a
#: correction could never build on one sent in the same bundle.
_STALE_CHAIN = ("death_registration", "death_correction")


def _correction_target(ingest: _Ingest, line: _Line, record: dict, digest: str):
    """Shared by both correction types: replay, case, actor, reason and the
    stale rule of contract 4.2. Returns ``(death, actor, replay_row)``."""
    reason = record.get("reason")
    if not isinstance(reason, str) or not 1 <= len(unicodedata.normalize("NFC", reason).strip()) <= 500:
        raise RecordRejected("invalid_reason", ["reason"])
    replay = ingest.replayed(line, digest)
    death = ingest.death(record.get("death_ref"))
    actor = ingest.actor(record, site_id=death.site_id, org_unit_id=death.org_unit_id)
    if replay is not None:
        return death, actor, replay
    if_updated_at, base = record.get("if_updated_at"), record.get("base_client_id")
    if if_updated_at is not None and not isinstance(if_updated_at, str):
        raise RecordRejected("record_invalid", ["if_updated_at"])
    if if_updated_at is None:
        base_id = _uuid(base)
        if base_id is None:
            raise RecordRejected("record_invalid", ["base_client_id"])
        last = db.session.scalar(
            sa.select(MapBundleRecord.client_id)
            .where(MapBundleRecord.death_id == death.death_id,
                   MapBundleRecord.record_type.in_(_STALE_CHAIN))
            .order_by(MapBundleRecord.applied_at.desc()).limit(1)
        ) or death.client_death_id
        if base_id != last:
            raise RecordRejected("death_stale")
    return death, actor, None


def _death_correction(ingest: _Ingest, line: _Line, record: dict, digest: str) -> _Outcome:
    """Contract 4.2: ``update_death`` on the station roster path."""
    changes = record.get("changes")
    if not isinstance(changes, dict) or not changes or "identifiers" in changes:
        raise RecordRejected("record_invalid", ["changes"])
    unknown = sorted(set(changes) - set(intake.REGISTER_FIELDS))
    if unknown:
        raise RecordRejected("invalid_death", unknown)
    _text_fields(changes, changes)
    death, actor, replay = _correction_target(ingest, line, record, digest)
    if replay is not None:
        return _Outcome(line, "duplicate", death_id=death.death_id, unique_id=death.unique_id)
    try:
        death = intake.update_death(actor, death.death_id, changes, if_updated_at=record.get("if_updated_at"),
                                    warnings=[], station_roster=True)
        consent_service.apply_registration_consent(actor, death, None, fields=changes, channel="bundle")
    except _SERVICE_ERRORS as exc:
        raise _service_code(exc, line.record_type) from None
    ingest.station_audit(death, actor, line, record)
    ingest.applied(line, digest, death.death_id)
    return _Outcome(line, "accepted", death_id=death.death_id, unique_id=death.unique_id)


def _identifiers_set(ingest: _Ingest, line: _Line, record: dict, digest: str) -> _Outcome:
    """Contract 4.2: ``put_identifiers`` on the station roster path."""
    values = record.get("identifiers")
    if (not isinstance(values, dict) or not 1 <= len(values) <= identifiers_svc.MAX_CODES_PER_REQUEST
            or not all(v is None or isinstance(v, str) for v in values.values())):
        raise RecordRejected("record_invalid", ["identifiers"])
    death, actor, replay = _correction_target(ingest, line, record, digest)
    if replay is not None:
        return _Outcome(line, "duplicate", death_id=death.death_id, unique_id=death.unique_id)
    try:
        identifiers_svc.check_limits(values)
        death = identifier_write.put_identifiers(actor, death.death_id, values, if_updated_at=record.get("if_updated_at"),
                                                 warnings=[], station_roster=True)
    except _SERVICE_ERRORS as exc:
        raise _service_code(exc, line.record_type) from None
    ingest.station_audit(death, actor, line, record)
    ingest.applied(line, digest, death.death_id)
    return _Outcome(line, "accepted", death_id=death.death_id, unique_id=death.unique_id)


def _interview(ingest: _Ingest, line: _Line, record: dict, digest: str) -> _Outcome:
    """The ``POST /intake/submissions`` path: answers hash before parse,
    ``check_device_answers``, ``check_device_times``, then
    ``submit_device_interview`` (or a later version of it), then the gate."""
    site_id = record.get("site_id")
    envelope, completion = record.get("draft"), record.get("completion")
    answers_json, claimed = record.get("answers_json"), record.get("answers_sha256")
    if not isinstance(site_id, str) or not isinstance(envelope, dict) or not isinstance(completion, dict):
        raise RecordRejected("invalid_interview")
    if not isinstance(answers_json, str) or not isinstance(claimed, str) or not _HEX64_RE.fullmatch(claimed.lower()):
        raise RecordRejected("answers_hash_required")
    raw = answers_json.encode("utf-8", "surrogatepass")
    if len(raw) > intake.DEVICE_ANSWERS_MAX_BYTES:
        raise RecordRejected("invalid_interview")
    answers_sha256 = hashlib.sha256(raw).hexdigest()
    del raw
    if not hmac.compare_digest(answers_sha256, claimed.lower()):
        raise RecordRejected("answers_hash_invalid")
    try:
        data = json.loads(answers_json)
    except (ValueError, RecursionError):
        data = None
    if not isinstance(data, dict):
        raise RecordRejected("invalid_interview")
    _check_text(data)  # answers_json is JSON text of its own: its escapes pass the record's check
    death = ingest.death(record.get("death_ref"))
    # The actor's scope is the case's, as for the other records; the record
    # must name the case's site and (when it names one) its unit.
    org_unit_id = record.get("org_unit_id")
    if site_id != death.site_id or (org_unit_id is not None and (
            not isinstance(org_unit_id, str) or org_unit_id != str(death.org_unit_id or ""))):
        raise RecordRejected("forbidden", ["site_id", "org_unit_id"])
    actor = ingest.actor(record, site_id=death.site_id, org_unit_id=death.org_unit_id)
    consent_ref = record.get("consent_client_id")
    try:
        intake.check_device_answers(data)
        intake.check_device_times(envelope)
        if consent_ref is not None:
            consent = db.session.scalar(sa.select(VaConsentRecord).where(
                VaConsentRecord.client_consent_id == _uuid(consent_ref)))
            if consent is None or consent.death_id != death.death_id:
                raise RecordRejected("consent_required", ["consent_client_id"])
        client_draft_id = line.client_id
        existing = intake.find_device_upload(actor, client_draft_id)
        if existing is not None and existing.answers_sha256 == answers_sha256:
            return _Outcome(line, "duplicate", received_sha256=answers_sha256, death_id=existing.death_id,
                            unique_id=existing.unique_id)
        if existing is not None:
            death = cases.lock_case(death)
            if ((existing.meta or {}).get("interviewOutcome") == "refused"
                    or consent_service.interview_refused(death=death, client_draft_id=client_draft_id, answers=data)):
                raise RecordRejected("consent_refused")
            kept, _locked = intake.resubmit_device_interview(
                actor, existing, envelope=envelope, data=data, answers_sha256=answers_sha256, completion=completion)
            draft = existing
        else:
            draft, kept, _locked = intake.submit_device_interview(
                actor, project_id=ingest.verified.project_id, client_draft_id=client_draft_id, site_id=site_id,
                org_unit_id=record.get("org_unit_id") or None, death_id=str(death.death_id), envelope=envelope,
                data=data, answers_sha256=answers_sha256, completion=completion,
                device_id=ingest.verified.device.device_id)
        case = db.session.get(VaDeathRegister, draft.death_id)
        consent_service.apply_interview_consent(
            actor, project_id=ingest.verified.project_id, death=case,
            client_draft_id=client_draft_id, consent=None, answers=data, channel="bundle")
    except _SERVICE_ERRORS as exc:
        raise _service_code(exc, line.record_type) from None
    ingest.station_audit(case, actor, line, record)
    ingest.applied(line, digest, draft.death_id)
    return _Outcome(line, "superseded" if kept == "server" else "accepted", received_sha256=answers_sha256,
                    death_id=draft.death_id, unique_id=draft.unique_id)


#: Station coding modes (contract 4.3) and the project modes each may land
#: in: the server keeps one classification per project (bundle spec 2.4 Q5).
CODING_MODE_TARGETS = {"icd11_doris": ("unmasked_doris",), "icd10": ("unmasked_simple", "masked_simple")}
#: ``final`` fields handed to the coder save as text.
_FINAL_TEXT = ("conclusive_cod", "remark", "immediate_cod", "other_conditions")


def _station_refusal(device: AuthDevice | None, project_id: str) -> str | None:
    """``offline_coding_disabled`` unless *device*, the station a coding
    result came from, is registered for *project_id* and not revoked (bundle
    spec 2.4 Q5); else None. ``_verify`` refuses a bundle of another project
    or a compromised station outright; this catches a station revoked after
    the bundle was made, at ingest and when a held result is applied."""
    if device is None or device.revoked_at is not None or device.project_id != project_id:
        return "offline_coding_disabled"
    return None


def _coding_refusal(project: VaProjectMaster, record: dict) -> str | None:
    """Why *project* takes no station coding result like *record* (bundle
    spec 2.4 Q5), or None: the record's ``coding_mode`` against the
    project's mode. A record without one (a station before the field) has
    the v1 rule, masked simple only. Checked at ingest and again when a held
    result is applied; the station and roster gate is the caller's."""
    mode, target = record.get("coding_mode"), project_mode(project)
    if mode is None:
        if target != "masked_simple":
            return "coding_mode_unsupported"
    elif not isinstance(mode, str) or mode not in CODING_MODE_TARGETS:
        return "coding_mode_unsupported"
    elif target not in CODING_MODE_TARGETS[mode]:
        return "coding_mode_mismatch"
    if is_masked(target) and record["kind"] == "final" and not isinstance(record.get("initial"), dict):
        # A masked project needs the coder's Step 1; none is made up.
        return "record_invalid" if mode is None else "coding_mode_mismatch"
    return None


def _coding_target(ingest: _Ingest, line: _Line, record: dict, digest: str):
    """Checks of a ``coding_result`` that write nothing (spec 2.4, 5.5).
    Returns ``(actor, draft, replay_row)``."""
    kind = record.get("kind")
    part = {"final": "final", "not_codeable": "not_codeable"}.get(kind)
    sha = record.get("coded_answers_sha256")
    draft_id = _uuid(record.get("client_draft_id"))
    if (part is None or draft_id is None or not isinstance(sha, str) or not _HEX64_RE.fullmatch(sha)
            or not isinstance(record.get(part), dict)):
        raise RecordRejected("record_invalid")
    if kind == "final" and any(not isinstance(record["final"].get(k), (str, type(None))) for k in _FINAL_TEXT):
        raise RecordRejected("record_invalid", ["final"])
    replay = ingest.replayed(line, digest)
    ingest.depends(draft_id)
    draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(VaWebIntakeDraft.client_draft_id == draft_id))
    # Only an interview this station uploaded (``submit_device_interview``
    # stores the uploading device server-side): its coder codes the station's
    # own cases, never another device's, whatever the roster lets them reach.
    if (draft is None or draft.va_sid is None or draft.project_id != ingest.verified.project_id
            or (draft.meta or {}).get("deviceId") != str(ingest.verified.device.device_id)):
        raise RecordRejected("not_available", ["client_draft_id"])
    death = db.session.get(VaDeathRegister, draft.death_id)
    actor = ingest.actor(record, site_id=death.site_id, org_unit_id=death.org_unit_id,
                         unroled="actor_not_station_coder")
    if replay is not None:
        return actor, draft, replay
    refusal = (_station_refusal(ingest.verified.device, ingest.verified.project_id)
               or _coding_refusal(db.session.get(VaProjectMaster, ingest.verified.project_id), record))
    if refusal is not None:
        raise RecordRejected(refusal)
    if not hmac.compare_digest(draft.answers_sha256 or "", sha):
        raise RecordRejected("coded_version_superseded")
    return actor, draft, None


def _needs_doris_processing(project: VaProjectMaster, record: dict) -> bool:
    """An ICD-11 DORIS final: the server reprocesses its certificate with the
    WHO service, so only the Celery applier saves it (bundle spec 2.4 Q5)."""
    return record["kind"] == "final" and project_mode(project) == "unmasked_doris"


def _station_doris_fields(actor: VaUsers, va_sid: str, final: dict) -> dict:
    """The DORIS fields of an online unmasked DORIS final for a station's
    certificate. The station holds no server process token and runs its own
    engine, so the server processes the certificate as ``POST
    /doris-clinical/process`` does and mints the proof that client would hold
    for the actor's allocation; ``submit_coder_final_cod`` then verifies and
    saves the server's results. The station's envelopes are not used.
    Raises ``CoderCodingError`` 422 ``invalid_doris``, 503
    ``who_unavailable`` / ``who_not_configured``. Calls the WHO service:
    the applier only."""
    from app.services.doris_process_proof import generate_process_proof
    from app.services.doris_processing import process_certificate
    from app.services.submission_payload_version_service import get_active_payload_version
    from app.services.who_icd_api import DEFAULT_ICD11_RELEASE, WhoIcdApiUnavailable

    image = coder_cod._who_image_digest()
    allocation = coder_cod.require_coding_session(actor, va_sid, coder_cod.derive_actiontype(va_sid))
    version = get_active_payload_version(va_sid)
    if version is None:
        return {}  # the final save refuses it final_blocked
    try:
        processed = process_certificate(
            {"schema_version": 1, "client_revision": 0, "certificate": final.get("doris_certificate")},
            release=DEFAULT_ICD11_RELEASE, who_image_digest=image)
    except (TypeError, ValueError) as exc:  # DorisCertificateError is a ValueError
        raise coder_cod.CoderCodingError(str(exc), 422, code="invalid_doris") from exc
    except WhoIcdApiUnavailable as exc:
        raise coder_cod.CoderCodingError("WHO ICD-11 service unavailable.", 503, code="who_unavailable") from exc
    token = generate_process_proof(
        certificate_digest=processed["certificate_digest"], result_digest=processed["result_digest"],
        va_sid=va_sid, role="coder", user_id=actor.user_id, allocation_id=allocation.va_allocation_id,
        payload_version_id=version.payload_version_id, icd_release=DEFAULT_ICD11_RELEASE, who_image_digest=image)
    # The plain {status, result} envelope: the final save's verify_process_submission rejects any other key and adds
    # the title and note fields (processing_extras) itself, as for a coder save.
    return {"doris_certificate": processed["certificate"], "doris_result": processed["doris"],
            "codedit_result": processed["codedit"], "doris_process_token": token,
            "doris_result_digest": processed["result_digest"]}


def _apply_coding(actor: VaUsers, va_sid: str, record: dict, project: VaProjectMaster) -> None:
    """The coder writes of ``POST /coding/initial|finalize|not-codeable`` in
    the project's mode (``_coding_refusal`` matched the record to it), after
    taking the actor's allocation. These services commit."""
    coder_workflow.allocate_pick_form(actor, va_sid, own_case=True)
    try:
        if record["kind"] == "not_codeable":
            part = record["not_codeable"]
            coder_cod.submit_coder_not_codeable(actor, va_sid, reason=part.get("reason"), other=part.get("other"))
            return
        final, mode = record["final"], project_mode(project)
        fields = {"conclusive_cod": final.get("conclusive_cod"), "remark": final.get("remark"),
                  "cod_search_id": final.get("cod_search_id"), "cod_chosen_code": final.get("cod_chosen_code"),
                  "cod_chosen_rank": final.get("cod_chosen_rank")}
        if is_masked(mode):
            initial = record["initial"]
            coder_cod.submit_coder_initial_cod(
                actor, va_sid, immediate_cod=initial.get("immediate_cod"),
                antecedent_cod=initial.get("antecedent_cod"), other_conditions=initial.get("other_conditions"))
        elif mode == "unmasked_simple":
            fields.update(immediate_cod=final.get("immediate_cod"), other_conditions=final.get("other_conditions"))
        else:
            fields.update(_station_doris_fields(actor, va_sid, final))
        try:
            coder_cod.submit_coder_final_cod(actor, va_sid, **fields)
        except coder_cod.CoderCodingError as exc:
            # A station cannot confirm an ICD-11 age conflict: refuse it
            # final_blocked, as before age warned (station contract, digitva-oh7j).
            if exc.code != "AGE_RESTRICTION_CONFIRMATION_REQUIRED":
                raise
            raise coder_cod.CoderCodingError(exc.message, 422, code="final_blocked") from exc
    except Exception:
        db.session.rollback()
        try:
            coder_workflow.release_own_coding_allocation(actor)
            db.session.commit()
        except coder_workflow.AllocationError:
            db.session.rollback()
        raise


_HANDLERS = {
    "death_registration": _registration,
    "consent": _consent,
    "death_correction": _death_correction,
    "interview_submission": _interview,
    "identifiers_set": _identifiers_set,
}


def _process(ingest: _Ingest) -> None:
    """Every record in spec order, each in its own savepoint; coding results
    last, outside savepoints (the coder services commit)."""
    lines = sorted(ingest.verified.container.lines, key=lambda ln: (_ORDER[ln.record_type], ln.index))
    ingest.lines_by_id = {}
    corrections = 0
    for line in lines:
        if line.client_id in ingest.lines_by_id:
            ingest.outcomes.setdefault(line.client_id, _Outcome(line, "rejected", "record_invalid"))
            continue
        ingest.lines_by_id[line.client_id] = line
    coding = []
    for line in lines:
        if ingest.outcomes.get(line.client_id) is not None or ingest.lines_by_id.get(line.client_id) is not line:
            continue  # applied with its registration, or a repeated client id
        if line.record_type in ("death_correction", "identifiers_set"):
            corrections += 1
            if corrections > MAX_CORRECTIONS:
                ingest.outcomes[line.client_id] = _Outcome(line, "rejected", "record_invalid")
                continue
        if line.record_type == "attachment_chunk":
            ingest.outcomes[line.client_id] = _Outcome(line, "rejected", "attachments_incomplete")
            continue
        if line.record_type == "coding_result":
            coding.append(line)
            continue
        ingest.outcomes[line.client_id] = _one(ingest, line)
    if coding and not ingest.dry_run:
        db.session.commit()
        intake_attachments.delete_committed_blobs()
    for line in coding:
        ingest.outcomes[line.client_id] = _one_coding(ingest, line)


def _one(ingest: _Ingest, line: _Line) -> _Outcome:
    named_consent = None
    queued_blobs = db.session().info.setdefault("web_intake_blobs_to_delete", [])
    queued_before = len(queued_blobs)
    try:
        with db.session.begin_nested():
            record, digest = ingest.open(line)
            if line.record_type == "death_registration":
                named_consent = ingest.lines_by_id.get(_uuid(record.get("consent_client_id")))
            with _device_projection(True):
                return _HANDLERS[line.record_type](ingest, line, record, digest)
    except RecordRejected as exc:
        rejection = _Outcome(line, "rejected", exc.code, exc.fields)
    except _SERVICE_ERRORS as exc:
        refused = _service_code(exc, line.record_type)
        rejection = _Outcome(line, "rejected", refused.code, refused.fields)
    except IntegrityError:
        rejection = _Outcome(line, "rejected", "conflict")
    except Exception as exc:  # noqa: BLE001 - one record must not fail the bundle
        # The savepoint is rolled back by ``begin_nested``. The class name
        # only: a message or traceback could carry the record's values.
        log.warning("bundle record failed | bundle=%s | client=%s | error=%s",
                    ingest.verified.container.bundle_id, line.client_id, type(exc).__name__)
        rejection = _Outcome(line, "rejected", "record_invalid")
    del queued_blobs[queued_before:]
    if named_consent is not None and named_consent.record_type == "consent":
        # Rolled back with the registration: the consent is rejected alike.
        ingest.outcomes.setdefault(named_consent.client_id, _Outcome(
            named_consent, "rejected", rejection.code if rejection.code.startswith("consent") else "depends_on_rejected",
            [str(line.client_id)] if not rejection.code.startswith("consent") else rejection.fields))
    return rejection


#: The coding fields a pending row keeps (spec 5.5; no envelope, no actor number).
_PENDING_RESULT_KEYS = ("client_draft_id", "coded_answers_sha256", "kind", "initial", "final", "not_codeable",
                        "coding_mode")


def _one_coding(ingest: _Ingest, line: _Line) -> _Outcome:
    draft = None
    try:
        with db.session.begin_nested():
            record, digest = ingest.open(line)
            with _device_projection(True):
                actor, draft, replay = _coding_target(ingest, line, record, digest)
        if replay is not None:
            return _Outcome(line, "duplicate", death_id=draft.death_id, unique_id=draft.unique_id)
        held = db.session.get(VaBundlePendingCoding, line.client_id)
        if held is not None:
            return _held_again(ingest, line, draft, held, digest)
        if ingest.dry_run:
            return _Outcome(line, "accepted", death_id=draft.death_id, unique_id=draft.unique_id)
        project = db.session.get(VaProjectMaster, ingest.verified.project_id)
        if _needs_doris_processing(project, record):
            return _hold(ingest, line, draft, actor, digest, record, "doris_pending")
        with _device_projection(True):
            _apply_coding(actor, draft.va_sid, record, project)
        ingest.station_audit(db.session.get(VaDeathRegister, draft.death_id), actor, line, record)
        ingest.applied(line, digest, draft.death_id)
        db.session.commit()
        return _Outcome(line, "accepted", death_id=draft.death_id, unique_id=draft.unique_id)
    except RecordRejected as exc:
        return _Outcome(line, "rejected", exc.code, exc.fields)
    except coder_workflow.AllocationError as exc:
        if exc.code in _STILL_PENDING:
            # Kept until the case is ready (or the coder's other case is done).
            db.session.rollback()
            return _hold(ingest, line, draft, actor, digest, record, exc.code)
        refused = _service_code(exc, line.record_type)
        return _Outcome(line, "rejected", refused.code, refused.fields)
    except _SERVICE_ERRORS as exc:
        refused = _service_code(exc, line.record_type)
        return _Outcome(line, "rejected", refused.code, refused.fields)
    except Exception as exc:  # noqa: BLE001 - one record must not fail the bundle
        # The earlier records are committed: a crash here must still end in a
        # processed report. The class name only, as in ``_one``.
        db.session.rollback()
        log.warning("bundle coding result failed | bundle=%s | client=%s | error=%s",
                    ingest.verified.container.bundle_id, line.client_id, type(exc).__name__)
        return _Outcome(line, "rejected", "not_available")


def _hold(ingest: _Ingest, line: _Line, draft, actor: VaUsers, digest: str, record: dict,
          code: str) -> _Outcome:
    """Keep a coding result for ``apply_pending_coding``, which applies it
    and rewrites this report (spec 5.5); *code* is the pending reason.
    Commits."""
    db.session.add(VaBundlePendingCoding(
        client_id=line.client_id, bundle_ids=[ingest.verified.container.bundle_id],
        project_id=ingest.verified.project_id, va_sid=draft.va_sid, death_id=draft.death_id,
        actor_user_id=actor.user_id, content_sha256=digest,
        result={k: record[k] for k in _PENDING_RESULT_KEYS if k in record}, status="pending", code=code,
    ))
    db.session.commit()
    return _Outcome(line, "pending", code, death_id=draft.death_id, unique_id=draft.unique_id)


def _held_again(ingest: _Ingest, line: _Line, draft, held: VaBundlePendingCoding, digest: str) -> _Outcome:
    """A coding result this server already holds as pending (a resend): the
    same content is still pending, and this report is rewritten with the
    first one when it resolves; other content is a ``conflict``; a held
    result already refused keeps its code."""
    ids = {"death_id": draft.death_id, "unique_id": draft.unique_id}
    if not hmac.compare_digest(held.content_sha256, digest):
        return _Outcome(line, "rejected", "conflict")
    if held.status == "rejected":
        return _Outcome(line, "rejected", held.code, **ids)
    if not ingest.dry_run and ingest.verified.container.bundle_id not in held.bundle_ids:
        held.bundle_ids = [*held.bundle_ids, ingest.verified.container.bundle_id]
        db.session.commit()
    return _Outcome(line, "pending", held.code or "not_ready", **ids)


# ---------------------------------------------------------------------------
# Pending coding results (spec 5.5)
# ---------------------------------------------------------------------------

#: Rows one applier run takes.
PENDING_BATCH = 50
#: Allocation refusals that leave a result pending: the case is not ready
#: yet, or the coder holds another case on the web for now.
_STILL_PENDING = frozenset({"not_ready", "allocation_exists"})
#: Coder save refusals that leave a held DORIS final pending: the WHO
#: service it is reprocessed with is down or not configured.
_WHO_DOWN = frozenset({"who_unavailable", "who_not_configured"})


def _resolve_in_reports(held: VaBundlePendingCoding, outcome: str, code: str | None,
                        fields: list[str] | None = None) -> None:
    """Rewrite every report that names *held* pending with its final outcome
    (the station keeps a pending record until a receipt names it). The
    stored receipt is cleared: the receipt route signs the new report when
    asked, since the worker that runs this holds no signing key."""
    client_id = str(held.client_id)
    for bundle_id in held.bundle_ids:
        row = db.session.get(VaBundleIngest, bundle_id)
        if row is None or row.report is None:
            continue
        report = json.loads(json.dumps(row.report))  # a new object: JSONB sees the change
        for entry in report["records"]:
            if entry["client_id"] == client_id and entry["outcome"] == "pending":
                entry["outcome"], entry["code"] = outcome, code
                entry.pop("fields", None)
                if fields:
                    entry["fields"] = _capped(fields)
        counts = dict.fromkeys(OUTCOMES, 0)
        for entry in report["records"]:
            counts[entry["outcome"]] = counts.get(entry["outcome"], 0) + 1
        report["counts"] = counts
        row.report, row.counts, row.receipt_text = report, counts, None


def _finish(held: VaBundlePendingCoding, outcome: str, code: str | None, fields=None) -> None:
    held.status = "applied" if outcome == "accepted" else "rejected"
    held.code, held.resolved_at = code, datetime.now(UTC)
    if outcome == "accepted":
        db.session.add(MapBundleRecord(
            client_id=held.client_id, bundle_id=held.bundle_ids[0], record_type="coding_result",
            content_sha256=held.content_sha256, death_id=held.death_id,
        ))
    _resolve_in_reports(held, outcome, code, fields)
    db.session.commit()


def _apply_one_pending(held: VaBundlePendingCoding) -> str:
    """Apply one held result whose case left the not-ready states; returns
    ``applied``, ``rejected`` or ``pending``. Commits. A Collect Plus
    standalone coding (contract section 17) is imported by its own service:
    no station, no DORIS reprocessing."""
    if offline_coding_import.is_offline_hold(held):
        return offline_coding_import.apply_held(held)
    actor = db.session.get(VaUsers, held.actor_user_id)
    record = dict(held.result)
    draft = db.session.scalar(
        sa.select(VaWebIntakeDraft).where(VaWebIntakeDraft.va_sid == held.va_sid,
                                          VaWebIntakeDraft.client_draft_id == _uuid(record.get("client_draft_id"))))
    project = db.session.get(VaProjectMaster, held.project_id)
    if actor is None or actor.user_status != VaStatuses.active or draft is None:
        _finish(held, "rejected", "not_available")
        return "rejected"
    first = db.session.get(VaBundleIngest, held.bundle_ids[0])
    refusal = (_station_refusal(db.session.get(AuthDevice, first.device_id), held.project_id)
               or _coding_refusal(project, record))
    if refusal is not None:
        _finish(held, "rejected", refusal)
        return "rejected"
    if not hmac.compare_digest(draft.answers_sha256 or "", record.get("coded_answers_sha256") or ""):
        _finish(held, "rejected", "coded_version_superseded")
        return "rejected"
    try:
        with _device_projection(True):
            _apply_coding(actor, held.va_sid, record, project)
    except coder_workflow.AllocationError as exc:
        db.session.rollback()
        if exc.code in _STILL_PENDING:
            return "pending"
        refused = _service_code(exc, "coding_result")
        _finish(held, "rejected", refused.code, refused.fields)
        return "rejected"
    except _SERVICE_ERRORS as exc:
        db.session.rollback()
        if getattr(exc, "code", None) in _WHO_DOWN:
            return "pending"
        refused = _service_code(exc, "coding_result")
        _finish(held, "rejected", refused.code, refused.fields)
        return "rejected"
    # The ingest's station audit row, from the first bundle that carried it.
    cases.record_action(db.session.get(VaDeathRegister, held.death_id), actor=actor, action="station_record",
                        changes=_station_changes(
                            "coder", actor.user_number, "coding_result", first.device_id,
                            first.station_config_id, first.bundle_id, held.client_id,
                            db.session.get(AuthStationCustodian, first.device_id)))
    _finish(held, "accepted", None)
    return "applied"


def apply_pending_coding(limit: int = PENDING_BATCH) -> dict:
    """Apply held coding results whose case is no longer waiting on SmartVA
    or attachments (spec 5.5), oldest first, at most *limit*: one indexed
    query picks them; each is applied as the ingest would (allocation for
    the actor, the coder writes; an ICD-11 DORIS final reprocessed with the
    WHO service first, bundle spec 2.4 Q5) and its reports and receipts
    rewritten. A case another coder holds, or one gone past coding, ends
    ``rejected`` with the allocation's code; a WHO outage leaves the row
    pending. Returns counts. The caller runs it under a lock (the Celery
    task); it commits per row."""
    from app.services.duplicate_exclusion import not_confirmed_duplicate_condition
    from app.services.workflow.definition import (
        WORKFLOW_ATTACHMENT_SYNC_PENDING,
        WORKFLOW_SMARTVA_PENDING,
    )

    counts = {"applied": 0, "rejected": 0, "pending": 0}
    ready = db.session.scalars(
        sa.select(VaBundlePendingCoding)
        .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaBundlePendingCoding.va_sid)
        .where(VaBundlePendingCoding.status == "pending",
               VaSubmissionWorkflow.workflow_state.notin_((WORKFLOW_SMARTVA_PENDING, WORKFLOW_ATTACHMENT_SYNC_PENDING)),
               not_confirmed_duplicate_condition(VaBundlePendingCoding.va_sid))
        .order_by(VaBundlePendingCoding.created_at)
        .limit(limit)
    ).all()
    for held in ready:
        try:
            counts[_apply_one_pending(held)] += 1
        except Exception as exc:  # noqa: BLE001 - one row must not stop the others
            db.session.rollback()
            log.warning("pending bundle coding failed | client=%s | error=%s", held.client_id, type(exc).__name__)
            counts["pending"] += 1
        finally:
            pii_crypto.clear_dek_cache()
    if any(counts.values()):
        log.info("pending bundle coding | applied=%d | rejected=%d | pending=%d",
                 counts["applied"], counts["rejected"], counts["pending"])
    return counts


# ---------------------------------------------------------------------------
# Report and receipt (spec 5.6)
# ---------------------------------------------------------------------------


def _missing_seq(device_id: uuid.UUID, current: int) -> list[int]:
    """``bundle_seq`` gaps of this station below the newest seen, at most
    ``MISSING_SEQ_MAX``: one indexed anti-join over a bounded series."""
    max_seq, seen_count = db.session.execute(
        sa.select(
            sa.func.coalesce(sa.func.max(VaBundleIngest.bundle_seq), 0),
            sa.func.count(VaBundleIngest.bundle_id),
        ).where(VaBundleIngest.device_id == device_id)
    ).one()
    newest = min(max(current, int(max_seq)), int(seen_count) + MISSING_SEQ_MAX + 1)
    if newest <= 1:
        return []
    rows = db.session.execute(
        sa.text(
            "SELECT s FROM generate_series(1, :newest) AS s WHERE s <> :current AND NOT EXISTS ("
            " SELECT 1 FROM va_bundle_ingests b WHERE b.device_id = :device AND b.bundle_seq = s)"
            " ORDER BY s LIMIT :cap"
        ),
        {"newest": newest, "current": current, "device": device_id, "cap": MISSING_SEQ_MAX},
    ).scalars()
    return list(rows)


def _report(ingest: _Ingest, ordered: list[_Line]) -> dict:
    verified = ingest.verified
    entries = [ingest.outcomes[line.client_id].as_report(ingest.dry_run)
               for line in ordered if line.client_id in ingest.outcomes]
    counts = dict.fromkeys(OUTCOMES, 0)
    if ingest.dry_run:
        counts["not_processed"] = 0
    for entry in entries:
        counts[entry["outcome"]] += 1
    return {
        "bundle_id": str(verified.container.bundle_id),
        "device_id": str(verified.device.device_id),
        "kem_key_id": verified.container.manifest["kem_key_id"],
        "status": "validated" if ingest.dry_run else "processed",
        "counts": counts,
        "missing_seq": _missing_seq(verified.device.device_id, verified.container.manifest["bundle_seq"]),
        "records": entries,
        "purge": sorted(station_config.purge_client_ids(verified.device)),
    }


def receipt_text(row: VaBundleIngest) -> str:
    """The signed receipt of a processed ingest: the stored one, or (after a
    held coding result resolved and cleared it) the current report signed
    now. Not stored here, so a GET writes nothing; Ed25519 is deterministic,
    so the bytes are the same each time. 503 ``StationConfigError`` without
    the server key."""
    return row.receipt_text or sign_receipt(row.report)


def sign_receipt(report: dict) -> str:
    """The two-line receipt: *report* as canonical JSON, signed with the
    server key over ``b"digitva-receipt-v1\\x00" || line1``."""
    return station_config.sign_two_line(report, station_config.server_signing_key(), RECEIPT_SIG_DOMAIN)


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def ingest_bundle(raw: bytes, *, uploader: VaUsers, bearer_device_id: uuid.UUID | None,
                  dry_run: bool) -> tuple[int, dict]:
    """Ingest (or, *dry_run*, validate) one bundle; returns ``(status,
    report)``: 201 new or resumed, 200 a replay of a stored bundle or a
    validation. Raises ``BundleRefusal`` for a whole-bundle refusal, before
    anything is written. Only the manifest and signature lines are parsed
    before the uploader check; the record lines only after the signature,
    body hash, replay and age. A real ingest runs under ``_ingest_lock`` and
    commits before releasing it (409 ``conflict`` while another request
    holds it); a ``processing`` row nobody holds is an interrupted ingest,
    resumed (each record is idempotent by client id, spec 4). A dry run
    leaves every write to the caller's rollback."""
    received_at = datetime.now(UTC)
    container = _parse_head(raw)
    _authorize_uploader(container, uploader, bearer_device_id)
    verified = _verify(container, received_at)
    stored = _stored(container, verified.manifest_sha256)
    if stored is not None and stored.status == "processed":
        return 200, stored.report
    _check_age_and_key(verified)
    _parse_records(container)
    if dry_run:
        return _ingest(verified, uploader, bearer_device_id, dry_run=True, resuming=False)
    with _ingest_lock(container.bundle_id):
        stored = _stored(container, verified.manifest_sha256)
        if stored is not None and stored.status == "processed":
            return 200, stored.report
        status, report = _ingest(verified, uploader, bearer_device_id, dry_run=False, resuming=stored is not None)
        db.session.commit()
        intake_attachments.delete_committed_blobs()
    return status, report


# ponytail: one request applies every record (MAX_RECORDS, each through the
# HTTPS services); the spec has no partial report, so there is no per-request
# budget. A worker killed midway is resumed by a resend; move the ingest to a
# background task (spec 5.6 runtime note) if bundles outgrow a request.
def _ingest(verified: _Verified, uploader: VaUsers, bearer_device_id: uuid.UUID | None, *,
            dry_run: bool, resuming: bool) -> tuple[int, dict]:
    """Unwrap the DEK, store the ``processing`` row (unless *resuming* one),
    apply the records and the report; ``ingest_bundle``'s second half."""
    container = verified.container
    if not dry_run:
        if not resuming:  # a resumed ingest's own row would count against it
            _check_device_rate(verified)
        station_config.server_signing_key()  # 503 before any record is applied
    try:
        dek = pii_crypto.unwrap_dek(container.manifest["dek_wrapped"], row_ref=f"bundle {container.bundle_id}")
    except pii_crypto.PiiCryptoError:
        raise BundleRefusal("The bundle key could not be opened with the server keys.", "bundle_key_unknown") from None
    if not dry_run and not resuming:
        row = VaBundleIngest(
            bundle_id=container.bundle_id, device_id=verified.device.device_id, project_id=verified.project_id,
            bundle_seq=container.manifest["bundle_seq"], manifest_sha256=verified.manifest_sha256,
            station_config_id=verified.config.config_id, kem_key_id=container.manifest["kem_key_id"],
            uploader_user_id=uploader.user_id, channel="device" if bearer_device_id else "browser",
            created_at=container.created_at, received_at=verified.received_at, status="processing",
        )
        try:
            with db.session.begin_nested():
                db.session.add(row)
        except IntegrityError:  # the same bundle_id raced in (not possible under the lock)
            raise BundleRefusal("This bundle is being ingested; ask for its report shortly.", "conflict", 409) from None
    ingest = _Ingest(verified=verified, dek=dek, dry_run=dry_run)
    # A dry run is rolled back: no SmartVA marker or run for a case it touched.
    suppress = smartva_service.queue_suppressed() if dry_run else contextlib.nullcontext()
    try:
        with suppress:
            ingest.load_actors()
            _process(ingest)
    finally:
        del dek
        ingest.dek = b""
        pii_crypto.clear_dek_cache()
    ordered = sorted(container.lines, key=lambda ln: (_ORDER[ln.record_type], ln.index))
    report = _report(ingest, ordered)
    if dry_run:
        return 200, report
    row = db.session.get(VaBundleIngest, container.bundle_id)
    row.status, row.report, row.counts = "processed", report, report["counts"]
    row.receipt_text = sign_receipt(report)
    log.info("bundle ingested | bundle=%s | device=%s | resumed=%s | counts=%s", container.bundle_id,
             verified.device.device_id, resuming, json.dumps(report["counts"], sort_keys=True))
    return 201, report


def record_refusal(refusal: BundleRefusal, raw_head: bytes, uploader: VaUsers | None) -> None:
    """One ``auth_security_events`` row per refused bundle (spec 5.6): the
    code and the claimed ids when the manifest parsed, nothing else."""
    detail = {"code": refusal.code}
    try:
        manifest = json.loads(raw_head.split(b"\n", 1)[0].decode("utf-8"))
        for key in ("bundle_id", "device_id"):
            if _uuid(manifest.get(key)) is not None:
                detail[key] = manifest[key]
    except (ValueError, UnicodeDecodeError, AttributeError, RecursionError):
        pass
    record_security_event(user_id=None, actor_user_id=uploader.user_id if uploader else None,
                          event_type="bundle_refused", detail=detail)
    log.info("bundle refused | code=%s | bundle=%s", refusal.code, detail.get("bundle_id"))


def stored_ingest(bundle_id, *, user: VaUsers, bearer_device_id: uuid.UUID | None) -> VaBundleIngest:
    """The processed ingest *bundle_id* for its station's bearer or a
    browser uploader of its project; 404 ``BundleRefusal`` otherwise (alike
    whether it exists)."""
    not_found = BundleRefusal("Bundle not found.", "not_found", 404)
    bundle_uuid = _uuid(bundle_id)
    row = db.session.get(VaBundleIngest, bundle_uuid) if bundle_uuid else None
    if row is None or row.status != "processed":
        raise not_found
    allowed = (row.device_id == bearer_device_id if bearer_device_id is not None
               else may_upload_for(user, row.project_id))
    if not allowed:
        raise not_found
    return row
