"""Public ICD-to-VA-cause mapping list: origin derived against the 2026 annex (digitva-712.3).

Policy: docs/policy/icd10-to-icd11-transition.md section 7. The unit tests run
the real annex (resource/ copy) against a small synthetic ICD-11 catalogue, so
each origin rule is pinned by a code whose answer is known. The DB tests seed a
scheme and check one build, the cache and the filters.
"""

import filecmp
import unittest
import uuid
from pathlib import Path

from app import db
from app.models import (
    MapIcdCodBucket,
    MasCodBucketNode,
    MasCodBucketScheme,
    MasIcd11Mms,
    MasIcd1020192,
)
from app.services import va_code_mapping_public_service as service
from app.services.cod_bucket_mapping_service import _slugify
from tests.base import BaseTestCase

RELEASE = "TEST-712.3"
WHO_REASON = "WHO lists this code for this cause."

# (code, title, parent) -- enough to exercise the annex ranges that share codes.
CATALOGUE = (
    ("1G40", "Sepsis without septic shock", None),
    ("KD30.2", "Birth asphyxia, severe", None),
    ("KD3B", "Fetal death", None),
    ("KD3B.0", "Antepartum fetal death", "KD3B"),
    ("KD3B.1", "Intrapartum fetal death", "KD3B"),
    ("PA00", "Unintentional land transport traffic event injuring a pedestrian", None),
    ("PA10", "Unintentional land transport nontraffic event injuring a pedestrian", None),
    ("PJ20", "Physical maltreatment", None),
)
# Codes the fixture marks selectable; the rest are not (digitva-xud).
SELECTABLE = {"1G40", "KD3B", "KD3B.1"}
# Hierarchy for the compare and ICD-11 state views: top-level catalogue codes
# sit in an inner block inside an outer block inside chapter 01, and one
# chapter X extension code is out of scope.
CHAPTER_URI, OUTER_BLOCK_URI, INNER_BLOCK_URI = "test712://ch01", "test712://blk1", "test712://blk2"


def annex_nodes() -> dict[str, str]:
    """`{node_code: label}` of every annex cause, as the live scheme has them."""
    rows = service._read_csv(service.ANNEX_PATH)
    nodes = {_slugify(r["va_code"], fallback_prefix=""): r["va_title"] for r in rows}
    nodes["vas_09_08"] = nodes.pop("vas_09_0")  # annex prints VAs-09.0
    return nodes


def seed_public_mapping_fixture(rows):
    """Seed a scheme with every annex cause node, one non-VA node, the given
    `(classification, code, node_code, match_type)` rows and the synthetic
    catalogue. Commits (inside the class transaction); returns the scheme."""
    scheme = MasCodBucketScheme(
        scheme_code=f"TEST_PUB_{uuid.uuid4().hex[:8].upper()}",
        scheme_name="Public mapping test", mapping_version=1, is_active=True,
    )
    db.session.add(scheme)
    db.session.flush()
    nodes = {}
    labels = {**annex_nodes(), "other_gastrointestinal_diseases": "Other Gastrointestinal Diseases"}
    for order, (node_code, label) in enumerate(labels.items(), start=1):
        nodes[node_code] = MasCodBucketNode(
            scheme_id=scheme.scheme_id, age_scope=None, node_type="field",
            node_code=node_code, node_label=label, sort_order=order,
        )
    db.session.add_all(nodes.values())
    db.session.flush()
    for classification, code, node_code, match_type in rows:
        db.session.add(
            MapIcdCodBucket(
                scheme_id=scheme.scheme_id, age_scope=None, icd_classification=classification,
                icd_code=code, node_id=nodes[node_code].node_id, match_type=match_type,
                mapping_note=f"note for {code}", is_active=True,
            )
        )
    if not db.session.scalar(
        db.select(MasIcd11Mms.id).where(MasIcd11Mms.release == RELEASE).limit(1)
    ):
        hierarchy = (
            (CHAPTER_URI, None, "chapter", None, "Certain infectious or parasitic diseases", None),
            (OUTER_BLOCK_URI, CHAPTER_URI, "block", "BlockL1-TST", "Outer test block", None),
            (INNER_BLOCK_URI, OUTER_BLOCK_URI, "block", "BlockL2-TST", "Inner test block", None),
            ("test712://XA00", None, "category", None, "Extension code", "XA00"),
        )
        for index, (uri, parent_uri, kind, block_id, title, code) in enumerate(hierarchy, start=-10):
            db.session.add(
                MasIcd11Mms(
                    release=RELEASE, linearization_uri=uri, parent_linearization_uri=parent_uri,
                    code=code, block_id=block_id, title=title, class_kind=kind,
                    chapter_no="X" if code == "XA00" else "01",
                    sort_order=index, source_version="test", is_active=True,
                )
            )
        for index, (code, title, parent) in enumerate(CATALOGUE):
            db.session.add(
                MasIcd11Mms(
                    release=RELEASE, linearization_uri=f"test712://{code}",
                    parent_linearization_uri=f"test712://{parent}" if parent else INNER_BLOCK_URI,
                    code=code, title=title, class_kind="category", chapter_no="01",
                    is_coding_selectable=code in SELECTABLE,
                    sort_order=index, source_version="test", is_active=True,
                )
            )
    if db.session.get(MasIcd1020192, "K70.2") is None:
        db.session.add(
            MasIcd1020192(
                code="K70.2", title="Alcoholic fibrosis and sclerosis of liver",
                node_type="category", semantic_level="four_character", sort_order=1,
                chapter_code="XI", chapter_title="Diseases of the digestive system",
                block_code="K70-K77", block_title="Diseases of liver",
                source_version="test", is_active=True,
            )
        )
    db.session.commit()
    return scheme


class OriginDerivationTests(BaseTestCase):
    """Pure derivation against the real annex and a synthetic catalogue."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        catalogue = {code: {"title": title, "parent": parent} for code, title, parent in CATALOGUE}
        cls.annex = service.build_annex_claims(
            service._read_csv(service.ANNEX_PATH),
            service._read_csv(service.FOOTNOTES_PATH),
            annex_nodes(),
            catalogue,
        )

    def icd10(self, code, node, match_type=None, mapping_note=""):
        return service.derive_origin(code, node, service.icd10_claims(code, self.annex), match_type, mapping_note)

    def icd11(self, code, node, match_type="range", mapping_note=""):
        return service.derive_origin(code, node, self.annex["icd11"].get(code, {}), match_type, mapping_note)

    def test_annex_cell_with_missing_separator_gives_both_ranges(self):
        ranges = service.parse_icd10_ranges("K40-K69; K70-K93 L00-L99; M00-M99")
        self.assertIn(("K70-K93", "K70", "K93"), ranges)
        self.assertIn(("L00-L99", "L00", "L99"), ranges)
        self.assertEqual(self.icd10("L05", "vas_98"), (service.ORIGIN_WHO, WHO_REASON))

    def test_icd10_range_is_prefix_ordered(self):
        self.assertTrue(service.icd10_in_range("A41.9", "A40", "A41"))
        self.assertTrue(service.icd10_in_range("A40", "A40", "A41"))
        self.assertFalse(service.icd10_in_range("A42", "A40", "A41"))
        self.assertTrue(service.icd10_in_range("K70.2", "K70.2", "K70.2"))
        self.assertFalse(service.icd10_in_range("K70", "K70.2", "K70.2"))
        self.assertFalse(service.icd10_in_range("I46.1", "I27", "I46.0"))

    def test_code_in_one_annex_range_is_who(self):
        self.assertEqual(self.icd10("A41.9", "vas_01_01"), (service.ORIGIN_WHO, WHO_REASON))

    def test_specific_code_beating_a_range_is_who_resolved(self):
        self.assertEqual(
            self.icd10("K70.2", "vas_06_02"),
            (service.ORIGIN_WHO_RESOLVED, "WHO names this code directly for this cause"),
        )

    def test_narrower_icd10_range_is_who_resolved(self):
        # X10-X19 is printed for VAs-12.99 and inside VAs-12.05's X00-X19.
        self.assertEqual(
            self.icd10("X15", "vas_12_99"),
            (service.ORIGIN_WHO_RESOLVED, "WHO's more specific range"),
        )

    def test_code_claimed_by_who_for_another_cause_differs(self):
        self.assertIn("vas_98", service.icd10_claims("K72", self.annex))
        self.assertEqual(
            self.icd10("K72", "vas_06_02"),
            (service.ORIGIN_DIFFERS, "WHO lists this code for another cause; expert review chose this cause."),
        )

    def test_bucket_that_is_not_a_va_cause_differs_if_who_lists_another_cause(self):
        self.assertEqual(
            self.icd10("K75", "other_gastrointestinal_diseases"),
            (service.ORIGIN_DIFFERS, "WHO lists this code for another cause; expert review chose this cause."),
        )

    def test_code_outside_every_annex_range_is_not_in_who(self):
        self.assertEqual(service.icd10_claims("I11", self.annex), {})
        self.assertEqual(
            self.icd10("I11", "vas_04_01"),
            (service.ORIGIN_NOT_IN_WHO, "Not in WHO's list; placed after expert review."),
        )

    def test_transport_follows_footnote_f(self):
        self.assertEqual(self.icd10("V01.1", "vas_12_01"), (service.ORIGIN_WHO, WHO_REASON))
        self.assertEqual(self.icd10("V01.0", "vas_12_02"), (service.ORIGIN_WHO, WHO_REASON))
        self.assertEqual(self.icd10("Y85.0", "vas_12_01"), (service.ORIGIN_WHO, WHO_REASON))
        # Footnote f's tail (water/air/other transport, Y85.9) is not road traffic.
        self.assertEqual(self.icd10("V90.1", "vas_12_02"), (service.ORIGIN_WHO, WHO_REASON))
        self.assertEqual(self.icd10("Y85.9", "vas_12_02"), (service.ORIGIN_WHO, WHO_REASON))
        self.assertEqual(
            self.icd10("V01.1", "vas_12_02"),
            (service.ORIGIN_DIFFERS, "WHO lists this code for another cause; expert review chose this cause."),
        )

    def test_ruptured_uterus_matched_by_label(self):
        self.assertEqual(self.icd10("O71.0", "vas_09_08"), (service.ORIGIN_WHO, WHO_REASON))

    def test_icd11_single_claim_is_who(self):
        self.assertEqual(self.icd11("1G40", "vas_01_01"), (service.ORIGIN_WHO, WHO_REASON))

    def test_icd11_pa_split_is_who_resolved(self):
        origin, rule = self.icd11("PA00", "vas_12_01", match_type="split")
        self.assertEqual(origin, service.ORIGIN_WHO_RESOLVED)
        self.assertEqual(rule, "Traffic events count as road traffic, others as other transport")

    def test_icd11_pj2x_names_the_owner_decision(self):
        origin, rule = self.icd11("PJ20", "vas_12_09", match_type="split")
        self.assertEqual(origin, service.ORIGIN_WHO_RESOLVED)
        self.assertEqual(rule, "Maltreatment by others counts as Assault")

    def test_fresh_stillbirth_wins_over_the_perinatal_range(self):
        # KD3B.1 is also inside VAs-10.99's KD30.2-KD5Z, so it is resolved, not plain WHO.
        self.assertEqual(
            set(self.annex["icd11"]["KD3B.1"]), {"vas_11_01", "vas_10_99"},
        )
        self.assertEqual(
            self.icd11("KD3B.1", "vas_11_01"),
            (service.ORIGIN_WHO_RESOLVED, "WHO names this code directly for this cause"),
        )

    def test_code_who_lists_for_two_causes_names_the_choice(self):
        # WHO prints P95 for both Fresh and Macerated stillbirth.
        self.assertEqual(set(service.icd10_claims("P95", self.annex)), {"vas_11_01", "vas_11_02"})
        origin, rule = self.icd10("P95", "vas_11_02")
        self.assertEqual(origin, service.ORIGIN_WHO_RESOLVED)
        self.assertEqual(rule, "WHO lists it for two causes and the code cannot tell them apart")

    def test_every_icd10_annex_token_is_parsed(self):
        # A malformed token would silently drop that cause's range.
        import csv
        import re
        with open(service.ANNEX_PATH, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                tokens = [t for t in re.split(r"[;,\s]+", row["icd10_codes"].upper()) if t]
                parsed = [token for token, _, _ in service.parse_icd10_ranges(row["icd10_codes"])]
                self.assertEqual(tokens, parsed, row["va_code"])

    def test_reviewed_changes_derive_plain_reasons(self):
        # Decision 11: WHO's ICD-10 column gives A80 to Unspecified infectious.
        self.assertIn("vas_01_99", service.icd10_claims("A80", self.annex))
        self.assertEqual(
            self.icd10(
                "A80", "vas_01_07", "owner_decision",
                "Owner decision 11 (2026-09-24): viral infections of the central nervous system go to Meningitis/encephalitis",
            ),
            (
                service.ORIGIN_DIFFERS,
                "Viral infections of the brain and spinal cord count as Meningitis/encephalitis, as in ICD-11",
            ),
        )
        # Decision 12: footnote f does not list boarding/alighting codes as road traffic.
        self.assertIn("vas_12_02", service.icd10_claims("V10.3", self.annex))
        self.assertEqual(
            self.icd10(
                "V10.3", "vas_12_01", "owner_decision",
                "Owner decision 12 (2026-09-24): person injured while boarding or alighting goes to Road traffic",
            ),
            (
                service.ORIGIN_DIFFERS,
                "Injured boarding or alighting a vehicle counts as Road traffic, as in WHO's ICD-10 to ICD-11 table",
            ),
        )
        # Decision 9: KD3B sits in the perinatal range, not a stillbirth one.
        self.assertIn("vas_10_99", self.annex["icd11"]["KD3B"])
        self.assertEqual(
            self.icd11(
                "KD3B", "vas_11_02", "owner_decision",
                "Owner decision 9 (2026-09-24): Fetal death with unknown timing -> Macerated stillbirth, as ICD-10 P95",
            ),
            (
                service.ORIGIN_DIFFERS,
                "Time of fetal death unknown; counted as Macerated stillbirth, like ICD-10 P95",
            ),
        )
        # Decisions 5a/5b: a code in no annex range.
        self.assertEqual(
            self.icd11(
                "5A22", "vas_03_03", "owner_decision",
                "Owner decision 5a (2026-09-24): Diabetic acute complications, in no annex range",
            ),
            (service.ORIGIN_NOT_IN_WHO, "Not in WHO's list; placed by clinical review (Diabetic acute complications)"),
        )

    def test_icd11_row_moved_off_its_annex_cause_differs(self):
        self.assertEqual(
            self.icd11("1G40", "vas_98"),
            (service.ORIGIN_DIFFERS, "WHO lists this code for another cause; expert review chose this cause."),
        )

    def test_fallback_decision_without_crosswalk_is_not_cod(self):
        note = "Owner decision 5b (2026-09-24): no annex range and no usable single-bucket crosswalk suggestion"
        self.assertEqual(
            self.icd11("1H00", "vas_99", "owner_fallback", note),
            (
                service.ORIGIN_NOT_COD,
                "Never selectable — WHO's cause list does not include it. Mapped to Unknown only so no record can go unreported.",
            ),
        )

    def test_fallback_decision_with_crosswalk_is_not_in_who(self):
        note = "Owner decision 5b (2026-09-24): crosswalk E75 suggests vas_98"
        self.assertEqual(
            self.icd11("1H00", "vas_98", "owner_fallback", note),
            (service.ORIGIN_NOT_IN_WHO, "Not in WHO's list; follows its ICD-10 equivalent E75"),
        )

    def test_ba5x_overlap_uses_its_icd10_equivalent_reason(self):
        claims = {"vas_04_01": (4, "BA50-BA5Z"), "vas_04_02": (10, "BA50-BA5Z")}
        note = "Owner decision 10 (2026-09-24): Mirrors ICD-10 I25 override (I25.x -> BA5x in WHO 10To11)"
        self.assertEqual(
            service.derive_origin("BA50", "vas_04_01", claims, "owner_decision", note),
            (service.ORIGIN_WHO_RESOLVED, "Reported the same way as its ICD-10 equivalent I25"),
        )

    def test_decision_tooltip_shows_only_expert_review_number_and_date(self):
        note = "Owner decision 12 (2026-09-24): internal text with vas_12_01 and override"
        self.assertEqual(service._review_tooltip(note), "Expert review decision 12 (2026-09-24)")

    def test_remaining_review_reasons_are_plain_language(self):
        cases = (
            (
                "Owner decision 4 (2026-09-24): Annex token 5C52.Y-5C52-Z read as 5C52.Y-5C52.Z",
                "WHO's range has a typo here; read as intended",
            ),
            (
                "Owner decision 10 (2026-09-24): heart failure is Acute cardiac in both classifications",
                "Heart failure counts as Acute cardiac disease in ICD-10 and ICD-11",
            ),
            (
                "Owner decision 16 (2026-09-25): WHO assumes traffic for unspecified vehicle accidents",
                "Traffic not stated; counted as road traffic, following WHO's ICD-10 rule",
            ),
            (
                "Owner decision 17 (2026-09-25): WHO's ICD-10 traffic assumption applied by analogy",
                "Traffic not stated; counted as road traffic, following WHO's ICD-10 rule",
            ),
            (
                "Carried forward from an existing manual override to match ICD-10 historical records",
                "Kept from DigitVA's earlier ICD-10 mapping for older records",
            ),
        )
        for note, expected in cases:
            with self.subTest(note=note):
                self.assertEqual(service._review_reason(note), expected)

    def test_csv_cell_neutralises_formulas(self):
        self.assertEqual(service.csv_cell("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(service.csv_cell("K70.2"), "K70.2")
        self.assertEqual(service.csv_cell(""), "")

    def test_resource_annex_copies_match_docs(self):
        docs = Path(service._REPO_ROOT) / "docs/icd-causegrp-mappings/ICD-to-VA-Buckets"
        if not docs.is_dir():
            self.skipTest("docs/ is not present in this image")
        for path in (service.ANNEX_PATH, service.FOOTNOTES_PATH):
            self.assertTrue(filecmp.cmp(path, docs / path.name, shallow=False), path.name)


class PublicMappingBuildTests(BaseTestCase):
    """One build from the database, the cache key, and the filters."""

    def setUp(self):
        super().setUp()
        self.scheme = seed_public_mapping_fixture([
            ("icd10", "K70.2", "vas_06_02", "exact"),
            ("icd10", "K72", "vas_06_02", "range"),
            ("icd10", "K75", "other_gastrointestinal_diseases", "range"),
            ("icd11", "PA00", "vas_12_01", "split"),
            ("icd11", "1G40", "vas_01_01", "range"),
        ])

    def build(self):
        return service.get_public_mappings(scheme_code=self.scheme.scheme_code, release=RELEASE)

    def test_rows_carry_titles_va_cause_and_origin(self):
        rows, va_causes = self.build()
        by_code = {row["code"]: row for row in rows}
        self.assertEqual(set(by_code), {"K70.2", "K72", "K75", "PA00", "1G40"})
        self.assertEqual(by_code["K70.2"]["code_title"], "Alcoholic fibrosis and sclerosis of liver")
        self.assertEqual(by_code["K70.2"]["origin"], service.ORIGIN_WHO_RESOLVED)
        self.assertEqual(by_code["K70.2"]["also_claimed_by"], "VAs-98")
        self.assertEqual(by_code["K72"]["origin"], service.ORIGIN_DIFFERS)
        self.assertEqual(by_code["K75"]["va_code"], "")
        self.assertEqual(by_code["K75"]["va_title"], "Other Gastrointestinal Diseases")
        self.assertEqual(by_code["1G40"]["code_title"], "Sepsis without septic shock")
        self.assertEqual(by_code["1G40"]["origin"], service.ORIGIN_WHO)
        self.assertEqual(by_code["PA00"]["origin"], service.ORIGIN_WHO_RESOLVED)
        self.assertEqual(by_code["1G40"]["note"], "note for 1G40")
        self.assertIn(("VAs-06.02", "Liver cirrhosis"), va_causes)

    def test_edit_is_seen_on_next_load_and_inactive_rows_are_hidden(self):
        rows, _ = self.build()
        self.assertIn("K72", {row["code"] for row in rows})
        k72 = db.session.scalar(
            db.select(MapIcdCodBucket).where(
                MapIcdCodBucket.scheme_id == self.scheme.scheme_id, MapIcdCodBucket.icd_code == "K72"
            )
        )
        k72.node_id = db.session.scalar(
            db.select(MasCodBucketNode.node_id).where(
                MasCodBucketNode.scheme_id == self.scheme.scheme_id, MasCodBucketNode.node_code == "vas_98"
            )
        )
        db.session.commit()
        rows, _ = self.build()
        k72_row = next(row for row in rows if row["code"] == "K72")
        self.assertEqual((k72_row["va_code"], k72_row["origin"]), ("VAs-98", service.ORIGIN_WHO))

        k72.is_active = False
        db.session.commit()
        rows, _ = self.build()
        self.assertIn("K70.2", {row["code"] for row in rows})
        self.assertNotIn("K72", {row["code"] for row in rows})

    def test_icd11_title_edit_is_seen_on_next_load(self):
        # digitva-yog: a title change in mas_icd11_mms alone must refresh the
        # mapping-row cache. PA00's title is asserted nowhere else.
        rows, _ = self.build()
        pa00 = next(row for row in rows if row["code"] == "PA00")
        self.assertTrue(pa00["code_title"].startswith("Unintentional land transport"))
        catalogue_row = db.session.scalar(
            db.select(MasIcd11Mms).where(
                MasIcd11Mms.release == RELEASE, MasIcd11Mms.code == "PA00"
            )
        )
        catalogue_row.title = "Unintentional land transport traffic event, retitled"
        db.session.commit()
        rows, _ = self.build()
        pa00 = next(row for row in rows if row["code"] == "PA00")
        self.assertEqual(pa00["code_title"], "Unintentional land transport traffic event, retitled")

    def test_unknown_scheme_gives_no_rows(self):
        self.assertEqual(service.get_public_mappings(scheme_code="NO_SUCH_SCHEME", release=RELEASE), ([], []))

    def test_filters(self):
        rows, _ = self.build()
        codes = lambda found: {row["code"] for row in found}  # noqa: E731
        self.assertEqual(codes(service.filter_mappings(rows, classification="icd11")), {"PA00", "1G40"})
        self.assertEqual(codes(service.filter_mappings(rows, origin="digitva")), {"K72", "K75"})
        self.assertEqual(codes(service.filter_mappings(rows, origin=service.ORIGIN_DIFFERS)), {"K72", "K75"})
        alias_rows = rows + [
            {**rows[0], "code": "TEST-NOT-IN-WHO", "origin": service.ORIGIN_NOT_IN_WHO},
            {**rows[0], "code": "TEST-NOT-COD", "origin": service.ORIGIN_NOT_COD},
        ]
        self.assertEqual(
            codes(service.filter_mappings(alias_rows, origin=service.ORIGIN_NOT_IN_WHO)),
            {"TEST-NOT-IN-WHO"},
        )
        self.assertEqual(
            codes(service.filter_mappings(alias_rows, origin=service.ORIGIN_DIGITVA)),
            {"K72", "K75", "TEST-NOT-IN-WHO", "TEST-NOT-COD"},
        )
        self.assertEqual(codes(service.filter_mappings(rows, va_code="VAs-06.02")), {"K70.2", "K72"})
        self.assertEqual(codes(service.filter_mappings(rows, q="sepsis")), {"1G40"})
        self.assertEqual(codes(service.filter_mappings(rows, q="LIVER CIRRHOSIS")), {"K70.2", "K72"})
        self.assertEqual(service.filter_mappings(rows, q="nothing matches this"), [])
        self.assertEqual(len(service.filter_mappings(rows)), 5)


class Icd11CatalogueAndCompareTests(BaseTestCase):
    """Hierarchy, the ICD-11 state view and the compare trees (digitva-xud)."""

    def setUp(self):
        super().setUp()
        self.scheme = seed_public_mapping_fixture([
            ("icd10", "K70.2", "vas_06_02", "exact"),
            ("icd10", "K72", "vas_06_02", "range"),
            ("icd11", "1G40", "vas_01_01", "range"),
            ("icd11", "KD3B.1", "vas_11_01", "range"),
        ])
        self.rows, _ = service.get_public_mappings(scheme_code=self.scheme.scheme_code, release=RELEASE)
        self.catalogue = service.get_icd11_catalogue(RELEASE)

    def test_catalogue_is_the_generator_scope_with_outermost_block(self):
        self.assertIn("KD3B.0", self.catalogue)
        self.assertNotIn("XA00", self.catalogue)  # chapter X is out of scope
        entry = self.catalogue["KD3B.0"]  # category under a category under two blocks
        self.assertEqual(entry["chapter"], ("01", "Certain infectious or parasitic diseases"))
        self.assertEqual(entry["block"], ("BlockL1-TST", "Outer test block"))
        self.assertEqual(list(self.catalogue)[0], "1G40")  # WHO order

    def test_selectable_filter_splits_the_catalogue(self):
        everything = service.filter_icd11_catalogue(self.catalogue)
        yes = service.filter_icd11_catalogue(self.catalogue, selectable="yes")
        no = service.filter_icd11_catalogue(self.catalogue, selectable="no")
        self.assertEqual(set(yes), SELECTABLE)
        self.assertIn("KD3B.0", no)
        self.assertNotIn("KD3B.0", yes)
        self.assertEqual(sorted(yes + no), sorted(everything))
        self.assertEqual(service.filter_icd11_catalogue(self.catalogue, q="fetal", selectable="no"), ["KD3B.0"])
        self.assertEqual(len(service.filter_icd11_catalogue(self.catalogue, q="outer test block")), len(CATALOGUE))

    def test_states_show_mapping_or_unmapped(self):
        states = {
            state["code"]: state
            for state in service.icd11_code_states(list(self.catalogue), self.catalogue, self.rows)
        }
        self.assertEqual((states["1G40"]["va_code"], states["1G40"]["origin"]), ("VAs-01.01", service.ORIGIN_WHO))
        self.assertEqual(
            service.public_origin_display(states["1G40"])["note"],
            "WHO lists this code for this cause.",
        )
        self.assertIn("KD3B.0", states)
        self.assertEqual((states["KD3B.0"]["va_code"], states["KD3B.0"]["origin"]), ("", ""))
        self.assertEqual(service.count_unmapped_icd11(self.catalogue, self.rows), len(CATALOGUE) - 2)
        csv_row = service.icd11_state_csv_row(states["KD3B.0"])
        self.assertEqual(csv_row[:6], [
            "KD3B.0", "Antepartum fetal death", "01 Certain infectious or parasitic diseases",
            "Outer test block", "no", "unreviewed",
        ])

    def test_origin_filter_needs_rows(self):
        # 1G40 is WHO (single icd11 claim); KD3B.1 is who_resolved (specific
        # code beats the perinatal range); everything else is unmapped.
        self.assertEqual(
            service.filter_icd11_catalogue(self.catalogue, self.rows, origin=service.ORIGIN_WHO), ["1G40"],
        )
        self.assertEqual(
            service.filter_icd11_catalogue(self.catalogue, self.rows, origin=service.ORIGIN_WHO_RESOLVED),
            ["KD3B.1"],
        )
        unmapped = service.filter_icd11_catalogue(self.catalogue, self.rows, origin="unmapped")
        self.assertEqual(set(unmapped), set(self.catalogue) - {"1G40", "KD3B.1"})
        legacy_rows = self.rows + [
            {"classification": "icd11", "code": "PA00", "origin": service.ORIGIN_NOT_IN_WHO},
            {"classification": "icd11", "code": "PJ20", "origin": service.ORIGIN_DIFFERS},
            {"classification": "icd11", "code": "KD3B.0", "origin": service.ORIGIN_NOT_COD},
        ]
        self.assertEqual(
            set(service.filter_icd11_catalogue(self.catalogue, legacy_rows, origin=service.ORIGIN_DIGITVA)),
            {"PA00", "PJ20", "KD3B.0"},
        )
        self.assertNotIn(service.ORIGIN_DIGITVA, service.ICD11_ORIGIN_FILTER_LABELS)
        # No origin filter: rows is not consulted, matches every code.
        self.assertEqual(
            sorted(service.filter_icd11_catalogue(self.catalogue)), sorted(self.catalogue),
        )

    def test_policy_status_filter(self):
        row = db.session.scalar(
            db.select(MasIcd11Mms).where(MasIcd11Mms.release == RELEASE, MasIcd11Mms.code == "1G40")
        )
        row.policy_status = "reviewed"
        db.session.commit()
        catalogue = service.get_icd11_catalogue(RELEASE)
        reviewed = service.filter_icd11_catalogue(catalogue, policy_status="reviewed")
        unreviewed = service.filter_icd11_catalogue(catalogue, policy_status="unreviewed")
        self.assertEqual(reviewed, ["1G40"])
        self.assertNotIn("1G40", unreviewed)
        self.assertEqual(len(reviewed) + len(unreviewed), len(catalogue))

    def test_catalogue_edit_is_seen_on_next_load(self):
        self.assertFalse(self.catalogue["KD3B.0"]["selectable"])
        row = db.session.scalar(
            db.select(MasIcd11Mms).where(MasIcd11Mms.release == RELEASE, MasIcd11Mms.code == "KD3B.0")
        )
        row.is_coding_selectable = True
        db.session.commit()
        self.assertTrue(service.get_icd11_catalogue(RELEASE)["KD3B.0"]["selectable"])

    def test_compare_trees_group_both_classifications(self):
        trees = service.compare_trees(self.rows, "VAs-06.02", self.catalogue)
        by_id = {node["id"]: node for node in trees["icd10"]}
        self.assertEqual(by_id["K70.2"]["parent_id"], "b:XI:K70-K77")
        self.assertEqual(by_id["b:XI:K70-K77"]["parent_id"], "c:XI")
        self.assertEqual(by_id["c:XI"]["title"], "Chapter XI: Diseases of the digestive system")
        self.assertEqual(by_id["K70.2"]["cells"]["origin"]["badge"], service.ORIGIN_LABELS[service.ORIGIN_WHO_RESOLVED])
        self.assertIn("WHO names this code directly for this cause", by_id["K70.2"]["cells"]["origin"]["note"])
        self.assertEqual(by_id["K70.2"]["cells"]["origin"]["title"], "")
        self.assertEqual(trees["icd11"], [])

        trees = service.compare_trees(self.rows, "VAs-01.01", self.catalogue)
        ids = [node["id"] for node in trees["icd11"]]
        self.assertEqual(ids, ["c:01", "b:01:BlockL1-TST", "1G40"])  # parents before children
        self.assertEqual(trees["icd11"][2]["title"], "1G40 Sepsis without septic shock")

    def test_compare_tree_keeps_public_reason_and_sanitized_tooltip(self):
        rows = [dict(row) for row in self.rows]
        row = next(item for item in rows if item["code"] == "K70.2")
        row["rule"] = "Injured boarding or alighting a vehicle counts as Road traffic"
        row["note"] = "Owner decision 12 (2026-09-24): crosswalk vas_12_01 10To11 override"
        cell = next(
            node["cells"]["origin"]
            for node in service.compare_trees(rows, "VAs-06.02", self.catalogue)["icd10"]
            if node.get("id") == "K70.2"
        )
        self.assertIn("Injured boarding or alighting a vehicle", cell["note"])
        self.assertEqual(cell["title"], "Expert review decision 12 (2026-09-24)")
        self.assertNotIn("Owner decision", repr(cell))
        self.assertNotIn("crosswalk", repr(cell))

    def test_icd10_catalogue_edit_reaches_the_compare_view(self):
        k70_2 = db.session.get(MasIcd1020192, "K70.2")
        self.assertIsNotNone(k70_2)
        k70_2.block_title = "Renamed liver block"
        db.session.commit()
        rows, _ = service.get_public_mappings(scheme_code=self.scheme.scheme_code, release=RELEASE)
        titles = {node["title"] for node in service.compare_trees(rows, "VAs-06.02", self.catalogue)["icd10"]}
        self.assertIn("K70-K77 Renamed liver block", titles)

    def test_tree_nodes_keep_leaves_without_hierarchy(self):
        nodes = service.tree_nodes([
            (("", ""), ("", ""), "Z99", "<b>not a tag</b>", {}),
        ])
        self.assertEqual(nodes[0], {"id": "c:", "parent_id": None, "expanded": True, "title": "Not in the catalogue"})
        self.assertEqual(nodes[1]["parent_id"], "c:")
        self.assertEqual(nodes[1]["title"], "Z99 <b>not a tag</b>")  # escaped by |tojson and textContent



class Icd11BlockPagesTests(unittest.TestCase):
    """icd11_block_pages: no DB, a block never straddles two pages (digitva-x67)."""

    @staticmethod
    def _catalogue(block_sizes):
        """`{code: entry}` for `[(block_id, count), ...]`, one chapter, WHO order."""
        catalogue = {}
        for block_id, count in block_sizes:
            for i in range(count):
                catalogue[f"{block_id}-{i:03d}"] = {"chapter": ("01", "Chapter"), "block": (block_id, block_id)}
        return catalogue

    def test_a_block_straddling_the_old_page_boundary_lands_whole_on_one_page(self):
        # 90 + 30 would split at a naive fixed-size-100 boundary; block-aligned
        # paging keeps the second block whole even though the page then holds 120.
        catalogue = self._catalogue([("A", 90), ("B", 30)])
        pages = service.icd11_block_pages(list(catalogue), catalogue, 100)
        self.assertEqual([len(p) for p in pages], [120])
        self.assertTrue(all(code.startswith("B") for code in pages[0][90:]))

    def test_a_block_bigger_than_the_target_gets_its_own_page(self):
        catalogue = self._catalogue([("A", 150), ("B", 10)])
        pages = service.icd11_block_pages(list(catalogue), catalogue, 100)
        self.assertEqual([len(p) for p in pages], [150, 10])
        self.assertTrue(all(code.startswith("A") for code in pages[0]))
        self.assertTrue(all(code.startswith("B") for code in pages[1]))

    def test_page_count_and_totals_stay_truthful(self):
        catalogue = self._catalogue([("A", 60), ("B", 60), ("C", 60)])
        codes = list(catalogue)
        pages = service.icd11_block_pages(codes, catalogue, 100)
        self.assertEqual(sum(len(p) for p in pages), len(codes))
        self.assertEqual(sorted(code for page in pages for code in page), sorted(codes))
        # A+B=120 already >= 100, so C starts its own page.
        self.assertEqual([len(p) for p in pages], [120, 60])

    def test_codes_with_no_block_group_by_chapter(self):
        catalogue = {
            "X1": {"chapter": ("09", "Chapter 9"), "block": ("", "")},
            "X2": {"chapter": ("09", "Chapter 9"), "block": ("", "")},
            "Y1": {"chapter": ("10", "Chapter 10"), "block": ("", "")},
        }
        pages = service.icd11_block_pages(list(catalogue), catalogue, 100)
        self.assertEqual(pages, [["X1", "X2", "Y1"]])  # all fit on one page

    def test_empty_codes_gives_no_pages(self):
        self.assertEqual(service.icd11_block_pages([], {}, 100), [])
