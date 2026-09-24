"""Tests for the ICD-11 MMS catalog service (importer, stats, search, policy).

Run (inside Docker):
  docker compose exec minerva_app_service uv run pytest tests/services/test_icd11_mms_service.py -v
"""
import tempfile
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models import MasIcd11Mms
from app.services.icd11_mms_service import (
    export_icd11_mms_policy_json,
    get_icd11_mms_node_details,
    get_icd11_mms_stats,
    import_icd11_mms_from_export,
    import_icd11_mms_policy_json,
    list_icd11_mms_children,
    search_icd11_mms,
    update_icd11_mms_policy,
)
from tests.base import BaseTestCase

_HEADER = (
    "Foundation URI\tLinearization URI\tCode\tBlockId\tTitle\tClassKind\t"
    "DepthInKind\tIsResidual\tChapterNo\tBrowserLink\tisLeaf\tPrimary tabulation\t"
    "Grouping1\tGrouping2\tGrouping3\tGrouping4\tGrouping5\tCodingNote\tParent\t"
    "Version:test\r\n"
)


def _row(
    foundation_uri,
    linearization_uri,
    code,
    block_id,
    title,
    class_kind,
    depth,
    is_residual,
    chapter_no,
    is_leaf,
    primary_tabulation,
    coding_note,
    parent,
):
    return (
        f"{foundation_uri}\t{linearization_uri}\t{code}\t{block_id}\t"
        f'"{title}"\t{class_kind}\t{depth}\t{is_residual}\t{chapter_no}\t\t{is_leaf}\t'
        f"{primary_tabulation}\t\t\t\t\t\t{coding_note}\t{parent}\r\n"
    )


_BASE_ROWS = (
    _row("f:ch1", "lin:ch1", "", "", "Chapter One", "chapter", 1, "false", "01", "false", "", "", ""),
    _row(
        "f:blk1", "lin:blk1", "", "BlockL1-1", "- Block One", "block", 1, "false", "01",
        "false", "", "", "f:ch1",
    ),
    _row(
        "", "lin:cat1", "1A00", "", "- - Some Disease", "category", 2, "false", "01",
        "true", "true", "", "f:blk1",
    ),
    _row(
        "", "lin:cat2", "1A0Z", "", "- - Some Disease, unspecified", "category", 2, "true",
        "01", "true", "false", "Use additional code", "f:blk1",
    ),
)


def _write_export(rows) -> Path:
    handle = tempfile.NamedTemporaryFile(mode="wb", suffix=".txt", delete=False)
    path = Path(handle.name)
    text = _HEADER + "".join(rows)
    handle.write(b"\xef\xbb\xbf" + text.encode("utf-8"))
    handle.close()
    return path


class Icd11MmsServiceTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        db.session.execute(sa.delete(MasIcd11Mms))
        db.session.flush()

    def test_import_parses_chapters_blocks_categories_and_residual(self):
        path = _write_export(_BASE_ROWS)
        try:
            result = import_icd11_mms_from_export(export_path=path, release="2026-01")
        finally:
            path.unlink()

        self.assertEqual(result.total_rows, 4)
        self.assertEqual(result.inserted, 4)
        self.assertEqual(result.updated, 0)
        self.assertEqual(result.deactivated, 0)

        chapter = db.session.scalar(
            sa.select(MasIcd11Mms).where(MasIcd11Mms.linearization_uri == "lin:ch1")
        )
        self.assertEqual(chapter.class_kind, "chapter")
        self.assertIsNone(chapter.parent_linearization_uri)
        self.assertEqual(chapter.title, "Chapter One")

        block = db.session.scalar(
            sa.select(MasIcd11Mms).where(MasIcd11Mms.linearization_uri == "lin:blk1")
        )
        self.assertEqual(block.class_kind, "block")
        # Title depth prefix ("- ") must be stripped.
        self.assertEqual(block.title, "Block One")
        self.assertEqual(block.parent_linearization_uri, "lin:ch1")

        category = db.session.scalar(
            sa.select(MasIcd11Mms).where(MasIcd11Mms.linearization_uri == "lin:cat1")
        )
        self.assertEqual(category.code, "1A00")
        self.assertEqual(category.title, "Some Disease")
        self.assertEqual(category.parent_linearization_uri, "lin:blk1")
        self.assertFalse(category.is_residual)
        self.assertTrue(category.is_leaf)
        self.assertTrue(category.primary_tabulation)

        residual = db.session.scalar(
            sa.select(MasIcd11Mms).where(MasIcd11Mms.linearization_uri == "lin:cat2")
        )
        self.assertTrue(residual.is_residual)
        self.assertEqual(residual.coding_note, "Use additional code")

    def test_import_is_idempotent_and_deactivates_missing_rows(self):
        path = _write_export(_BASE_ROWS)
        try:
            import_icd11_mms_from_export(export_path=path, release="2026-01")
        finally:
            path.unlink()

        # Second import drops the residual row (lin:cat2).
        path = _write_export(_BASE_ROWS[:3])
        try:
            result = import_icd11_mms_from_export(export_path=path, release="2026-01")
        finally:
            path.unlink()

        self.assertEqual(result.inserted, 0)
        self.assertEqual(result.updated, 3)
        self.assertEqual(result.deactivated, 1)

        residual = db.session.scalar(
            sa.select(MasIcd11Mms).where(MasIcd11Mms.linearization_uri == "lin:cat2")
        )
        self.assertFalse(residual.is_active)
        self.assertIsNotNone(residual)  # never deleted

    def test_import_preserves_policy_columns_unless_apply_policy_columns(self):
        path = _write_export(_BASE_ROWS)
        try:
            import_icd11_mms_from_export(export_path=path, release="2026-01")
        finally:
            path.unlink()

        update_icd11_mms_policy(
            "lin:cat1",
            release="2026-01",
            is_coding_selectable=True,
            sex_selectable="both",
            age_group_selectable="all",
            restriction_note="curated",
        )

        # Rerun without apply_policy_columns: policy survives.
        path = _write_export(_BASE_ROWS)
        try:
            import_icd11_mms_from_export(export_path=path, release="2026-01")
        finally:
            path.unlink()

        category = db.session.scalar(
            sa.select(MasIcd11Mms).where(MasIcd11Mms.linearization_uri == "lin:cat1")
        )
        self.assertTrue(category.is_coding_selectable)
        self.assertEqual(category.restriction_note, "curated")

        # Rerun with apply_policy_columns: policy resets to unreviewed/None.
        path = _write_export(_BASE_ROWS)
        try:
            import_icd11_mms_from_export(
                export_path=path, release="2026-01", apply_policy_columns=True
            )
        finally:
            path.unlink()

        category = db.session.scalar(
            sa.select(MasIcd11Mms).where(MasIcd11Mms.linearization_uri == "lin:cat1")
        )
        self.assertIsNone(category.is_coding_selectable)
        self.assertIsNone(category.restriction_note)
        self.assertEqual(category.policy_status, "unreviewed")

    def test_stats_counts_by_class_kind(self):
        path = _write_export(_BASE_ROWS)
        try:
            import_icd11_mms_from_export(export_path=path, release="2026-01")
        finally:
            path.unlink()

        stats = get_icd11_mms_stats(release="2026-01")
        self.assertEqual(stats["total_rows"], 4)
        self.assertEqual(stats["chapters"], 1)
        self.assertEqual(stats["blocks"], 1)
        self.assertEqual(stats["categories"], 2)
        self.assertEqual(stats["residual_rows"], 1)

    def test_list_children_and_node_details(self):
        path = _write_export(_BASE_ROWS)
        try:
            import_icd11_mms_from_export(export_path=path, release="2026-01")
        finally:
            path.unlink()

        roots = list_icd11_mms_children(None, release="2026-01")
        self.assertEqual([row["linearization_uri"] for row in roots], ["lin:ch1"])
        self.assertEqual(roots[0]["child_count"], 1)

        children = list_icd11_mms_children("lin:blk1", release="2026-01")
        self.assertEqual(
            sorted(row["linearization_uri"] for row in children), ["lin:cat1", "lin:cat2"]
        )

        details = get_icd11_mms_node_details("lin:cat1", release="2026-01")
        self.assertEqual(details["code"], "1A00")
        self.assertEqual(
            [a["linearization_uri"] for a in details["ancestors"]], ["lin:ch1", "lin:blk1"]
        )

    def test_search_ranks_exact_code_match_first(self):
        path = _write_export(_BASE_ROWS)
        try:
            import_icd11_mms_from_export(export_path=path, release="2026-01")
        finally:
            path.unlink()

        update_icd11_mms_policy(
            "lin:cat1",
            release="2026-01",
            is_coding_selectable=True,
            sex_selectable="both",
            age_group_selectable="all",
            restriction_note=None,
        )
        update_icd11_mms_policy(
            "lin:cat2",
            release="2026-01",
            is_coding_selectable=True,
            sex_selectable="both",
            age_group_selectable="all",
            restriction_note=None,
        )

        results = search_icd11_mms("1A00", release="2026-01")
        self.assertTrue(results)
        self.assertEqual(results[0]["icd_code"], "1A00")

        title_results = search_icd11_mms("disease", release="2026-01")
        codes = [row["icd_code"] for row in title_results]
        self.assertIn("1A00", codes)
        self.assertIn("1A0Z", codes)

        # '%' and '_' match literally, not as LIKE wildcards.
        self.assertEqual(search_icd11_mms("1_00", release="2026-01"), [])
        self.assertEqual(search_icd11_mms("%%%", release="2026-01"), [])

    def test_policy_export_and_import_round_trip(self):
        path = _write_export(_BASE_ROWS)
        try:
            import_icd11_mms_from_export(export_path=path, release="2026-01")
        finally:
            path.unlink()

        update_icd11_mms_policy(
            "lin:cat1",
            release="2026-01",
            is_coding_selectable=True,
            sex_selectable="both",
            age_group_selectable="all",
            restriction_note=None,
        )
        export = export_icd11_mms_policy_json(release="2026-01")
        self.assertEqual(export["release"], "2026-01")
        self.assertEqual(export["row_count"], 1)

        import_payload = {
            "items": [
                {
                    "linearization_uri": "lin:cat2",
                    "is_coding_selectable": True,
                    "sex_selectable": "female",
                    "age_group_selectable": "adult",
                }
            ]
        }
        result = import_icd11_mms_policy_json(import_payload, release="2026-01")
        self.assertEqual(result.updated_items, 1)
        # lin:cat1 was not in the import payload, so it resets to disabled.
        self.assertEqual(result.reset_items, 1)

        cat1 = db.session.scalar(
            sa.select(MasIcd11Mms).where(MasIcd11Mms.linearization_uri == "lin:cat1")
        )
        self.assertFalse(cat1.is_coding_selectable)
        cat2 = db.session.scalar(
            sa.select(MasIcd11Mms).where(MasIcd11Mms.linearization_uri == "lin:cat2")
        )
        self.assertEqual(cat2.sex_selectable, "female")
