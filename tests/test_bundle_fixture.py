"""Bundle conformance fixtures (digitva-gb8w.2; the start of gb8w.6's vectors).

``tests/fixtures/bundles/sample_bundle.dvb`` is written by the Rust writer
(``desktop/crates/digitva-bundle/tests/bundle_fixture.rs``,
``build_bundle_deterministic``) from the signed station config fixture, the
published test KEM key ``tv1`` (``tests/fixtures/pii_envelope_vectors.json``)
and the test station key seed ``0x52 * 32``. This test opens it with the
server's ingest parser: container, signature, body hash, DEK unwrap and
every record's envelope and keys. ``sample_receipt.dvr`` is the receipt the
server signs for it with the station config test key; the Rust test checks
it with ``verify_and_plan_receipt``. Rewrite the receipt after a deliberate
change with ``python -m tests.test_bundle_fixture --write``.
"""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from flask import current_app

from app.services import bundle_ingest_service as service
from app.services import station_config_service
from app.services.device_signing_service import compute_signing_key_id, verify_bundle_signature
from app.utils import pii_crypto

FIXTURES = Path(__file__).parent / "fixtures"
BUNDLE = FIXTURES / "bundles" / "sample_bundle.dvb"
RECEIPT = FIXTURES / "bundles" / "sample_receipt.dvr"
STATION_KEY = Ed25519PrivateKey.from_private_bytes(b"\x52" * 32)


def _tv1() -> pii_crypto.KemPrivateKey:
    vectors = json.loads((FIXTURES / "pii_envelope_vectors.json").read_text(encoding="utf-8"))
    entry = next(k for k in vectors["deterministic"]["test_keys"]["kem_keys"] if k["key_id"] == "tv1")
    return pii_crypto.parse_private_key(entry["private_key_file_text"])


def _report(container) -> dict:
    """The report the server gives the sample when every record is applied."""
    records = []
    for line in sorted(container.lines, key=lambda ln: (service.RECORD_ORDER.index(ln.record_type), ln.index)):
        records.append({
            "client_id": str(line.client_id), "record_type": line.record_type, "outcome": "accepted",
            "code": None, "received_sha256": None, "death_id": "d0000000-0000-4000-8000-000000000001",
            "unique_id": "TS01-000001",
        })
    return {
        "bundle_id": str(container.bundle_id), "device_id": str(container.device_id),
        "kem_key_id": container.manifest["kem_key_id"], "status": "processed",
        "counts": {"accepted": len(records), "duplicate": 0, "superseded": 0, "pending": 0, "rejected": 0},
        "missing_seq": [], "records": records, "purge": [],
    }


def generate_receipt() -> str:
    container = service.parse_container(BUNDLE.read_bytes())
    report = _report(container)
    interview = next(r for r in report["records"] if r["record_type"] == "interview_submission")
    plain = _open_all(container)
    interview["received_sha256"] = plain[interview["client_id"]]["answers_sha256"]
    key = station_config_service.parse_signing_key(
        (FIXTURES / "station_config" / "test_server_signing_key").read_text(encoding="ascii"))
    return station_config_service.sign_two_line(report, key, service.RECEIPT_SIG_DOMAIN)


def _open_all(container) -> dict:
    """Every record of *container* opened by the ingest's own ``open``."""
    keyring = pii_crypto.Keyring(pii_crypto.current_public_key(), {"tv1": _tv1()}, b"\x00" * 32)
    with mock.patch.dict(current_app.extensions, {"pii_keyring": keyring}):
        dek = pii_crypto.unwrap_dek(container.manifest["dek_wrapped"], row_ref="fixture")
    ingest = service._Ingest(verified=SimpleNamespace(container=container, project_id="TST001"),
                             dek=dek, dry_run=True)
    return {str(line.client_id): ingest.open(line)[0] for line in container.lines}


class BundleFixtureTests(unittest.TestCase):

    def test_the_rust_bundle_parses_verifies_and_opens(self):
        raw = BUNDLE.read_bytes()
        container = service.parse_container(raw)
        self.assertEqual(container.manifest["signing_key_id"],
                         compute_signing_key_id(STATION_KEY.public_key().public_bytes_raw()))
        self.assertTrue(verify_bundle_signature(
            STATION_KEY.public_key().public_bytes_raw(), container.manifest_line, container.signature))
        self.assertEqual(container.body_sha256, container.manifest["body_sha256"])
        self.assertEqual([ln.record_type for ln in container.lines],
                         ["death_registration", "consent", "interview_submission"])
        records = _open_all(container)
        registration, consent, interview = (records[str(ln.client_id)] for ln in container.lines)
        self.assertEqual(registration["consent_client_id"], consent["client_id"])
        self.assertEqual(consent["death_ref"], {"client_death_id": registration["client_id"]})
        self.assertIsNone(consent["client_draft_id"])
        self.assertEqual(interview["draft"]["deviceClockAt"], container.manifest["created_at"])
        self.assertEqual(interview["actor_user_id"], 7)

    def test_a_flipped_record_byte_fails_the_body_hash(self):
        raw = bytearray(BUNDLE.read_bytes())
        at = raw.rindex(b'"ct":"v1:aes256gcm:') + 40  # inside the last record's ciphertext
        raw[at] = ord("A") if raw[at] != ord("A") else ord("B")
        container = service.parse_container(bytes(raw))
        self.assertNotEqual(container.body_sha256, container.manifest["body_sha256"])

    def test_the_receipt_regenerates_byte_for_byte(self):
        self.assertEqual(RECEIPT.read_bytes(), generate_receipt().encode("utf-8"))


if __name__ == "__main__" and "--write" in sys.argv:  # pragma: no cover
    from config import TestConfig
    from tests.base import create_app_without_celery_takeover

    with create_app_without_celery_takeover(TestConfig).app_context():
        RECEIPT.write_text(generate_receipt(), encoding="utf-8")
