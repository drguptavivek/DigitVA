"""app/services/payload_pii_split.py: the split and the one version fingerprint.

Policy: docs/policy/pii-encryption-at-rest.md, "Fingerprint and change
detection". No database: the keyring comes from a throwaway Flask app.
Payloads are synthetic, shaped like the dev ODK payloads (top-level keys,
strings, a numeric ``Id10010a``, nulls, the ``OdkReviewComments`` list).
"""
import copy
import hashlib
import hmac
import json
import random
from types import SimpleNamespace

from app.services import payload_pii_split as split_mod
from app.services.pii_field_registry import PII_FIELDS
from app.services.submission_payload_version_service import normalize_payload_for_fingerprint
from app.utils import pii_crypto as pc
from tests.test_pii_crypto import KeyringCase

SEALED = frozenset(PII_FIELDS)
BLIND = "cd" * 32


def odk_payload(**overrides):
    payload = {
        "KEY": "uuid:4f2c0d1e-0000-4000-8000-000000000001",
        "SubmissionDate": "2026-09-30T10:11:12.000Z",
        "instanceID": "uuid:4f2c0d1e-0000-4000-8000-000000000001",
        "FormVersion": "2026091501",
        "DeviceID": "collect:abc123",
        "SubmitterID": "17",
        "AttachmentsExpected": "2",
        "AttachmentsPresent": "2",
        "OdkReviewComments": [{"body": "checked", "createdAt": "2026-10-01"}],
        "ageInYears": "64",
        "Id10007": "Ramesh Kumar",
        "Id10010": "Interviewer One",
        "Id10010a": 34,
        "Id10010b": "female",
        "Id10010c": "INT-0042",
        "Id10017": "Sita",
        "Id10018": None,
        "Id10019": "female",
        "Id10023": "2026-08-01",
        "Id10055": None,
        "Id10057": "Ward 4, Rampur",
        "Id10061": None,
        "Id10062": None,
        "Id10070": "REG/2026/77",
        "Id10071": "2026-08-03",
        "Id10072": "Rampur PHC",
        "Id10073": "1234 5678 9012",
        "Id10120": "3",
        "Id10476": "She had fever for three days.",
        "unique_id": "SITE01-2026-0001",
    }
    payload.update(overrides)
    return payload


class SplitCase(KeyringCase):
    def setUp(self):
        super().setUp()
        self.use_pair("k1", blind=BLIND)


class SplitJoinTests(SplitCase):
    def test_split_moves_the_sealed_set_and_join_restores_it(self):
        raw = odk_payload()
        before = copy.deepcopy(raw)
        split = split_mod.split_payload(raw, SEALED)
        self.assertEqual(raw, before)  # input untouched
        self.assertIn("Id10017", split.pii)
        self.assertEqual(split.pii["Id10073"], "XXXXXXXXX012")
        self.assertIn("Id10018", split.pii)  # a null answer travels too
        self.assertFalse(SEALED & set(split.stripped))
        self.assertEqual(split.stripped["Id10476"], raw["Id10476"])
        expected = dict(raw, Id10073="XXXXXXXXX012")
        self.assertEqual(split_mod.join_payload(split.stripped, split.pii), expected)
        # No digit of the national ID stays in the stripped payload.
        dumped = json.dumps(split.stripped)
        for text in ("XXXXXXXXX012", "9012", "Id10073"):
            self.assertNotIn(text, dumped)

    def test_form_flagged_field_is_sealed_too(self):
        split = split_mod.split_payload(odk_payload(), SEALED | {"Id10120"})
        self.assertEqual(split.pii["Id10120"], "3")
        self.assertNotIn("Id10120", split.stripped)

    def test_free_text_national_id_is_redacted_and_flagged(self):
        split = split_mod.split_payload(odk_payload(Id10476="Aadhaar 1234 5678 9012 seen"), SEALED)
        self.assertIn("Id10476", split.review_flags)
        self.assertNotIn("5678", split.stripped["Id10476"])

    def test_empty_and_missing_payloads(self):
        for payload in (None, {}):
            with self.subTest(payload=payload):
                split = split_mod.split_payload(payload, SEALED)
                self.assertEqual((split.stripped, split.pii, split.review_flags), ({}, {}, []))
        self.assertEqual(split_mod.join_payload(None, None), {})


class FingerprintTests(SplitCase):
    def fp(self, payload, sealed=SEALED):
        return split_mod.fingerprint_of(payload, sealed)

    def test_stored_split_form_has_the_same_fingerprint_as_the_full_payload(self):
        for name, raw in {
            "full": odk_payload(),
            "pii keys absent": {k: v for k, v in odk_payload().items() if k not in SEALED},
            "pii keys null": dict(odk_payload(), **{k: None for k in SEALED}),
            "pii keys blank": dict(odk_payload(), **{k: "  " for k in SEALED}),
            "abha present": odk_payload(abha_number="12-3456-7890-1234", abha_address="sita@abdm"),
        }.items():
            with self.subTest(name):
                split = split_mod.split_payload(raw, SEALED)
                side_row = SimpleNamespace(pii_digest=split_mod.pii_digest(split.pii), sealed_ids=sorted(SEALED))
                expected = self.fp(raw)
                # Stripped stored payload plus the side row's digest (no decrypt).
                self.assertEqual(split_mod.stored_fingerprint(split.stripped, side_row, SEALED), expected)
                # Not yet stripped: stale PII in payload_data is ignored beside the side row.
                self.assertEqual(split_mod.stored_fingerprint(raw, side_row, SEALED), expected)
                # Not yet backfilled: no side row, the stored payload is split here.
                self.assertEqual(split_mod.stored_fingerprint(raw, None, SEALED), expected)
                version = SimpleNamespace(payload_data=split.stripped)
                self.assertTrue(split_mod.same_content(raw, version, side_row, SEALED))
                # The side row's own set decides, not the registry passed in.
                self.assertTrue(split_mod.same_content(raw, version, side_row, SEALED | {"Id10019"}))

    def test_absent_null_blank_whitespace_and_na_pii_compare_equal(self):
        for key in ("Id10017", "Id10073", "abha_number", "Id10010a"):
            variants = {"absent": None, "null": None, "empty": "", "whitespace": "   ", "na": "N/A"}
            prints = set()
            for name, value in variants.items():
                raw = odk_payload()
                if name == "absent":
                    raw.pop(key, None)
                else:
                    raw[key] = value
                prints.add(self.fp(raw))
            with self.subTest(key):
                self.assertEqual(len(prints), 1)

    def test_key_order_does_not_matter(self):
        raw = odk_payload()
        items = list(raw.items())
        random.Random(7).shuffle(items)
        self.assertEqual(self.fp(dict(items)), self.fp(raw))

    def test_national_id_full_reduced_and_last_three(self):
        base = self.fp(odk_payload())
        self.assertEqual(self.fp(odk_payload(Id10073="XXXXXXXXX012")), base)
        self.assertEqual(self.fp(odk_payload(Id10073="123456789012")), base)
        # OD1, accepted: another number with the same last 3 is not a change.
        self.assertEqual(self.fp(odk_payload(Id10073="9999 8888 7012")), base)
        self.assertNotEqual(self.fp(odk_payload(Id10073="1234 5678 9013")), base)
        self.assertNotEqual(self.fp(odk_payload(Id10073=None)), base)

    def test_pii_and_other_changes_are_detected(self):
        base = self.fp(odk_payload())
        self.assertNotEqual(self.fp(odk_payload(Id10017="Gita")), base)
        self.assertNotEqual(self.fp(odk_payload(Id10010a=35)), base)
        self.assertNotEqual(self.fp(odk_payload(Id10120="4")), base)
        self.assertEqual(self.fp(odk_payload(Id10010a="34")), base)  # number vs text, as today
        self.assertEqual(self.fp(odk_payload(Id10017=" Sita ")), base)
        self.assertEqual(self.fp(odk_payload(FormVersion="2026100101", ageInYears="65")), base)  # volatile

    def test_digest_and_algorithm_are_pinned(self):
        split = split_mod.split_payload(odk_payload(), SEALED)
        normalised = {
            "Id10007": "Ramesh Kumar", "Id10010": "Interviewer One", "Id10010a": "34",
            "Id10010b": "female", "Id10010c": "INT-0042", "Id10017": "Sita",
            "Id10057": "Ward 4, Rampur", "Id10070": "REG/2026/77", "Id10071": "2026-08-03",
            "Id10072": "Rampur PHC", "Id10073": {"last3": "012", "present": True},
        }
        subkey = pc.subkey("payload-fp")
        digest = hmac.new(
            subkey, json.dumps(normalised, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256
        ).hexdigest()
        self.assertEqual(split.pii_digest, digest)
        body = {"payload": normalize_payload_for_fingerprint(split.stripped), "pii": digest}
        self.assertEqual(
            split.fingerprint,
            hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        )

    def test_digest_is_keyed(self):
        before = self.fp(odk_payload())
        self.use_pair("k1", blind="ef" * 32)
        self.assertNotEqual(self.fp(odk_payload()), before)
