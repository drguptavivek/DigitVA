"""Round-trip coverage for the frozen WHO_2022_VA admin-editor overrides.

Bead digitva-2g7: dev holds 34 mappings added through the admin bucket editor
that the frozen `ICD_Mapped` workbook never had (real curation -- heart
failure, liver disease, unknown-cause codes). Freezing them into
`WHO_2022_VA_Bucket_Mapping_admin_overrides.csv` and reapplying that CSV on
every import means a fresh clone reaches the same 2,414 mappings dev has,
instead of the workbook's 2,380.
"""

import csv

import sqlalchemy as sa

from app import db
from app.models import MapIcdCodBucket, MasCodBucketNode, MasCodBucketScheme
from app.services.cod_bucket_mapping_service import (
    DEFAULT_WHO_2022_VA_ADMIN_OVERRIDES_PATH,
    MANUAL_OVERRIDE_SOURCE_SHEET,
    MIGRATION_ARTIFACT_WHO_2022_VA_WORKBOOK_PATH,
    SCHEME_CODE_WHO_2022_VA,
    import_who_2022_va_scheme,
)
from tests.base import BaseTestCase


def _bucket_label(scheme_id, icd_code):
    return db.session.execute(
        sa.select(MasCodBucketNode.node_label)
        .join(MapIcdCodBucket, MapIcdCodBucket.node_id == MasCodBucketNode.node_id)
        .where(
            MapIcdCodBucket.scheme_id == scheme_id,
            MapIcdCodBucket.icd_code == icd_code,
        )
    ).scalar_one()


def _mapping_count(scheme_id):
    return db.session.scalar(
        sa.select(sa.func.count())
        .select_from(MapIcdCodBucket)
        .where(MapIcdCodBucket.scheme_id == scheme_id)
    )


class Who2022VaAdminOverridesTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(MapIcdCodBucket))
        db.session.execute(sa.delete(MasCodBucketNode))
        db.session.execute(sa.delete(MasCodBucketScheme))
        db.session.flush()

    def test_fresh_import_reaches_2414_with_the_34_overrides_present(self):
        scheme = import_who_2022_va_scheme(MIGRATION_ARTIFACT_WHO_2022_VA_WORKBOOK_PATH)

        self.assertEqual(_mapping_count(scheme.scheme_id), 2414)

        with open(DEFAULT_WHO_2022_VA_ADMIN_OVERRIDES_PATH, newline="") as handle:
            override_rows = list(csv.DictReader(handle))
        self.assertEqual(len(override_rows), 34)

        for row in override_rows:
            mapping = db.session.scalar(
                sa.select(MapIcdCodBucket).where(
                    MapIcdCodBucket.scheme_id == scheme.scheme_id,
                    MapIcdCodBucket.icd_code == row["icd_code"],
                )
            )
            self.assertIsNotNone(mapping, f"{row['icd_code']} missing from import")
            self.assertEqual(mapping.source_sheet, MANUAL_OVERRIDE_SOURCE_SHEET)
            self.assertEqual(_bucket_label(scheme.scheme_id, row["icd_code"]), row["node_label"])

        # spot-check the two buckets the workbook never had at all
        self.assertEqual(_bucket_label(scheme.scheme_id, "K64"), "Other Gastrointestinal Diseases")
        self.assertEqual(_bucket_label(scheme.scheme_id, "UU2"), "Other Defined cause of Child Death")

    def test_reimport_is_idempotent(self):
        first = import_who_2022_va_scheme(MIGRATION_ARTIFACT_WHO_2022_VA_WORKBOOK_PATH)
        first_count = _mapping_count(first.scheme_id)

        second = import_who_2022_va_scheme(MIGRATION_ARTIFACT_WHO_2022_VA_WORKBOOK_PATH)

        self.assertEqual(second.scheme_id, first.scheme_id)
        self.assertEqual(_mapping_count(second.scheme_id), first_count)
        scheme_count = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(MasCodBucketScheme)
            .where(MasCodBucketScheme.scheme_code == SCHEME_CODE_WHO_2022_VA)
        )
        self.assertEqual(scheme_count, 1)

    def test_reimport_keeps_a_live_admin_edit_made_after_the_freeze(self):
        scheme = import_who_2022_va_scheme(MIGRATION_ARTIFACT_WHO_2022_VA_WORKBOOK_PATH)
        # G46 is frozen to "vas_04_02" (Stroke); an admin repoints it elsewhere
        # through the editor after the freeze.
        retarget = db.session.scalar(
            sa.select(MasCodBucketNode).where(
                MasCodBucketNode.scheme_id == scheme.scheme_id,
                MasCodBucketNode.node_code == "vas_04_01",
            )
        )
        mapping = db.session.scalar(
            sa.select(MapIcdCodBucket).where(
                MapIcdCodBucket.scheme_id == scheme.scheme_id,
                MapIcdCodBucket.icd_code == "G46",
            )
        )
        mapping.node_id = retarget.node_id
        mapping.source_sheet = MANUAL_OVERRIDE_SOURCE_SHEET
        db.session.flush()

        reimported = import_who_2022_va_scheme(MIGRATION_ARTIFACT_WHO_2022_VA_WORKBOOK_PATH)

        self.assertEqual(_bucket_label(reimported.scheme_id, "G46"), retarget.node_label)


class OverridesAreTiedToTheWorkbookTheySupplementTests(BaseTestCase):
    """The 34 frozen rows correct ONE derivation, so they must not ride along
    onto a different WHO_2022_VA workbook.

    Found 2026-09-20: the first version applied them to every import, so a
    two-row synthetic workbook produced 36 mappings. Beyond the noisy test,
    that meant importing an updated WHO derivation would silently layer stale
    corrections onto whatever the new workbook said about those same codes.
    """

    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(MapIcdCodBucket))
        db.session.execute(sa.delete(MasCodBucketNode))
        db.session.execute(sa.delete(MasCodBucketScheme))
        db.session.flush()

    def _frozen_codes(self):
        with open(DEFAULT_WHO_2022_VA_ADMIN_OVERRIDES_PATH, newline="", encoding="utf-8") as fh:
            return {row["icd_code"] for row in csv.DictReader(fh)}

    def test_the_frozen_workbook_does_get_them(self):
        """Present before absent: the overrides must work where they belong."""
        scheme = import_who_2022_va_scheme(
            workbook_path=MIGRATION_ARTIFACT_WHO_2022_VA_WORKBOOK_PATH
        )
        db.session.flush()

        applied = db.session.scalars(
            sa.select(MapIcdCodBucket.icd_code).where(
                MapIcdCodBucket.scheme_id == scheme.scheme_id,
                MapIcdCodBucket.source_sheet == MANUAL_OVERRIDE_SOURCE_SHEET,
            )
        ).all()
        self.assertEqual(set(applied), self._frozen_codes())

    def test_passing_none_skips_them_even_for_the_frozen_workbook(self):
        scheme = import_who_2022_va_scheme(
            workbook_path=MIGRATION_ARTIFACT_WHO_2022_VA_WORKBOOK_PATH,
            overrides_path=None,
        )
        db.session.flush()

        applied = db.session.scalars(
            sa.select(MapIcdCodBucket.icd_code).where(
                MapIcdCodBucket.scheme_id == scheme.scheme_id,
                MapIcdCodBucket.source_sheet == MANUAL_OVERRIDE_SOURCE_SHEET,
            )
        ).all()
        self.assertEqual(applied, [], "overrides applied despite overrides_path=None")
        self.assertEqual(_mapping_count(scheme.scheme_id), 2380)
