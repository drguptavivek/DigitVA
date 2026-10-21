"""Registration identifier rules: normalisation, value validation, type save.

Policy: docs/policy/death-registration-identifiers.md, "Tests" (Type save,
Value). Pure functions, no database.
"""
import re
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import re2

from app.services.death_identifier_rules import (
    _RE2_OPTIONS,
    IdentifierRuleError,
    check_pattern,
    clean_type_fields,
    normalise,
    validate_value,
)


def make_type(**overrides):
    base = dict(label="MCCD number", min_length=1, max_length=64, char_type=None, pattern=None,
                example=None, is_active=True)
    return SimpleNamespace(**{**base, **overrides})


class NormaliseTests(unittest.TestCase):
    def test_trim_collapse_nfkc_and_upper_case(self):
        self.assertEqual(normalise("  mccd/ 2026   0001 "), "MCCD/ 2026 0001")
        self.assertEqual(normalise("ＡＢ１"), "AB1")  # full-width, NFKC
        self.assertEqual(normalise("mccd/1"), normalise(" MCCD/1 "))

    def test_empty_is_no_value(self):
        for raw in (None, "", "   ", "\t\n"):
            self.assertIsNone(normalise(raw))

    def test_non_text_is_refused(self):
        for raw in (12, {"a": 1}, ["a"], True):
            with self.assertRaises(IdentifierRuleError):
                normalise(raw)


class ValidateValueTests(unittest.TestCase):
    def refusal(self, identifier_type, value):
        with self.assertRaises(IdentifierRuleError) as caught:
            validate_value(identifier_type, value)
        return str(caught.exception)

    def test_valid_value_passes(self):
        validate_value(make_type(char_type="letters_digits", pattern=r"[A-Z]{4}\d{4}"), "ABCD1234")

    def test_each_char_type_accepts_its_set_and_refuses_outside_it(self):
        accepts = {"digits": "123", "letters": "ABC", "letters_digits": "AB12", "letters_digits_hyphen_slash": "A-1/B"}
        refuses = {"digits": "12-3", "letters": "AB1", "letters_digits": "AB-1", "letters_digits_hyphen_slash": "A_1"}
        for char_type in accepts:
            with self.subTest(char_type):
                validate_value(make_type(char_type=char_type), accepts[char_type])  # subject present
                self.refusal(make_type(char_type=char_type), refuses[char_type])

    def test_length_is_checked_before_character_type_and_pattern(self):
        t = make_type(min_length=4, max_length=6, char_type="digits", pattern=r"\d+")
        short, long_ = self.refusal(t, "AB"), self.refusal(t, "ABCDEFGH")
        self.assertIn("between 4 and 6", short)
        self.assertIn("between 4 and 6", long_)  # not the character-type message
        self.assertIn("exactly 5", self.refusal(make_type(min_length=5, max_length=5), "1"))

    def test_all_rules_must_pass(self):
        t = make_type(min_length=3, max_length=8, char_type="letters_digits", pattern=r"AB\d+", example="AB123")
        validate_value(t, "AB123")
        message = self.refusal(t, "CD123")  # right length and characters, wrong pattern
        self.assertIn("must look like AB123", message)

    def test_inactive_type_is_refused(self):
        self.assertIn("not in use", self.refusal(make_type(is_active=False), "X1"))

    def test_message_never_echoes_the_value(self):
        t = make_type(min_length=2, max_length=4, char_type="digits", pattern=r"\d+", example="1234")
        for value in ("SECRETVALUE", "9", "99999999", "12AB"):
            self.assertNotIn(value, self.refusal(t, value))

    def test_message_shows_example_or_rule(self):
        self.assertIn("MCCD/2026/000123", self.refusal(
            make_type(pattern=r"MCCD/\d{4}/\d{6}", example="MCCD/2026/000123"), "X"))
        self.assertIn("required format", self.refusal(make_type(pattern=r"\d+"), "X"))


class PatternSafetyTests(unittest.TestCase):
    def test_safe_subset_is_accepted(self):
        for pattern in (r"\d{4}", r"[A-Z]{2}\d{6,10}", r"MCCD/\d{4}/\d{6}", r"(AB|CD)\d+", r"(?:ab)+",
                        r"\w+-\w{2,3}", r".{3}", r"[A-Z0-9/-]{5,20}", r"\d+\.\d?",
                        r"[A-Z]{2}\d{6}", r"MCCD/\d{4}/\d{4,6}", r"[A-Z0-9]+-[A-Z0-9]+",
                        r"[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]*", r"([A-Z0-9]+-)[A-Z0-9]+"):
            with self.subTest(pattern):
                check_pattern(pattern)

    def test_anchors_are_stripped_on_save(self):
        self.assertEqual(check_pattern(r"^\d{4}$"), r"\d{4}")
        self.assertEqual(check_pattern(r"\d\$"), r"\d\$")  # an escaped dollar is a literal

    def test_refused_constructs(self):
        refused = {
            "backreference": r"(\d)\1",
            "lookahead": r"(?=\d)\d+",
            "negative lookahead": r"(?!0)\d+",
            "lookbehind": r"(?<=A)\d+",
            "named group": r"(?P<n>\d)+",
            "conditional": r"(\d)?(?(1)A|B)",
            "inline flag": r"(?i)abc",
            "scoped flag": r"(?i:abc)",
            "atomic group": r"(?>\d+)",
            "possessive": r"\d++",
            "lazy": r"\d+?",
            "nested quantifier": r"(\d+)+",
            "nested bounded quantifier": r"(\d{2})+",
            "quantified alternation": r"(AB|CD)+",
            "repeat over 64": r"\d{1,1000}",
            "exact repeat over 64": r"\d{65}",
            "word boundary": r"\bAB",
            "over length": "A" * 201,
            "invalid": r"(\d",
            "empty after anchors": "^$",
            "optional repeats then a literal": "a?" * 30 + "a" * 30,
            "star repeats then a literal": r"\d*" * 25 + "X",
            "class repeats then a literal": "[0-9]*" * 12 + "!",
            "four variable parts": r"[A-Z]+-\d+-[A-Z]+-\d+",
            "adjacent overlapping repeats": r"\d+\d+",
            "overlap across an optional part": r"\d*-?\d*",
            "overlap across a group edge": r"(\d+)\d+",
            "overlapping alternation then repeat": r"(A|AB)[A-Z]+",
            "dot overlaps anything": r".+\d*",
        }
        for name, pattern in refused.items():
            with self.subTest(name), self.assertRaises(IdentifierRuleError):
                check_pattern(pattern)

    def test_repeat_of_64_is_accepted(self):
        check_pattern(r"\d{1,64}")

    def test_a_fixed_repeat_is_not_a_variable_part(self):
        check_pattern(r"\d{2}-\d{2}-\d{2}-\d{2}-\d{2}")  # five fixed counts, none variable

    def test_refusal_messages_never_echo_the_pattern(self):
        for pattern in ("a?" * 30 + "SECRETLITERAL", r"\d+\d+"):
            with self.assertRaises(IdentifierRuleError) as caught:
                check_pattern(pattern)
            self.assertNotIn("SECRETLITERAL", str(caught.exception))

    def test_accepted_worst_case_matches_quickly(self):
        pattern = check_pattern(r"[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]*")
        compiled = re.compile(pattern, re.ASCII)
        for value in ("1" * 64, "1-" * 31 + "!!", "-" * 64):
            started = time.perf_counter()
            self.assertIsNone(compiled.fullmatch(value))
            self.assertLess(time.perf_counter() - started, 0.5)
        self.assertTrue(compiled.fullmatch("AB-12-"))  # the subject matches what it should


# Every construct the safe subset allows, against values that probe ASCII vs
# Unicode classes, the dot, escapes and anchors. Python ``re`` (ASCII) is the
# reference; re2 must agree. The one known difference, ``\s`` and ``\v``, is
# unreachable because ``normalise`` turns every whitespace into a plain space.
ENGINE_PATTERNS = [
    r"AB-\d{4}", r"[A-Z]{2}\d{6}", r"\w+", r"\w{3,8}", r"A\sB", r"\d+/\d+", r"[A-Z]+-[0-9]+",
    r"(AB|CD)-\d{2}", r"(?:AB|CD)\d+", r".{3}", r"A.B", r"A\.B", r"A\-B", r"A\/B", r"A\_B", r"A\(B\)",
    r"[A-C0-3]+", r"[^0-9]+", r"[\d]+", r"[\w-]+", r"[A-Z/-]{2,10}", r"\d?X", r"A{2,3}", r"[.]+",
    r"\\", r"[\\]+", r"\$\d", r"\^A", r"\x41B", r"\D+", r"\W+", r"\S+", r"\d{1,3}\.\d{1,3}",
    r"[^\s]+", "\u00e9+", r"[a-z]+", r"A|B", r"AB?C",
]
ENGINE_VALUES = [
    "", "A", "AB", "AB-1234", "CD-12", "AB12", "AB123456", "12/34", "1.2", "A.B", "A-B", "A/B", "A_B",
    "A(B)", "A B", "ab", "aB", "\u0661\u0662\u0663", "\u00c9", "\u00e9\u00e9", "\uff11\uff12", "123", "X", "12X",
    "A\\B", "\\", "$1", "^A", "AAB", "AAAA", "A\nB", "\n", " ", "A\u00a0B", "\u2003", "-" * 64,
]


class Re2EngineTests(unittest.TestCase):
    def test_re2_agrees_with_python_re_on_the_allowed_subset(self):
        for pattern in ENGINE_PATTERNS:
            stored = check_pattern(pattern)
            reference = re.compile(stored, re.ASCII)
            engine = re2.compile(stored, _RE2_OPTIONS)
            for value in ENGINE_VALUES:
                with self.subTest(pattern=pattern, value=value):
                    self.assertEqual(bool(reference.fullmatch(value)), bool(engine.fullmatch(value)))

    def test_known_difference_vertical_tab_is_unreachable(self):
        # Python ASCII \s matches \v, re2 does not; normalise() removes it first.
        self.assertTrue(re.fullmatch(r"\s", "\v", re.ASCII))
        self.assertFalse(re2.fullmatch(r"\s", "\v"))
        self.assertEqual(normalise("A\vB"), "A B")

    def test_re2_is_linear_on_patterns_the_checker_would_refuse(self):
        # Compiled directly, bypassing check_pattern: the second guard on its own.
        cases = (("a?" * 30 + "a" * 30, "a" * 30 + "b"), (r"\d*" * 25 + "X", "1" * 5000),
                 ("[0-9]*" * 12 + "!", "1" * 5000), (r"(a+)+b", "a" * 5000))
        for pattern, value in cases:
            started = time.perf_counter()
            self.assertIsNone(re2.compile(pattern, _RE2_OPTIONS).fullmatch(value))
            self.assertLess(time.perf_counter() - started, 0.5)

    def test_validate_value_matches_with_re2(self):
        with mock.patch("app.services.death_identifier_rules.re.compile",
                        side_effect=AssertionError("Python re must not match")):
            validate_value(make_type(pattern=r"AB-\d{4}"), "AB-1234")
            with self.assertRaises(IdentifierRuleError):
                validate_value(make_type(pattern=r"AB-\d{4}"), "AB-12345")

    def test_pattern_re2_cannot_compile_is_refused_on_save(self):
        with mock.patch("app.services.death_identifier_rules.re2.compile", side_effect=re2.error("x")):
            with self.assertRaises(IdentifierRuleError) as caught:
                check_pattern(r"SECRETLITERAL\d")
        self.assertNotIn("SECRETLITERAL", str(caught.exception))

    def test_brace_comma_repeat_is_refused_because_engines_differ(self):
        with self.assertRaises(IdentifierRuleError):
            check_pattern(r"\d{,3}")
        check_pattern(r"A\{,3}")  # an escaped brace is literal text in both engines

    def test_stored_pattern_re2_rejects_is_a_refusal_not_a_crash(self):
        with self.assertRaises(IdentifierRuleError) as caught:
            validate_value(make_type(pattern=r"(?=a)a"), "A")
        self.assertNotIn("(?=", str(caught.exception))


class TypeSaveTests(unittest.TestCase):
    def good(self, **overrides):
        return {"code": "mccd", "label": "MCCD number", "min_length": 6, "max_length": 20,
                "char_type": "letters_digits_hyphen_slash", "pattern": r"MCCD/\d{4}/\d{6}",
                "example": "mccd/2026/000123", **overrides}

    def test_valid_type_is_cleaned_and_example_capitalised(self):
        cleaned = clean_type_fields(self.good())
        self.assertEqual(cleaned["example"], "MCCD/2026/000123")
        self.assertEqual(cleaned["code"], "mccd")
        self.assertEqual(cleaned["uniqueness_scope"], "project")
        self.assertFalse(cleaned["required_at_report"])

    def test_defaults(self):
        cleaned = clean_type_fields({"code": "crs", "label": "CRS"})
        self.assertEqual((cleaned["min_length"], cleaned["max_length"], cleaned["is_active"]), (1, 64, True))

    def test_min_greater_than_max_refused(self):
        with self.assertRaises(IdentifierRuleError):
            clean_type_fields(self.good(min_length=21, max_length=20, example=None))

    def test_length_range_must_be_within_1_to_64(self):
        for name, value in (("min_length", 0), ("max_length", 65), ("min_length", "3"), ("max_length", True)):
            with self.subTest(name=name, value=value), self.assertRaises(IdentifierRuleError):
                clean_type_fields(self.good(**{name: value}))

    def test_example_failing_any_rule_is_refused(self):
        for example in ("MCCD", "mccd#2026#000123", "MCCX/2026/000123"):  # length, characters, pattern
            with self.subTest(example), self.assertRaises(IdentifierRuleError):
                clean_type_fields(self.good(example=example, min_length=1))

    def test_char_type_values(self):
        for char_type in ("digits", "letters", "letters_digits", "letters_digits_hyphen_slash", None):
            clean_type_fields({"code": "crs", "label": "CRS", "char_type": char_type})
        for bad in ("hex", ["digits"], {"a": 1}, 7, True):
            with self.subTest(bad), self.assertRaises(IdentifierRuleError):
                clean_type_fields({"code": "crs", "label": "CRS", "char_type": bad})

    def test_code_shape(self):
        for code in ("a", "1abc", "Abc", "a-b", "x" * 33, "", None):
            with self.subTest(code), self.assertRaises(IdentifierRuleError):
                clean_type_fields({"code": code, "label": "L"})

    def test_unsafe_pattern_refused_at_save(self):
        with self.assertRaises(IdentifierRuleError):
            clean_type_fields(self.good(pattern=r"(\d+)+", example=None))

    def test_update_is_validated_as_a_whole(self):
        current = clean_type_fields(self.good())
        with self.assertRaises(IdentifierRuleError):
            clean_type_fields({"max_length": 10}, current)  # the stored example is now too long
        self.assertEqual(clean_type_fields({"label": "New label"}, current)["label"], "New label")

    def test_uniqueness_scope_values(self):
        for scope in ("none", "project"):
            clean_type_fields({"code": "crs", "label": "CRS", "uniqueness_scope": scope})
        with self.assertRaises(IdentifierRuleError):
            clean_type_fields({"code": "crs", "label": "CRS", "uniqueness_scope": "site"})


if __name__ == "__main__":
    unittest.main()
