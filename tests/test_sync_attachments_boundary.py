"""Attachment sync must not touch the filesystem or the store itself.

The module boundary in docs/policy/attachment-storage.md says no module outside
``app/services/attachment_service.py`` performs filesystem, store or Central
operations for an attachment. ``va_odk_07_syncattachments`` is the module that
used to, so it gets an explicit guard: it may list attachments, issue the
conditional GET, write the body to the temp path the service hands it, and
apply the row — nothing else.
"""

import ast
import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.utils.va_odk import va_odk_07_syncattachments as sync


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


class SyncAttachmentBoundaryTests(TestCase):
    def test_the_module_imports_no_filesystem_or_subprocess_tooling(self):
        source = open(sync.__file__, encoding="utf-8").read()
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        for banned in ("os", "shutil", "subprocess", "tempfile", "pathlib"):
            self.assertNotIn(
                banned, imported,
                f"{banned} belongs to the attachment service, not to sync",
            )

    def test_the_module_never_calls_the_attachment_store(self):
        source = open(sync.__file__, encoding="utf-8").read()
        self.assertNotIn("attachment_store", source)
        self.assertNotIn("media_dir", source)

    def test_a_download_is_handed_to_the_service_as_a_temp_path(self):
        va_form = SimpleNamespace(
            project_id="PROJ01",
            odk_project_id="11",
            odk_form_id="FORM_A",
            form_id="FORM01",
        )
        client = SimpleNamespace(session=_FakeSession([
            _FakeResponse(json_data=[{"name": "photo.jpg", "exists": True}]),
            _FakeResponse(
                headers={"ETag": '"abc"', "Content-Type": "image/jpeg"},
                content=b"image-bytes",
            ),
        ]))

        captured = {}

        def fake_temp_path(form_id):
            captured["temp_path"] = os.path.join(self._tmp, "download.tmp")
            return captured["temp_path"]

        def fake_ingest(**kwargs):
            captured["kwargs"] = kwargs
            with open(kwargs["temp_path"], "rb") as handle:
                captured["body"] = handle.read()
            os.remove(kwargs["temp_path"])
            from datetime import datetime, timezone
            return SimpleNamespace(
                storage_name="token.jpg",
                local_path="/managed/by/the/service.jpg",
                store_state="local",
                mime_type=kwargs["mime_type"],
                etag=kwargs["etag"],
                downloaded_at=kwargs["downloaded_at"] or datetime.now(timezone.utc),
                state_values={"source_state": "available"},
            )

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            self._tmp = tmp
            with patch.object(sync, "new_ingest_temp_path", side_effect=fake_temp_path), \
                    patch.object(sync, "ingest_download", side_effect=fake_ingest):
                result = sync._sync_submission_attachments_no_db(
                    va_form, "uuid:abc", "uuid:abc-form01", {}, {}, {}, client,
                )

        self.assertEqual(result.downloaded, 1)
        self.assertEqual(captured["body"], b"image-bytes")
        self.assertEqual(captured["kwargs"]["va_form_id"], "FORM01")
        self.assertEqual(captured["kwargs"]["filename"], "photo.jpg")
        self.assertEqual(captured["kwargs"]["mime_type"], "image/jpeg")
        change = result.changes[0]
        self.assertEqual(change.storage_name, "token.jpg")
        self.assertEqual(change.state_values, {"source_state": "available"})
