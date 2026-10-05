"""GET /api/v1/attachments/... (digitva-xl43 phase 3a).

The media URLs the renderer emits. Authorization and delivery are
``attachment_service``'s, shared with ``/vaform/attachment`` and
``/vaform/media`` (covered by tests/routes/test_serve_attachment*.py); this
covers the /api/v1 surface: cookie or bearer, JSON errors, and the delivery
outcomes (local Range, S3 redirect, 502/503) as ``{error, code}``. Device
enrolment helpers are reused from tests/routes/test_device_api.py.
"""
import io
import os
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import sqlalchemy as sa
from moto import mock_aws

from app import cache as flask_cache
from app import db, limiter
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
)
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.services import attachment_service as svc
from app.services import attachment_source_central as central
from app.services import attachment_store as store_mod
from tests.base import BaseTestCase
from tests.routes import test_device_api as device_tests

_DEV = device_tests.DeviceApiTests.__dict__
_CODER_EMAIL = "base.coder@test.local"
_CODER_PASSWORD = "BaseCoder123"
BASE = "/api/v1/attachments"


class AttachmentsApiTests(BaseTestCase):
    FORM_ID = "XL43ATT_FORM"
    # The coder signs a device in through an interviewer grant of their own;
    # that project is also the out-of-scope case.
    PROJECT_ID = "XL43A"
    SITE_ID = "XA43"
    OTHER_FORM_ID = f"{PROJECT_ID}{SITE_ID}01"[:12]

    _make_project = _DEV["_make_project"]
    _make_site = _DEV["_make_site"]
    _grant = _DEV["_grant"]
    _code = _DEV["_code"]
    _enrol = _DEV["_enrol"]
    _sign_in = _DEV["_sign_in"]
    _session = _DEV["_session"]
    _bearer = _DEV["_bearer"]

    @classmethod
    def _submission(cls, form_id):
        submission = VaSubmissions(
            va_sid=f"uuid:xl43att-{uuid.uuid4().hex[:10]}", va_form_id=form_id,
            va_data_collector="Collector", va_consent="yes", va_narration_language="English",
            va_deceased_age=60, va_deceased_gender="Male", va_uniqueid_masked=f"m-{uuid.uuid4().hex[:8]}",
            va_summary=[], va_catcount={}, va_category_list=[],
        )
        db.session.add(submission)
        db.session.flush()
        return submission

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls._ensure_base_research_project_and_site()
        if db.session.get(VaForms, cls.FORM_ID) is None:
            db.session.add(VaForms(
                form_id=cls.FORM_ID, project_id=cls.BASE_PROJECT_ID, site_id=cls.BASE_SITE_ID,
                odk_form_id="XL43_ATT_FORM", odk_project_id="46", form_type="WHO VA 2022",
                form_status=VaStatuses.active, form_registered_at=now, form_updated_at=now,
            ))
        if db.session.get(VaProjectMaster, cls.PROJECT_ID) is None:
            cls._make_project(cls.PROJECT_ID, cls.SITE_ID, now)
        cls._grant(cls.base_coder_user, cls.PROJECT_ID)
        cls.collaborator = cls._make_user(f"xl43att.collab.{uuid.uuid4().hex[:6]}@test.local", "Collab123")
        db.session.add(VaUserAccessGrants(
            user_id=cls.collaborator.user_id, role=VaAccessRoles.collaborator,
            scope_type=VaAccessScopeTypes.project, project_id=cls.BASE_PROJECT_ID,
            notes="xl43att", grant_status=VaStatuses.active,
        ))
        cls.submission = cls._submission(cls.FORM_ID)
        cls.other_submission = cls._submission(cls.OTHER_FORM_ID)
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        flask_cache.clear()
        self.addCleanup(flask_cache.clear)
        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self._device_for = {}

    # -- fixtures ------------------------------------------------------------------

    def _media_dir(self, form_id=None):
        path = os.path.join(self.app.config["APP_DATA"], form_id or self.FORM_ID, "media")
        os.makedirs(path, exist_ok=True)
        return path

    def _file(self, name, payload, form_id=None):
        path = os.path.join(self._media_dir(form_id), name)
        with open(path, "wb") as handle:
            handle.write(payload)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def _token(self, payload=b"fake-image-data", submission=None, on_disk=True, mime="image/jpeg"):
        """A token attachment row, its bytes on the local store when *on_disk*."""
        submission = submission or self.submission
        name = uuid.uuid4().hex + ".jpg"
        path = self._file(name, payload, submission.va_form_id) if on_disk else None
        db.session.add(VaSubmissionAttachments(
            va_sid=submission.va_sid, filename=f"orig_{uuid.uuid4().hex[:6]}.jpg", local_path=path,
            mime_type=mime, storage_name=name, exists_on_odk=True,
            last_downloaded_at=datetime.now(UTC),
        ))
        db.session.commit()
        self.addCleanup(lambda: flask_cache.delete(f"att:{name}"))
        return name

    def _legacy(self, payload=b"legacy-bytes", submission=None):
        """A pre-storage_name row: the ODK filename names the object."""
        submission = submission or self.submission
        filename = f"legacy_{uuid.uuid4().hex[:6]}.jpg"
        path = self._file(filename, payload, submission.va_form_id)
        db.session.add(VaSubmissionAttachments(
            va_sid=submission.va_sid, filename=filename, local_path=path, mime_type="image/jpeg",
            storage_name=None, exists_on_odk=True, last_downloaded_at=datetime.now(UTC),
        ))
        db.session.commit()
        return filename

    def _get(self, path, user=None, **kwargs):
        self._login(user or self.base_admin_id)
        return self.client.get(path, **kwargs)

    def _assert_private(self, response):
        self.assertIn("private", response.headers["Cache-Control"])
        self.assertIn("no-store", response.headers["Cache-Control"])

    # -- token route ---------------------------------------------------------------

    def test_a_cookie_session_gets_the_bytes_privately(self):
        name = self._token()
        response = self._get(f"{BASE}/{name}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"fake-image-data")
        self._assert_private(response)
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_a_bearer_credential_gets_the_bytes_and_none_is_401(self):
        name = self._token()
        _device, tokens = self._session(email=_CODER_EMAIL, password=_CODER_PASSWORD)
        bearer_only = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        response = bearer_only.get(f"{BASE}/{name}", headers=self._bearer(tokens))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"fake-image-data")
        anonymous = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        refused = anonymous.get(f"{BASE}/{name}")
        self.assertEqual(refused.status_code, 401)
        self.assertEqual(refused.get_json(), {"error": "Authentication required.", "code": "unauthorized"})

    def test_a_plain_collaborator_is_forbidden(self):
        name = self._token()
        # Present: a viewer with personal data in the same scope is served.
        self.assertEqual(self._get(f"{BASE}/{name}").status_code, 200)
        response = self._get(f"{BASE}/{name}", user=str(self.collaborator.user_id))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "forbidden")
        self._assert_private(response)

    def test_a_case_outside_the_callers_scope_is_forbidden(self):
        name = self._token(submission=self.other_submission)
        self.assertEqual(self._get(f"{BASE}/{name}").status_code, 200)  # admin: present
        response = self._get(f"{BASE}/{name}", user=self.base_coder_id)
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "forbidden"))

    def test_a_bad_or_unknown_token_is_404(self):
        for token in ("not-a-token.jpg", "A" * 32 + ".jpg", "a" * 32, f"{uuid.uuid4().hex}.jpg"):
            response = self._get(f"{BASE}/{token}")
            self.assertEqual((response.status_code, response.get_json()["code"]), (404, "not_found"), token)
            self._assert_private(response)

    def test_a_row_the_source_no_longer_has_is_404(self):
        name = self._token()
        db.session.execute(sa.update(VaSubmissionAttachments).where(
            VaSubmissionAttachments.storage_name == name).values(exists_on_odk=False))
        db.session.commit()
        self.assertEqual(self._get(f"{BASE}/{name}").get_json()["code"], "not_found")

    def test_missing_bytes_are_404(self):
        name = self._token(on_disk=False)
        response = self._get(f"{BASE}/{name}")
        self.assertEqual((response.status_code, response.get_json()["code"]), (404, "not_found"))

    def test_a_range_request_on_the_local_store_is_206(self):
        name = self._token(payload=b"0123456789")
        response = self._get(f"{BASE}/{name}", headers={"Range": "bytes=2-5"})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.data, b"2345")
        self.assertEqual(response.headers["Content-Range"], "bytes 2-5/10")
        self._assert_private(response)

    def test_a_range_past_the_end_is_416_json(self):
        name = self._token(payload=b"0123456789")
        response = self._get(f"{BASE}/{name}", headers={"Range": "bytes=50-60"})
        self.assertEqual(response.status_code, 416)
        self.assertEqual(response.get_json()["code"], "range_not_satisfiable")
        self._assert_private(response)

    # -- delivery failures as JSON ---------------------------------------------------

    def _central_miss(self, result):
        name = self._token(on_disk=False)
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.attachment_central_fetch_enabled = True
        db.session.commit()

        def disable():
            db.session.get(VaProjectMaster, self.BASE_PROJECT_ID).attachment_central_fetch_enabled = False
            db.session.commit()

        self.addCleanup(disable)
        patcher = patch.object(central, "fetch", return_value=result)
        patcher.start()
        self.addCleanup(patcher.stop)
        return name

    def test_an_upstream_auth_failure_is_502_json(self):
        name = self._central_miss(central.CentralFetch(outcome=central.FETCH_AUTH))
        response = self._get(f"{BASE}/{name}")
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()["code"], "upstream_error")
        self._assert_private(response)

    def test_a_transient_upstream_failure_is_503_json_with_retry_after(self):
        name = self._central_miss(central.CentralFetch(outcome=central.FETCH_THROTTLED))
        response = self._get(f"{BASE}/{name}")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json()["code"], "unavailable")
        self.assertEqual(response.headers["Retry-After"], str(svc.ATTACHMENT_UNAVAILABLE_RETRY_AFTER_SECONDS))
        self._assert_private(response)

    def test_an_upstream_not_found_is_404_json(self):
        name = self._central_miss(central.CentralFetch(outcome=central.FETCH_NOT_FOUND))
        response = self._get(f"{BASE}/{name}")
        self.assertEqual((response.status_code, response.get_json()["code"]), (404, "not_found"))

    # -- S3 ---------------------------------------------------------------------------

    def test_the_s3_store_answers_a_private_redirect_to_a_presigned_url(self):
        name = self._token(on_disk=False)
        db.session.execute(sa.update(VaSubmissionAttachments).where(
            VaSubmissionAttachments.storage_name == name).values(store_state=svc.STORE_STATE_S3))
        db.session.commit()
        previous = self.app.config["ATTACHMENT_STORE"]
        self.app.config["ATTACHMENT_STORE"] = svc.STORE_STATE_S3
        self.addCleanup(lambda: self.app.config.__setitem__("ATTACHMENT_STORE", previous))
        self.addCleanup(lambda: self.app.extensions.pop("attachment_store", None))
        with mock_aws():
            store_mod.reset_s3_clients()
            self.addCleanup(store_mod.reset_s3_clients)
            self.app.extensions.pop("attachment_store", None)
            store = store_mod.get_attachment_store()
            store.client.create_bucket(
                Bucket=store.bucket,
                CreateBucketConfiguration={"LocationConstraint": self.app.config["S3_REGION"]},
            )
            store.put(
                store_mod.StoreTarget(va_form_id=self.FORM_ID, storage_name=name),
                io.BytesIO(b"img"), content_type="image/jpeg",
            )
            response = self._get(f"{BASE}/{name}")
        self.assertEqual(response.status_code, 302)
        self.assertIn("X-Amz-Signature", response.headers["Location"])
        self._assert_private(response)

    # -- legacy route ------------------------------------------------------------------

    def test_a_legacy_row_is_served_by_form_and_filename(self):
        filename = self._legacy()
        response = self._get(f"{BASE}/legacy/{self.FORM_ID}/{filename}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"legacy-bytes")
        self._assert_private(response)
        # The same bytes over a bearer.
        _device, tokens = self._session(email=_CODER_EMAIL, password=_CODER_PASSWORD)
        bearer_only = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        response = bearer_only.get(f"{BASE}/legacy/{self.FORM_ID}/{filename}", headers=self._bearer(tokens))
        self.assertEqual((response.status_code, response.data), (200, b"legacy-bytes"))

    def test_the_legacy_route_has_the_same_refusals(self):
        filename = self._legacy()
        url = f"{BASE}/legacy/{self.FORM_ID}/{filename}"
        self.assertEqual(self._get(url).status_code, 200)  # present
        response = self._get(url, user=str(self.collaborator.user_id))
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "forbidden"))
        other = self._legacy(submission=self.other_submission)
        response = self._get(f"{BASE}/legacy/{self.OTHER_FORM_ID}/{other}", user=self.base_coder_id)
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "forbidden"))
        response = self._get(f"{BASE}/legacy/{self.FORM_ID}/{uuid.uuid4().hex}.jpg")
        self.assertEqual((response.status_code, response.get_json()["code"]), (404, "not_found"))
        response = self._get(f"{BASE}/legacy/bad.form/{filename}")
        self.assertEqual((response.status_code, response.get_json()["code"]), (400, "invalid_request"))
        anonymous = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self.assertEqual(anonymous.get(url).status_code, 401)
