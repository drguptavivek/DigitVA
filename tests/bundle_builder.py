"""A test writer of offline bundles (.dvb), mirroring ``build_bundle`` in
desktop/crates/digitva-bundle/src/lib.rs (bundle spec 2-3): JCS lines, one
AES-256-GCM DEK per bundle wrapped to the server KEM public key, a nonce
and ``record_aad("digitva_bundle", "<type>/<client_id>", bundle_id bytes)``
per record, an Ed25519 signature over ``b"digitva-bundle-v1\\x00" ||
manifest``. Records are written in the spec's type order. Test use only.
"""
from __future__ import annotations

import base64
import hashlib
import os
import uuid
from datetime import UTC, datetime

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.services.bundle_ingest_service import AAD_TABLE, RECORD_ORDER
from app.services.station_config_service import canonical_json
from app.utils import pii_crypto


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def record(record_type: str, *, project_id: str, actor_user_id: int, acting_role: str,
           client_id: uuid.UUID | None = None, recorded_at: str = "2026-10-20T10:00:00+05:30", **body) -> dict:
    """One record's plaintext object (spec 2.4 envelope plus *body*)."""
    return {
        "record_type": record_type, "client_id": str(client_id or uuid.uuid4()), "project_id": project_id,
        "actor_user_id": actor_user_id, "acting_role": acting_role, "recorded_at": recorded_at, **body,
    }


def build(records: list[dict], *, signing_key, device_id, station_config_id, project_id: str,
          bundle_id: uuid.UUID | None = None, bundle_seq: int = 1, created_at: datetime | None = None,
          public_key=None, record_bytes=None, manifest_overrides: dict | None = None,
          aad_bundle_id: uuid.UUID | None = None) -> bytes:
    """The bundle bytes of *records* (plaintext dicts). *record_bytes*
    (``{client_id: bytes}``) replaces a record's plaintext with raw bytes;
    *manifest_overrides* changes manifest fields before signing;
    *aad_bundle_id* seals the records for another bundle (a moved record)."""
    bundle_id = bundle_id or uuid.uuid4()
    created = (created_at or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")
    public = public_key or pii_crypto.current_public_key()
    dek = os.urandom(32)
    ordered = sorted(records, key=lambda r: RECORD_ORDER.index(r["record_type"]))
    body = b""
    counts: dict[str, int] = {}
    versions = set()
    for rec in ordered:
        counts[rec["record_type"]] = counts.get(rec["record_type"], 0) + 1
        if rec["record_type"] == "interview_submission":
            versions.add(rec["draft"]["instrumentVersion"])
        plaintext = (record_bytes or {}).get(rec["client_id"]) or canonical_json(rec)
        aad = pii_crypto.record_aad(AAD_TABLE, f"{rec['record_type']}/{rec['client_id']}",
                                 (aad_bundle_id or bundle_id).bytes)
        nonce = os.urandom(12)
        ct = pii_crypto.DATA_PREFIX + b64u(nonce + AESGCM(dek).encrypt(nonce, plaintext, aad))
        body += canonical_json({"client_id": rec["client_id"], "ct": ct, "record_type": rec["record_type"]}) + b"\n"
    manifest = {
        "app_version": "0.1.0", "body_sha256": hashlib.sha256(body).hexdigest(), "bundle_format_version": 1,
        "bundle_id": str(bundle_id), "bundle_seq": bundle_seq, "crate_version": "0.1.0", "created_at": created,
        "dek_wrapped": pii_crypto.wrap_dek(dek, public), "device_id": str(device_id),
        "instrument_versions": sorted(versions), "kem_key_id": public.key_id, "project_ids": [project_id],
        "record_counts": counts, "signing_key_id": key_id(signing_key), "station_config_id": str(station_config_id),
        **(manifest_overrides or {}),
    }
    line1 = canonical_json(manifest)
    sig = signing_key.sign(b"digitva-bundle-v1\x00" + line1)
    line2 = canonical_json({"alg": "ed25519", "sig": b64u(sig), "signing_key_id": manifest["signing_key_id"]})
    return line1 + b"\n" + line2 + b"\n" + body


def public_bytes(signing_key) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return signing_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def key_id(signing_key) -> str:
    return hashlib.sha256(public_bytes(signing_key)).digest()[:8].hex()
