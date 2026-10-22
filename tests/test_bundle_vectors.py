"""The committed bundle conformance vectors (digitva-gb8w.6): see
``tests/bundle_vectors.py``. This module checks, without a database, that
every file under ``tests/fixtures/bundles/vectors/`` is what ``expected.json``
says (signature, body hash, record types, station identity), that
``expected.json`` is the scenario table, and that a record line over the limit
is refused 413. The per-record ingest reports are asserted against the real
ingest in ``tests/routes/test_bundle_ingest_api.py``; the Rust crate checks the
same container facts in ``desktop/crates/digitva-bundle/tests/bundle_vectors.rs``.

Rewrite the vectors after a deliberate change with
``DIGITVA_WRITE_BUNDLE_VECTORS=1 python -m pytest tests/test_bundle_vectors.py``.
"""
import json
import os
import unittest

from app.services import bundle_ingest_service as service
from app.services.device_signing_service import verify_bundle_signature
from tests import bundle_vectors as vectors
from tests.test_bundle_fixture import _open_all

EXPECTED = vectors.VECTORS / "expected.json"


class BundleVectorTests(unittest.TestCase):

    @unittest.skipUnless(os.environ.get("DIGITVA_WRITE_BUNDLE_VECTORS"), "regenerates the committed vectors")
    def test_write_vectors(self):
        vectors.write()

    def test_expected_json_is_the_scenario_table(self):
        self.assertEqual(json.loads(EXPECTED.read_text(encoding="utf-8")),
                         json.loads(json.dumps(vectors.expected_document())),
                         "regenerate: DIGITVA_WRITE_BUNDLE_VECTORS=1 pytest tests/test_bundle_vectors.py")

    def test_every_vector_is_what_expected_json_says(self):
        expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
        # The key a manifest's signing_key_id names; the unknown-key vector is signed by its own.
        publics = {vectors.key_id(k): k.public_key().public_bytes_raw() for k in (vectors.STATION_KEY, vectors.OTHER_KEY)}
        checked = 0
        for name, entry in expected.items():
            for file, want in zip(entry["files"] or [], entry["container"] or []):
                with self.subTest(vector=file):
                    container = service.parse_container((vectors.VECTORS / file).read_bytes())
                    manifest = container.manifest
                    self.assertEqual(verify_bundle_signature(
                        publics[manifest["signing_key_id"]], container.manifest_line, container.signature),
                        want["signature_ok"])
                    self.assertEqual(container.body_sha256 == manifest["body_sha256"], want["body_hash_ok"])
                    self.assertEqual([ln.record_type for ln in container.lines], want["record_types"])
                    self.assertEqual((manifest["device_id"], manifest["station_config_id"], manifest["project_ids"]),
                                     (str(vectors.DEVICE_ID), str(vectors.CONFIG_ID), ["TST001"]))
                    checked += 1
        self.assertGreaterEqual(checked, 20)

    def test_the_valid_vector_opens_and_holds_no_informant_data_without_consent(self):
        container = service.parse_container((vectors.VECTORS / "valid.dvb").read_bytes())
        records = _open_all(container)
        registration = next(r for r in records.values() if r["record_type"] == "death_registration")
        consent = next(r for r in records.values() if r["record_type"] == "consent")
        self.assertEqual(registration["consent_client_id"], consent["client_id"])
        self.assertEqual(consent["decision"], "granted")

    def test_a_record_line_over_the_limit_is_refused_413(self):
        raw = vectors.oversize(vectors.FixedKit("oversize"))
        with self.assertRaises(service.BundleRefusal) as caught:
            service.parse_container(raw)
        self.assertEqual((caught.exception.code, caught.exception.status), ("payload_too_large", 413))
