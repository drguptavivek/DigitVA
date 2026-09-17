"""Attachment delivery on the S3 store.

The local-store contract is covered by ``tests/routes/test_serve_attachment.py``
and keeps running under ``ATTACHMENT_STORE=local`` (the TestConfig default).
This module flips the selected store to S3 for its own tests and runs entirely
against moto — nothing here may reach a real bucket.

Policy baseline: docs/policy/attachment-storage.md.
"""

import io
import uuid
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import sqlalchemy as sa
from moto import mock_aws

from app import cache as flask_cache
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
from app.services import attachment_source_central as central
from app.services import attachment_store as store_mod
from tests.base import BaseTestCase

_ATTACHMENT_BASE = "/vaform/attachment"


class _FakeUpstream:
    """Minimal stand-in for a streamed requests.Response from Central."""

    def __init__(self, payload=b"", headers=None):
        self.headers = headers or {}
        self._payload = payload
        self.closed = False

    def iter_content(self, chunk_size=1):
        for index in range(0, len(self._payload), chunk_size):
            yield self._payload[index:index + chunk_size]

    def close(self):
        self.closed = True


class S3AttachmentDeliveryTests(BaseTestCase):
    FORM_ID = "SA_S3_FORM"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        if not db.session.get(VaResearchProjects, cls.BASE_PROJECT_ID):
            db.session.add(VaResearchProjects(
                project_id=cls.BASE_PROJECT_ID,
                project_code=cls.BASE_PROJECT_ID,
                project_name="Base Research Project",
                project_nickname="BaseResearch",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
            db.session.flush()
        if not db.session.scalar(sa.select(VaSites).where(VaSites.site_id == cls.BASE_SITE_ID)):
            db.session.add(VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="Base Test Site",
                site_abbr=cls.BASE_SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            ))
            db.session.flush()
        db.session.add(VaForms(
            form_id=cls.FORM_ID,
            project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID,
            odk_form_id="SA_S3_ODK",
            odk_project_id="97",
            form_type="WHO VA 2022",
            form_status=VaStatuses.active,
            form_registered_at=now,
            form_updated_at=now,
        ))
        cls.submission = VaSubmissions(
            va_sid=str(uuid.uuid4()),
            va_form_id=cls.FORM_ID,
            va_data_collector="Test Collector",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=42,
            va_deceased_gender="male",
            va_uniqueid_masked="S3001",
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(cls.submission)
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.mock = mock_aws()
        self.mock.start()
        self.addCleanup(self.mock.stop)
        store_mod.reset_s3_clients()
        self.addCleanup(store_mod.reset_s3_clients)

        self._previous_store = self.app.config["ATTACHMENT_STORE"]
        self.app.config["ATTACHMENT_STORE"] = svc.STORE_STATE_S3
        self.addCleanup(self._restore_store)

        with self.app.app_context():
            self.store = store_mod.get_attachment_store()
        self.store.client.create_bucket(
            Bucket=self.store.bucket,
            CreateBucketConfiguration={
                "LocationConstraint": self.app.config["S3_REGION"]
            },
        )

    def _restore_store(self):
        self.app.config["ATTACHMENT_STORE"] = self._previous_store
        self.app.extensions.pop("attachment_store", None)

    # -- fixtures ---------------------------------------------------------

    def _storage_name(self, ext=".jpg"):
        return uuid.uuid4().hex + ext

    def _row(self, storage_name, *, store_state=svc.STORE_STATE_S3, local_path=None,
             filename=None, mime="image/jpeg"):
        row = VaSubmissionAttachments(
            va_sid=self.submission.va_sid,
            filename=filename or f"original_{uuid.uuid4().hex[:6]}.jpg",
            local_path=local_path,
            mime_type=mime,
            storage_name=storage_name,
            exists_on_odk=True,
            last_downloaded_at=datetime.now(timezone.utc),
            store_state=store_state,
        )
        db.session.add(row)
        db.session.flush()
        if storage_name:
            self.addCleanup(lambda: flask_cache.delete(f"att:{storage_name}"))
        return row

    def _put_object(self, storage_name, payload=b"img", content_type="image/jpeg"):
        self.store.put(
            store_mod.StoreTarget(va_form_id=self.FORM_ID, storage_name=storage_name),
            self._as_file(payload),
            content_type=content_type,
        )

    def _as_file(self, payload):
        return io.BytesIO(payload)

    def _set_central_fetch(self, enabled):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.attachment_central_fetch_enabled = enabled
        db.session.flush()

    def _enable_central_fetch(self):
        self._set_central_fetch(True)
        self.addCleanup(self._set_central_fetch, False)

    # -- delivery ---------------------------------------------------------

    def test_store_hit_redirects_to_a_short_lived_presigned_url(self):
        storage_name = self._storage_name()
        self._row(storage_name)
        self._put_object(storage_name)
        self._login(self.base_admin_id)

        response = self.client.get(f"{_ATTACHMENT_BASE}/{storage_name}")
        self.assertEqual(response.status_code, 302)

        # The redirect itself must not be cached: a browser has to re-run the
        # authorized DigitVA request rather than replay a stale signature.
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertIn("private", response.headers["Cache-Control"])

        params = parse_qs(urlparse(response.headers["Location"]).query)
        self.assertEqual(params["response-content-type"], ["image/jpeg"])
        self.assertEqual(
            params["response-content-disposition"],
            [f'inline; filename="{storage_name}"'],
        )
        self.assertEqual(params["response-cache-control"], ["private, no-store"])
        self.assertEqual(
            int(params["X-Amz-Expires"][0]),
            self.app.config["ATTACHMENT_PRESIGN_EXPIRY_SECONDS"],
        )
        self.assertEqual(params["X-Amz-Expires"], ["300"])

    def test_store_miss_with_the_flag_off_is_404_and_never_presigns(self):
        storage_name = self._storage_name()
        self._row(storage_name)
        self._login(self.base_admin_id)

        with patch.object(
            self.store, "presigned_url", side_effect=AssertionError("must not presign")
        ):
            response = self.client.get(f"{_ATTACHMENT_BASE}/{storage_name}")
        self.assertEqual(response.status_code, 404)

    def test_legacy_row_without_a_storage_name_is_never_presigned(self):
        filename = f"legacy_{uuid.uuid4().hex[:6]}.jpg"
        self._row(None, filename=filename, store_state=svc.STORE_STATE_LOCAL)
        self._login(self.base_admin_id)

        with patch.object(
            self.store, "presigned_url", side_effect=AssertionError("must not presign")
        ):
            response = self.client.get(f"/vaform/media/{self.FORM_ID}/{filename}")
        self.assertEqual(response.status_code, 404)

    def test_central_self_heal_tees_the_body_into_the_bucket(self):
        storage_name = self._storage_name()
        row = self._row(storage_name, store_state=svc.STORE_STATE_LOCAL)
        self._enable_central_fetch()
        patcher = patch.object(central, "fetch", return_value=central.CentralFetch(
            outcome=central.FETCH_OK,
            response=_FakeUpstream(b"central-bytes"),
            mime_type="image/jpeg",
            content_length=13,
        ))
        patcher.start()
        self.addCleanup(patcher.stop)
        self._login(self.base_admin_id)

        response = self.client.get(f"{_ATTACHMENT_BASE}/{storage_name}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"central-bytes")

        target = store_mod.StoreTarget(
            va_form_id=self.FORM_ID, storage_name=storage_name
        )
        self.assertTrue(self.store.exists(target))
        head = self.store.head(self.store.key_for(target))
        self.assertEqual(head["ContentLength"], 13)
        self.assertEqual(head["CacheControl"], "private, no-store")

        db.session.expire_all()
        refreshed = db.session.get(
            VaSubmissionAttachments, (row.va_sid, row.filename)
        )
        self.assertEqual(refreshed.store_state, svc.STORE_STATE_S3)
        self.assertIsNone(refreshed.local_path)
        self.assertEqual(refreshed.local_fallback_state, svc.LOCAL_ABSENT)

    # -- presence and readiness ------------------------------------------

    def test_readiness_reports_the_store_state(self):
        storage_name = self._storage_name()
        row = self._row(storage_name)
        states = svc.readiness([self.submission.va_sid])[self.submission.va_sid]
        match = [entry for entry in states if entry.storage_name == storage_name]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0].store_state, svc.STORE_STATE_S3)
        self.assertEqual(match[0].filename, row.filename)

    def test_bulk_presence_trusts_store_state_without_a_head_request(self):
        stored = self._storage_name()
        pending = self._storage_name()
        self._row(stored, store_state=svc.STORE_STATE_S3)
        self._row(pending, store_state=svc.STORE_STATE_LOCAL)

        with patch.object(
            self.store, "head", side_effect=AssertionError("bulk presence must not HEAD")
        ):
            present = svc.present_attachment_files_by_submission(self.FORM_ID)

        identities = present.get(self.submission.va_sid, set())
        self.assertIn(f"{self.FORM_ID}/media/{stored}", identities)
        self.assertNotIn(f"{self.FORM_ID}/media/{pending}", identities)

    def test_form_level_presence_uses_store_state_for_audio_derivatives(self):
        self._row(self._storage_name(".mp3"), filename="narration.amr")
        self.assertTrue(
            svc.is_attachment_present_for_form(self.FORM_ID, "narration.amr")
        )
        self.assertTrue(
            svc.is_attachment_present_for_form(self.FORM_ID, "narration.mp3")
        )
        self.assertFalse(
            svc.is_attachment_present_for_form(self.FORM_ID, "elsewhere.jpg")
        )
