import tempfile
from pathlib import Path
from unittest import TestCase

from scripts.check_attachment_integrity import (
    _orphan_destination,
    _quarantine_orphans,
    _scan_media_files,
)


class CheckAttachmentIntegrityTests(TestCase):
    def test_scan_media_files_skips_orphaned_subtree(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app_data = Path(temp_dir)
            media_dir = app_data / "FORM01" / "media"
            orphaned_dir = media_dir / ".orphaned"
            orphaned_dir.mkdir(parents=True)
            (media_dir / "live.txt").write_text("live", encoding="utf-8")
            (orphaned_dir / "old.txt").write_text("old", encoding="utf-8")

            total, files = _scan_media_files(app_data)

            self.assertEqual(total, 1)
            self.assertEqual(files, [(media_dir / "live.txt").resolve(strict=False)])

    def test_orphan_destination_preserves_relative_path_under_media(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            media_dir = Path(temp_dir) / "FORM01" / "media"
            source = media_dir / "nested" / "attachment.jpg"

            destination = _orphan_destination(source)

            self.assertEqual(
                destination,
                media_dir / ".orphaned" / "nested" / "attachment.jpg",
            )

    def test_quarantine_orphans_moves_files_without_overwriting_existing_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            media_dir = Path(temp_dir) / "FORM01" / "media"
            source = media_dir / "nested" / "attachment.jpg"
            existing = media_dir / ".orphaned" / "nested" / "attachment.jpg"
            source.parent.mkdir(parents=True, exist_ok=True)
            existing.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("orphan", encoding="utf-8")
            existing.write_text("already-there", encoding="utf-8")

            moved = _quarantine_orphans([source])

            self.assertEqual(len(moved), 1)
            self.assertFalse(source.exists())
            self.assertTrue(existing.exists())
            self.assertTrue(moved[0][1].exists())
            self.assertEqual(moved[0][1].read_text(encoding="utf-8"), "orphan")
            self.assertNotEqual(moved[0][1], existing)
            self.assertEqual(moved[0][1].name, "attachment.1.jpg")
