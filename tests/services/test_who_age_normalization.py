"""Regression tests for WHO 2022 age normalization."""

from decimal import Decimal
import unittest

from app.services.who_age_normalization import (
    derive_final_age_in_years,
    normalize_who_2022_age,
)


class WhoAgeNormalizationTests(unittest.TestCase):
    def test_nan_like_values_are_treated_as_missing(self):
        result = normalize_who_2022_age(
            {
                "ageInDays": "NaN",
                "ageInMonths": "nan",
                "ageInYears": float("nan"),
                "finalAgeInYears": Decimal("NaN"),
            }
        )

        self.assertEqual(result.legacy_age_years, 0)
        self.assertIsNone(result.normalized_age_days)
        self.assertIsNone(result.normalized_age_years)
        self.assertIsNone(result.normalized_age_source)


class DeriveFinalAgeInYearsTests(unittest.TestCase):
    """The ND01 finalAgeInYears calculate."""

    def test_age_in_years_wins(self):
        self.assertEqual(derive_final_age_in_years({"ageInYears": "47", "ageInYears2": "50"}), "47")

    def test_age_in_years2_when_age_in_years_is_empty_or_nan(self):
        for empty in ("", "NaN", None, float("nan")):
            with self.subTest(empty=empty):
                self.assertEqual(derive_final_age_in_years({"ageInYears": empty, "ageInYears2": "12"}), "12")

    def test_000_when_both_are_empty_or_absent(self):
        self.assertEqual(derive_final_age_in_years({"ageInYears": "NaN", "ageInYears2": ""}), "000")
        self.assertEqual(derive_final_age_in_years({}), "000")
        self.assertEqual(derive_final_age_in_years(None), "000")
