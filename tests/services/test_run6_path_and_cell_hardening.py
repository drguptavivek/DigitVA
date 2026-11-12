"""Path, cell and presign hardening for the WHO proxy, exports, ODK sync and S3 links."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock

from app.services.attachment_store import S3AttachmentStore
from app.services.data_management_service import _serialize_csv_cell
from app.services.who_icd_api import _validate_resource
from app.utils.va_odk import va_odk_07_syncattachments as sync


class WhoResourceTests(TestCase):
    def test_encoded_dot_segments_are_refused(self):
        for bad in (
            "icd/release/11/mms/%2e%2e/%2e%2e/swagger",
            "icd/release/11/mms/%252e%252e/x",
            "icd/release/11/mms/%2E%2E/x",
        ):
            with self.assertRaises(ValueError):
                _validate_resource(bad)

    def test_codeinfo_style_encoding_still_passes(self):
        ok = "icd/release/11/2026-01/mms/codeinfo/1A00%26%2F%3B"
        self.assertEqual(_validate_resource(ok), ok)


class CsvCellTests(TestCase):
    def test_formula_text_is_neutralised(self):
        self.assertEqual(_serialize_csv_cell('=HYPERLINK("http://x")'), "'=HYPERLINK(\"http://x\")")
        self.assertEqual(_serialize_csv_cell("plain"), "plain")
        self.assertEqual(_serialize_csv_cell(None), "")


class SyncUrlTests(TestCase):
    def test_central_supplied_segments_stay_one_encoded_segment(self):
        urls = []

        class Session:
            def get(self, url, **kwargs):
                urls.append(url)
                if len(urls) == 1:
                    return SimpleNamespace(
                        status_code=200,
                        json=lambda: [{"name": "../../users?x#", "exists": True}],
                    )
                return SimpleNamespace(status_code=404, headers={}, text="", close=lambda: None)

        va_form = SimpleNamespace(
            project_id="P", odk_project_id="11", odk_form_id="F", form_id="F1"
        )
        try:
            sync._sync_submission_attachments_no_db(
                va_form, "uuid:a/b", "sid", {}, {}, {},
                SimpleNamespace(session=Session()),
            )
        except Exception:
            pass
        self.assertEqual(urls[0], "projects/11/forms/F/submissions/uuid%3Aa%2Fb/attachments")
        self.assertEqual(
            urls[1],
            "projects/11/forms/F/submissions/uuid%3Aa%2Fb/attachments/..%2F..%2Fusers%3Fx%23",
        )


class PresignTests(TestCase):
    def _params(self, content_type, filename="f"):
        client = MagicMock()
        store = S3AttachmentStore(bucket="b", prefix="", expiry_seconds=60, client=client)
        record = SimpleNamespace(va_form_id="F", storage_name="tok", local_path=None)
        store.presigned_url(record, content_type=content_type, filename=filename)
        return client.generate_presigned_url.call_args.kwargs["Params"]

    def test_html_and_svg_are_forced_to_download(self):
        for ctype in ("text/html", "image/svg+xml"):
            params = self._params(ctype, "x.html")
            self.assertEqual(params["ResponseContentType"], "application/octet-stream")
            self.assertTrue(params["ResponseContentDisposition"].startswith("attachment;"))

    def test_allowlisted_type_stays_inline(self):
        params = self._params("image/png", "x.png")
        self.assertEqual(params["ResponseContentType"], "image/png")
        self.assertTrue(params["ResponseContentDisposition"].startswith("inline;"))
