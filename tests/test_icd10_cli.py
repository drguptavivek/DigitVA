import csv
import json
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


class Icd10PolicyImportCliTestCase(BaseTestCase):
    """`flask icd10 policy-import` is full-replacement and global: every
    editable code absent from the file is reset to not selectable, for
    every project. This pins that reset, not just the codes present in the
    file -- a partial file silently making thousands of codes unselectable
    would otherwise fail quietly.
    """

    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(MasIcd1020192))
        db.session.flush()
        self.runner = self.app.test_cli_runner()

    def _seed_row(self, code: str, **overrides) -> MasIcd1020192:
        defaults = dict(
            code=code,
            title=code,
            node_type="category",
            semantic_level="three_character",
            has_children=False,
            is_leaf=True,
            is_three_character_code=True,
            is_detailed_code=False,
            is_coding_selectable=True,
            sex_selectable="both",
            age_group_selectable="all",
            restriction_note=None,
            source_version="ICD-10-2019",
            is_active=True,
        )
        defaults.update(overrides)
        row = MasIcd1020192(**defaults)
        db.session.add(row)
        db.session.flush()
        return row

    def _write_policy_json(self, items: list[dict]) -> Path:
        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        path = Path(handle.name)
        try:
            json.dump({"items": items}, handle)
        finally:
            handle.close()
        return path

    def test_code_absent_from_file_is_reset_to_not_selectable(self):
        # Present first: A01 really is selectable before the import.
        self._seed_row("A01", is_coding_selectable=True, sex_selectable="female")
        db.session.commit()
        row = db.session.get(MasIcd1020192, "A01")
        self.assertTrue(row.is_coding_selectable)

        # The file only mentions A00 -- A01 is absent.
        json_path = self._write_policy_json(
            [{"code": "A00", "is_coding_selectable": True}]
        )
        self._seed_row("A00", is_coding_selectable=False)
        db.session.commit()

        result = self.runner.invoke(
            args=["icd10", "policy-import", "--path", str(json_path)]
        )
        self.assertEqual(result.exit_code, 0, result.output)

        # Then what must be absent: A01 is no longer selectable, and its
        # sex/age/restriction fields were cleared along with it.
        row = db.session.get(MasIcd1020192, "A01")
        self.assertIs(row.is_coding_selectable, False)
        self.assertIsNone(row.sex_selectable)
        self.assertIsNone(row.age_group_selectable)
        self.assertIsNone(row.restriction_note)

    def test_code_in_file_is_updated_to_the_given_policy(self):
        self._seed_row("A00", is_coding_selectable=False, sex_selectable=None)
        db.session.commit()

        json_path = self._write_policy_json(
            [
                {
                    "code": "A00",
                    "is_coding_selectable": True,
                    "sex_selectable": "male",
                    "age_group_selectable": "adult",
                    "restriction_note": "Adult male only",
                }
            ]
        )

        result = self.runner.invoke(
            args=["icd10", "policy-import", "--path", str(json_path)]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("total_items=1 updated_items=1 reset_items=0", result.output)

        row = db.session.get(MasIcd1020192, "A00")
        self.assertTrue(row.is_coding_selectable)
        self.assertEqual(row.sex_selectable, "male")
        self.assertEqual(row.age_group_selectable, "adult")
        self.assertEqual(row.restriction_note, "Adult male only")

    def test_non_editable_semantic_level_is_never_touched(self):
        # Chapter-level rows are outside POLICY_EDITABLE_LEVELS: neither the
        # file nor the reset pass may change them.
        self._seed_row(
            "I",
            semantic_level="chapter",
            is_three_character_code=False,
            is_coding_selectable=True,
            sex_selectable="both",
        )
        db.session.commit()

        json_path = self._write_policy_json([])
        result = self.runner.invoke(
            args=["icd10", "policy-import", "--path", str(json_path)]
        )
        self.assertEqual(result.exit_code, 0, result.output)

        row = db.session.get(MasIcd1020192, "I")
        self.assertTrue(row.is_coding_selectable)
        self.assertEqual(row.sex_selectable, "both")

    def test_inactive_code_is_never_touched(self):
        self._seed_row("A02", is_coding_selectable=True, is_active=False)
        db.session.commit()

        json_path = self._write_policy_json([])
        result = self.runner.invoke(
            args=["icd10", "policy-import", "--path", str(json_path)]
        )
        self.assertEqual(result.exit_code, 0, result.output)

        row = db.session.get(MasIcd1020192, "A02")
        self.assertTrue(row.is_coding_selectable)

    def test_unknown_code_in_file_is_skipped_not_inserted(self):
        json_path = self._write_policy_json(
            [{"code": "Z99", "is_coding_selectable": True}]
        )
        result = self.runner.invoke(
            args=["icd10", "policy-import", "--path", str(json_path)]
        )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("skipped_items=1", result.output)
        self.assertIn("skipped: {'code': 'Z99', 'reason': 'unknown_or_non_editable_code'}", result.output)

        self.assertIsNone(db.session.get(MasIcd1020192, "Z99"))
