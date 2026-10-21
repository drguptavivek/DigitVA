"""app/services/payload_pii_accessor.py against map_payload_version_pii.

Policy: docs/policy/pii-encryption-at-rest.md, "Payload design". Since
part II-A the writers reach the accessor through ``write_payload_version``
(behind PAYLOAD_PII_SPLIT_ENABLED) and ``flask pii split-payloads``; the
readers do not yet (part II-B). These tests drive it directly on real
payload version rows.
"""
from datetime import UTC, datetime
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import MapPayloadVersionPii, VaSubmissionPayloadVersion, VaSubmissions
from app.services import payload_pii_accessor as accessor
from app.services import payload_pii_split as split_mod
from app.services.pii_field_registry import PII_FIELDS
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.utils import pii_crypto as pc
from tests.base import BaseTestCase
from tests.services.test_national_id_sync_rerun import create_form
from tests.services.test_payload_pii_split import odk_payload

SEALED = frozenset(PII_FIELDS)


class PayloadPiiAccessorTests(BaseTestCase):
    FORM_ID = "PPA01PA0101"
    PROJECT_ID = "PPA01"
    SITE_ID = "PA01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_form(cls.PROJECT_ID, cls.SITE_ID, cls.FORM_ID)

    def _version(self, sid: str, payload: dict) -> VaSubmissionPayloadVersion:
        now = datetime.now(UTC)
        sub = VaSubmissions(
            va_sid=sid, va_form_id=self.FORM_ID, va_submission_date=now,
            va_odk_updatedat=now.replace(tzinfo=None), va_data_collector="Collector",
            va_odk_reviewstate=None, va_consent="yes", va_narration_language="English",
            va_deceased_age=64, va_deceased_gender="female", va_uniqueid_masked="masked",
            va_summary=[], va_catcount={}, va_category_list=[],
        )
        db.session.add(sub)
        db.session.flush()
        version = ensure_active_payload_version(sub, payload_data=payload, created_by_role="vasystem")
        db.session.flush()
        return version

    def _rows(self, version) -> int:
        return db.session.scalar(
            sa.select(sa.func.count()).select_from(MapPayloadVersionPii)
            .where(MapPayloadVersionPii.payload_version_id == version.payload_version_id)
        )

    def test_no_side_row_reads_as_no_pii(self):
        version = self._version("ppa-none", odk_payload())
        self.assertEqual(self._rows(version), 0)
        self.assertEqual(accessor.get_pii(version), {})
        self.assertEqual(accessor.get_full_payload(version), version.payload_data)

    def test_put_then_get_round_trip(self):
        version = self._version("ppa-put", odk_payload())
        pii = {
            "Id10017": "Sita", "Id10018": None, "Id10010a": 34,
            "Id10073": "1234 5678 9012",  # a full number given directly is reduced here
            "abha_number": "12-3456-7890-1234", "abha_address": " Sita@ABDM ",
        }
        row = accessor.put_pii(version, pii, ["Id10070"], sealed_ids=SEALED)
        self.assertEqual(self._rows(version), 1)
        self.assertEqual(row.va_sid, version.va_sid)
        self.assertEqual(set(row.sealed), set(pii))
        stored = str(row.sealed) + row.dek_wrapped
        for plain in ("Sita", "9012", "ABDM", "1234"):
            self.assertNotIn(plain, stored)
        self.assertEqual(row.key_id, pc.current_key_id())
        self.assertEqual(row.blind_key_id, pc.blind_key_id())
        self.assertEqual(row.review_flags, ["Id10070"])
        self.assertEqual(row.abha_number_bidx, pc.class_index("abha_number", "12345678901234"))
        self.assertEqual(row.abha_address_bidx, pc.class_index("abha_address", "sita@abdm"))

        pc.clear_dek_cache()
        opened = accessor.get_pii(version)
        self.assertEqual(opened, dict(pii, Id10073="XXXXXXXXX012"))
        self.assertIsNone(opened["Id10018"])
        self.assertEqual(opened["Id10010a"], 34)
        self.assertEqual(row.pii_digest, split_mod.pii_digest(opened))

    def test_abha_indexes_absent_for_malformed_or_missing_values(self):
        version = self._version("ppa-abha", odk_payload())
        row = accessor.put_pii(version, {"abha_number": "1234", "abha_address": "  "}, [], sealed_ids=SEALED)
        self.assertIsNone(row.abha_number_bidx)
        self.assertIsNone(row.abha_address_bidx)
        row = accessor.put_pii(version, {}, [], sealed_ids=SEALED)
        self.assertEqual(row.sealed, {})
        self.assertEqual(accessor.get_pii(version), {})

    def test_second_put_replaces_the_row_and_keeps_flags(self):
        version = self._version("ppa-upsert", odk_payload())
        first = accessor.put_pii(version, {"Id10017": "Sita", "Id10073": "12"}, [], sealed_ids=SEALED)
        self.assertEqual(first.review_flags, ["Id10073"])  # under 3 digits: flagged
        first_wrapped = first.dek_wrapped
        second = accessor.put_pii(version, {"Id10017": "Gita"}, [], sealed_ids=SEALED)
        self.assertIs(second, first)
        self.assertEqual(self._rows(version), 1)
        self.assertNotEqual(second.dek_wrapped, first_wrapped)  # fresh DEK per write
        self.assertEqual(second.review_flags, ["Id10073"])
        self.assertEqual(accessor.get_pii(version), {"Id10017": "Gita"})

    def test_side_row_moved_to_another_version_does_not_open(self):
        version = self._version("ppa-aad-a", odk_payload())
        other = self._version("ppa-aad-b", odk_payload())
        row = accessor.put_pii(version, {"Id10017": "Sita"}, [], sealed_ids=SEALED)
        moved = accessor.put_pii(other, {"Id10017": "Other"}, [], sealed_ids=SEALED)
        moved.sealed, moved.dek_wrapped = dict(row.sealed), row.dek_wrapped
        db.session.flush()
        self.assertEqual(accessor.get_pii(version), {"Id10017": "Sita"})
        with self.assertRaises(pc.PiiCryptoError) as caught:
            accessor.get_pii(other)
        self.assertIn(str(other.payload_version_id), str(caught.exception))
        self.assertNotIn("Sita", str(caught.exception))

    def test_one_unwrap_per_version_per_request(self):
        version = self._version("ppa-cache", odk_payload())
        accessor.put_pii(version, {"Id10017": "Sita", "Id10018": "Devi"}, [], sealed_ids=SEALED)
        pc.clear_dek_cache()
        with mock.patch.object(pc, "unwrap_dek", wraps=pc.unwrap_dek) as spy:
            accessor.get_pii(version)
            accessor.get_full_payload(version)
        self.assertEqual(spy.call_count, 1)

    def test_strip_version_moves_pii_and_keeps_the_fingerprint_rule(self):
        raw = odk_payload(Id10476="Card 2345 6789 0123 shown", abha_number="12345678901234")
        version = self._version("ppa-strip", raw)
        full_before = dict(version.payload_data)
        expected_fp = split_mod.fingerprint_of(full_before, SEALED)

        row = accessor.strip_version(version, SEALED)
        db.session.flush()
        db.session.expire(version)
        self.assertFalse(SEALED & set(version.payload_data))
        self.assertIn("Id10476", version.payload_data)  # subject present, redacted
        self.assertNotIn("6789", version.payload_data["Id10476"])
        self.assertEqual(version.payload_fingerprint, expected_fp)
        self.assertEqual(split_mod.stored_fingerprint(version.payload_data, row, SEALED), expected_fp)
        self.assertEqual(accessor.get_full_payload(version), full_before)
        self.assertEqual(frozenset(row.sealed_ids), SEALED)
        self.assertTrue(split_mod.same_content(raw, version, row, SEALED))  # ODK resends the full record
        self.assertFalse(split_mod.same_content(dict(raw, Id10017="Gita"), version, row, SEALED))

        # Rerun: nothing lost, nothing changes.
        sealed_fields, flags = set(row.sealed), list(row.review_flags)
        accessor.strip_version(version, SEALED)
        db.session.flush()
        self.assertEqual(set(row.sealed), sealed_fields)
        self.assertEqual(row.review_flags, flags)
        self.assertEqual(version.payload_fingerprint, expected_fp)
        self.assertEqual(accessor.get_full_payload(version), full_before)
        self.assertEqual(self._rows(version), 1)

    def test_unflushed_version_is_refused(self):
        version = VaSubmissionPayloadVersion(va_sid="ppa-x", payload_data={})
        with self.assertRaises(ValueError):
            accessor.put_pii(version, {"Id10017": "Sita"}, [], sealed_ids=SEALED)
