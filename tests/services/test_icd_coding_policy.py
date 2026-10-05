"""Shared ICD-10/ICD-11 age/sex coding policy: sex and age mapping and the clause."""

import unittest
from decimal import Decimal

from app.models import MasIcd11Mms, MasIcd1020192, VaSubmissions
from app.services.icd_coding_policy import (
    coding_age_group_for_submission,
    coding_context_for_submission,
    coding_policy_clause,
    coding_sex_for_submission,
)
from tests.base import BaseTestCase


def _sql(clause) -> str:
    return str(clause.compile(compile_kwargs={"literal_binds": True}))


class CodingAgeSexMappingTests(unittest.TestCase):
    def test_missing_submission_has_no_age_group_or_sex(self):
        self.assertIsNone(coding_age_group_for_submission(None))
        self.assertIsNone(coding_sex_for_submission(None))

    def test_normalized_days_map_to_groups_incl_neonate_infant_boundaries(self):
        for days, expected in (
            ("0", "neonate"),
            ("27.999", "neonate"),
            ("28", "infant"),
            ("364.999", "infant"),
            ("365", "child"),
            ("4383", "adult"),  # 12 * 365.25
        ):
            submission = VaSubmissions(va_deceased_age_normalized_days=Decimal(days))
            self.assertEqual(coding_age_group_for_submission(submission), expected, days)

    def test_legacy_age_used_only_without_normalized_days(self):
        self.assertEqual(
            coding_age_group_for_submission(VaSubmissions(va_deceased_age=11)), "child"
        )
        self.assertEqual(
            coding_age_group_for_submission(VaSubmissions(va_deceased_age=12)), "adult"
        )
        self.assertIsNone(coding_age_group_for_submission(VaSubmissions()))

    def test_sex_is_male_or_female_else_unknown(self):
        for raw, expected in (
            ("male", "male"),
            (" Female ", "female"),
            ("MALE", "male"),
            ("unknown", None),
            ("", None),
            (None, None),
        ):
            submission = VaSubmissions(va_deceased_gender=raw)
            self.assertEqual(coding_sex_for_submission(submission), expected, raw)


class CodingPolicyClauseTests(unittest.TestCase):
    def test_same_predicate_shape_for_both_models(self):
        for age_group, sex in (("neonate", "male"), ("child", "female"), (None, None)):
            icd10 = _sql(coding_policy_clause(MasIcd1020192, age_group=age_group, sex=sex))
            icd11 = _sql(coding_policy_clause(MasIcd11Mms, age_group=age_group, sex=sex))
            self.assertEqual(
                icd10.replace("mas_icd10_2019_2", "T"),
                icd11.replace("mas_icd11_mms", "T"),
                (age_group, sex),
            )

    def test_neonate_and_infant_include_neonate_infant_others_do_not(self):
        for age_group, expected in (
            ("neonate", True),
            ("infant", True),
            ("child", False),
            ("adult", False),
        ):
            sql = _sql(coding_policy_clause(MasIcd11Mms, age_group=age_group, sex=None))
            self.assertEqual("'neonate_infant'" in sql, expected, age_group)

    def test_unknown_sex_and_age_add_no_condition(self):
        sql = _sql(coding_policy_clause(MasIcd11Mms, age_group=None, sex=None))
        self.assertIn("is_coding_selectable", sql)  # subject present
        self.assertNotIn("age_group_selectable", sql)
        self.assertNotIn("sex_selectable", sql)

    def test_known_sex_filters_on_both_or_that_sex(self):
        sql = _sql(coding_policy_clause(MasIcd11Mms, age_group=None, sex="female"))
        self.assertIn("'both'", sql)
        self.assertIn("'female'", sql)


class CodingContextTests(BaseTestCase):
    def test_unknown_submission_returns_none(self):
        self.assertIsNone(coding_context_for_submission("uuid:does-not-exist"))
