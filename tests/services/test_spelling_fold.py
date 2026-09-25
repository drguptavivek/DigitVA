"""Spelling-fold and hyphen-insensitive matching for the coding searches.

digitva-zpe.3. Mechanism (docs/policy/icd-coding-search-vocabulary.md):
localspelling (MIT) word map plus a 22-entry medical supplement, applied as
spelling variants x hyphen forms to the lexical endpoints, the vocabulary
lookup, ``result_tier`` and the admin panel search — one helper everywhere
(``icd_search_vocabulary_service.spelling_variants``).

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/services/test_spelling_fold.py -q
"""

import csv
from pathlib import Path

from app.services.icd_search_vocabulary_service import (
    _MEDICAL_SPELLING_SUPPLEMENT,
    _NON_TERM_CHARS,
    _compact_key,
    _query_lookup_keys,
    normalize_term,
    spelling_variants,
)
from tests.base import BaseTestCase

_REPO_ROOT = Path(__file__).resolve().parents[2]

# 34 medical pairs the localspelling word map itself converts (verified
# round-trip), spanning the ae/oe/our/re/ise/lyse taxonomy categories.
LIBRARY_PAIRS = [
    ("anaemia", "anemia"),
    ("diarrhoea", "diarrhea"),
    ("oedema", "edema"),
    ("tumour", "tumor"),
    ("paralyse", "paralyze"),
    ("centre", "center"),
    ("fibre", "fiber"),
    ("paediatric", "pediatric"),
    ("aetiology", "etiology"),
    ("coeliac", "celiac"),
    ("haemorrhage", "hemorrhage"),
    ("manoeuvre", "maneuver"),
    ("orthopaedic", "orthopedic"),
    ("haemoglobin", "hemoglobin"),
    ("oesophagus", "esophagus"),
    ("foetal", "fetal"),
    ("gynaecology", "gynecology"),
    ("anaesthesia", "anesthesia"),
    ("haemolytic", "hemolytic"),
    ("haemophilia", "hemophilia"),
    ("paediatrician", "pediatrician"),
    ("foetus", "fetus"),
    ("favour", "favor"),
    ("behaviour", "behavior"),
    ("labour", "labor"),
    ("rigour", "rigor"),
    ("anaemic", "anemic"),
    ("mould", "mold"),
    ("smoulder", "smolder"),
    ("tumours", "tumors"),
    ("haemorrhoids", "hemorrhoids"),
    ("hydrolyse", "hydrolyze"),
    ("analyse", "analyze"),
    ("organise", "organize"),
]

# Words that are identical in both conventions must pass through untouched.
UNCHANGED_PHRASES = [
    "aerobic",
    "anaerobic",
    "humoral",
    "does",
    "goes",
    "fever",
    "does the patient have fever",
]


class SpellingVariantsTest(BaseTestCase):
    def test_uk_and_us_queries_reach_both_spellings(self):
        self.assertEqual(spelling_variants("anaemia"), ["anaemia", "anemia"])
        self.assertEqual(spelling_variants("anemia"), ["anemia", "anaemia"])

    def test_supplement_pairs_fold_both_directions(self):
        for uk, us in _MEDICAL_SPELLING_SUPPLEMENT.items():
            with self.subTest(pair=(uk, us)):
                self.assertIn(us, spelling_variants(uk))
                self.assertIn(uk, spelling_variants(us))

    def test_normalization_lowercases_and_collapses(self):
        self.assertEqual(spelling_variants("  Anaemia   tropica  ")[0], "anaemia tropica")

    def test_identical_in_both_conventions_stays_unchanged(self):
        for phrase in UNCHANGED_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertEqual(spelling_variants(phrase), [phrase])

    def test_empty_query_has_no_variants(self):
        self.assertEqual(spelling_variants(""), [])
        self.assertEqual(spelling_variants(None), [])

    def test_normalize_term_folds_to_the_us_key(self):
        self.assertEqual(normalize_term("septicaemia"), "septicemia")
        self.assertEqual(normalize_term("septicemia"), "septicemia")
        self.assertEqual(normalize_term("self-harm"), "self-harm")
        self.assertEqual(normalize_term("Koch's disease"), "koch s disease")

    def test_query_lookup_keys_carry_spelling_and_hyphen_forms(self):
        self.assertEqual(
            _query_lookup_keys("self harm"), {"self harm", "selfharm"}
        )
        self.assertEqual(
            _query_lookup_keys("septicaemia"), {"septicaemia", "septicemia"}
        )


class FoldRoundTripPropertyTest(BaseTestCase):
    def test_taxonomy_round_trips_both_directions(self):
        pairs = list(LIBRARY_PAIRS) + list(_MEDICAL_SPELLING_SUPPLEMENT.items())
        self.assertGreaterEqual(len(pairs), 54)
        for uk, us in pairs:
            with self.subTest(pair=(uk, us)):
                self.assertIn(us, spelling_variants(uk), f"UK {uk} must reach {us}")
                self.assertIn(uk, spelling_variants(us), f"US {us} must reach {uk}")


class CatalogueNonCollisionPropertyTest(BaseTestCase):
    """Folding must never merge two titles that were distinct.

    Data is the real in-repo catalogue material: the frozen ICD-11 MMS
    2026-01 hierarchy (35k titles) and the authored vocabulary seed. The
    ICD-10 2019 catalogue lives only in the database; it is covered by the
    same property in the reported one-off check against dev (12,475 titles,
    0 collisions).
    """

    def _titles(self):
        path = _REPO_ROOT / "resource" / "icd11_mms_2026_01_hierarchy.csv"
        with path.open(newline="", encoding="utf-8") as handle:
            return [
                row["title"].strip().lower()
                for row in csv.DictReader(handle)
                if row.get("title")
            ]

    def _seed_keys(self):
        path = _REPO_ROOT / "resource" / "icd_search_vocabulary_seed.csv"
        with path.open(newline="", encoding="utf-8") as handle:
            return [
                row["term_normalized"].strip()
                for row in csv.DictReader(handle)
                if row.get("term_normalized")
            ]

    def _merged_groups(self, values, normalize=normalize_term):
        """Fold to the given canonical key; return only the groups that
        merged previously-distinct values."""
        folded: dict[str, set[str]] = {}
        for value in {value for value in values if value}:
            folded.setdefault(normalize(value), set()).add(value)
        return {
            canonical: originals
            for canonical, originals in folded.items()
            if len(originals) > 1
        }

    def test_icd11_titles_never_collide_under_the_fold(self):
        titles = self._titles()
        self.assertGreater(len(titles), 30_000)

        def normalize_without_fold(value):
            return " ".join(_NON_TERM_CHARS.sub(" ", value.lower()).split())

        preexisting = set(self._merged_groups(titles, normalize_without_fold))
        for canonical, originals in self._merged_groups(titles).items():
            if canonical in preexisting:
                # Merged by plain normalization already (punctuation shapes
                # like "del(5q)" vs "del (5q)") — not the fold's doing.
                continue
            for original in originals:
                others = set(originals) - {original}
                reachable = _query_lookup_keys(original) | {
                    _compact_key(original)
                }
                self.assertTrue(
                    others <= reachable,
                    f"fold merged unrelated titles: {originals} -> {canonical}",
                )

    def test_seed_keys_only_merge_with_their_own_spelling_variants(self):
        # The seed deliberately holds both spellings of a term
        # (septicaemia/septicemia): those unifying IS the feature. A merge is
        # legitimate only when every member is a spelling or hyphen variant
        # of the others.
        seed_keys = self._seed_keys()
        self.assertGreater(len(seed_keys), 100)
        for canonical, originals in self._merged_groups(seed_keys).items():
            for original in originals:
                others = set(originals) - {original}
                reachable = _query_lookup_keys(original) | {
                    original.replace("-", "")
                }
                self.assertTrue(
                    others <= reachable,
                    f"fold merged unrelated seed keys: {originals} -> {canonical}",
                )
