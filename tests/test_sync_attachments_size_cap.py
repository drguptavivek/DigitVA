"""ODK sync caps each attachment and stores only what it can name.

Policy: docs/policy/odk-attachment-intake-limits.md. A file over its cap is not
stored: the cap is checked on Content-Length first and then on the bytes as they
stream, so a body is never read past the cap. The row keeps its metadata and
Central's ETag, so only a changed ETag fetches it again. The stored MIME comes
from the leading bytes when they are recognised, and an active label a browser
could run is stored as application/octet-stream.
"""

import os
import tempfile
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.services import attachment_service as svc
from app.utils.va_odk import va_odk_07_syncattachments as sync

JPEG_HEAD = b"\xff\xd8\xff\xe0" + b"\x00" * 60


class _FakeResponse:
    def __init__(self, *, status_code=200, headers=None, content=b"", json_data=None, chunk=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._content = content
        self._json = json_data
        self._chunk = chunk
        self.text = ""
        self.chunks_read = 0

    def json(self):
        return self._json

    def iter_content(self, chunk_size=1):
        step = self._chunk or chunk_size
        for index in range(0, len(self._content), step):
            self.chunks_read += 1
            yield self._content[index:index + step]

    def close(self):
        pass


class _FakeSession:
    """Serves queued responses in order; an unexpected extra GET fails loudly."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError(f"Unexpected GET {url}")
        return self.responses.pop(0)


def _va_form():
    return SimpleNamespace(
        project_id="PROJ01",
        odk_project_id="11",
        odk_form_id="FORM_A",
        form_id="FORM01",
    )


class _SyncHarness(TestCase):
    """Runs one submission sync with the store and temp files faked out."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmpdir.cleanup)
        self.temp_paths = []
        self.ingest_calls = []

    def _temp_path(self, form_id):
        path = os.path.join(self._tmpdir.name, f"download-{len(self.temp_paths)}.tmp")
        self.temp_paths.append(path)
        return path

    def _ingest(self, **kwargs):
        self.ingest_calls.append(kwargs)
        os.remove(kwargs["temp_path"])
        from datetime import datetime, timezone
        return SimpleNamespace(
            storage_name="token" + os.path.splitext(kwargs["filename"])[1],
            local_path="/managed/" + kwargs["filename"],
            store_state="local",
            mime_type=kwargs["mime_type"],
            etag=kwargs["etag"],
            downloaded_at=kwargs["downloaded_at"] or datetime.now(timezone.utc),
            state_values={"source_state": "available"},
        )

    def sync(self, responses, *, existing_etags=None, existing_refused=None, existing_local_paths=None,
             existing_storage_names=None, force_redownload=False):
        session = _FakeSession(responses)
        client = SimpleNamespace(session=session)
        with patch.object(sync, "new_ingest_temp_path", side_effect=self._temp_path), \
                patch.object(sync, "ingest_download", side_effect=self._ingest):
            result = sync._sync_submission_attachments_no_db(
                _va_form(), "uuid:abc", "uuid:abc-form01",
                existing_etags or {}, existing_local_paths or {}, existing_storage_names or {},
                client,
                force_redownload=force_redownload,
                existing_refused=existing_refused,
            )
        return result, session


def _listing(*names):
    return _FakeResponse(json_data=[{"name": name, "exists": True} for name in names])


class SizeCapTests(_SyncHarness):
    def test_under_cap_file_is_stored_with_the_type_its_bytes_show(self):
        photo = JPEG_HEAD + b"body"
        result, _ = self.sync([
            _listing("photo.jpg"),
            _FakeResponse(
                headers={"ETag": '"v1"', "Content-Type": "application/octet-stream", "Content-Length": str(len(photo))},
                content=photo,
            ),
        ])

        self.assertEqual(result.downloaded, 1)
        self.assertEqual(result.refused, 0)
        self.assertEqual(self.ingest_calls[0]["mime_type"], "image/jpeg")
        self.assertIsNone(result.changes[0].state_values.get("refused_reason", None))

    def test_declared_length_over_the_cap_is_refused_without_reading_the_body(self):
        response = _FakeResponse(
            headers={"ETag": '"big"', "Content-Type": "image/jpeg",
                     "Content-Length": str(svc.MAX_BYTES + 1)},
            content=b"never read",
        )
        result, _ = self.sync([_listing("big.jpg"), response])

        self.assertEqual(result.refused, 1)
        self.assertEqual(result.errors, 0)
        self.assertEqual(response.chunks_read, 0)
        self.assertEqual(self.ingest_calls, [])
        self.assertEqual(self.temp_paths, [])
        change = result.changes[0]
        self.assertTrue(change.exists_on_odk)
        self.assertIsNone(change.local_path)
        self.assertEqual(change.etag, '"big"')
        self.assertEqual(change.state_values["refused_reason"], "too_large")
        self.assertEqual(change.state_values["refused_size_bytes"], svc.MAX_BYTES + 1)

    def test_body_crossing_the_cap_mid_stream_is_refused_and_stops_reading(self):
        cap = 100
        response = _FakeResponse(
            headers={"ETag": '"stream"', "Content-Type": "image/jpeg"},
            content=b"x" * 1000,
            chunk=50,
        )
        with patch.object(sync, "max_bytes_for", return_value=cap):
            result, _ = self.sync([_listing("grow.jpg"), response])

        self.assertEqual(result.refused, 1)
        self.assertEqual(self.ingest_calls, [])
        # Three 50-byte chunks take the count past the cap of 100; no fourth is read.
        self.assertEqual(response.chunks_read, 3)
        self.assertEqual(result.changes[0].state_values["refused_size_bytes"], 150)
        for path in self.temp_paths:
            self.assertFalse(os.path.exists(path), "capped download left its temp file behind")

    def test_amr_over_five_megabytes_is_refused_by_the_amr_cap(self):
        response = _FakeResponse(
            headers={"ETag": '"amr"', "Content-Length": str(svc.AMR_MAX_BYTES + 1)},
            content=b"#!AMR",
        )
        result, _ = self.sync([_listing("narration.amr"), response])

        self.assertEqual(result.refused, 1)
        self.assertEqual(self.ingest_calls, [])
        self.assertEqual(result.changes[0].state_values["refused_reason"], "too_large")


class RefusedRowTests(_SyncHarness):
    def test_unchanged_etag_on_a_refused_row_is_skipped_and_not_refetched(self):
        result, session = self.sync(
            [
                _listing("big.jpg"),
                _FakeResponse(status_code=304),
            ],
            existing_etags={"big.jpg": '"big"'},
            existing_refused={"big.jpg"},
        )

        self.assertEqual(result.skipped, 1)
        self.assertEqual(result.refused, 1)
        self.assertEqual(result.errors, 0)
        self.assertEqual(result.changes, [])
        self.assertEqual(self.ingest_calls, [])
        # Exactly two GETs: the listing and the conditional fetch. A forced
        # re-download would be a third; the fake session raises on it.
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[1][1]["headers"], {"If-None-Match": '"big"'})

    def test_changed_etag_under_the_cap_clears_the_refusal_and_stores(self):
        photo = JPEG_HEAD + b"new"
        result, _ = self.sync(
            [
                _listing("big.jpg"),
                _FakeResponse(
                    headers={"ETag": '"v2"', "Content-Type": "image/jpeg"},
                    content=photo,
                ),
            ],
            existing_etags={"big.jpg": '"v1"'},
            existing_refused={"big.jpg"},
        )

        self.assertEqual(result.downloaded, 1)
        self.assertEqual(result.refused, 0)
        self.assertEqual(len(self.ingest_calls), 1)
        row = SimpleNamespace(
            exists_on_odk=True, local_path=None, mime_type=None, etag='"v1"',
            last_downloaded_at=None, storage_name=None, source_state="unknown",
            refused_reason="too_large", refused_size_bytes=30_000_000,
        )
        sync._apply_submission_attachment_result(
            {"uuid:abc-form01": {"big.jpg": row}}, result,
        )
        self.assertIsNone(row.refused_reason)
        self.assertIsNone(row.refused_size_bytes)
        self.assertEqual(row.local_path, "/managed/" + "big.jpg")

    def test_forced_redownload_of_a_refused_row_tries_again(self):
        result, session = self.sync(
            [
                _listing("big.jpg"),
                _FakeResponse(status_code=200, headers={"ETag": '"big"', "Content-Length": str(svc.MAX_BYTES + 1)}),
            ],
            existing_etags={"big.jpg": '"big"'},
            existing_refused={"big.jpg"},
            force_redownload=True,
        )

        self.assertEqual(result.refused, 1)
        self.assertNotIn("If-None-Match", session.calls[1][1].get("headers") or {})


class RetryRuleTests(_SyncHarness):
    def test_unchanged_etag_on_an_ordinary_missing_blob_still_refetches(self):
        # The 304 skip is for refused rows only; a plain missing blob self-heals.
        photo = JPEG_HEAD + b"again"
        with patch.object(sync, "attachment_present", return_value=False):
            result, session = self.sync(
                [
                    _listing("photo.jpg"),
                    _FakeResponse(status_code=304),
                    _FakeResponse(headers={"ETag": '"p"', "Content-Type": "image/jpeg"}, content=photo),
                ],
                existing_etags={"photo.jpg": '"p"'},
                existing_storage_names={"photo.jpg": "photo-token.jpg"},
            )

        self.assertEqual(len(session.calls), 3)
        self.assertNotIn("If-None-Match", session.calls[2][1].get("headers") or {})
        self.assertEqual(result.downloaded, 1)
        self.assertEqual(result.refused, 0)

    def test_removal_on_central_clears_a_refusal(self):
        row = SimpleNamespace(
            exists_on_odk=True, local_path=None, mime_type=None, etag='"big"',
            last_downloaded_at=None, storage_name=None, source_state="available",
            refused_reason="too_large", refused_size_bytes=30_000_000,
        )
        self.assertEqual(row.refused_reason, "too_large")
        removed = sync.AttachmentChange(filename="big.jpg", exists_on_odk=False)
        result = sync.SubmissionAttachmentSyncResult(
            va_sid="uuid:abc", downloaded=0, non_audit_downloaded=0, audit_downloaded=0,
            skipped=0, errors=0, etag_not_modified=0, local_present_on_etag=0,
            local_missing_on_etag=0, changes=[removed],
        )

        sync._apply_submission_attachment_result({"uuid:abc": {"big.jpg": row}}, result)

        self.assertFalse(row.exists_on_odk)
        self.assertIsNone(row.refused_reason)
        self.assertIsNone(row.refused_size_bytes)


class ContentTypeTests(_SyncHarness):
    def test_audit_csv_keeps_its_text_label(self):
        result, _ = self.sync([
            _listing("audit.csv"),
            _FakeResponse(headers={"ETag": '"a"', "Content-Type": "text/csv"}, content=b"a,b\n1,2\n"),
        ])

        self.assertEqual(result.audit_downloaded, 1)
        self.assertEqual(self.ingest_calls[0]["mime_type"], "text/csv")

    def test_active_labels_are_stored_as_octet_stream(self):
        result, _ = self.sync([
            _listing("page.html", "drawing.svg", "notes.txt"),
            _FakeResponse(headers={"ETag": '"h"', "Content-Type": "text/html; charset=utf-8"}, content=b"<html>x"),
            _FakeResponse(headers={"ETag": '"s"', "Content-Type": "image/svg+xml"}, content=b"<svg></svg>"),
            _FakeResponse(headers={"ETag": '"t"', "Content-Type": "text/plain"}, content=b"plain"),
        ])

        self.assertEqual(result.downloaded, 3)
        mimes = {call["filename"]: call["mime_type"] for call in self.ingest_calls}
        self.assertEqual(mimes["page.html"], "application/octet-stream")
        self.assertEqual(mimes["drawing.svg"], "application/octet-stream")
        self.assertEqual(mimes["notes.txt"], "text/plain")


class RefusalApplyTests(TestCase):
    """The row write for a refusal: the blob and its name stay, the ETag moves."""

    def _row(self):
        return SimpleNamespace(
            exists_on_odk=True,
            local_path="/managed/old.jpg",
            mime_type="image/jpeg",
            etag='"v1"',
            last_downloaded_at=None,
            storage_name="old-token.jpg",
            source_state="available",
            refused_reason=None,
            refused_size_bytes=None,
        )

    def test_refusal_keeps_the_existing_blob_and_records_the_size(self):
        row = self._row()
        refusal = sync._refusal_change("uuid:abc", "big.jpg", '"v2"', 30_000_000)
        result = sync.SubmissionAttachmentSyncResult(
            va_sid="uuid:abc", downloaded=0, non_audit_downloaded=0, audit_downloaded=0,
            skipped=0, errors=0, etag_not_modified=0, local_present_on_etag=0,
            local_missing_on_etag=0, changes=[refusal], refused=1,
        )

        sync._apply_submission_attachment_result({"uuid:abc": {"big.jpg": row}}, result)

        self.assertEqual(row.refused_reason, "too_large")
        self.assertEqual(row.refused_size_bytes, 30_000_000)
        self.assertEqual(row.etag, '"v2"')
        self.assertEqual(row.local_path, "/managed/old.jpg")
        self.assertEqual(row.storage_name, "old-token.jpg")
        self.assertTrue(row.exists_on_odk)

    def test_an_accepted_download_clears_the_refusal(self):
        row = self._row()
        row.refused_reason = "too_large"
        row.refused_size_bytes = 30_000_000
        accepted = sync.AttachmentChange(
            filename="big.jpg",
            exists_on_odk=True,
            local_path="/managed/new.jpg",
            mime_type="image/jpeg",
            etag='"v3"',
            storage_name="new-token.jpg",
            state_values={"source_state": "available"},
        )
        result = sync.SubmissionAttachmentSyncResult(
            va_sid="uuid:abc", downloaded=1, non_audit_downloaded=1, audit_downloaded=0,
            skipped=0, errors=0, etag_not_modified=0, local_present_on_etag=0,
            local_missing_on_etag=0, changes=[accepted],
        )

        sync._apply_submission_attachment_result({"uuid:abc": {"big.jpg": row}}, result)

        self.assertIsNone(row.refused_reason)
        self.assertIsNone(row.refused_size_bytes)
        self.assertEqual(row.local_path, "/managed/new.jpg")
