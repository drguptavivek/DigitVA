"""Shared Python/native exact coding receipt vectors, without database access."""
import json
import unittest
from pathlib import Path

from app.services.offline_coding_import_service import OfflineCodingError, coding_receipt_sha256


class CodingReceiptTests(unittest.TestCase):
    def test_shared_native_vectors(self):
        vectors = json.loads((Path(__file__).parents[1] / "fixtures/offline_coding_receipts.json").read_text())
        for vector in vectors:
            with self.subTest(vector=vector["name"]):
                self.assertEqual(coding_receipt_sha256(vector["value"]), vector["sha256"])

    def test_reordered_objects_and_equivalent_numbers_have_one_identity(self):
        self.assertEqual(coding_receipt_sha256({"b": 1.0, "a": -0.0}),
                         coding_receipt_sha256({"a": 0, "b": 1}))
        self.assertNotEqual(coding_receipt_sha256({}), coding_receipt_sha256({"a": None}))
        self.assertNotEqual(coding_receipt_sha256([1, 2]), coding_receipt_sha256([2, 1]))

    def test_nonfinite_and_lossy_numbers_are_refused(self):
        for value in (float("nan"), float("inf"), 2 ** 53 + 1, 10 ** 400):
            with self.subTest(value=value), self.assertRaises(OfflineCodingError):
                coding_receipt_sha256({"value": value})
