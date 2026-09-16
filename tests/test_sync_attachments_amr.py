"""AMR→MP3 conversion failure must be an explicit error, never a corrupt row.

Plan Finding 5: the converter used to return the *source* path on failure and
the caller then recorded a temp AMR blob as a ``.mp3`` storage_name.
"""

import os
import subprocess
import tempfile
from unittest import TestCase
from unittest.mock import patch

from app.utils.va_odk.va_odk_07_syncattachments import (
    AmrConversionError,
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
