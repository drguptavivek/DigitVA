"""Regression tests for WHO 2022 age normalization."""

from decimal import Decimal
import unittest

from app.services.who_age_normalization import normalize_who_2022_age


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
