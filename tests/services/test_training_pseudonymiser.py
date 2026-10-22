"""Pseudonymisation of one payload: every PII field type, narrative, consistency."""

import copy
import re
import unittest

from app.services.pii_field_registry import PII_FIELDS
from app.services.training_pseudonymiser import (
    COUNT_KEYS,
    HANDLED_FIELDS,
    pseudonymise_payload,
    residual_categories,
)

PAYLOAD = {
    "Id10017": "Ramesh",
    "Id10018": "Kumarasamy",
    "Id10007": "Sunita Kumarasamy",
    "Id10010": "Dr. Priya Nair",
    "Id10061": "Gopal Kumarasamy",
    "Id10062": "Lakshmi Devi Kumarasamy",
    "Id10055": "12 Temple Road, Kalpet",
    "Id10057": "12 temple road, kalpet",
    "visit_address": "Near the bus stand, Kalpet",
    "visit_remarks": "Family lives at 12 Temple Road, Kalpet",
    "Id10010a": "34",
    "Id10010b": "female",
    "Id10010c": "EMP4471",
    "Id10070": "REG-2024-00917",
    "Id10071": "2024-03-02",
    "Id10072": "Kalpet Municipal Office",
    "Id10073": {"last3": "482", "present": True},
    "abha_number": "12-3456-7890-1234",
    "abha_address": "ramesh.k@abdm",
    "Id10019": "male",
    "ageInYears": "61",
    "Id10022": "2024-02-11",
    "Id10476": (
        "Ramesh Kumarasamy fell ill after returning from 12 Temple Road, Kalpet. "
        "RAMESH had fever; his wife Sunita said KUMARASAMY was weak. Ramesheswar was a neighbour. "
        "She called REG-2024-00917 office."
    ),
    "Id10099": "Loss of weight over three months",
    "narrative_audio": "Ramesh_Kumarasamy.amr",
    "sid": "src-1",
}


class PseudonymiserTests(unittest.TestCase):
    def setUp(self):
        self.original = copy.deepcopy(PAYLOAD)
        self.out, self.counts = pseudonymise_payload(PAYLOAD, "S001:1")

    def test_registry_fields_are_all_handled(self):
        self.assertEqual(set(PII_FIELDS), set(HANDLED_FIELDS))

    def test_input_unchanged_and_subject_present(self):
        self.assertEqual(PAYLOAD, self.original)
        self.assertTrue(self.out["Id10017"])  # present before asserting absence

    def test_every_pii_field_changes(self):
        for field in ("Id10017", "Id10018", "Id10007", "Id10010", "Id10061", "Id10062", "Id10055",
                      "Id10057", "visit_address", "visit_remarks", "Id10010c", "Id10070", "Id10071",
                      "Id10072", "abha_number", "abha_address"):
            self.assertTrue(self.out[field], field)
            self.assertNotEqual(self.out[field], PAYLOAD[field], field)
        self.assertNotEqual(self.out["Id10073"]["last3"], "482")
        self.assertTrue(self.out["Id10073"]["present"])
        self.assertEqual(len(self.out["Id10073"]["last3"]), 3)

    def test_same_value_same_fake_within_the_case(self):
        self.assertEqual(self.out["Id10055"], self.out["Id10057"])  # case-insensitive
        surname = self.out["Id10018"]
        for field in ("Id10007", "Id10061", "Id10062"):
            self.assertTrue(self.out[field].endswith(surname), field)

    def test_narrative_uses_the_same_fakes_whole_word_case_insensitive(self):
        text = self.out["Id10476"]
        given, surname = self.out["Id10017"], self.out["Id10018"]
        self.assertIn(f"{given} {surname}", text)
        self.assertIn(given.upper(), text)
        self.assertIn(surname.upper(), text)
        self.assertNotIn("Ramesh ", text)
        self.assertNotIn("Kumarasamy", text.replace(surname, ""))
        self.assertIn("Ramesheswar", text)  # a longer word is not a whole-word match
        self.assertNotIn("Temple Road", text)
        self.assertIn(self.out["Id10055"], text)
        self.assertNotIn("REG-2024-00917", text)
        self.assertIn(self.out["Id10070"], text)
        self.assertGreater(self.counts["text_replacements"], 4)

    def test_non_pii_answers_and_media_names_kept(self):
        for field in ("Id10019", "ageInYears", "Id10022", "Id10099", "narrative_audio", "sid"):
            self.assertEqual(self.out[field], PAYLOAD[field], field)
        self.assertEqual(self.out["Id10010"].split()[0], "Dr.")
        self.assertEqual(self.out["Id10010b"] in ("male", "female"), True)

    def test_shapes_kept(self):
        self.assertRegex(self.out["abha_number"], r"^\d\d-\d{4}-\d{4}-\d{4}$")
        self.assertTrue(self.out["abha_address"].endswith("@abdm"))
        self.assertRegex(self.out["Id10071"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(self.out["Id10070"], r"^[A-Z]{3}-\d{4}-\d{5}$")
        self.assertRegex(self.out["Id10055"], r"^House \d+, Ward \d+, Synthetic Village \d+$")

    def test_deterministic_per_seed_and_different_across_seeds(self):
        again, _ = pseudonymise_payload(PAYLOAD, "S001:1")
        other, _ = pseudonymise_payload(PAYLOAD, "S001:2")
        self.assertEqual(self.out, again)
        self.assertNotEqual(self.out["Id10055"] + self.out["Id10070"], other["Id10055"] + other["Id10070"])

    def test_counts_only(self):
        self.assertEqual(set(self.counts), set(COUNT_KEYS))
        self.assertEqual(self.counts["names"], 6)
        self.assertEqual(self.counts["addresses"], 4)

    def test_empty_and_missing_fields_are_left(self):
        out, counts = pseudonymise_payload({"Id10017": "", "Id10055": None, "Id10476": "No names here."}, "x")
        self.assertEqual(out, {"Id10017": "", "Id10055": None, "Id10476": "No names here."})
        self.assertEqual(sum(counts.values()), 0)

    def test_address_place_words_are_replaced_in_free_text(self):
        out, counts = pseudonymise_payload(
            {
                "Id10055": "Ward 4, Bhojpur Kalan near the bus stand",
                "Id10476": "He came back from Bhojpur and fell ill; Kalan is far. The Ward was crowded.",
            },
            "p:1",
        )
        text = out["Id10476"]
        self.assertTrue(text)
        self.assertNotIn("Bhojpur", text)
        self.assertNotIn("Kalan", text)
        self.assertIn("Ward", text)  # a generic address word stays
        self.assertGreaterEqual(counts["text_replacements"], 2)
        # one fake place per original word, the same each time
        again, _ = pseudonymise_payload({"Id10055": "Bhojpur Kalan", "Id10476": "Bhojpur, Bhojpur"}, "p:1")
        first, second = again["Id10476"].split(", ")
        self.assertEqual(first, second)
        self.assertNotEqual(first, "Bhojpur")

    def test_devanagari_name_found_inside_devanagari_narrative(self):
        source = {
            "Id10017": "रमेश",
            "Id10018": "कुमार",
            "Id10055": "ग्राम सीतापुर",
            "Id10476": "रमेश कुमार को बुखार आया। रमेश की पत्नी ने बताया कि वे सीतापुर से लौटे। रमेशजी नहीं थे।",
        }
        out, _ = pseudonymise_payload(source, "dev:1")
        text = out["Id10476"]
        self.assertTrue(out["Id10017"])
        self.assertNotEqual(out["Id10017"], "रमेश")
        self.assertIn(out["Id10017"], text)
        self.assertNotIn("रमेश कुमार", text)
        self.assertNotIn("सीतापुर", text)
        self.assertIn("रमेशजी", text)  # a longer word with attached marks is not a whole-word match
        self.assertIn("।", text)  # the danda is punctuation, not part of the word
        self.assertEqual(residual_categories(source, out), set())

    def test_phone_numbers_in_free_text_are_replaced_consistently(self):
        source = {
            "Id10476": "Call 98765 43210 or +91-9876543210 or 09876543210; also 0 and 12345 stay. Born 2024-03-02.",
            "Id10099": "Alt number 9876543210.",
        }
        out, counts = pseudonymise_payload(source, "ph:1")
        numbers = re.findall(r"\b\d{10}\b", out["Id10476"] + " " + out["Id10099"])
        self.assertEqual(len(numbers), 4)
        self.assertEqual(len(set(numbers)), 1)  # same number, same fake
        self.assertNotIn("9876543210", numbers)
        self.assertIn("12345", out["Id10476"])
        self.assertIn("2024-03-02", out["Id10476"])
        self.assertEqual(counts["phone_replacements"], 4)
        self.assertEqual(residual_categories(source, out), set())

    def test_residual_categories_report_what_survives(self):
        source = {"Id10017": "Ramesh", "Id10055": "Kalpet", "Id10476": "Ramesh at Kalpet 9876543210"}
        self.assertEqual(residual_categories(source, dict(source)), {"names", "addresses", "phones"})
        out, _ = pseudonymise_payload(source, "r:1")
        self.assertEqual(residual_categories(source, out), set())


if __name__ == "__main__":
    unittest.main()
