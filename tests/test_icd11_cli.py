"""Tests for the `flask icd11` CLI commands.

Run (inside Docker):
  docker compose exec minerva_app_service uv run pytest tests/test_icd11_cli.py -v
"""
import json
import tempfile
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models import MasIcd11Mms
from tests.base import BaseTestCase

_HEADER = (
    "Foundation URI\tLinearization URI\tCode\tBlockId\tTitle\tClassKind\t"
    "DepthInKind\tIsResidual\tChapterNo\tBrowserLink\tisLeaf\tPrimary tabulation\t"
    "Grouping1\tGrouping2\tGrouping3\tGrouping4\tGrouping5\tCodingNote\tParent\t"
    "Version:test\r\n"
)
def _row(foundation_uri, linearization_uri, code, title, class_kind, depth, chapter_no, is_leaf, parent):
    # foundation_uri, linearization_uri, code, block_id, title, class_kind,
    # depth_in_kind, is_residual, chapter_no, browser_link, is_leaf,
    # primary_tabulation, grouping1-5, coding_note, parent  (19 cells)
    return (
        f'{foundation_uri}\t{linearization_uri}\t{code}\t\t"{title}"\t{class_kind}\t'
        f"{depth}\tfalse\t{chapter_no}\t\t{is_leaf}\t\t\t\t\t\t\t\t{parent}\r\n"
    )


_ROWS = (
    _row("f:ch1", "lin:ch1", "", "Chapter One", "chapter", 1, "01", "false", ""),
    _row("f:cat1", "lin:cat1", "1A00", "Cholera", "category", 2, "01", "true", "f:ch1"),
)


class Icd11CliTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(MasIcd11Mms))
        db.session.flush()
        self.runner = self.app.test_cli_runner()

    def _write_export(self) -> Path:
        handle = tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False)
        path = Path(handle.name)
        text = _HEADER + "".join(_ROWS)
        handle.write(b"\xef\xbb\xbf" + text.encode("utf-8"))
        handle.close()
        return path

    def test_import_cli_populates_table(self):
        export_path = self._write_export()
        result = self.runner.invoke(
            args=["icd11", "import", "--export-path", str(export_path), "--release", "2026-01"]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("rows=2 inserted=2 updated=0 deactivated=0", result.output)

        row = db.session.scalar(
            sa.select(MasIcd11Mms).where(MasIcd11Mms.linearization_uri == "lin:cat1")
        )
        self.assertIsNotNone(row)
        self.assertEqual(row.title, "Cholera")

    def test_stats_cli_reports_counts(self):
        export_path = self._write_export()
        self.runner.invoke(
            args=["icd11", "import", "--export-path", str(export_path), "--release", "2026-01"]
        )

        result = self.runner.invoke(args=["icd11", "stats", "--release", "2026-01"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("total_rows=2", result.output)
        self.assertIn("chapters=1", result.output)
        self.assertIn("categories=1", result.output)

    def test_generate_seed_csv_cli_writes_expected_rows(self):
        export_path = self._write_export()
        with tempfile.TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "seed.csv"
            result = self.runner.invoke(
                args=[
                    "icd11",
                    "generate-seed-csv",
                    "--export-path",
                    str(export_path),
                    "--csv-path",
                    str(csv_path),
                ]
            )
            self.assertEqual(result.exit_code, 0, result.output)
            self.assertIn("Wrote 2 rows", result.output)
            self.assertTrue(csv_path.exists())
            content = csv_path.read_text(encoding="utf-8")
            self.assertIn("lin:cat1", content)
            self.assertIn("1A00", content)

    def test_policy_export_and_import_cli_round_trip(self):
        export_path = self._write_export()
        self.runner.invoke(
            args=["icd11", "import", "--export-path", str(export_path), "--release", "2026-01"]
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            export_json_path = Path(tmp_dir) / "policy.json"
            export_result = self.runner.invoke(
                args=[
                    "icd11",
                    "policy-export",
                    "--release",
                    "2026-01",
                    "--output",
                    str(export_json_path),
                ]
            )
            self.assertEqual(export_result.exit_code, 0, export_result.output)
            self.assertTrue(export_json_path.exists())

            import_json_path = Path(tmp_dir) / "import.json"
            import_json_path.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "linearization_uri": "lin:cat1",
                                "is_coding_selectable": True,
                                "sex_selectable": "both",
                                "age_group_selectable": "all",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            import_result = self.runner.invoke(
                args=["icd11", "policy-import", str(import_json_path), "--release", "2026-01"]
            )
            self.assertEqual(import_result.exit_code, 0, import_result.output)
            self.assertIn("updated_items=1", import_result.output)

        row = db.session.scalar(
            sa.select(MasIcd11Mms).where(MasIcd11Mms.linearization_uri == "lin:cat1")
        )
        self.assertTrue(row.is_coding_selectable)
