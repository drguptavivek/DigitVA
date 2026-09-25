"""Tests for the COD search vocabulary service (digitva-zpe.1).

The vocabulary cache is process-global, so every class here clears it in
setUp and tearDown: a class transaction's rows roll back, and a stale cache
that still believes in them would feed phantom matches to unrelated search
tests. Run (inside Docker):
  docker compose exec -T minerva_app_service uv run --no-sync pytest \
    tests/services/test_icd_search_vocabulary_service.py -q -p no:cacheprovider
"""
import csv
import unittest
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models import MasIcd1020192, MasIcd11Mms, MasIcdSearchTerms
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE
from app.services.icd_search_vocabulary_service import (
    clear_cache,
    code_in_catalogue,
    create_term,
    list_terms,
    merge_vocabulary_results,
    normalize_term,
    set_active,
    update_term,
    vocabulary_matches,
)
from tests.base import BaseTestCase

_REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_CSV_PATH = _REPO_ROOT / "resource" / "icd_search_vocabulary_seed.csv"


def _seed_csv_rows():
    with SEED_CSV_PATH.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class NormalizeTermTest(unittest.TestCase):
    """Pure function: no database needed."""

    def test_matches_every_seed_row_term_normalized(self):
        mismatches = [
            row
            for row in _seed_csv_rows()
            if normalize_term(row["term"]) != row["term_normalized"]
        ]
        self.assertEqual(mismatches, [])

    def test_normalization_variants(self):
        cases = {
            "MI": "mi",
            "  CVA  ": "cva",
            "Koch's disease": "koch s disease",
            "diabetes (mellitus)(obese): adult-onset": "diabetes mellitus obese adult-onset",
            "any condition in I50.-, I51.4-I51.9": "any condition in i50 - i51 4-i51 9",
            "non-insulin-dependent": "non-insulin-dependent",
            "": "",
            "   ": "",
        }
        for raw, expected in cases.items():
            self.assertEqual(normalize_term(raw), expected, raw)


class VocabularyServiceTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        clear_cache()
        db.session.execute(sa.delete(MasIcdSearchTerms))
        db.session.flush()

    def tearDown(self):
        clear_cache()
        super().tearDown()


class VocabularyMatchesTest(VocabularyServiceTestCase):
    def _add(self, term, classification, code, is_active=True):
        row = MasIcdSearchTerms(
            term=term,
            term_normalized=normalize_term(term),
            icd_classification=classification,
            icd_code=code,
            source="admin",
            is_active=is_active,
        )
        db.session.add(row)
        db.session.flush()
        return row

    def test_exact_match_returns_active_links_only(self):
        icd10 = self._add("MI", "icd10", "I21")
        icd11 = self._add("MI", "icd11", "BA41")
        inactive = self._add("MI", "icd10", "I22", is_active=False)
        self._add("CVA", "icd10", "I64")

        matches = vocabulary_matches("MI")

        self.assertEqual([row["icd_code"] for row in matches], ["I21", "BA41"])
        self.assertEqual(
            [str(row["term_id"]) for row in matches],
            [str(icd10.term_id), str(icd11.term_id)],
        )
        self.assertNotIn(inactive.icd_code, [row["icd_code"] for row in matches])

    def test_classification_filter_narrows_to_one_catalogue(self):
        self._add("MI", "icd10", "I21")
        self._add("MI", "icd11", "BA41")

        icd10_only = vocabulary_matches("MI", classification="icd10")

        self.assertEqual([row["icd_code"] for row in icd10_only], ["I21"])
        self.assertTrue(all(row["icd_classification"] == "icd10" for row in icd10_only))

    def test_lookup_normalizes_the_query(self):
        self._add("Cerebrovascular Accident", "icd10", "I64")

        self.assertEqual(
            [row["icd_code"] for row in vocabulary_matches("  cerebrovascular  ACCIDENT ")],
            ["I64"],
        )

    def test_no_prefix_or_fuzzy_matching(self):
        # Positive control first: the machinery finds MI at all.
        self._add("MI", "icd10", "I21")
        self.assertEqual(len(vocabulary_matches("MI")), 1)

        self.assertEqual(vocabulary_matches("Miliary"), [])
        self.assertEqual(vocabulary_matches("MIA"), [])
        self.assertEqual(vocabulary_matches(""), [])


class CacheInvalidationTest(VocabularyServiceTestCase):
    def test_writes_take_effect_on_the_next_search(self):
        row = create_term(term="RTA", icd_classification="icd10", icd_code="V89")
        self.assertEqual(
            [hit["icd_code"] for hit in vocabulary_matches("rta")], ["V89"]
        )

        update_term(
            str(row.term_id),
            term="road traffic accident",
            icd_classification="icd10",
            icd_code="V89",
        )
        self.assertEqual(vocabulary_matches("rta"), [])
        self.assertEqual(
            [hit["icd_code"] for hit in vocabulary_matches("road traffic accident")],
            ["V89"],
        )

        set_active(str(row.term_id), False)
        self.assertEqual(vocabulary_matches("road traffic accident"), [])

        set_active(str(row.term_id), True)
        self.assertEqual(
            [hit["icd_code"] for hit in vocabulary_matches("road traffic accident")],
            ["V89"],
        )


class AdminCrudTest(VocabularyServiceTestCase):
    def test_create_derives_the_normalized_key(self):
        row = create_term(
            term="  Chest Infection!  ",
            icd_classification="icd11",
            icd_code="ca40",
            note="shorthand",
        )
        self.assertEqual(row.term, "Chest Infection!")
        self.assertEqual(row.term_normalized, "chest infection")
        self.assertEqual(row.icd_code, "CA40")
        self.assertEqual(row.source, "admin")
        self.assertTrue(row.is_active)

    def test_create_rejects_invalid_input(self):
        with self.assertRaises(ValueError):
            create_term(term="X", icd_classification="icd9", icd_code="X00")
        with self.assertRaises(ValueError):
            create_term(term="  ", icd_classification="icd10", icd_code="X00")
        with self.assertRaises(ValueError):
            create_term(term="X", icd_classification="icd10", icd_code="")
        with self.assertRaises(ValueError):
            create_term(term="X", icd_classification="icd10", icd_code="X00", source="scraped")

    def test_update_and_set_active_reject_unknown_or_bad_input(self):
        row = create_term(term="AKI", icd_classification="icd10", icd_code="N17")
        unknown_id = "00000000-0000-0000-0000-000000000000"

        with self.assertRaises(LookupError):
            update_term(unknown_id, term="AKI", icd_classification="icd10", icd_code="N17")
        with self.assertRaises(LookupError):
            set_active(unknown_id, False)
        with self.assertRaises(ValueError):
            set_active(str(row.term_id), "yes")

    def test_list_terms_searches_and_pages(self):
        for index in range(3):
            create_term(
                term=f"shorthand {index}", icd_classification="icd10", icd_code=f"A0{index}"
            )
        create_term(term="cva", icd_classification="icd11", icd_code="8B20")
        inactive = create_term(term="hidden term", icd_classification="icd10", icd_code="A99")
        set_active(str(inactive.term_id), False)

        listed = list_terms(search="shorthand", page=1, per_page=2)
        self.assertEqual(listed["total"], 3)
        self.assertEqual(listed["pages"], 2)
        self.assertEqual([row["term"] for row in listed["rows"]], ["shorthand 0", "shorthand 1"])

        by_code = list_terms(search="8B20")
        self.assertEqual([row["term"] for row in by_code["rows"]], ["cva"])

        everything = list_terms()
        # Inactive rows stay listed (deactivation is the audit trail).
        self.assertEqual(everything["total"], 5)
        self.assertIn("hidden term", [row["term"] for row in everything["rows"]])


class MergeVocabularyResultsTest(unittest.TestCase):
    """Pure function: ranking and dedupe, no database."""

    def test_vocabulary_ranks_first_and_promotes_lexical_hits(self):
        lexical = [
            {"icd_code": "B50", "title": "Falciparum malaria"},
            {"icd_code": "I21", "title": "Acute myocardial infarction"},
        ]
        vocabulary = [
            {"icd_code": "I21", "vocabulary": True, "term": "MI"},
            {"icd_code": "V89", "vocabulary": True, "term": "RTA"},
        ]

        merged = merge_vocabulary_results(lexical, vocabulary)

        self.assertEqual(
            [(row["icd_code"], row.get("vocabulary")) for row in merged],
            [("I21", True), ("V89", True), ("B50", None)],
        )
        # The promoted lexical row keeps its own display shape.
        self.assertEqual(merged[0]["title"], "Acute myocardial infarction")

    def test_lexical_hit_never_appears_twice(self):
        lexical = [{"icd_code": "I64", "title": "Stroke"}]
        vocabulary = [{"icd_code": "I64", "vocabulary": True}]

        merged = merge_vocabulary_results(lexical, vocabulary)

        self.assertEqual([row["icd_code"] for row in merged], ["I64"])


class CodeInCatalogueTest(VocabularyServiceTestCase):
    def setUp(self):
        super().setUp()
        db.session.add(
            MasIcd1020192(
                code="I21",
                title="Acute myocardial infarction",
                node_type="category",
                semantic_level="three_character",
                source_version="ICD-10-2019",
                is_active=True,
            )
        )
        db.session.add(
            MasIcd11Mms(
                release=DEFAULT_ICD11_RELEASE,
                linearization_uri="lin:BA41",
                code="BA41",
                title="Acute myocardial infarction",
                class_kind="category",
                source_version="ICD-11-MMS-2026-01",
                is_active=True,
            )
        )
        db.session.flush()

    def test_known_codes_resolve_and_unknown_do_not(self):
        self.assertTrue(code_in_catalogue("icd10", "I21"))
        self.assertTrue(code_in_catalogue("icd11", "BA41"))
        self.assertFalse(code_in_catalogue("icd10", "I99"))
        self.assertFalse(code_in_catalogue("icd11", "ZZ99"))

    def test_case_is_normalized_before_lookup(self):
        self.assertTrue(code_in_catalogue("icd10", "i21"))


if __name__ == "__main__":
    unittest.main()
