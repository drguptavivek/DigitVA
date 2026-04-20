import csv
import tempfile
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models import MasIcd1020192
from tests.base import BaseTestCase


CSV_FIELDS = [
    "code",
    "title",
    "node_type",
    "semantic_level",
    "parent_code",
    "chapter_code",
    "chapter_title",
    "block_code",
    "block_title",
    "three_character_code",
    "three_character_title",
    "has_children",
    "is_leaf",
    "is_three_character_code",
    "is_detailed_code",
    "is_coding_selectable",
    "sex_selectable",
    "age_group_selectable",
    "policy_status",
    "restriction_note",
]


class Icd10CliTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(MasIcd1020192))
        db.session.flush()
        self.runner = self.app.test_cli_runner()

    def _write_csv(self) -> Path:
        handle = tempfile.NamedTemporaryFile(
            mode="w",
            newline="",
            suffix=".csv",
            delete=False,
        )
        path = Path(handle.name)
        try:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerow(
                {
                    "code": "A00",
                    "title": "Cholera",
                    "node_type": "category",
                    "semantic_level": "three_character",
                    "parent_code": "",
                    "chapter_code": "I",
                    "chapter_title": "Certain infectious and parasitic diseases",
                    "block_code": "A00-A09",
                    "block_title": "Intestinal infectious diseases",
                    "three_character_code": "A00",
                    "three_character_title": "Cholera",
                    "has_children": "false",
                    "is_leaf": "true",
                    "is_three_character_code": "true",
                    "is_detailed_code": "false",
                    "is_coding_selectable": "",
                    "sex_selectable": "",
                    "age_group_selectable": "",
                    "policy_status": "unreviewed",
                    "restriction_note": "",
                }
            )
        finally:
            handle.close()
        return path

    def test_import_2019_2_cli_populates_table(self):
        csv_path = self._write_csv()
        result = self.runner.invoke(args=["icd10", "import-2019-2", "--csv-path", str(csv_path)])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Imported mas_icd10_2019_2 rows=1 inserted=1 updated=0 deactivated=0", result.output)

        row = db.session.get(MasIcd1020192, "A00")
        self.assertIsNotNone(row)
        self.assertEqual(row.title, "Cholera")

    def test_stats_2019_2_cli_reports_counts(self):
        csv_path = self._write_csv()
        self.runner.invoke(args=["icd10", "import-2019-2", "--csv-path", str(csv_path)])

        result = self.runner.invoke(args=["icd10", "stats-2019-2"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("total_rows=1", result.output)
        self.assertIn("active_rows=1", result.output)
        self.assertIn("three_character_rows=1", result.output)

        active_count = db.session.scalar(
            sa.select(sa.func.count()).select_from(MasIcd1020192).where(
                MasIcd1020192.is_active.is_(True)
            )
        )
        self.assertEqual(active_count, 1)
