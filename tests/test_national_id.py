"""National-ID reduction (app/utils/national_id.py), PII slice 1a.

Pure functions: no app or database. docs/kb/pii-slice-1a.md.
"""

from unittest import TestCase

from app.utils.national_id import (
    NATIONAL_ID_KEEP_DIGITS,
    looks_like_national_id,
    redact_national_id_digits,
    redact_payload_national_ids,
    reduce_national_id,
    reduce_national_id_flagged,
)


class ReduceNationalIdTests(TestCase):
    def test_keeps_the_last_three_digits_at_fixed_width(self):
        self.assertEqual(NATIONAL_ID_KEEP_DIGITS, 3)
        for typed in ("234567890123", "2345 6789 0123", "2345-6789-0123", " 234567890123 "):
            with self.subTest(typed=typed):
                self.assertEqual(reduce_national_id_flagged(typed), ("XXXXXXXXX123", False))

    def test_a_sixteen_digit_vid_is_stored_at_the_same_width(self):
        self.assertEqual(reduce_national_id_flagged("9123 4567 8901 2345"), ("XXXXXXXXX345", False))

    def test_unicode_digits_are_folded(self):
        devanagari = "२३४५६७८९०१२३"
        arabic_indic = "٢٣٤٥٦٧٨٩٠١٢٣"
        fullwidth = "２３４５６７８９０１２３"
        for typed in (devanagari, arabic_indic, fullwidth):
            with self.subTest(typed=typed):
                self.assertEqual(reduce_national_id_flagged(typed), ("XXXXXXXXX123", False))

    def test_reduction_is_idempotent(self):
        once = reduce_national_id("234567890123")
        self.assertEqual(once, "XXXXXXXXX123")
        self.assertEqual(reduce_national_id_flagged(once), (once, False))
        self.assertFalse(looks_like_national_id(once))
        masked = reduce_national_id("dk")
        self.assertEqual(reduce_national_id_flagged(masked), (masked, False))

    def test_junk_is_reduced_conservatively_and_flagged(self):
        self.assertEqual(reduce_national_id_flagged("12345678901"), ("XXXXXXXXX901", True))  # 11 digits
        self.assertEqual(reduce_national_id_flagged("1234567890123"), ("XXXXXXXXX123", True))  # 13 digits
        self.assertEqual(reduce_national_id_flagged("A1B2C3D4"), ("XXXXXXXXX234", True))
        self.assertEqual(reduce_national_id_flagged("not known"), ("XXXXXXXXXXXX", True))
        self.assertEqual(reduce_national_id_flagged("12"), ("XXXXXXXXXXXX", True))

    def test_blank_and_null_like_are_not_answered(self):
        for value in (None, "", "   ", "NA", "n/a", "None", "null", "-", '"_"', "..."):
            with self.subTest(value=value):
                self.assertEqual(reduce_national_id_flagged(value), (None, False))

    def test_a_number_value_is_reduced(self):
        self.assertEqual(reduce_national_id(234567890123), "XXXXXXXXX123")


class LooksLikeNationalIdTests(TestCase):
    def test_matches_twelve_and_sixteen_digit_runs(self):
        for text in ("234567890123", "id 2345 6789 0123.", "2345-6789-0123", "9123456789012345",
                     "Aadhaar no.234567890123", "Aadhaar:234567890123"):
            with self.subTest(text=text):
                self.assertTrue(looks_like_national_id(text))

    def test_does_not_match_other_numbers(self):
        for text in (
            "9876543210",            # 10-digit phone
            "+91 98765 43210",       # phone, 5-5 groups
            "12345678901",           # 11 digits
            "1234567890123",         # 13 digits
            "12345678901234",        # 14 digits (ABHA number)
            "0.123456789012",        # decimal
            "4.5633123456789012",    # long decimal
            "169512345678.jpg",      # attachment file name
            "D1234567890123456789",  # registration number with 19 digits
            "REG234567890123",       # glued to letters
            "1b4e28ba-2fa1-1234-5678-123456789012",  # UUID with decimal groups
            "XXXXXXXXX123",
            "",
        ):
            with self.subTest(text=text):
                self.assertFalse(looks_like_national_id(text))
        self.assertFalse(looks_like_national_id(None))


class RedactFreeTextTests(TestCase):
    def test_masks_each_match_and_keeps_the_rest(self):
        text = "Aadhaar 2345 6789 0123 and VID 9123-4567-8901-2345, phone 9876543210."
        self.assertTrue(looks_like_national_id(text))
        new_text, found = redact_national_id_digits(text)
        self.assertTrue(found)
        self.assertEqual(new_text, "Aadhaar XXXXXXXXX123 and VID XXXXXXXXX345, phone 9876543210.")
        self.assertEqual(redact_national_id_digits(new_text), (new_text, False))

    def test_text_without_a_match_is_unchanged(self):
        self.assertEqual(redact_national_id_digits("fever for 3 days"), ("fever for 3 days", False))


class RedactPayloadTests(TestCase):
    def test_reduces_id10073_sweeps_free_text_and_flags_id10070(self):
        payload = {
            "Id10073": "234567890123",
            "Id10476": "The ID 345678901234 was shown.",
            "Id10070": "234567890123",
            "Id10213": "9.9999999999999999",
            "md_im1": "169512345678.jpg",
            "site_individual_id": "234567890123",
            "abha_number": "12-3456-7890-1234",
            "Id10019": "female",
        }
        reduced, flagged = redact_payload_national_ids(payload)
        self.assertEqual(reduced["Id10073"], "XXXXXXXXX123")
        self.assertEqual(reduced["Id10476"], "The ID XXXXXXXXX234 was shown.")
        self.assertEqual(reduced["Id10070"], "234567890123")  # flag only
        for kept in ("Id10213", "md_im1", "site_individual_id", "abha_number", "Id10019"):
            self.assertEqual(reduced[kept], payload[kept])
        self.assertEqual(sorted(flagged), ["Id10070", "Id10476"])
        self.assertEqual(payload["Id10073"], "234567890123")  # the input is not mutated

    def test_nested_values_are_swept(self):
        payload = {"group": [{"Id10073": "234567890123", "comment": "234567890123"}]}
        reduced, _ = redact_payload_national_ids(payload)
        self.assertEqual(reduced["group"][0], {"Id10073": "XXXXXXXXX123", "comment": "XXXXXXXXX123"})

    def test_an_already_reduced_payload_is_returned_as_is(self):
        reduced, _ = redact_payload_national_ids({"Id10073": "234567890123", "x": 1})
        again, flagged = redact_payload_national_ids(reduced)
        self.assertIs(again, reduced)
        self.assertEqual(flagged, [])

    def test_non_dict_passes_through(self):
        self.assertEqual(redact_payload_national_ids(None), (None, []))
