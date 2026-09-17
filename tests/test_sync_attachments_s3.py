"""Attachment sync writes its blobs to the selected store.

The local-store behaviour is covered by ``tests/test_sync_attachments_amr.py``
and ``tests/services/test_odk_client_reuse.py``. These tests run the same
network-only sync with ``ATTACHMENT_STORE=s3`` under moto and assert that the
blob lands in the bucket, that no file is left on this app server, and that a
failed upload leaves neither an object nor a temp file.
"""

import os
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from moto import mock_aws

from app.services import attachment_service as svc
from app.services import attachment_store as store_mod
from app.utils.va_odk import va_odk_07_syncattachments as sync
from tests.services.test_attachment_store import make_s3_app


class _FakeResponse:
    def __init__(self, *, status_code=200, headers=None, content=b"", json_data=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._content = content
        self._json = json_data
        self.text = ""
        self.closed = False

    def json(self):
        return self._json

    def iter_content(self, chunk_size=1):
        for index in range(0, len(self._content), chunk_size):
            yield self._content[index:index + chunk_size]

    def close(self):
        self.closed = True


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)

    def get(self, url, **kwargs):
        if not self._responses:
            raise AssertionError(f"No fake response configured for {url}")
        return self._responses.pop(0)


class SyncToS3StoreTests(TestCase):
    FORM_ID = "SYNCS3"

    def setUp(self):
        self.mock = mock_aws()
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.addCleanup(store_mod.reset_s3_clients)
        self.app = make_s3_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        self.store = store_mod.get_attachment_store()

        self.app_data = tempfile.TemporaryDirectory()
        self.addCleanup(self.app_data.cleanup)
        self.app.config["APP_DATA"] = self.app_data.name
        self.media_dir = os.path.join(self.app_data.name, self.FORM_ID, "media")
        self.va_form = SimpleNamespace(
            project_id="PROJ01",
            odk_project_id="11",
            odk_form_id="FORM_A",
            form_id=self.FORM_ID,
        )

    def _run(self, responses):
        return sync._sync_submission_attachments_no_db(
            self.va_form,
            "uuid:abc",
            "uuid:abc-form01",
            {},
            {},
            {},
            SimpleNamespace(session=_FakeSession(responses)),
        )

    def _key(self, storage_name):
        return self.store.key_for(
            store_mod.StoreTarget(va_form_id=self.FORM_ID, storage_name=storage_name)
        )

    def _media_files(self):
        """Everything this app server left on disk for the form, if anything."""
        if not os.path.isdir(self.media_dir):
            return []
        return sorted(os.listdir(self.media_dir))

    def _leftover_temp_files(self):
        return [name for name in self._media_files() if name.startswith(".tmp_")]

    def test_image_download_is_put_in_the_bucket_and_leaves_no_local_file(self):
        result = self._run([
            _FakeResponse(json_data=[{"name": "photo.jpg", "exists": True}]),
            _FakeResponse(
                headers={"ETag": '"abc"', "Content-Type": "image/jpeg"},
                content=b"image-bytes",
            ),
        ])

        self.assertEqual(result.downloaded, 1)
        self.assertEqual(result.errors, 0)
        change = result.changes[0]
        self.assertEqual(change.store_state, svc.STORE_STATE_S3)
        self.assertIsNone(change.local_path)

        head = self.store.head(self._key(change.storage_name))
        self.assertIsNotNone(head)
        self.assertEqual(head["ContentLength"], len(b"image-bytes"))
        self.assertEqual(head["ContentType"], "image/jpeg")
        self.assertEqual(self._media_files(), [])

    def test_amr_is_converted_then_put_as_the_mp3_derivative(self):
        def fake_convert(amr_path, form_id, output_path=None):
            os.remove(amr_path)
            with open(output_path, "wb") as handle:
                handle.write(b"mp3-bytes")
            return output_path

        with patch.object(svc, "_convert_amr_to_mp3", side_effect=fake_convert):
            result = self._run([
                _FakeResponse(json_data=[{"name": "narration.amr", "exists": True}]),
                _FakeResponse(
                    headers={"ETag": '"amr"', "Content-Type": "audio/amr"},
                    content=b"amr-bytes",
                ),
            ])

        change = result.changes[0]
        self.assertTrue(change.storage_name.endswith(".mp3"))
        self.assertEqual(change.store_state, svc.STORE_STATE_S3)
        head = self.store.head(self._key(change.storage_name))
        self.assertEqual(head["ContentType"], svc.DERIVATIVE_MIME_TYPE)
        self.assertEqual(head["ContentLength"], len(b"mp3-bytes"))
        self.assertEqual(self._media_files(), [])

    def test_a_failed_upload_records_an_error_and_leaves_nothing_behind(self):
        with patch.object(
            self.store, "put",
            side_effect=store_mod.AttachmentStoreError("boom"),
        ):
            result = self._run([
                _FakeResponse(json_data=[{"name": "photo.jpg", "exists": True}]),
                _FakeResponse(
                    headers={"ETag": '"abc"', "Content-Type": "image/jpeg"},
                    content=b"image-bytes",
                ),
            ])

        self.assertEqual(result.downloaded, 0)
        self.assertEqual(result.errors, 1)
        self.assertEqual(result.changes, [])
        self.assertEqual(list(self.store.iter_keys()), [])
        self.assertEqual(self._leftover_temp_files(), [])

    def test_an_s3_stored_row_is_not_redownloaded_on_a_304(self):
        result = sync._sync_submission_attachments_no_db(
            self.va_form,
            "uuid:abc",
            "uuid:abc-form01",
            {"photo.jpg": '"abc"'},
            {"photo.jpg": None},
            {"photo.jpg": "token.jpg"},
            SimpleNamespace(session=_FakeSession([
                _FakeResponse(json_data=[{"name": "photo.jpg", "exists": True}]),
                _FakeResponse(status_code=304),
            ])),
            existing_store_states={"photo.jpg": svc.STORE_STATE_S3},
        )

        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.local_present_on_etag, 1)
        self.assertEqual(result.changes, [])
