"""Tests for the Central-backed attachment source (plan Phase 4a).

Covers connection resolution (including failing closed), response
classification, server-side redirect handling, MIME correction, the stored
state each outcome writes, and the streaming contract. The HTTP layer is a fake
session returning canned ``requests.Response``-like objects, in the same shape
``tests/services/test_odk_client_reuse.py`` uses.
"""

import os
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import (
    MasOdkConnections,
    VaForms,
    VaProjectMaster,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissions,
)
from app.models.map_project_odk import MapProjectOdk
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.services import attachment_source_central as central
from app.services import attachment_service as svc
from app.services.odk_connection_guard_service import OdkRequestSlotBusyError
from tests.base import BaseTestCase

_BASE_URL = "https://central.example.org/v1/"


class _FakeResponse:
    def __init__(self, *, status_code=200, headers=None, content=b""):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content
        self.closed = False
        self.chunks_yielded = 0

    def iter_content(self, chunk_size=1):
        for index in range(0, len(self.content), chunk_size):
            self.chunks_yielded += 1
            yield self.content[index:index + chunk_size]

    def close(self):
        self.closed = True


class _FakeSession:
    base_url = _BASE_URL

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if not self._responses:
            raise AssertionError(f"No fake response configured for {url}")
        return self._responses.pop(0)


class AttachmentSourceCentralTests(BaseTestCase):
    PROJECT_ID = "ATTC01"
    SITE_ID = "AC01"
    FORM_ID = "ATTC01AC0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)

        if not db.session.get(VaProjectMaster, cls.PROJECT_ID):
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="Attachment Central Project",
                project_nickname="AttCentral",
                project_status=VaStatuses.active,
            ))
        if not db.session.get(VaResearchProjects, cls.PROJECT_ID):
            db.session.add(VaResearchProjects(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="Attachment Central Project",
                project_nickname="AttCentral",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
        db.session.flush()

        if not db.session.get(VaSites, cls.SITE_ID):
            db.session.add(VaSites(
                site_id=cls.SITE_ID,
                project_id=cls.PROJECT_ID,
                site_name="Attachment Central Site",
                site_abbr=cls.SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            ))
            db.session.flush()

        if not db.session.get(VaForms, cls.FORM_ID):
            db.session.add(VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.PROJECT_ID,
                site_id=cls.SITE_ID,
                odk_form_id="who_va_2022",
                odk_project_id="7",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            ))
            db.session.flush()

        cls.connection = db.session.scalar(
            sa.select(MasOdkConnections).join(
                MapProjectOdk,
                MapProjectOdk.connection_id == MasOdkConnections.connection_id,
            ).where(MapProjectOdk.project_id == cls.PROJECT_ID)
        )
        if cls.connection is None:
            cls.connection = MasOdkConnections(
                connection_name=f"attachment-central-{uuid.uuid4().hex[:8]}",
                base_url="https://central.example.org",
                username_enc="enc", username_salt="salt",
                password_enc="enc", password_salt="salt",
                status=VaStatuses.active,
            )
            db.session.add(cls.connection)
            db.session.flush()
            db.session.add(MapProjectOdk(
                project_id=cls.PROJECT_ID,
                connection_id=cls.connection.connection_id,
            ))
        db.session.commit()

    # -- fixtures ------------------------------------------------------

    def _attachment(self, *, filename="photo.jpg", source_state=svc.SOURCE_LISTED,
                    source_mime_type=None):
        va_sid = f"uuid:{uuid.uuid4()}-{self.FORM_ID.lower()}"
        db.session.add(VaSubmissions(
            va_sid=va_sid,
            va_form_id=self.FORM_ID,
            va_data_collector="Collector",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=40,
            va_deceased_gender="male",
            va_uniqueid_masked="AC001",
            va_summary=[], va_catcount={}, va_category_list=[],
        ))
        db.session.flush()
        storage_name = uuid.uuid4().hex + ".jpg"
        db.session.add(VaSubmissionAttachments(
            va_sid=va_sid,
            filename=filename,
            local_path=None,
            mime_type="image/jpeg",
            storage_name=storage_name,
            exists_on_odk=True,
            source_state=source_state,
            source_mime_type=source_mime_type,
        ))
        db.session.flush()
        return svc.AttachmentRecord(
            va_sid=va_sid,
            va_form_id=self.FORM_ID,
            storage_name=storage_name,
            filename=filename,
            local_path=None,
            mime_type="image/jpeg",
            source_mime_type=source_mime_type,
        )

    def _with_session(self, responses):
        """Patch the client factory with a fake session and return it."""
        session = _FakeSession(responses)
        patcher = patch.object(
            central, "_client_for_connection",
            return_value=SimpleNamespace(session=session),
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return session

    def _row(self, record):
        return db.session.get(
            VaSubmissionAttachments, (record.va_sid, record.filename)
        )

    # -- resolution ----------------------------------------------------

    def test_resolve_source_uses_the_projects_own_connection(self):
        record = self._attachment()
        self._with_session([])
        source = central.resolve_source(record)
        self.assertIsNotNone(source)
        self.assertEqual(source.odk_project_id, "7")
        self.assertEqual(source.odk_form_id, "who_va_2022")
        self.assertEqual(
            source.instance_id,
            record.va_sid[: -len(f"-{self.FORM_ID.lower()}")],
        )
        self.assertEqual(source.connection_id, self.connection.connection_id)
        self.assertIn("attachments/photo.jpg", source.attachment_path)

    def test_resolve_source_fails_closed_without_an_active_connection(self):
        record = self._attachment()
        self._with_session([])
        self.connection.status = VaStatuses.deactive
        db.session.flush()
        self.assertIsNone(central.resolve_source(record))
        self.connection.status = VaStatuses.active
        db.session.flush()

    def test_fetch_without_a_mapped_connection_is_unconfigured(self):
        record = self._attachment()
        with patch.object(central, "resolve_source", return_value=None):
            result = central.fetch(record)
        self.assertEqual(result.outcome, central.FETCH_UNCONFIGURED)
        self.assertEqual(result.error_code, svc.SOURCE_ERROR_AUTH)

    # -- classification ------------------------------------------------

    def test_fetch_200_returns_an_open_streamed_response(self):
        record = self._attachment()
        session = self._with_session([
            _FakeResponse(headers={"Content-Type": "image/jpeg",
                                   "Content-Length": "9"}, content=b"jpegbytes")
        ])
        result = central.fetch(record)
        self.assertTrue(result.ok)
        self.assertEqual(result.mime_type, "image/jpeg")
        self.assertEqual(result.content_length, 9)
        self.assertFalse(result.redirect_followed)
        self.assertEqual(session.calls[0][1]["stream"], True)
        self.assertEqual(session.calls[0][1]["allow_redirects"], False)
        result.response.close()

    def test_fetch_corrects_a_literal_null_content_type(self):
        record = self._attachment(source_mime_type="image/png")
        self._with_session([
            _FakeResponse(headers={"Content-Type": "null"}, content=b"x")
        ])
        result = central.fetch(record)
        self.assertEqual(result.mime_type, "image/png")
        result.response.close()

    def test_fetch_follows_a_same_origin_redirect(self):
        record = self._attachment()
        session = self._with_session([
            _FakeResponse(status_code=301, headers={
                "Location": "https://central.example.org/v1/projects/7/forms/"
                            "who_va_2022/submissions/other/attachments/photo.jpg",
            }),
            _FakeResponse(headers={"Content-Type": "image/jpeg"}, content=b"ok"),
        ])
        result = central.fetch(record)
        self.assertTrue(result.ok)
        self.assertTrue(result.redirect_followed)
        self.assertEqual(len(session.calls), 2)
        result.response.close()

    def test_fetch_rejects_a_redirect_to_another_host(self):
        record = self._attachment()
        session = self._with_session([
            _FakeResponse(status_code=307, headers={
                "Location": "https://bucket.s3.example.com/blob?sig=abc",
            }),
        ])
        result = central.fetch(record)
        self.assertEqual(result.outcome, central.FETCH_INVALID_REDIRECT)
        self.assertEqual(len(session.calls), 1)

    def test_fetch_rejects_an_endless_redirect_chain(self):
        record = self._attachment()
        hop = _FakeResponse(status_code=302, headers={
            "Location": "https://central.example.org/v1/loop",
        })
        self._with_session([hop] * (central.MAX_REDIRECT_HOPS + 1))
        result = central.fetch(record)
        self.assertEqual(result.outcome, central.FETCH_INVALID_REDIRECT)

    def test_fetch_classifies_error_statuses(self):
        for status, expected in (
            (404, central.FETCH_NOT_FOUND),
            (401, central.FETCH_AUTH),
            (403, central.FETCH_AUTH),
            (429, central.FETCH_THROTTLED),
            (503, central.FETCH_TRANSIENT),
            (418, central.FETCH_UNKNOWN),
        ):
            with self.subTest(status=status):
                record = self._attachment()
                response = _FakeResponse(status_code=status)
                self._with_session([response])
                result = central.fetch(record)
                self.assertEqual(result.outcome, expected)
                self.assertTrue(response.closed)

    def test_fetch_treats_a_busy_pacing_slot_as_throttled(self):
        record = self._attachment()
        self._with_session([_FakeResponse()])
        with patch.object(
            central, "guarded_odk_call",
            side_effect=OdkRequestSlotBusyError("MINERVA", 0.4),
        ):
            result = central.fetch(record)
        self.assertEqual(result.outcome, central.FETCH_THROTTLED)

    # -- stored state --------------------------------------------------

    def test_success_marks_the_source_available(self):
        record = self._attachment()
        central.record_fetch_state(
            record, central.CentralFetch(outcome=central.FETCH_OK,
                                         mime_type="image/jpeg")
        )
        row = self._row(record)
        self.assertEqual(row.source_state, svc.SOURCE_AVAILABLE)
        self.assertIsNone(row.source_error_code)
        self.assertEqual(row.source_mime_type, "image/jpeg")
        self.assertIsNotNone(row.source_verified_at)

    def test_not_found_marks_the_source_missing(self):
        record = self._attachment()
        central.record_fetch_state(
            record, central.CentralFetch(outcome=central.FETCH_NOT_FOUND)
        )
        row = self._row(record)
        self.assertEqual(row.source_state, svc.SOURCE_MISSING)
        self.assertEqual(row.source_error_code, svc.SOURCE_ERROR_NOT_FOUND)
        self.assertIsNone(row.source_verified_at)

    def test_a_transient_failure_does_not_unprove_an_available_row(self):
        record = self._attachment(source_state=svc.SOURCE_AVAILABLE)
        central.record_fetch_state(
            record, central.CentralFetch(outcome=central.FETCH_TRANSIENT)
        )
        row = self._row(record)
        self.assertEqual(row.source_state, svc.SOURCE_AVAILABLE)
        self.assertEqual(row.source_error_code, svc.SOURCE_ERROR_TRANSIENT)

    def test_a_transient_failure_on_an_unproven_row_is_an_error(self):
        record = self._attachment(source_state=svc.SOURCE_LISTED)
        central.record_fetch_state(
            record, central.CentralFetch(outcome=central.FETCH_AUTH)
        )
        row = self._row(record)
        self.assertEqual(row.source_state, svc.SOURCE_ERROR)
        self.assertEqual(row.source_error_code, svc.SOURCE_ERROR_AUTH)

    # -- streaming and the DigitVA store -------------------------------

    def _media_dir(self, record):
        from flask import current_app
        media_dir = os.path.join(
            current_app.config["APP_DATA"], record.va_form_id, "media"
        )
        os.makedirs(media_dir, exist_ok=True)
        return media_dir

    def _tmp_names(self, media_dir):
        return [name for name in os.listdir(media_dir) if name.startswith(".tmp_")]

    def test_central_body_is_streamed_lazily_stored_once_and_closed(self):
        record = self._attachment()
        payload = b"a" * (svc.ATTACHMENT_STREAM_CHUNK_SIZE * 3)
        upstream = _FakeResponse(headers={"Content-Type": "image/jpeg"},
                                 content=payload)
        result = central.CentralFetch(
            outcome=central.FETCH_OK, response=upstream,
            mime_type="image/jpeg", content_length=len(payload),
        )
        with self.app.test_request_context("/"):
            media_dir = self._media_dir(record)
            target = os.path.join(media_dir, record.storage_name)
            self.addCleanup(lambda: os.path.exists(target) and os.unlink(target))

            response = svc._stream_central_response(record, result)
            # Nothing has been read yet: building the response must not pull
            # the body into memory, and nothing is in the store yet either.
            self.assertEqual(upstream.chunks_yielded, 0)
            self.assertFalse(os.path.exists(target))
            self.assertEqual(response.headers["Content-Length"], str(len(payload)))
            self.assertIn("inline", response.headers["Content-Disposition"])
            self.assertIn(record.storage_name, response.headers["Content-Disposition"])
            self.assertIn("no-store", response.headers["Cache-Control"])
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

            body = b"".join(response.iter_encoded())
            self.assertEqual(body, payload)
            self.assertEqual(upstream.chunks_yielded, 3)
            self.assertTrue(upstream.closed)

            with open(target, "rb") as handle:
                self.assertEqual(handle.read(), payload)
            self.assertEqual(self._tmp_names(media_dir), [])
            self.assertEqual(self._row(record).local_path, target)
            self.assertEqual(self._row(record).local_fallback_state, svc.LOCAL_PRESENT)

    def test_an_abandoned_stream_leaves_no_partial_object(self):
        """A client disconnect must not leave a temp file or a partial object."""
        record = self._attachment()
        payload = b"b" * (svc.ATTACHMENT_STREAM_CHUNK_SIZE * 3)
        with self.app.test_request_context("/"):
            media_dir = self._media_dir(record)
            target = os.path.join(media_dir, record.storage_name)
            self.addCleanup(lambda: os.path.exists(target) and os.unlink(target))

            def chunks():
                yield payload[:svc.ATTACHMENT_STREAM_CHUNK_SIZE]
                yield payload[svc.ATTACHMENT_STREAM_CHUNK_SIZE:]

            stream = svc._store_write(record, chunks())
            next(stream)
            self.assertEqual(len(self._tmp_names(media_dir)), 1)
            stream.close()

            self.assertFalse(os.path.exists(target))
            self.assertEqual(self._tmp_names(media_dir), [])

    def test_a_failing_upstream_leaves_no_partial_object(self):
        record = self._attachment()
        with self.app.test_request_context("/"):
            media_dir = self._media_dir(record)
            target = os.path.join(media_dir, record.storage_name)
            self.addCleanup(lambda: os.path.exists(target) and os.unlink(target))

            def chunks():
                yield b"half"
                raise OSError("upstream died")

            with self.assertRaises(OSError):
                list(svc._store_write(record, chunks()))

            self.assertFalse(os.path.exists(target))
            self.assertEqual(self._tmp_names(media_dir), [])

    def test_store_exists_prefers_the_storage_name_object(self):
        record = self._attachment()
        with self.app.test_request_context("/"):
            media_dir = self._media_dir(record)
            self.assertIsNone(svc._store_exists(record))
            target = os.path.join(media_dir, record.storage_name)
            with open(target, "wb") as handle:
                handle.write(b"stored")
            self.addCleanup(lambda: os.path.exists(target) and os.unlink(target))
            self.assertEqual(svc._store_exists(record), os.path.realpath(target))
