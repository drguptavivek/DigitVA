"""`neonate_infant` policy age value (owner, 2026-09-29).

It matches a submission coded `neonate` or `infant`, never `child`/`adult`;
`all` and the other exact values behave as before. Checked on the compiled
search clause for both classifications, then on real rows through the coding
screen's search functions.
"""

import unittest

from app import db
from app.models import MasIcd11Mms, MasIcd1020192
from app.services.icd10_2019_2_service import (
    _coding_policy_clause as icd10_clause,
)
from app.services.icd10_2019_2_service import (
    search_icd10_2019_2_coding_choices_for_policy,
)
from app.services.icd11_mms_service import _coding_policy_clause as icd11_clause
from app.services.icd11_mms_service import search_icd11_mms
from tests.base import BaseTestCase

RELEASE = "TEST-NEOINF"
# (code, sex_selectable, age_group_selectable); the title carries a unique token.
ROWS = (
    ("KZ20", "both", "neonate_infant"),
    ("KZ21", "both", "neonate"),
    ("KZ22", "both", "all"),
    ("GZ10", "female", "all"),
    ("GZ90", "male", "all"),
    ("GZ20", "both", "all"),
)
AGES = ("neonate", "infant", "child", "adult")


def _sql(clause) -> str:
    return str(clause.compile(compile_kwargs={"literal_binds": True}))


class NeonateInfantAgeMatchTests(unittest.TestCase):
    def _clauses(self, age_group):
        return (
            _sql(icd10_clause(MasIcd1020192, age_group=age_group, sex=None)),
            _sql(icd11_clause(age_group=age_group, sex=None)),
        )

    def test_matches_neonate_and_infant_submissions(self):
        for age_group in ("neonate", "infant"):
            for sql in self._clauses(age_group):
                self.assertIn("'neonate_infant'", sql, age_group)
                self.assertIn("'all'", sql, age_group)
                self.assertIn(f"'{age_group}'", sql, age_group)

    def test_does_not_match_child_or_adult_submissions(self):
        for age_group in ("child", "adult"):
            for sql in self._clauses(age_group):
                self.assertNotIn("neonate_infant", sql, age_group)
                self.assertIn("'all'", sql, age_group)
                self.assertIn(f"'{age_group}'", sql, age_group)

    def test_no_age_group_adds_no_age_condition(self):
        for sql in self._clauses(None):
            self.assertNotIn("age_group_selectable", sql)


class NeonateInfantRealRowTests(BaseTestCase):
    """The clause against rows in the database, not just its compiled SQL."""

    def setUp(self):
        super().setUp()
        for index, (code, sex, age) in enumerate(ROWS):
            db.session.add(
                MasIcd11Mms(
                    release=RELEASE,
                    linearization_uri=f"test://{code}",
                    code=code,
                    title=f"Zqneoinf {code}",
                    class_kind="category",
                    chapter_no="19",
                    sort_order=index,
                    source_version="test",
                    is_active=True,
                    is_coding_selectable=True,
                    sex_selectable=sex,
                    age_group_selectable=age,
                )
            )
            db.session.add(
                MasIcd1020192(
                    code=f"Y{code}",
                    title=f"Zqneoinf {code}",
                    node_type="category",
                    semantic_level="detailed_code",
                    sort_order=index,
                    source_version="test",
                    is_active=True,
                    is_coding_selectable=True,
                    sex_selectable=sex,
                    age_group_selectable=age,
                )
            )
        db.session.flush()

    def _hits(self, age_group, sex):
        icd11 = {
            r["icd_code"]
            for r in search_icd11_mms("Zqneoinf", release=RELEASE, age_group=age_group, sex=sex)
        }
        icd10 = {
            r["icd_code"][1:]
            for r in search_icd10_2019_2_coding_choices_for_policy(
                "Zqneoinf", age_group=age_group, sex=sex
            )
        }
        return icd11, icd10

    def test_age_matching_on_real_rows(self):
        expected = {
            "neonate": {"KZ20", "KZ21", "KZ22"},
            "infant": {"KZ20", "KZ22"},
            "child": {"KZ22"},
            "adult": {"KZ22"},
        }
        for age_group, codes in expected.items():
            for hits in self._hits(age_group, None):
                self.assertTrue({"KZ22", "GZ20"} <= hits, age_group)  # subject present
                self.assertEqual(hits & {"KZ20", "KZ21", "KZ22"}, codes, age_group)

    def test_sex_matching_on_real_rows(self):
        for age_group in AGES:
            for sex, present, absent in (("female", "GZ10", "GZ90"), ("male", "GZ90", "GZ10")):
                for hits in self._hits(age_group, sex):
                    self.assertIn(present, hits, (age_group, sex))
                    self.assertIn("GZ20", hits, (age_group, sex))
                    self.assertNotIn(absent, hits, (age_group, sex))
