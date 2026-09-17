"""The attachment service owns the whole attachment lifecycle.

Ingest (conversion, store write, readiness state, temp cleanup), the cleanup of
superseded blobs, and repair from ODK Central all live behind
``app/services/attachment_service.py``. These tests exercise that surface
directly; the sync module's own tests assert only that it delegates.

Policy baseline: docs/policy/attachment-storage.md.
"""

import os
import tempfile
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa
from moto import mock_aws

from app import db
from app.models import (
    VaForms,
    VaProjectMaster,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissions,
)
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.services import attachment_service as svc
from app.services import attachment_store as store_mod
from app.services.odk_retirement_service import MISSING_IN_ODK
from tests.base import BaseTestCase

_DOWNLOADED_AT = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)


class _FakeResponse:
    """Just enough of a streamed ``requests.Response`` for a Central fetch."""

    def __init__(self, content=b"", headers=None):
        self.headers = headers or {}
        self._content = content
        self.closed = False

    def iter_content(self, chunk_size=1):
        for index in range(0, len(self._content), chunk_size):
            yield self._content[index:index + chunk_size]

    def close(self):
        self.closed = True


class AttachmentLifecycleBase(BaseTestCase):
    """One project, site and form of our own, plus a throwaway APP_DATA."""

    PROJECT_ID = "ATTL01"
    SITE_ID = "AL01"
    FORM_ID = "ATTL01AL0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        if not db.session.get(VaProjectMaster, cls.PROJECT_ID):
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="Attachment Lifecycle Project",
                project_nickname="AttLifecycle",
                project_status=VaStatuses.active,
                attachment_central_fetch_enabled=False,
            ))
        if not db.session.get(VaResearchProjects, cls.PROJECT_ID):
            db.session.add(VaResearchProjects(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="Attachment Lifecycle Project",
                project_nickname="AttLifecycle",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
        db.session.flush()
        if not db.session.get(VaSites, cls.SITE_ID):
            db.session.add(VaSites(
                site_id=cls.SITE_ID,
                project_id=cls.PROJECT_ID,
                site_name="Attachment Lifecycle Site",
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
                odk_form_id="ATTL_ODK",
                odk_project_id="97",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._old_app_data = self.app.config.get("APP_DATA")
        self.app.config["APP_DATA"] = self._tmp_dir.name

    def tearDown(self):
        self.app.config["APP_DATA"] = self._old_app_data
        self._tmp_dir.cleanup()
        super().tearDown()

    # -- fixtures ----------------------------------------------------------

    def _submission(self, *, sync_issue_code=None):
        sub = VaSubmissions(
            va_sid=str(uuid.uuid4()),
            va_form_id=self.FORM_ID,
            va_data_collector="c",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=1,
            va_deceased_gender="male",
            va_uniqueid_masked="X",
            va_summary=[],
            va_catcount={},
            va_category_list=[],
            va_sync_issue_code=sync_issue_code,
        )
        db.session.add(sub)
        db.session.flush()
        return sub

    def _row(self, va_sid, filename, storage_name, **overrides):
        values = dict(
            va_sid=va_sid,
            filename=filename,
            storage_name=storage_name,
            local_path=None,
            mime_type="image/jpeg",
            exists_on_odk=True,
            last_downloaded_at=datetime.now(timezone.utc),
        )
        values.update(overrides)
        row = VaSubmissionAttachments(**values)
        db.session.add(row)
        db.session.flush()
        return row

    def _record(self, row, filename=None):
        return svc.AttachmentRecord(
            va_sid=row.va_sid,
            va_form_id=self.FORM_ID,
            storage_name=row.storage_name,
            filename=filename or row.filename,
            local_path=row.local_path,
            mime_type=row.mime_type,
            source_mime_type=None,
        )

    def _temp_with(self, payload=b"bytes"):
        path = svc.new_ingest_temp_path(self.FORM_ID)
        with open(path, "wb") as handle:
            handle.write(payload)
        return path

    def _media_files(self):
        media_dir = os.path.join(self._tmp_dir.name, self.FORM_ID, "media")
        if not os.path.isdir(media_dir):
            return []
        return sorted(os.listdir(media_dir))

    def _set_central_fetch(self, enabled):
        project = db.session.get(VaProjectMaster, self.PROJECT_ID)
        project.attachment_central_fetch_enabled = enabled
        db.session.flush()


class LocalIngestTests(AttachmentLifecycleBase):
    def test_image_ingest_stores_the_blob_and_reports_available(self):
        result = svc.ingest_download(
            va_sid="sid-1",
            va_form_id=self.FORM_ID,
            filename="photo.jpg",
            temp_path=self._temp_with(b"image-bytes"),
            mime_type="image/jpeg",
            etag='"abc"',
            downloaded_at=_DOWNLOADED_AT,
        )

        self.assertEqual(result.store_state, svc.STORE_STATE_LOCAL)
        self.assertTrue(result.storage_name.endswith(".jpg"))
        self.assertEqual(self._media_files(), [result.storage_name])
        with open(result.local_path, "rb") as handle:
            self.assertEqual(handle.read(), b"image-bytes")
        self.assertEqual(result.state_values["source_state"], svc.SOURCE_AVAILABLE)
        self.assertEqual(result.state_values["source_verified_at"], _DOWNLOADED_AT)
        self.assertEqual(result.state_values["source_mime_type"], "image/jpeg")
        self.assertNotIn("derivative_state", result.state_values)

    def test_amr_ingest_converts_and_records_a_ready_derivative(self):
        def fake_convert(amr_path, form_id, output_path=None):
            os.remove(amr_path)
            with open(output_path, "wb") as handle:
                handle.write(b"mp3-bytes")
            return output_path

        with patch.object(svc, "_convert_amr_to_mp3", side_effect=fake_convert):
            result = svc.ingest_download(
                va_sid="sid-2",
                va_form_id=self.FORM_ID,
                filename="narration.amr",
                temp_path=self._temp_with(b"amr-bytes"),
                mime_type="audio/amr",
                etag='"amr-etag"',
                downloaded_at=_DOWNLOADED_AT,
            )

        self.assertTrue(result.storage_name.endswith(".mp3"))
        self.assertEqual(self._media_files(), [result.storage_name])
        self.assertEqual(result.state_values["derivative_state"], svc.DERIVATIVE_READY)
        self.assertEqual(result.state_values["derivative_mime_type"], svc.DERIVATIVE_MIME_TYPE)
        self.assertEqual(result.state_values["derivative_source_validator"], '"amr-etag"')

    def test_a_failed_conversion_leaves_no_object_and_no_temp_file(self):
        temp_path = self._temp_with(b"amr-bytes")

        with patch.object(
            svc, "_convert_amr_to_mp3", side_effect=svc.AmrConversionError("boom")
        ):
            with self.assertRaises(svc.AmrConversionError):
                svc.ingest_download(
                    va_sid="sid-3",
                    va_form_id=self.FORM_ID,
                    filename="narration.amr",
                    temp_path=temp_path,
                    mime_type="audio/amr",
                    etag='"amr-etag"',
                    downloaded_at=_DOWNLOADED_AT,
                )

        self.assertEqual(self._media_files(), [])
        self.assertFalse(os.path.exists(temp_path))

    def test_cleanup_superseded_removes_only_unreferenced_local_files(self):
        sub = self._submission()
        keep_path = os.path.join(self._tmp_dir.name, "keep.jpg")
        drop_path = os.path.join(self._tmp_dir.name, "drop.jpg")
        for path in (keep_path, drop_path):
            with open(path, "wb") as handle:
                handle.write(b"x")
        self._row(sub.va_sid, "keep.jpg", uuid.uuid4().hex + ".jpg", local_path=keep_path)

        svc.cleanup_superseded(stale_paths=[
            (drop_path, "/new/a.jpg"),
            (keep_path, "/new/b.jpg"),
        ])

        self.assertFalse(os.path.exists(drop_path))
        self.assertTrue(os.path.exists(keep_path))


class S3IngestTests(AttachmentLifecycleBase):
    """The same ingest contract with ``ATTACHMENT_STORE=s3``, under moto."""

    def setUp(self):
        super().setUp()
        self.mock = mock_aws()
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.addCleanup(store_mod.reset_s3_clients)
        store_mod.reset_s3_clients()
        self._old_store_name = self.app.config.get("ATTACHMENT_STORE")
        self.app.config["ATTACHMENT_STORE"] = "s3"
        self.app.extensions.pop("attachment_store", None)
        self.addCleanup(self._restore_store)
        self.store = store_mod.get_attachment_store()
        self.store.client.create_bucket(
            Bucket=self.store.bucket,
            CreateBucketConfiguration={
                "LocationConstraint": self.app.config["S3_REGION"]
            },
        )

    def _restore_store(self):
        self.app.config["ATTACHMENT_STORE"] = self._old_store_name
        self.app.extensions.pop("attachment_store", None)

    def _key(self, storage_name):
        return self.store.key_for(
            store_mod.StoreTarget(va_form_id=self.FORM_ID, storage_name=storage_name)
        )

    def test_image_ingest_puts_the_object_and_keeps_no_local_file(self):
        result = svc.ingest_download(
            va_sid="sid-1",
            va_form_id=self.FORM_ID,
            filename="photo.jpg",
            temp_path=self._temp_with(b"image-bytes"),
            mime_type="image/jpeg",
            etag='"abc"',
            downloaded_at=_DOWNLOADED_AT,
        )

        self.assertEqual(result.store_state, svc.STORE_STATE_S3)
        self.assertIsNone(result.local_path)
        self.assertEqual(
            result.state_values["local_fallback_state"], svc.LOCAL_ABSENT
        )
        head = self.store.head(self._key(result.storage_name))
        self.assertEqual(head["ContentLength"], len(b"image-bytes"))
        self.assertEqual(self._media_files(), [])

    def test_a_failed_conversion_leaves_no_object_and_no_temp_file(self):
        temp_path = self._temp_with(b"amr-bytes")

        with patch.object(
            svc, "_convert_amr_to_mp3", side_effect=svc.AmrConversionError("boom")
        ):
            with self.assertRaises(svc.AmrConversionError):
                svc.ingest_download(
                    va_sid="sid-2",
                    va_form_id=self.FORM_ID,
                    filename="narration.amr",
                    temp_path=temp_path,
                    mime_type="audio/amr",
                    etag='"amr-etag"',
                    downloaded_at=_DOWNLOADED_AT,
                )

        self.assertEqual(list(self.store.iter_keys()), [])
        self.assertEqual(self._media_files(), [])
        self.assertFalse(os.path.exists(temp_path))

    def test_cleanup_superseded_deletes_only_unreferenced_objects(self):
        sub = self._submission()
        keep_name = uuid.uuid4().hex + ".jpg"
        drop_name = uuid.uuid4().hex + ".jpg"
        for name in (keep_name, drop_name):
            svc.ingest_download(
                va_sid=sub.va_sid,
                va_form_id=self.FORM_ID,
                filename="photo.jpg",
                temp_path=self._temp_with(b"x"),
                mime_type="image/jpeg",
                etag=None,
                downloaded_at=_DOWNLOADED_AT,
                storage_name=name,
            )
        self._row(sub.va_sid, "keep.jpg", keep_name, store_state=svc.STORE_STATE_S3)

        svc.cleanup_superseded(stale_objects=[
            (self.FORM_ID, drop_name),
            (self.FORM_ID, keep_name),
        ])

        keys = {key for key, _size, _etag in self.store.iter_keys()}
        self.assertIn(self._key(keep_name), keys)
        self.assertNotIn(self._key(drop_name), keys)


class RepairAttachmentTests(AttachmentLifecycleBase):
    def _patch_fetch(self, response, mime_type="image/jpeg"):
        from app.services import attachment_source_central as central

        result = central.CentralFetch(
            outcome=central.FETCH_OK, response=response, mime_type=mime_type
        )
        return patch.object(central, "fetch", return_value=result)

    def test_a_missing_original_is_refetched_and_stored(self):
        self._set_central_fetch(True)
        sub = self._submission()
        row = self._row(sub.va_sid, "photo.jpg", uuid.uuid4().hex + ".jpg")
        record = self._record(row)
        response = _FakeResponse(b"refetched-bytes")

        from app.services import attachment_source_central as central

        with self._patch_fetch(response), patch.object(central, "record_fetch_state"):
            outcome = svc.repair_attachment(record)

        self.assertEqual(outcome.outcome, svc.REPAIR_REPAIRED)
        self.assertTrue(outcome.repaired)
        self.assertEqual(self._media_files(), [record.storage_name])
        self.assertTrue(response.closed)

    def test_a_stale_derivative_is_rebuilt_through_central(self):
        self._set_central_fetch(True)
        sub = self._submission()
        storage_name = uuid.uuid4().hex + ".mp3"
        row = self._row(
            sub.va_sid, "narration.amr", storage_name,
            mime_type="audio/mpeg",
            derivative_state=svc.DERIVATIVE_STALE,
        )
        record = self._record(row)

        def fake_convert(amr_path, form_id, output_path=None):
            os.remove(amr_path)
            with open(output_path, "wb") as handle:
                handle.write(b"rebuilt-mp3")
            return output_path

        from app.services import attachment_source_central as central

        response = _FakeResponse(b"amr-bytes", headers={"ETag": '"amr-v2"'})
        with self._patch_fetch(response, mime_type="audio/amr"), \
                patch.object(central, "record_fetch_state"), \
                patch.object(svc, "_convert_amr_to_mp3", side_effect=fake_convert):
            outcome = svc.repair_attachment(record)

        self.assertEqual(outcome.outcome, svc.REPAIR_DERIVATIVE_REBUILT)
        self.assertEqual(self._media_files(), [storage_name])
        refreshed = db.session.execute(
            sa.select(
                VaSubmissionAttachments.derivative_state,
                VaSubmissionAttachments.derivative_source_validator,
            ).where(
                VaSubmissionAttachments.va_sid == sub.va_sid,
                VaSubmissionAttachments.filename == "narration.amr",
            )
        ).one()
        self.assertEqual(refreshed.derivative_state, svc.DERIVATIVE_READY)
        self.assertEqual(refreshed.derivative_source_validator, '"amr-v2"')

    def test_a_retired_submission_is_never_probed(self):
        self._set_central_fetch(True)
        sub = self._submission(sync_issue_code=MISSING_IN_ODK)
        row = self._row(sub.va_sid, "photo.jpg", uuid.uuid4().hex + ".jpg")

        from app.services import attachment_source_central as central

        with patch.object(central, "fetch") as fetch:
            outcome = svc.repair_attachment(self._record(row))

        self.assertEqual(outcome.outcome, svc.REPAIR_RETIRED)
        fetch.assert_not_called()

    def test_central_fetch_disabled_reports_itself_without_a_request(self):
        self._set_central_fetch(False)
        sub = self._submission()
        row = self._row(sub.va_sid, "photo.jpg", uuid.uuid4().hex + ".jpg")

        from app.services import attachment_source_central as central

        with patch.object(central, "fetch") as fetch:
            outcome = svc.repair_attachment(self._record(row))

        self.assertEqual(outcome.outcome, svc.REPAIR_CENTRAL_DISABLED)
        fetch.assert_not_called()

    def test_a_present_object_needs_no_repair(self):
        self._set_central_fetch(True)
        sub = self._submission()
        storage_name = uuid.uuid4().hex + ".jpg"
        media_dir = os.path.join(self._tmp_dir.name, self.FORM_ID, "media")
        os.makedirs(media_dir, exist_ok=True)
        with open(os.path.join(media_dir, storage_name), "wb") as handle:
            handle.write(b"present")
        row = self._row(sub.va_sid, "photo.jpg", storage_name)

        from app.services import attachment_source_central as central

        with patch.object(central, "fetch") as fetch:
            outcome = svc.repair_attachment(self._record(row))

        self.assertEqual(outcome.outcome, svc.REPAIR_NOT_NEEDED)
        fetch.assert_not_called()


class AttachmentStateTests(AttachmentLifecycleBase):
    def test_retired_submissions_are_flagged_and_audit_is_excluded(self):
        retired = self._submission(sync_issue_code=MISSING_IN_ODK)
        self._row(retired.va_sid, "photo.jpg", uuid.uuid4().hex + ".jpg")
        audit_only = self._submission()
        self._row(audit_only.va_sid, "audit.csv", None)

        states = svc.attachment_state_by_submission(self.FORM_ID)

        self.assertTrue(states[retired.va_sid].retired)
        self.assertEqual(states[audit_only.va_sid].ready_count, 0)
        self.assertEqual(states[audit_only.va_sid].unready, ())

    def test_a_source_central_no_longer_holds_never_blocks(self):
        sub = self._submission()
        self._row(
            sub.va_sid, "photo.jpg", uuid.uuid4().hex + ".jpg",
            source_state=svc.SOURCE_MISSING,
        )

        states = svc.attachment_state_by_submission(self.FORM_ID)

        self.assertEqual(states[sub.va_sid].unready, ())

    def test_repair_candidates_skip_retired_submissions(self):
        retired = self._submission(sync_issue_code=MISSING_IN_ODK)
        self._row(retired.va_sid, "photo.jpg", uuid.uuid4().hex + ".jpg")
        broken = self._submission()
        self._row(broken.va_sid, "photo.jpg", uuid.uuid4().hex + ".jpg")

        candidates = svc.repair_candidates(self.FORM_ID)

        self.assertEqual([c.va_sid for c in candidates], [broken.va_sid])


class AttachmentOverviewTests(AttachmentLifecycleBase):
    def test_overview_is_scoped_and_carries_only_counts(self):
        sub = self._submission()
        self._row(
            sub.va_sid, "photo.jpg", uuid.uuid4().hex + ".jpg",
            source_state=svc.SOURCE_AVAILABLE,
        )

        report = svc.attachment_management_overview([self.PROJECT_ID])

        self.assertEqual(report["project_ids"], [self.PROJECT_ID])
        self.assertEqual(
            {p["project_id"] for p in report["projects"]}, {self.PROJECT_ID}
        )
        form = next(f for f in report["forms"] if f["form_id"] == self.FORM_ID)
        self.assertEqual(form["project_id"], self.PROJECT_ID)
        self.assertEqual(form["source_state"][svc.SOURCE_AVAILABLE], 1)
        self.assertIn(svc.OUTCOME_LOCAL, report["delivery_counters"])
        # Scoping to another project must not leak this form.
        other = svc.attachment_management_overview(["NOSUCH"])
        self.assertEqual(other["forms"], [])


class RequestPathRetryTests(BaseTestCase):
    """A request-path fetch must be classified after exactly one attempt.

    pyODK mounts a ``Retry`` with a two-second backoff factor on its session,
    so a 503 would otherwise cost roughly fourteen seconds before this module
    could answer. The fetch runs through a no-retry clone instead, and the
    shared session keeps its own retries.
    """

    def setUp(self):
        super().setUp()
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.attempts = []
        attempts = self.attempts

        class _AlwaysUnavailable(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - http.server's own naming
                attempts.append(self.path)
                self.send_response(503)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _AlwaysUnavailable)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}/v1/"

    def _pyodk_like_session(self):
        """A session mounted the way pyODK mounts its own (backoff removed)."""
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        session = requests.Session()
        session.base_url = self.base_url
        adapter = HTTPAdapter(max_retries=Retry(
            total=3, backoff_factor=0,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
        ))
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def test_the_shared_session_would_retry(self):
        # Establishes that the fixture really does carry pyODK's retry policy,
        # so the single-attempt assertion below is about our clone. urllib3
        # raises once the retries are exhausted; the attempt count is the point.
        import requests

        session = self._pyodk_like_session()
        with self.assertRaises(requests.exceptions.RetryError):
            session.get(self.base_url + "probe")
        self.assertEqual(len(self.attempts), 4)

    def test_a_503_on_the_request_path_is_one_attempt_and_transient(self):
        from app.services import attachment_source_central as central

        session = self._pyodk_like_session()
        source = central.CentralSource(
            connection_id=uuid.uuid4(),
            base_url=self.base_url,
            odk_project_id="1",
            odk_form_id="F",
            instance_id="uuid:abc",
            filename="photo.jpg",
            client=SimpleNamespace(session=session),
        )
        record = svc.AttachmentRecord(
            va_sid="sid", va_form_id="F", storage_name="token.jpg",
            filename="photo.jpg", local_path=None, mime_type=None,
        )

        with patch.object(central, "resolve_source", return_value=source):
            result = central.fetch(record)

        self.assertEqual(result.outcome, central.FETCH_TRANSIENT)
        self.assertEqual(len(self.attempts), 1)
