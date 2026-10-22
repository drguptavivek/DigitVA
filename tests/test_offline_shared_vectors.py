"""The server side of the shared offline vectors (offline-api-contract.md 14).

The Rust station (desktop/crates/digitva-text) and the Expo app
(mobile/digitva-collect/__tests__/offline-shared-vectors.test.ts) read the
same files; the Python functions here are the authority they follow. Pure
functions: nothing here touches the database.
"""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

from app.services import death_identifier_rules as rules
from app.services.pii_field_registry import PII_FIELDS
from app.utils.national_id import reduce_national_id_flagged
from app.utils.phone import normalise_phone

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _broken_rule(message: str) -> str:
    """The rule a ``validate_value`` refusal names, from its message (rules
    without an example, so the length and pattern messages do not overlap)."""
    if "characters" in message and " must be " in message:
        return "length"
    if "may contain only" in message:
        return "char_type"
    return "pattern"


class PhoneVectorTests(TestCase):
    def test_every_case(self):
        cases = _load("phone_vectors.json")["cases"]
        self.assertGreater(len(cases), 0)
        for case in cases:
            with self.subTest(input=case["input"]):
                self.assertEqual(normalise_phone(case["input"]), case["expected"])


class IdentifierVectorTests(TestCase):
    def setUp(self):
        self.data = _load("identifier_vectors.json")

    def test_normalise(self):
        self.assertGreater(len(self.data["normalise"]), 0)
        for case in self.data["normalise"]:
            with self.subTest(input=case["input"]):
                self.assertEqual(rules.normalise(case["input"]), case["expected"])

    def test_rule_patterns_pass_the_save_check(self):
        for name, rule in self.data["rules"].items():
            if rule["pattern"]:
                with self.subTest(rule=name):
                    self.assertEqual(rules.check_pattern(rule["pattern"]), rule["pattern"])

    def test_validate(self):
        self.assertGreater(len(self.data["validate"]), 0)
        for case in self.data["validate"]:
            with self.subTest(rule=case["rule"], input=case["input"]):
                identifier_type = SimpleNamespace(**self.data["rules"][case["rule"]], is_active=True)
                norm = rules.normalise(case["input"])
                if norm is None:
                    self.assertEqual(case["expected"], {"value": None})
                    continue
                try:
                    rules.validate_value(identifier_type, norm)
                except rules.IdentifierRuleError as exc:
                    self.assertEqual({"error": _broken_rule(str(exc))}, case["expected"])
                else:
                    self.assertEqual({"value": norm}, case["expected"])


class NationalIdVectorTests(TestCase):
    def test_every_case(self):
        cases = _load("national_id_vectors.json")["cases"]
        self.assertGreater(len(cases), 0)
        for case in cases:
            with self.subTest(input=case["input"]):
                self.assertEqual(reduce_national_id_flagged(case["input"]),
                                 (case["expected"], case["needs_review"]))


class PiiFieldsFloorTests(TestCase):
    def test_floor_is_pii_fields(self):
        fields = _load("pii_fields_floor.json")["fields"]
        self.assertIn("Id10073", fields)
        self.assertEqual(len(fields), len(set(fields)))
        self.assertEqual(sorted(fields), sorted(PII_FIELDS))
