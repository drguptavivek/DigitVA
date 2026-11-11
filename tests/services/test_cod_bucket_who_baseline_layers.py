"""WHO_2022_VA_2026: reset gives the WHO baseline, overrides are a layer (digitva-ozd1).

Policy: docs/policy/icd11-cod-bucket-schemes.md ("WHO baseline and DigitVA
overrides"). Runs on the real 2026-01 ICD-11 catalogue, the frozen
WHO_2022_VA and WHO_2022_VA_2026 workbooks and the checked-in decisions
files, so it pins the state the migrations produced
(resource/who_2022_va_2026_icd11_native_mappings.csv).
"""

import csv
import importlib.util
import uuid
from pathlib import Path
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import MapIcdCodBucket, MasCodBucketNode, MasIcd11Mms, VaCodBucketSchemeSnapshot
from app.services.cod_bucket_icd11_generator import (
    DECISIONS_PATH,
    LAYER_DIGITVA,
    LAYER_WHO_FIX,
    generate_icd11_buckets,
)
from app.services.cod_bucket_mapping_service import (
    DEFAULT_WHO_2022_VA_2026_OWNER_DECISIONS_PATH,
    MIGRATION_ARTIFACT_WHO_2022_VA_2026_WORKBOOK_PATH,
    SCHEME_CODE_WHO_2022_VA_2026,
    apply_cod_bucket_scheme_overrides,
    get_cod_bucket_scheme,
    import_who_2022_va_2026_scheme,
    import_who_2022_va_scheme,
    reset_cod_bucket_scheme_age_band_to_source,
)
from app.services.icd11_mms_service import DEFAULT_ICD11_RELEASE
from tests.base import BaseTestCase

REPO = Path(__file__).resolve().parents[2]
SEED_CSV = REPO / "resource" / "who_2022_va_2026_icd11_native_mappings.csv"
CATALOGUE_MIGRATION = REPO / "migrations" / "versions" / "b6edb1b7d01a_add_mas_icd11_mms_table.py"


def _load_catalogue_rows():
    spec = importlib.util.spec_from_file_location("catalogue_seed", CATALOGUE_MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.RELEASE == DEFAULT_ICD11_RELEASE
    return module._load_seed_rows()


def _rows(scheme, classification):
    return {
        row.icd_code: row
        for row in db.session.execute(
            sa.select(
                MapIcdCodBucket.icd_code,
                MasCodBucketNode.node_code,
                MapIcdCodBucket.match_type,
                MapIcdCodBucket.mapping_note,
                MapIcdCodBucket.source_sheet,
                MapIcdCodBucket.source_category,
                MapIcdCodBucket.source_row_number,
            )
            .join(MasCodBucketNode, MasCodBucketNode.node_id == MapIcdCodBucket.node_id)
            .where(
                MapIcdCodBucket.scheme_id == scheme.scheme_id,
                MapIcdCodBucket.icd_classification == classification,
            )
        )
    }


class WhoBaselineAndOverridesTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        rows = _load_catalogue_rows()
        for start in range(0, len(rows), 5000):
            db.session.execute(sa.insert(MasIcd11Mms.__table__), rows[start:start + 5000])
        # The decision 5b fallback reads WHO_2022_VA's ICD-10 rows.
        import_who_2022_va_scheme()
        import_who_2022_va_2026_scheme(MIGRATION_ARTIFACT_WHO_2022_VA_2026_WORKBOOK_PATH)
        db.session.commit()

    def _scheme(self):
        return get_cod_bucket_scheme(SCHEME_CODE_WHO_2022_VA_2026)

    def test_reset_regenerates_icd11_as_the_who_fix_only_baseline(self):
        expected = generate_icd11_buckets(
            scheme_code=SCHEME_CODE_WHO_2022_VA_2026,
            release=DEFAULT_ICD11_RELEASE,
            decision_layers=(LAYER_WHO_FIX,),
        )
        self.assertEqual(expected.unmapped, [])
        self.assertEqual(expected.review_count("tie"), 0)
        expected_rows = {row["code"]: (row["node_code"], row["match_type"]) for row in expected.mappings}
        for reset_entire_scheme in (True, False):
            scheme, _ = reset_cod_bucket_scheme_age_band_to_source(
                scheme_code=SCHEME_CODE_WHO_2022_VA_2026,
                age_scope=None,
                reset_entire_scheme=reset_entire_scheme,
            )
            self.assertEqual(scheme.icd11_method, "native")
            icd11 = _rows(scheme, "icd11")
            self.assertEqual(len(icd11), 18505)
            self.assertEqual({code: (r.node_code, r.match_type) for code, r in icd11.items()}, expected_rows)
            # Decision 4 (who_fix) stays; decision 9 (digitva) does not.
            self.assertEqual(icd11["5C52.Y"].match_type, "owner_decision")
            self.assertNotEqual(icd11["KD3B"].match_type, "owner_decision")
            icd10 = _rows(scheme, "icd10")
            self.assertEqual(len(icd10), 2498)
            self.assertFalse([code for code, r in icd10.items() if r.match_type == "owner_decision"])

    def test_apply_overrides_changes_only_decided_codes_snapshots_and_is_idempotent(self):
        scheme = self._scheme()
        before = {cls: _rows(scheme, cls) for cls in ("icd10", "icd11")}

        scheme, snapshot_id, counts = apply_cod_bucket_scheme_overrides(scheme_code=scheme.scheme_code)

        snapshot = db.session.get(VaCodBucketSchemeSnapshot, snapshot_id)
        self.assertEqual(snapshot.reason, VaCodBucketSchemeSnapshot.REASON_APPLY_OVERRIDES)
        after = {cls: _rows(scheme, cls) for cls in ("icd10", "icd11")}
        with open(DEFAULT_WHO_2022_VA_2026_OWNER_DECISIONS_PATH, newline="", encoding="utf-8") as handle:
            icd10_decided = {row["icd_code"] for row in csv.DictReader(handle)}
        for cls in ("icd10", "icd11"):
            changed = {code for code, row in after[cls].items() if row != before[cls][code]}
            self.assertEqual(set(after[cls]), set(before[cls]), "no row added or removed")
            self.assertEqual(len(changed), counts[cls], cls)
            self.assertTrue(changed)
            self.assertTrue(all(after[cls][code].match_type == "owner_decision" for code in changed))
        # Every ICD-10 decision row; ICD-11 rows whose node or match type differ
        # from the WHO baseline (147 by bucket, 38 by provenance only).
        self.assertEqual(counts, {"icd10": 151, "icd11": 185})
        icd10_changed = {code for code, row in after["icd10"].items() if row != before["icd10"][code]}
        self.assertLessEqual(icd10_changed, icd10_decided)

        _, second_snapshot_id, second = apply_cod_bucket_scheme_overrides(scheme_code=scheme.scheme_code)
        self.assertEqual(second, {"icd10": 0, "icd11": 0})
        self.assertNotEqual(second_snapshot_id, snapshot_id)

    def test_reset_then_apply_equals_the_migrated_state(self):
        reset_cod_bucket_scheme_age_band_to_source(
            scheme_code=SCHEME_CODE_WHO_2022_VA_2026, age_scope=None, reset_entire_scheme=True
        )
        scheme, _, _ = apply_cod_bucket_scheme_overrides(scheme_code=SCHEME_CODE_WHO_2022_VA_2026)

        icd11 = _rows(scheme, "icd11")
        with SEED_CSV.open(newline="", encoding="utf-8") as handle:
            seed = {row["icd_code"]: row for row in csv.DictReader(handle)}
        self.assertEqual(set(icd11), set(seed))
        mismatched = [
            code for code, row in seed.items()
            if (
                icd11[code].node_code, icd11[code].match_type, icd11[code].mapping_note,
                icd11[code].source_sheet, icd11[code].source_category,
                str(icd11[code].source_row_number or ""),
            ) != (
                row["node_code"], row["match_type"], row["mapping_note"],
                row["source_sheet"], row["source_category"], row["source_row_number"],
            )
        ]
        self.assertEqual(mismatched, [])

        icd10 = _rows(scheme, "icd10")
        with open(DEFAULT_WHO_2022_VA_2026_OWNER_DECISIONS_PATH, newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                code = row["icd_code"].strip().upper()
                if code not in icd10:
                    continue
                self.assertEqual(icd10[code].node_code, row["node_code"], code)
                self.assertEqual(icd10[code].match_type, row["match_type"], code)
                self.assertEqual(icd10[code].mapping_note, row["mapping_note"], code)

    def test_every_icd11_decision_row_has_a_known_layer(self):
        with open(REPO / DECISIONS_PATH, newline="", encoding="utf-8") as handle:
            layers = [row["layer"] for row in csv.DictReader(handle)]
        self.assertEqual(len(layers), 42)
        self.assertLessEqual(set(layers), {LAYER_WHO_FIX, LAYER_DIGITVA})
        self.assertEqual(layers.count(LAYER_WHO_FIX), 1)

    def test_a_failed_icd11_regeneration_refuses_the_whole_reset(self):
        scheme = self._scheme()
        before = {cls: len(_rows(scheme, cls)) for cls in ("icd10", "icd11")}
        with patch(
            "app.services.cod_bucket_icd11_generator.generate_icd11_buckets",
            side_effect=FileNotFoundError("cause list"),
        ):
            with self.assertRaisesRegex(ValueError, "reset refused"):
                reset_cod_bucket_scheme_age_band_to_source(
                    scheme_code=SCHEME_CODE_WHO_2022_VA_2026, age_scope=None, reset_entire_scheme=True
                )
        scheme = self._scheme()
        self.assertEqual(scheme.icd11_method, "native")
        self.assertEqual({cls: len(_rows(scheme, cls)) for cls in ("icd10", "icd11")}, before)

    def test_apply_overrides_route(self):
        self._login(self.base_admin_id)
        response = self.client.post(
            f"/admin/api/cod-bucket-schemes/{SCHEME_CODE_WHO_2022_VA_2026}/apply-overrides",
            json={},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        payload = response.get_json()
        self.assertGreater(payload["changed"]["icd10"], 0)
        self.assertGreater(payload["changed"]["icd11"], 0)
        self.assertIsNotNone(db.session.get(VaCodBucketSchemeSnapshot, uuid.UUID(payload["snapshot_id"])))


    def test_reset_and_apply_refuse_without_a_catalogue_when_icd11_rows_exist(self):
        from app.services import cod_bucket_mapping_service as svc

        scheme = svc.get_cod_bucket_scheme(svc.SCHEME_CODE_WHO_2022_VA_2026)
        self.assertEqual(scheme.icd11_method, "native")
        before = db.session.scalar(sa.select(sa.func.count()).select_from(VaCodBucketSchemeSnapshot))
        with patch.object(svc, "DEFAULT_ICD11_RELEASE", "no-such-release"):
            with self.assertRaisesRegex(ValueError, "No ICD-11 catalogue"):
                svc.reset_cod_bucket_scheme_age_band_to_source(
                    scheme_code=scheme.scheme_code, age_scope=None, reset_entire_scheme=True
                )
            with self.assertRaisesRegex(ValueError, "No ICD-11 catalogue"):
                svc.apply_cod_bucket_scheme_overrides(scheme_code=scheme.scheme_code)
        after = db.session.scalar(sa.select(sa.func.count()).select_from(VaCodBucketSchemeSnapshot))
        self.assertEqual(before, after)
        self.assertTrue(db.session.scalar(sa.select(sa.exists().where(
            MapIcdCodBucket.scheme_id == scheme.scheme_id,
            MapIcdCodBucket.icd_classification == "icd11",
        ))))
