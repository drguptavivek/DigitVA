"""Native ICD-11 bucket generator (digitva-712.1).

Policy: docs/policy/icd11-cod-bucket-schemes.md ("Native method"). Runs
against a small synthetic catalogue release and cause list so each rule --
range expansion, more specific wins, ties, the PA and PJ2x splits, the
crosswalk cross-check -- is pinned by a code whose answer is known.
"""

import csv
import tempfile
from pathlib import Path

import sqlalchemy as sa
from openpyxl import Workbook

from app import db
from app.models import MapIcdCodBucket, MasCodBucketNode, MasCodBucketScheme, MasIcd11Mms
from app.services.cod_bucket_icd11_generator import (
    apply_icd11_generation,
    expand_range,
    generate_icd11_buckets,
    parse_icd11_ranges,
    write_icd11_generation_report,
)
from tests.base import BaseTestCase

RELEASE = "TEST-712"
SCHEME_CODE = "TEST_ICD11_GEN"
CURATED_CODE = "TEST_ICD11_CURATED"

# (code, title, parent code, chapter)
CATALOGUE = (
    ("1D00", "Infectious encephalitis", None, "01"),
    ("1D00.0", "Encephalitis, specified", "1D00", "01"),
    ("1D20", "Dengue without warning signs", None, "01"),
    ("1D21", "Dengue with warning signs", None, "01"),
    ("1D2Z", "Dengue, unspecified", None, "01"),
    ("1D40", "Yellow fever", None, "01"),
    ("1D4Z", "Haemorrhagic fever, unspecified", None, "01"),
    ("1D90", "Viral infection of unspecified site", None, "01"),
    ("8A00", "Parkinsonism", None, "08"),
    ("JB0A", "Rupture of uterus", None, "18"),
    ("JB0A.0", "Rupture of uterus before onset of labour", "JB0A", "18"),
    ("KD3B", "Stillbirth", None, "19"),
    ("KD3B.1", "Fresh stillbirth", "KD3B", "19"),
    ("PA00", "Unintentional land transport traffic event injuring a pedestrian", None, "23"),
    ("PA10", "Unintentional land transport nontraffic event injuring a pedestrian", None, "23"),
    ("PA20", "Unintentional land transport event unknown whether traffic or nontraffic injuring a pedestrian", None, "23"),
    ("PA40", "Unintentional water transport injury event", None, "23"),
    ("PA40.0", "Unintentional water transport injury event causing drowning", "PA40", "23"),
    ("PJ20", "Physical maltreatment", None, "23"),
    ("PJ2Z", "Maltreatment, unspecified", None, "23"),
    ("QA00", "Health examination", None, "24"),
    ("XA0001", "An extension code", None, "X"),
)

CAUSE_ROWS = (
    ("VAs-01.11", "Haemorrhagic fever", "1D00-1D4Z"),
    ("VAs-01.12", "Dengue fever", "1D20-1D2Z"),
    ("VAs-01.99", "Unspecified infectious disease", "1D00-1D9Z"),
    ("VAs-12.01", "Road traffic accident", "PA00-PA5Z"),
    ("VAs-12.02", "Other transport accident", "PA00-PA5Z"),
    ("VAs-12.09", "Assault", "PJ20-PJ2Z"),
    ("VAs-12.99", "Other and unspecified external cause of death", "PJ20-PJ2Z"),
    ("VAs-98", "Other and unspecified non-communicable disease", "8A00; 5C52.Y-5C52-Z"),
    ("VAs-99", "Unknown and ill-defined cause of death", "8A00"),
    ("VAs-09.0", "Ruptured uterus", "JB0A.0"),
    ("VAs-11.01", "Fresh stillbirth", "KD3B.1"),
)

NODE_CODES = (
    ("vas_01_11", "Haemorrhagic fever"),
    ("vas_01_12", "Dengue fever"),
    ("vas_01_99", "Unspecified infectious disease"),
    ("vas_12_01", "Road traffic accident"),
    ("vas_12_02", "Other transport accident"),
    ("vas_12_09", "Assault"),
    ("vas_12_99", "Other and unspecified external cause of death"),
    ("vas_98", "Other and unspecified non-communicable disease"),
    ("vas_99", "Cause of death unknown"),
    ("vas_09_08", "Ruptured uterus"),
)


class Icd11GeneratorUnitTests(BaseTestCase):
    def test_parse_splits_on_semicolons_and_commas_and_reports_malformed_tokens(self):
        ranges, bad = parse_icd11_ranges("CA00-CA07.1; CA45, 1d2z; 5C52.Y-5C52-Z")
        self.assertEqual(
            ranges,
            [("CA00-CA07.1", "CA00", "CA07.1"), ("CA45", "CA45", "CA45"), ("1D2Z", "1D2Z", "1D2Z")],
        )
        self.assertEqual(bad, ["5C52.Y-5C52-Z"])

    def test_expand_range_is_lexical_plus_descendants_along_the_parent_chain(self):
        catalogue = {
            "CA06": {"parent": None},
            "CA07": {"parent": None},
            "CA07.0": {"parent": "CA07"},
            "CA07.1": {"parent": "CA07"},
            "CA07.10": {"parent": "CA07.1"},
            "CA07.Y": {"parent": "CA07"},
            "CA08": {"parent": None},
        }
        covered, past_end = expand_range("CA07", "CA07.1", sorted(catalogue), catalogue)
        # CA07.10 descends from the end itself; CA07.Y only from its ancestor.
        self.assertEqual(covered, ["CA07", "CA07.0", "CA07.1", "CA07.10", "CA07.Y"])
        self.assertEqual(past_end, ["CA07.Y"])
        self.assertNotIn("CA08", covered)

        single, past_end = expand_range("CA07", "CA07", sorted(catalogue), catalogue)
        self.assertEqual(single, ["CA07", "CA07.0", "CA07.1", "CA07.10", "CA07.Y"])
        self.assertEqual(past_end, [])


class Icd11GeneratorTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self._seed_catalogue()
        self.scheme = self._seed_scheme(SCHEME_CODE, NODE_CODES)
        curated = self._seed_scheme(CURATED_CODE, (("vas_01_11", "Haemorrhagic fever"),))
        # The curated ICD-10 scheme puts dengue (A97) with haemorrhagic fever,
        # so the crosswalk check must flag every generated dengue code.
        db.session.add(
            MapIcdCodBucket(
                scheme_id=curated.scheme_id,
                age_scope=None,
                icd_classification="icd10",
                icd_code="A97",
                node_id=self._node(curated, "vas_01_11").node_id,
                is_active=True,
            )
        )
        self.icd10_row = MapIcdCodBucket(
            scheme_id=self.scheme.scheme_id,
            age_scope=None,
            icd_classification="icd10",
            icd_code="A90",
            node_id=self._node(self.scheme, "vas_01_12").node_id,
            is_active=True,
        )
        db.session.add(self.icd10_row)
        db.session.flush()
        self.paths = self._write_sources()

    def _seed_catalogue(self):
        for index, (code, title, parent, chapter) in enumerate(CATALOGUE):
            db.session.add(
                MasIcd11Mms(
                    release=RELEASE,
                    linearization_uri=f"test://{code}",
                    parent_linearization_uri=f"test://{parent}" if parent else None,
                    code=code,
                    title=title,
                    class_kind="category",
                    chapter_no=chapter,
                    sort_order=index,
                    source_version="test",
                    is_active=True,
                )
            )
        db.session.flush()

    def _seed_scheme(self, scheme_code, node_codes):
        scheme = MasCodBucketScheme(
            scheme_code=scheme_code, scheme_name=scheme_code, mapping_version=1, is_active=True
        )
        db.session.add(scheme)
        db.session.flush()
        category = MasCodBucketNode(
            scheme_id=scheme.scheme_id, age_scope=None, node_type="category",
            node_code="all", node_label="All", sort_order=1,
        )
        db.session.add(category)
        for order, (node_code, label) in enumerate(node_codes, start=1):
            db.session.add(
                MasCodBucketNode(
                    scheme_id=scheme.scheme_id, age_scope=None, node_type="field",
                    parent=category, node_code=node_code, node_label=label, sort_order=order,
                )
            )
        db.session.flush()
        return scheme

    def _node(self, scheme, node_code):
        return db.session.scalar(
            sa.select(MasCodBucketNode).where(
                MasCodBucketNode.scheme_id == scheme.scheme_id,
                MasCodBucketNode.node_code == node_code,
            )
        )

    def _write_sources(self):
        cause_list = self.tmp / "causes.csv"
        with open(cause_list, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["group", "va_code", "va_title", "icd10_codes", "icd11_codes", "footnote", "note"])
            for va_code, title, icd11 in CAUSE_ROWS:
                writer.writerow(["group", va_code, title, "", icd11, "", ""])
        crosswalk = self.tmp / "11To10.txt"
        crosswalk.write_text(
            "Linearization (release) URI\ticd11Code\ticd11Chapter\ticd11Title\ticd10Code\ticd10Chapter\ticd10Title\n"
            "u\t1D20\t01\tDengue\tA97.0\tI\tDengue\n"
            "u\tOLD1\t01\tDengue with warning signs\tA97.1\tI\tDengue\n",
            encoding="utf-8",
        )
        changes = self.tmp / "changes.xlsx"
        workbook = Workbook()
        workbook.active.append(["Chapter", "Foundation", "2025", "2026", "Code", "Title", "Status"])
        workbook.active.append(["01", None, None, None, "OLD1 -> 1D21", "Dengue with warning signs", "MovedTo"])
        workbook.save(changes)
        return {
            "cause_list_path": str(cause_list),
            "crosswalk_path": str(crosswalk),
            "change_list_path": str(changes),
            "curated_scheme_code": CURATED_CODE,
        }

    def _generate(self):
        return generate_icd11_buckets(scheme_code=SCHEME_CODE, release=RELEASE, **self.paths)

    def _decided(self, result):
        return {row["code"]: (row["node_code"], row["match_type"]) for row in result.mappings}

    def _icd11_rows(self):
        return {
            (row.icd_code, self._node_code(row.node_id), row.match_type, row.source_category)
            for row in db.session.scalars(
                sa.select(MapIcdCodBucket).where(
                    MapIcdCodBucket.scheme_id == self.scheme.scheme_id,
                    MapIcdCodBucket.icd_classification == "icd11",
                )
            )
        }

    def _node_code(self, node_id):
        return db.session.get(MasCodBucketNode, node_id).node_code

    def test_more_specific_range_wins_and_dengue_beats_haemorrhagic_fever(self):
        decided = self._decided(self._generate())

        for code in ("1D20", "1D21", "1D2Z"):
            self.assertEqual(decided[code], ("vas_01_12", "range"))
        # 1D40 is in both the haemorrhagic fever and the residual range; the
        # narrower haemorrhagic fever range wins.
        self.assertEqual(decided["1D40"], ("vas_01_11", "range"))
        self.assertEqual(decided["1D90"], ("vas_01_99", "range"))
        # A descendant is covered with its parent.
        self.assertEqual(decided["1D00.0"], ("vas_01_11", "range"))

    def test_exact_tie_is_not_mapped_and_listed_for_review(self):
        result = self._generate()

        self.assertNotIn("8A00", self._decided(result))
        ties = [row for row in result.review if row["review_type"] == "tie"]
        self.assertEqual([row["code"] for row in ties], ["8A00"])
        self.assertIn("8A00", {row["code"] for row in result.unmapped if row["reason"] == "tie"})

    def test_pa_range_splits_per_code_and_flags_titles_that_do_not_fit(self):
        result = self._generate()
        decided = self._decided(result)

        self.assertEqual(decided["PA00"], ("vas_12_01", "split"))
        for code in ("PA10", "PA20", "PA40", "PA40.0"):
            self.assertEqual(decided[code], ("vas_12_02", "split"))
        verification = {row["code"]: row["detail"] for row in result.review if row["review_type"] == "pa_split"}
        self.assertEqual(verification["PA00"], "title fits")
        self.assertIn("DOES NOT FIT", verification["PA20"])

    def test_pj2x_is_proposed_as_assault_and_every_code_listed_for_the_owner(self):
        result = self._generate()
        decided = self._decided(result)

        self.assertEqual(decided["PJ20"], ("vas_12_09", "split"))
        self.assertEqual(decided["PJ2Z"], ("vas_12_09", "split"))
        listed = {row["code"] for row in result.review if row["review_type"] == "pj2x_owner_decision"}
        self.assertEqual(listed, {"PJ20", "PJ2Z"})

    def test_nodes_resolve_by_code_then_label_and_causes_without_a_node_are_reported(self):
        result = self._generate()
        decided = self._decided(result)

        self.assertEqual(decided["JB0A.0"], ("vas_09_08", "range"))
        self.assertNotIn("KD3B.1", decided)
        self.assertIn(("KD3B.1", "no_node"), {(row["code"], row["reason"]) for row in result.unmapped})
        review_types = {(row["review_type"], row["va_code"]) for row in result.review}
        self.assertIn(("node_matched_by_label", "VAs-09.0"), review_types)
        self.assertIn(("cause_without_node", "VAs-11.01"), review_types)
        self.assertIn(("range_issue", "VAs-98"), review_types)

    def test_crosswalk_disagreement_and_unmapped_suggestions(self):
        result = self._generate()

        by_code = {row["code"]: row for row in result.mappings}
        self.assertEqual(by_code["1D20"]["icd10_crosswalk"], "A97.0")
        # 1D21 is absent from the 2025-01 crosswalk; the change list maps it back.
        self.assertEqual(by_code["1D21"]["icd10_crosswalk"], "A97.1")
        self.assertEqual(by_code["1D21"]["curated_icd10_bucket"], "vas_01_11")
        disagreements = {row["code"] for row in result.review if row["review_type"] == "crosswalk_disagreement"}
        self.assertEqual(disagreements, {"1D20", "1D21"})

        unmapped = {row["code"]: row["reason"] for row in result.unmapped}
        self.assertEqual(unmapped["QA00"], "no_range")
        self.assertNotIn("XA0001", unmapped, "chapter X extension codes are not stems")

    def test_dry_run_writes_the_report_but_no_rows(self):
        result = self._generate()
        written = write_icd11_generation_report(result, self.tmp / "report")

        self.assertEqual(self._icd11_rows(), set())
        self.assertIsNone(db.session.get(MasCodBucketScheme, self.scheme.scheme_id).icd11_method)
        self.assertEqual(
            sorted(path.name for path in written),
            ["README.md", "icd11_generated_mappings.csv", "icd11_review.csv",
             "icd11_unmapped_with_suggestion.csv"],
        )
        self.assertIn("VAs-01.12 | Dengue fever | 3", (self.tmp / "report" / "README.md").read_text())

    def test_apply_is_idempotent_and_leaves_icd10_rows_alone(self):
        apply_icd11_generation(self._generate())
        first = self._icd11_rows()
        self.assertIn(("1D20", "vas_01_12", "range", "VAs-01.12"), first)
        self.assertIn(("PA00", "vas_12_01", "split", "VAs-12.01"), first)
        scheme = db.session.get(MasCodBucketScheme, self.scheme.scheme_id)
        self.assertEqual(scheme.icd11_method, "native")
        self.assertEqual(scheme.mapping_version, 2)

        apply_icd11_generation(self._generate())

        self.assertEqual(self._icd11_rows(), first)
        self.assertEqual(db.session.get(MasCodBucketScheme, self.scheme.scheme_id).mapping_version, 3)
        icd10 = db.session.get(MapIcdCodBucket, self.icd10_row.mapping_id)
        self.assertIsNotNone(icd10)
        self.assertEqual((icd10.icd_code, icd10.icd_classification), ("A90", "icd10"))

    def test_cli_dry_run_writes_nothing_and_unknown_scheme_fails(self):
        runner = self.app.test_cli_runner()
        missing = runner.invoke(args=["cod-buckets", "generate-icd11", "--scheme", "NOPE", "--release", RELEASE])
        self.assertNotEqual(missing.exit_code, 0)
        self.assertIn("Unknown COD bucket scheme", missing.output)

        result = runner.invoke(
            args=[
                "cod-buckets", "generate-icd11", "--scheme", SCHEME_CODE, "--release", RELEASE,
                "--report-dir", str(self.tmp / "cli"),
            ]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Dry run", result.output)
        self.assertEqual(self._icd11_rows(), set())
