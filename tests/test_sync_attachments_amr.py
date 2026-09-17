"""AMR→MP3 conversion failure must be an explicit error, never a corrupt row.

Plan Finding 5: the converter used to return the *source* path on failure and
the caller then recorded a temp AMR blob as a ``.mp3`` storage_name.
"""

import os
import subprocess
import tempfile
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from sqlalchemy.dialects import postgresql

from app.utils.va_odk.va_odk_07_syncattachments import (
    AmrConversionError,
    SubmissionAttachmentSyncResult,
    _apply_submission_attachment_result,
    _convert_amr_to_mp3,
)


class AmrConversionFailureTests(TestCase):
    def test_failure_raises_and_leaves_no_partial_output(self):
        with tempfile.TemporaryDirectory() as media_dir:
            src = os.path.join(media_dir, ".tmp_source")
            with open(src, "wb") as f:
                f.write(b"amr-bytes")
            out = os.path.join(media_dir, "derivative.mp3")

            def failing_run(cmd, **kwargs):
                with open(out, "wb") as partial:
                    partial.write(b"partial")
                raise subprocess.CalledProcessError(1, cmd, stderr="sox failed")

            with patch("app.utils.va_odk.va_odk_07_syncattachments.subprocess.check_output", side_effect=OSError("no soxi")), \
                 patch("app.utils.va_odk.va_odk_07_syncattachments.subprocess.run", side_effect=failing_run):
                with self.assertRaises(AmrConversionError):
                    _convert_amr_to_mp3(src, "FORM01", output_path=out)

            self.assertTrue(os.path.exists(src), "source is left for the caller's cleanup")
            self.assertFalse(os.path.exists(out), "no partial derivative may remain")

    def test_success_removes_source_and_returns_output(self):
        with tempfile.TemporaryDirectory() as media_dir:
            src = os.path.join(media_dir, ".tmp_source")
            with open(src, "wb") as f:
                f.write(b"amr-bytes")
            out = os.path.join(media_dir, "derivative.mp3")

            def ok_run(cmd, **kwargs):
                with open(out, "wb") as mp3:
                    mp3.write(b"mp3")
                return subprocess.CompletedProcess(cmd, 0)

            with patch("app.utils.va_odk.va_odk_07_syncattachments.subprocess.check_output", return_value=b"2.0"), \
                 patch("app.utils.va_odk.va_odk_07_syncattachments.subprocess.run", side_effect=ok_run):
                result = _convert_amr_to_mp3(src, "FORM01", output_path=out)

            self.assertEqual(result, out)
            self.assertFalse(os.path.exists(src))
            self.assertTrue(os.path.exists(out))


class AmrSyncStateWriteTests(TestCase):
    """Phase 2 state written by the attachment sync apply path.

    Existing rows are plain namespaces: the apply path assigns attributes on an
    ORM row and needs no session for that branch.
    """

    SID = "uuid:state-form01"

    def _existing_row(self, **overrides):
        base = dict(
            storage_name="old-token.mp3",
            local_path="/tmp/old.mp3",
            exists_on_odk=True,
            mime_type="audio/amr",
            etag="old-etag",
            last_downloaded_at=None,
            source_state="listed",
            source_verified_at=None,
            source_error_code="transient",
            source_mime_type=None,
            derivative_state="ready",
            derivative_mime_type="audio/mpeg",
            derivative_source_validator="old-etag",
            derivative_verified_at=None,
            derivative_error_code=None,
        )
        base.update(overrides)
        return SimpleNamespace(**base)

    def _apply(self, record, filename, result_kwargs):
        defaults = dict(
            va_sid=self.SID,
            downloaded=0,
            non_audit_downloaded=0,
            audit_downloaded=0,
            skipped=0,
            errors=0,
            etag_not_modified=0,
            local_present_on_etag=0,
            local_missing_on_etag=0,
            changes=[],
        )
        defaults.update(result_kwargs)
        result = SubmissionAttachmentSyncResult(**defaults)
        with patch(
            "app.utils.va_odk.va_odk_07_syncattachments._invalidate_attachment_cache"
        ):
            _apply_submission_attachment_result(
                {self.SID: {filename: record}}, result
            )

    def test_successful_amr_download_records_source_and_derivative_state(self):
        record = self._existing_row()
        downloaded_at = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)
        change = SimpleNamespace(
            filename="narration.amr",
            exists_on_odk=True,
            local_path="/tmp/new.mp3",
            mime_type="audio/amr",
            etag="new-etag",
            last_downloaded_at=downloaded_at,
            storage_name="new-token.mp3",
        )

        self._apply(record, "narration.amr", {"changes": [change]})

        self.assertEqual(record.source_state, "available")
        self.assertEqual(record.source_verified_at, downloaded_at)
        self.assertIsNone(record.source_error_code)
        self.assertEqual(record.source_mime_type, "audio/amr")
        self.assertEqual(record.derivative_state, "ready")
        self.assertEqual(record.derivative_mime_type, "audio/mpeg")
        self.assertEqual(record.derivative_source_validator, "new-etag")
        self.assertEqual(record.derivative_verified_at, downloaded_at)
        self.assertIsNone(record.derivative_error_code)

    def test_image_download_leaves_derivative_state_untouched(self):
        record = self._existing_row(derivative_state=None, derivative_mime_type=None)
        change = SimpleNamespace(
            filename="photo.jpg",
            exists_on_odk=True,
            local_path="/tmp/new.jpg",
            mime_type="image/jpeg",
            etag="new-etag",
            last_downloaded_at=datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc),
            storage_name="new-token.jpg",
        )

        self._apply(record, "photo.jpg", {"changes": [change]})

        self.assertEqual(record.source_state, "available")
        self.assertEqual(record.source_mime_type, "image/jpeg")
        self.assertIsNone(record.derivative_state)

    def test_attachment_removed_on_odk_is_marked_missing(self):
        record = self._existing_row()
        change = SimpleNamespace(
            filename="narration.amr",
            exists_on_odk=False,
            local_path=None,
            mime_type=None,
            etag=None,
            last_downloaded_at=None,
            storage_name=None,
        )

        self._apply(record, "narration.amr", {"changes": [change]})

        self.assertEqual(record.source_state, "missing")
        # The local copy and its derivative record are not rewritten.
        self.assertEqual(record.derivative_state, "ready")

    def test_conversion_failure_records_an_explicit_derivative_error(self):
        record = self._existing_row()

        self._apply(
            record, "narration.amr", {"derivative_failures": ["narration.amr"]}
        )

        self.assertEqual(record.derivative_state, "error")
        self.assertEqual(record.derivative_error_code, "conversion_failed")
        # Finding 5: the previous blob and its storage name are left alone.
        self.assertEqual(record.storage_name, "old-token.mp3")
        self.assertEqual(record.local_path, "/tmp/old.mp3")

    def test_new_amr_row_upserts_the_state_columns(self):
        change = SimpleNamespace(
            filename="narration.amr",
            exists_on_odk=True,
            local_path="/tmp/new.mp3",
            mime_type="audio/amr",
            etag="new-etag",
            last_downloaded_at=datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc),
            storage_name="new-token.mp3",
        )
        result = SubmissionAttachmentSyncResult(
            va_sid=self.SID,
            downloaded=1,
            non_audit_downloaded=1,
            audit_downloaded=0,
            skipped=0,
            errors=0,
            etag_not_modified=0,
            local_present_on_etag=0,
            local_missing_on_etag=0,
            changes=[change],
        )
        statements = []
        session = MagicMock()
        session.execute.side_effect = lambda stmt: statements.append(stmt)

        with patch("app.db.session", session), patch(
            "app.utils.va_odk.va_odk_07_syncattachments._invalidate_attachment_cache"
        ):
            _apply_submission_attachment_result({self.SID: {}}, result)

        compiled = statements[0].compile(dialect=postgresql.dialect())
        self.assertEqual(compiled.params["source_state"], "available")
        self.assertEqual(compiled.params["derivative_state"], "ready")
        self.assertEqual(compiled.params["derivative_mime_type"], "audio/mpeg")
        self.assertEqual(compiled.params["derivative_source_validator"], "new-etag")
        conflict_clause = str(compiled).split("DO UPDATE SET", 1)[1]
        self.assertIn("source_state", conflict_clause)
        self.assertIn("derivative_state", conflict_clause)
