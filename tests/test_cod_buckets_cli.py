from tempfile import NamedTemporaryFile

import sqlalchemy as sa
from openpyxl import Workbook

from app import db
from app.models import (
    MapIcdCodBucket,
    MasCodBucketNode,
    MasCodBucketScheme,
    VaCodBucketSchemeSnapshot,
)
from app.services.cod_bucket_mapping_service import SCHEME_CODE_WHO_2022_VA_2026
from tests.base import BaseTestCase


class CodBucketsCliTestCase(BaseTestCase):
    """`flask cod-buckets import-who-2022-va-2026` had no test of its own --
    only the underlying service function did. This pins the CLI command
    itself: argument wiring, exit code and the echoed summary line.
    """

    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(MapIcdCodBucket))
        db.session.execute(sa.delete(MasCodBucketNode))
        db.session.execute(sa.delete(MasCodBucketScheme))
        db.session.flush()
        self.runner = self.app.test_cli_runner()

    def _make_who_2022_va_2026_workbook(self) -> str:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "ICD_Mapped"
        sheet.append(
            [
                "disease_id",
                "icd_code",
                "icd_to_display",
                "category",
                "WHO_2022_VA_section",
                "WHO_2022_VA_code",
                "WHO_2022_VA_cause",
                "WHO_2022_VA_match_type",
                "WHO_2022_VA_note",
            ]
        )
        sheet.append(
            [
                1,
                "A33",
                "A33-Tetanus neonatorum",
                "Tetanus",
                "Neonatal causes of death",
                "VAs-10.05",
                "Neonatal tetanus",
                "exact",
                None,
            ]
        )
        with NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            workbook.save(tmp.name)
            return tmp.name

    def test_import_who_2022_va_2026_cli_creates_scheme(self):
        workbook_path = self._make_who_2022_va_2026_workbook()

        result = self.runner.invoke(
            args=["cod-buckets", "import-who-2022-va-2026", "--path", workbook_path]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(f"Imported {SCHEME_CODE_WHO_2022_VA_2026} from {workbook_path}", result.output)

        scheme = db.session.scalar(
            sa.select(MasCodBucketScheme).where(
                MasCodBucketScheme.scheme_code == SCHEME_CODE_WHO_2022_VA_2026
            )
        )
        self.assertIsNotNone(scheme)
        self.assertEqual(scheme.source_path, workbook_path)

        mapping_count = db.session.scalar(
            sa.select(sa.func.count()).select_from(MapIcdCodBucket).where(
                MapIcdCodBucket.scheme_id == scheme.scheme_id
            )
        )
        self.assertEqual(mapping_count, 1)

    def test_import_who_2022_va_2026_cli_rerun_replaces_contents(self):
        workbook_path = self._make_who_2022_va_2026_workbook()
        self.runner.invoke(
            args=["cod-buckets", "import-who-2022-va-2026", "--path", workbook_path]
        )
        first_scheme_id = db.session.scalar(
            sa.select(MasCodBucketScheme.scheme_id).where(
                MasCodBucketScheme.scheme_code == SCHEME_CODE_WHO_2022_VA_2026
            )
        )

        result = self.runner.invoke(
            args=["cod-buckets", "import-who-2022-va-2026", "--path", workbook_path]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        scheme_count = db.session.scalar(
            sa.select(sa.func.count()).select_from(MasCodBucketScheme).where(
                MasCodBucketScheme.scheme_code == SCHEME_CODE_WHO_2022_VA_2026
            )
        )
        self.assertEqual(scheme_count, 1, "re-running must replace the existing scheme, not duplicate it")
        second_scheme_id = db.session.scalar(
            sa.select(MasCodBucketScheme.scheme_id).where(
                MasCodBucketScheme.scheme_code == SCHEME_CODE_WHO_2022_VA_2026
            )
        )
        self.assertEqual(first_scheme_id, second_scheme_id)

    def test_import_over_existing_scheme_creates_one_cli_import_snapshot(self):
        workbook_path = self._make_who_2022_va_2026_workbook()
        self.runner.invoke(
            args=["cod-buckets", "import-who-2022-va-2026", "--path", workbook_path]
        )

        result = self.runner.invoke(
            args=["cod-buckets", "import-who-2022-va-2026", "--path", workbook_path]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Snapshot", result.output)
        self.assertIn("saved before re-import.", result.output)
        snapshot_count = db.session.scalar(
            sa.select(sa.func.count()).select_from(VaCodBucketSchemeSnapshot).where(
                VaCodBucketSchemeSnapshot.scheme_code == SCHEME_CODE_WHO_2022_VA_2026,
                VaCodBucketSchemeSnapshot.reason == VaCodBucketSchemeSnapshot.REASON_CLI_IMPORT,
            )
        )
        self.assertEqual(snapshot_count, 1)

    def test_import_into_absent_scheme_creates_no_snapshot(self):
        workbook_path = self._make_who_2022_va_2026_workbook()

        result = self.runner.invoke(
            args=["cod-buckets", "import-who-2022-va-2026", "--path", workbook_path]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("Snapshot", result.output)
        snapshot_count = db.session.scalar(
            sa.select(sa.func.count()).select_from(VaCodBucketSchemeSnapshot).where(
                VaCodBucketSchemeSnapshot.scheme_code == SCHEME_CODE_WHO_2022_VA_2026
            )
        )
        self.assertEqual(snapshot_count, 0)
