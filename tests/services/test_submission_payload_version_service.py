"""Regression coverage for normalized payload fingerprinting."""

from unittest import TestCase

from app.services.submission_payload_version_service import (
    canonical_payload_fingerprint,
    normalize_payload_for_fingerprint,
)


class SubmissionPayloadFingerprintTests(TestCase):
    def test_fingerprint_ignores_volatile_metadata_and_numeric_representation(self):
        previous = {
            "Id10120": 10.0,
            "Id10148": 0.0,
            "finalAgeInYears": 58,
            "ageInYears": 58.0,
            "survey_state": 29,
            "DeviceID": "collect:abc",
            "OdkReviewComments": None,
            "instanceID": "uuid:1",
        }
        incoming = {
            "Id10120": "10",
            "Id10148": "0",
            "finalAgeInYears": "58",
            "ageInYears": "58",
            "survey_state": "29",
            "DeviceID": None,
            "OdkReviewComments": [],
            "instanceID": None,
        }

        self.assertEqual(
            normalize_payload_for_fingerprint(previous),
            {"Id10120": "10", "Id10148": "0"},
        )
        self.assertEqual(
            canonical_payload_fingerprint(previous),
            canonical_payload_fingerprint(incoming),
        )

    def test_fingerprint_keeps_real_interview_answer_changes(self):
        previous = {
            "Id10120": "10",
            "Id10477": "1",
            "comment": "old",
        }
        incoming = {
            "Id10120": "10",
            "Id10477": "2",
            "comment": "new",
        }

        self.assertNotEqual(
            canonical_payload_fingerprint(previous),
            canonical_payload_fingerprint(incoming),
        )

    def test_fingerprint_treats_null_like_placeholders_as_none(self):
        previous = {
            "site_individual_id": None,
            "Id10476": "",
            "Id10477": "NA",
            "comment": "None",
        }
        incoming = {
            "site_individual_id": "NA",
            "Id10476": "None",
            "Id10477": "n/a",
            "comment": "null",
        }

        self.assertEqual(
            normalize_payload_for_fingerprint(previous),
            {
                "site_individual_id": None,
                "Id10476": None,
                "Id10477": None,
                "comment": None,
            },
        )
        self.assertEqual(
            canonical_payload_fingerprint(previous),
            canonical_payload_fingerprint(incoming),
        )
