"""Public ICD-to-VA-cause mapping list: origin derived against the 2026 annex (digitva-712.3).

Policy: docs/policy/icd10-to-icd11-transition.md section 7. The unit tests run
the real annex (resource/ copy) against a small synthetic ICD-11 catalogue, so
each origin rule is pinned by a code whose answer is known. The DB tests seed a
scheme and check one build, the cache and the filters.
"""

import filecmp
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
        for index, (code, title, parent) in enumerate(CATALOGUE):
            db.session.add(
                MasIcd11Mms(
                    release=RELEASE, linearization_uri=f"test712://{code}",
                    parent_linearization_uri=f"test712://{parent}" if parent else None,
                    code=code, title=title, class_kind="category", chapter_no="01",
                    sort_order=index, source_version="test", is_active=True,
                )
            )
    if db.session.get(MasIcd1020192, "K70.2") is None:
        db.session.add(
            MasIcd1020192(
                code="K70.2", title="Alcoholic fibrosis and sclerosis of liver",
                node_type="category", semantic_level="four_character", sort_order=1,
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

    def icd10(self, code, node):
        return service.derive_origin(code, node, service.icd10_claims(code, self.annex))

    def icd11(self, code, node, match_type="range"):
        return service.derive_origin(code, node, self.annex["icd11"].get(code, {}), match_type)

    def test_annex_cell_with_missing_separator_gives_both_ranges(self):
        ranges = service.parse_icd10_ranges("K40-K69; K70-K93 L00-L99; M00-M99")
        self.assertIn(("K70-K93", "K70", "K93"), ranges)
        self.assertIn(("L00-L99", "L00", "L99"), ranges)
        self.assertEqual(self.icd10("L05", "vas_98"), (service.ORIGIN_WHO, ""))

    def test_icd10_range_is_prefix_ordered(self):
        self.assertTrue(service.icd10_in_range("A41.9", "A40", "A41"))
        self.assertTrue(service.icd10_in_range("A40", "A40", "A41"))
        self.assertFalse(service.icd10_in_range("A42", "A40", "A41"))
        self.assertTrue(service.icd10_in_range("K70.2", "K70.2", "K70.2"))
        self.assertFalse(service.icd10_in_range("K70", "K70.2", "K70.2"))
        self.assertFalse(service.icd10_in_range("I46.1", "I27", "I46.0"))

    def test_code_in_one_annex_range_is_who(self):
        self.assertEqual(self.icd10("A41.9", "vas_01_01"), (service.ORIGIN_WHO, ""))

    def test_specific_code_beating_a_range_is_who_resolved(self):
        self.assertEqual(
            self.icd10("K70.2", "vas_06_02"),
            (service.ORIGIN_WHO_RESOLVED, "Specific code beats range"),
        )

    def test_narrower_icd10_range_is_who_resolved(self):
        # X10-X19 is printed for VAs-12.99 and inside VAs-12.05's X00-X19.
        self.assertEqual(
            self.icd10("X15", "vas_12_99"),
            (service.ORIGIN_WHO_RESOLVED, "Narrowest range wins"),
        )

    def test_carried_override_is_digitva(self):
        self.assertIn("vas_98", service.icd10_claims("K72", self.annex))
        self.assertEqual(self.icd10("K72", "vas_06_02"), (service.ORIGIN_DIGITVA, ""))

    def test_bucket_that_is_not_a_va_cause_is_digitva(self):
        self.assertEqual(self.icd10("K75", "other_gastrointestinal_diseases"), (service.ORIGIN_DIGITVA, ""))

    def test_code_outside_every_annex_range_is_digitva(self):
        self.assertEqual(service.icd10_claims("I11", self.annex), {})
        self.assertEqual(self.icd10("I11", "vas_04_01"), (service.ORIGIN_DIGITVA, ""))

    def test_transport_follows_footnote_f(self):
        self.assertEqual(self.icd10("V01.1", "vas_12_01"), (service.ORIGIN_WHO, ""))
        self.assertEqual(self.icd10("V01.0", "vas_12_02"), (service.ORIGIN_WHO, ""))
        self.assertEqual(self.icd10("Y85.0", "vas_12_01"), (service.ORIGIN_WHO, ""))
        # Footnote f's tail (water/air/other transport, Y85.9) is not road traffic.
        self.assertEqual(self.icd10("V90.1", "vas_12_02"), (service.ORIGIN_WHO, ""))
        self.assertEqual(self.icd10("Y85.9", "vas_12_02"), (service.ORIGIN_WHO, ""))
        self.assertEqual(self.icd10("V01.1", "vas_12_02"), (service.ORIGIN_DIGITVA, ""))

    def test_ruptured_uterus_matched_by_label(self):
        self.assertEqual(self.icd10("O71.0", "vas_09_08"), (service.ORIGIN_WHO, ""))

    def test_icd11_single_claim_is_who(self):
        self.assertEqual(self.icd11("1G40", "vas_01_01"), (service.ORIGIN_WHO, ""))

    def test_icd11_pa_split_is_who_resolved(self):
        origin, rule = self.icd11("PA00", "vas_12_01", match_type="split")
        self.assertEqual(origin, service.ORIGIN_WHO_RESOLVED)
        self.assertIn("Transport split", rule)

    def test_icd11_pj2x_names_the_owner_decision(self):
        origin, rule = self.icd11("PJ20", "vas_12_09", match_type="split")
        self.assertEqual(origin, service.ORIGIN_WHO_RESOLVED)
        self.assertIn("maltreatment by others to Assault", rule)

    def test_fresh_stillbirth_wins_over_the_perinatal_range(self):
        # KD3B.1 is also inside VAs-10.99's KD30.2-KD5Z, so it is resolved, not plain WHO.
        self.assertEqual(
            set(self.annex["icd11"]["KD3B.1"]), {"vas_11_01", "vas_10_99"},
        )
        self.assertEqual(
            self.icd11("KD3B.1", "vas_11_01"),
            (service.ORIGIN_WHO_RESOLVED, "Specific code beats range"),
        )

    def test_code_who_lists_for_two_causes_names_the_choice(self):
        # WHO prints P95 for both Fresh and Macerated stillbirth.
        self.assertEqual(set(service.icd10_claims("P95", self.annex)), {"vas_11_01", "vas_11_02"})
        origin, rule = self.icd10("P95", "vas_11_02")
        self.assertEqual(origin, service.ORIGIN_WHO_RESOLVED)
        self.assertIn("same code for more than one cause", rule)

    def test_every_icd10_annex_token_is_parsed(self):
        # A malformed token would silently drop that cause's range.
        import csv
        import re
        with open(service.ANNEX_PATH, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                tokens = [t for t in re.split(r"[;,\s]+", row["icd10_codes"].upper()) if t]
                parsed = [token for token, _, _ in service.parse_icd10_ranges(row["icd10_codes"])]
                self.assertEqual(tokens, parsed, row["va_code"])

    def test_owner_decisions_of_2026_09_24_derive_as_digitva(self):
        # Decision 11: WHO's ICD-10 column gives A80 to Unspecified infectious.
        self.assertIn("vas_01_99", service.icd10_claims("A80", self.annex))
        self.assertEqual(self.icd10("A80", "vas_01_07"), (service.ORIGIN_DIGITVA, ""))
        # Decision 12: footnote f does not list boarding/alighting codes as road traffic.
        self.assertIn("vas_12_02", service.icd10_claims("V10.3", self.annex))
        self.assertEqual(self.icd10("V10.3", "vas_12_01"), (service.ORIGIN_DIGITVA, ""))
        # Decision 9: KD3B sits in the perinatal range, not a stillbirth one.
        self.assertIn("vas_10_99", self.annex["icd11"]["KD3B"])
        self.assertEqual(self.icd11("KD3B", "vas_11_02", "owner_decision"), (service.ORIGIN_DIGITVA, ""))
        # Decisions 5a/5b: a code in no annex range.
        self.assertEqual(self.icd11("5A22", "vas_03_03", "owner_decision"), (service.ORIGIN_DIGITVA, ""))

    def test_icd11_row_moved_off_its_annex_cause_is_digitva(self):
        self.assertEqual(self.icd11("1G40", "vas_98"), (service.ORIGIN_DIGITVA, ""))

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
        self.assertEqual(by_code["K72"]["origin"], service.ORIGIN_DIGITVA)
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

    def test_unknown_scheme_gives_no_rows(self):
        self.assertEqual(service.get_public_mappings(scheme_code="NO_SUCH_SCHEME", release=RELEASE), ([], []))

    def test_filters(self):
        rows, _ = self.build()
        codes = lambda found: {row["code"] for row in found}  # noqa: E731
        self.assertEqual(codes(service.filter_mappings(rows, classification="icd11")), {"PA00", "1G40"})
        self.assertEqual(codes(service.filter_mappings(rows, origin="digitva")), {"K72", "K75"})
        self.assertEqual(codes(service.filter_mappings(rows, va_code="VAs-06.02")), {"K70.2", "K72"})
        self.assertEqual(codes(service.filter_mappings(rows, q="sepsis")), {"1G40"})
        self.assertEqual(codes(service.filter_mappings(rows, q="LIVER CIRRHOSIS")), {"K70.2", "K72"})
        self.assertEqual(service.filter_mappings(rows, q="nothing matches this"), [])
        self.assertEqual(len(service.filter_mappings(rows)), 5)
