"""Policy-excluded matches reported beside the coding search (digitva-e5j).

Excluded rows explain an empty/short result; they are never selectable and
cost one extra bounded query.
"""

import sqlalchemy as sa

from app import db
from app.models import MasIcd11Mms, MasIcd1020192
from app.services.coding_search_explain import explained_payload
from app.services.icd10_2019_2_service import (
    excluded_icd10_2019_2_matches,
    search_icd10_2019_2_coding_choices_for_policy,
)
from app.services.icd11_mms_service import excluded_icd11_mms_matches, search_icd11_mms
from tests.base import BaseTestCase

RELEASE = "TEST-EXCL"
TOKEN = "Zqexcl"
# (code, sex, age); titles carry the unique token.
ROWS = (
    ("KX10", "both", "neonate"),
    ("KX11", "both", "neonate_infant"),
    ("KX12", "female", "all"),
    ("KX13", "both", "all"),
    ("KX14", "male", "adult"),
)


class CodingSearchExcludedTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        for index, (code, sex, age) in enumerate(ROWS):
            db.session.add(
                MasIcd11Mms(
                    release=RELEASE,
                    linearization_uri=f"test://{code}",
                    code=code,
                    title=f"{TOKEN} {code}",
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
                    title=f"{TOKEN} {code}",
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
        # Admin-disabled row: matches the text and would fail the age rule for
        # an adult, but disabled codes are never reported as age/sex exclusions.
        db.session.add(
            MasIcd1020192(
                code="YOFF",
                title=f"{TOKEN} disabled",
                node_type="category",
                semantic_level="detailed_code",
                sort_order=0,
                source_version="test",
                is_active=True,
                is_coding_selectable=False,
                sex_selectable="both",
                age_group_selectable="neonate",
            )
        )
        db.session.flush()

    def _icd10(self, age_group, sex):
        results = search_icd10_2019_2_coding_choices_for_policy(
            TOKEN, age_group=age_group, sex=sex
        )
        return results, excluded_icd10_2019_2_matches(
            TOKEN, age_group=age_group, sex=sex, selectable_count=len(results)
        )

    def _icd11(self, age_group, sex):
        results = search_icd11_mms(TOKEN, release=RELEASE, age_group=age_group, sex=sex)
        return results, excluded_icd11_mms_matches(
            TOKEN, age_group=age_group, sex=sex, selectable_count=len(results), release=RELEASE
        )

    def test_infant_female_excludes_neonate_only_and_male_only_adult(self):
        for results, excluded in (self._icd10("infant", "female"), self._icd11("infant", "female")):
            codes = {r["icd_code"].removeprefix("Y") for r in results}
            self.assertEqual(codes, {"KX11", "KX12", "KX13"})  # subject present
            self.assertEqual(excluded["count"], 2)
            reasons = {e["code"].removeprefix("Y"): e["reason"] for e in excluded["examples"]}
            self.assertEqual(reasons, {"KX10": "neonate only", "KX14": "adult only, male only"})
            self.assertFalse(codes & set(reasons))  # excluded never selectable

    def test_sex_restricted_code_reason(self):
        results, excluded = self._icd10("neonate", "male")
        self.assertNotIn("YKX12", {r["icd_code"] for r in results})
        self.assertEqual(
            {e["code"]: e["reason"] for e in excluded["examples"]}["YKX12"], "female only"
        )

    def test_nothing_filtered_means_no_excluded(self):
        # Adult male with a query only the always-allowed row matches.
        results = search_icd10_2019_2_coding_choices_for_policy(
            "KX13", age_group="adult", sex="male"
        )
        self.assertEqual([r["icd_code"] for r in results], ["YKX13"])
        self.assertIsNone(
            excluded_icd10_2019_2_matches(
                "KX13", age_group="adult", sex="male", selectable_count=len(results)
            )
        )
        body = explained_payload(
            results, classification="icd10", query="KX13", age_group="adult", sex="male"
        )
        self.assertNotIn("excluded", body)

    def test_admin_disabled_rows_are_not_reported_as_policy_exclusions(self):
        _, excluded = self._icd10("adult", "male")
        self.assertIsNotNone(excluded)
        self.assertTrue(excluded["examples"])
        self.assertNotIn("YOFF", {e["code"] for e in excluded["examples"]})

    def test_unknown_age_and_sex_report_nothing(self):
        self.assertIsNone(
            excluded_icd10_2019_2_matches(TOKEN, age_group=None, sex=None, selectable_count=0)
        )

    def test_full_page_skips_the_lookup(self):
        self.assertIsNone(
            excluded_icd10_2019_2_matches(TOKEN, age_group="infant", sex="female", selectable_count=30)
        )

    def test_examples_capped_and_count_exact(self):
        for index in range(5):
            db.session.add(
                MasIcd1020192(
                    code=f"YN{index}",
                    title=f"{TOKEN} extra {index}",
                    node_type="category",
                    semantic_level="detailed_code",
                    sort_order=20 + index,
                    source_version="test",
                    is_active=True,
                    is_coding_selectable=True,
                    sex_selectable="both",
                    age_group_selectable="neonate",
                )
            )
        db.session.flush()

        _, excluded = self._icd10("adult", "female")

        self.assertEqual(len(excluded["examples"]), 3)
        self.assertEqual(excluded["count"], 8)  # KX10, KX11, KX14 + 5 extra
        self.assertIn("and 5 more", excluded["message"])

    def test_one_extra_query(self):
        statements = []

        def count(conn, cursor, statement, *args):
            statements.append(statement)

        engine = db.session.get_bind()
        sa.event.listen(engine, "before_cursor_execute", count)
        try:
            excluded_icd10_2019_2_matches(TOKEN, age_group="infant", sex="female", selectable_count=0)
            excluded_icd11_mms_matches(
                TOKEN, age_group="infant", sex="female", selectable_count=0, release=RELEASE
            )
        finally:
            sa.event.remove(engine, "before_cursor_execute", count)

        self.assertEqual(len(statements), 2)  # one per classification
        self.assertTrue(all("LIMIT" in s.upper() for s in statements))
