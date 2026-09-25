"""Vocabulary expansion in the coding-search endpoints (digitva-zpe.1).

Covers the additive wiring in ``search_icd10_2019_2_coding_choices`` and
``search_icd11_mms``: matches rank first with the ``vocabulary`` flag, and a
target the endpoint's own policy filters exclude contributes nothing.

The vocabulary cache is process-global; every class clears it in setUp and
tearDown so rolled-back fixture rows can never leak into another test.
Run (inside Docker):
  docker compose exec -T minerva_app_service uv run --no-sync pytest \
    tests/services/test_coding_search_vocabulary.py -q -p no:cacheprovider
"""
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa

from app import db
from app.models import (
    MasIcd11Mms,
    MasIcd1020192,
    MasIcdSearchTerms,
    VaForms,
    VaStatuses,
    VaSubmissions,
)
from app.services.icd10_2019_2_service import search_icd10_2019_2_coding_choices
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE, search_icd11_mms
from app.services.icd_search_vocabulary_service import (
    clear_cache,
    create_term,
    set_active,
)
from tests.base import BaseTestCase

_ICD11_SOURCE_VERSION = "ICD-11-MMS-2026-01"
_FUTURE_RELEASE = "2099-01"


def _icd11_row(code, title, *, release=DEFAULT_ICD11_RELEASE, selectable=True, sex="both", age="all"):
    return MasIcd11Mms(
        release=release,
        linearization_uri=f"lin:{release}:{code}",
        code=code,
        title=title,
        class_kind="category",
        depth_in_kind=2,
        is_residual=False,
        is_leaf=True,
        is_coding_selectable=selectable,
        sex_selectable=sex,
        age_group_selectable=age,
        source_version=_ICD11_SOURCE_VERSION,
        source_path="test",
        is_active=True,
    )


def _icd10_row(code, title, *, selectable=True, sex="both", age="all"):
    return MasIcd1020192(
        code=code,
        title=title,
        node_type="category",
        semantic_level="three_character",
        source_version="ICD-10-2019",
        source_path="test",
        is_coding_selectable=selectable,
        sex_selectable=sex,
        age_group_selectable=age,
        is_active=True,
    )


def _vocabulary_flags_only(results):
    return [row["icd_code"] for row in results if row.get("vocabulary")]


class CodingSearchVocabularyTestCase(BaseTestCase):
    """Shared form/submission scaffolding; catalogue rows stay per class."""

    FORM_ID = "VOCAB1BS0101"
    SID_FEMALE = "uuid:test-icd-vocab-female"
    SID_MALE = "uuid:test-icd-vocab-male"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_base_research_project_and_site()
        if db.session.get(VaForms, cls.FORM_ID) is None:
            now = datetime.now(UTC)
            db.session.add(
                VaForms(
                    form_id=cls.FORM_ID,
                    project_id=cls.BASE_PROJECT_ID,
                    site_id=cls.BASE_SITE_ID,
                    odk_form_id="ICD_VOCAB_FORM",
                    odk_project_id="1",
                    form_type="WHO 2022 VA",
                    form_status=VaStatuses.active,
                    form_registered_at=now,
                    form_updated_at=now,
                )
            )
        db.session.commit()

    @classmethod
    def _submission(cls, va_sid, *, gender, age_years=42):
        now = datetime.now(UTC)
        return VaSubmissions(
            va_sid=va_sid,
            va_form_id=cls.FORM_ID,
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="tester",
            va_instance_name="ICD-VOCAB-1",
            va_uniqueid_real="ICD-VOCAB-1",
            va_uniqueid_masked="ICD-VOCAB-1",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=age_years,
            va_deceased_age_normalized_days=Decimal(age_years * 365),
            va_deceased_age_normalized_years=Decimal(age_years),
            va_deceased_gender=gender,
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )

    def setUp(self):
        super().setUp()
        clear_cache()
        db.session.execute(sa.delete(MasIcdSearchTerms))
        db.session.execute(
            sa.delete(VaSubmissions).where(
                VaSubmissions.va_sid.in_([self.SID_FEMALE, self.SID_MALE])
            )
        )
        db.session.add(self._submission(self.SID_FEMALE, gender="female"))
        db.session.add(self._submission(self.SID_MALE, gender="male"))
        db.session.flush()

    def tearDown(self):
        clear_cache()
        super().tearDown()


class Icd10CodingChoicesVocabularyTest(CodingSearchVocabularyTestCase):
    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(MasIcd1020192))
        db.session.add_all(
            [
                _icd10_row("I21", "Acute myocardial infarction"),
                _icd10_row("V89", "Motor- or nonmotor-vehicle accident, type of vehicle unspecified"),
                _icd10_row("I46", "Cardiac arrest", sex="male"),
                _icd10_row("B50", "Plasmodium falciparum malaria"),
            ]
        )
        db.session.flush()
        create_term(term="MI", icd_classification="icd10", icd_code="I21")
        create_term(term="RTA", icd_classification="icd10", icd_code="V89")
        create_term(term="cardiac arrest", icd_classification="icd10", icd_code="I46")

    def test_mi_returns_i21_first_with_vocabulary_flag(self):
        results = search_icd10_2019_2_coding_choices(self.SID_FEMALE, "MI")

        self.assertEqual(results[0]["icd_code"], "I21")
        self.assertIs(results[0]["vocabulary"], True)
        self.assertTrue(results[0]["icd_to_display"].startswith("MI — "))
        self.assertEqual(results[0]["tier"], "focused")
        # A lexical hit for the same code is promoted, never duplicated.
        self.assertEqual(
            [row["icd_code"] for row in results].count("I21"),
            1,
        )

    def test_rta_surfaces_its_target_with_vocabulary_display(self):
        results = search_icd10_2019_2_coding_choices(self.SID_FEMALE, "RTA")

        # RTA shares no substring with its title: reachable only via vocabulary.
        self.assertEqual(_vocabulary_flags_only(results), ["V89"])
        self.assertTrue(
            results[0]["icd_to_display"].startswith("RTA — V89 ")
        )

    def test_lexical_only_results_carry_no_vocabulary_flag(self):
        results = search_icd10_2019_2_coding_choices(self.SID_FEMALE, "malaria")

        self.assertEqual(
            [row["icd_code"] for row in results if row.get("vocabulary")],
            [],
        )
        self.assertEqual(results[0]["icd_code"], "B50")

    def test_tier_flags_focused_and_expanded_matches(self):
        # Exact code match: focused.
        exact = search_icd10_2019_2_coding_choices(self.SID_FEMALE, "B50")
        self.assertEqual(exact[0]["icd_code"], "B50")
        self.assertEqual(exact[0]["tier"], "focused")

        # Title prefix: focused.
        prefix = search_icd10_2019_2_coding_choices(self.SID_FEMALE, "plasmodium")
        self.assertEqual([row["tier"] for row in prefix], ["focused"])

        # Title contains but does not start with the query: expanded.
        contains = search_icd10_2019_2_coding_choices(self.SID_FEMALE, "malaria")
        self.assertEqual([row["tier"] for row in contains], ["expanded"])

        # Code prefix without an exact code match: expanded.
        code_prefix = search_icd10_2019_2_coding_choices(self.SID_FEMALE, "B5")
        self.assertEqual(code_prefix[0]["icd_code"], "B50")
        self.assertEqual([row["tier"] for row in code_prefix], ["expanded"])

    def test_policy_disabled_target_contributes_nothing(self):
        # Positive control: the machinery injects V89 for this query...
        healthy = search_icd10_2019_2_coding_choices(self.SID_FEMALE, "RTA")
        self.assertEqual(_vocabulary_flags_only(healthy), ["V89"])

        db.session.execute(
            sa.update(MasIcd1020192)
            .where(MasIcd1020192.code == "I21")
            .values(is_coding_selectable=False)
        )
        results = search_icd10_2019_2_coding_choices(self.SID_FEMALE, "MI")

        self.assertNotIn("I21", [row["icd_code"] for row in results])
        self.assertEqual(
            [row for row in results if row.get("vocabulary")],
            [],
        )

    def test_inactive_vocabulary_link_is_ignored(self):
        link = create_term(term="heart attack", icd_classification="icd10", icd_code="I21")
        set_active(str(link.term_id), False)

        self.assertEqual(
            search_icd10_2019_2_coding_choices(self.SID_FEMALE, "heart attack"),
            [],
        )

    def test_va_sid_age_and_sex_filter_respected(self):
        # I46 is male-only policy; the female death gets nothing injected...
        self.assertEqual(
            search_icd10_2019_2_coding_choices(self.SID_FEMALE, "cardiac arrest"),
            [],
        )
        # ...while the same query for the male death surfaces it flagged.
        results = search_icd10_2019_2_coding_choices(self.SID_MALE, "cardiac arrest")

        self.assertEqual(_vocabulary_flags_only(results), ["I46"])


class Icd11SearchVocabularyTest(CodingSearchVocabularyTestCase):
    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(MasIcd11Mms))
        db.session.add_all(
            [
                _icd11_row("BA41", "Acute myocardial infarction"),
                _icd11_row("1B10", "Tuberculosis"),
                _icd11_row("BA41", "Acute myocardial infarction, other release",
                           release=_FUTURE_RELEASE),
            ]
        )
        db.session.flush()
        create_term(term="MI", icd_classification="icd11", icd_code="BA41")
        create_term(term="kochs", icd_classification="icd11", icd_code="1B10")

    def test_mi_surfaces_ba41_when_policy_allows(self):
        results = search_icd11_mms("MI")

        self.assertEqual(results[0]["icd_code"], "BA41")
        self.assertIs(results[0]["vocabulary"], True)
        self.assertTrue(results[0]["icd_to_display"].startswith("MI — BA41 "))
        self.assertEqual(results[0]["tier"], "focused")
        self.assertEqual([row["icd_code"] for row in results].count("BA41"), 1)

    def test_lexical_search_unchanged(self):
        results = search_icd11_mms("tuberculosis")

        self.assertEqual([row["icd_code"] for row in results], ["1B10"])
        self.assertEqual(
            [row["icd_code"] for row in results if row.get("vocabulary")],
            [],
        )

    def test_tier_flags_focused_and_expanded_matches(self):
        # Exact code match: focused.
        exact = search_icd11_mms("BA41")
        self.assertEqual(exact[0]["icd_code"], "BA41")
        self.assertEqual(exact[0]["tier"], "focused")

        # Title prefix: focused.
        prefix = search_icd11_mms("tuberculosis")
        self.assertEqual(prefix[0]["tier"], "focused")

        # Title contains but does not start with the query: expanded.
        contains = search_icd11_mms("berculosis")
        self.assertEqual(contains[0]["icd_code"], "1B10")
        self.assertEqual(contains[0]["tier"], "expanded")

    def test_policy_filtered_target_not_injected(self):
        # Coding policy applies when a submission is in play: the positive
        # control (kochs -> selectable 1B10) reaches its target through the
        # same SID...
        control = search_icd11_mms("kochs", va_sid=self.SID_FEMALE)
        self.assertEqual(_vocabulary_flags_only(control), ["1B10"])

        db.session.execute(
            sa.update(MasIcd11Mms)
            .where(
                MasIcd11Mms.release == DEFAULT_ICD11_RELEASE,
                MasIcd11Mms.code == "BA41",
            )
            .values(is_coding_selectable=None)
        )
        results = search_icd11_mms("MI", va_sid=self.SID_FEMALE)

        self.assertNotIn("BA41", [row["icd_code"] for row in results])
        self.assertEqual(_vocabulary_flags_only(results), [])

    def test_release_filter_applies_to_vocabulary_targets(self):
        # "future term" -> ZZZ9 resolves only where the code exists in that
        # release's catalogue; the default release must not reach into
        # another release.
        db.session.add(_icd11_row("ZZZ9", "Future only code", release=_FUTURE_RELEASE))
        create_term(term="future term", icd_classification="icd11", icd_code="ZZZ9")

        self.assertEqual(_vocabulary_flags_only(search_icd11_mms("future term")), [])

        future = search_icd11_mms("future term", release=_FUTURE_RELEASE)
        self.assertEqual(_vocabulary_flags_only(future), ["ZZZ9"])

    def test_va_sid_age_and_sex_policy_respected(self):
        db.session.execute(
            sa.update(MasIcd11Mms)
            .where(
                MasIcd11Mms.release == DEFAULT_ICD11_RELEASE,
                MasIcd11Mms.code == "BA41",
            )
            .values(age_group_selectable="child")
        )
        # Adult death: the child-only target is filtered out for the SID...
        with_adult_sid = search_icd11_mms("MI", va_sid=self.SID_FEMALE)
        self.assertEqual(_vocabulary_flags_only(with_adult_sid), [])

        # ...and without a submission in play the target is injected.
        self.assertEqual(_vocabulary_flags_only(search_icd11_mms("MI")), ["BA41"])
