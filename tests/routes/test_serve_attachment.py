"""Tests for the /attachment/<storage_name> serving route.

Covers the security contract (Option B — auth-first):
  1. Unauthenticated → 302 redirect to the login page (no DB lookup). The
     role_required decorator returns JSON 401 only for /api/-style paths;
     /vaform/attachment/... is a web path, so it redirects to va_auth.va_login.
  2. Invalid token format → 404
  3. Valid format, no DB record → 404
  4. exists_on_odk=False record → 404
  5. Authenticated + no form access → 403
  6. Authenticated + valid token + file missing on disk → 404
  7. Authenticated + valid token + file present → 200
  8. Submission-level matrix (docs/policy/attachment-storage.md):
     admin → 200 without allocation; coder → active allocation or own coder
     outcome, else 403; reviewer with form access → 200; a deterministically
     derivable legacy token grants nothing on its own
  9. Attachment bytes carry Cache-Control: private, no-store

Route URL: /vaform/attachment/<storage_name>  (va_form blueprint, prefix /vaform)
"""

import os
import uuid
from datetime import datetime, timezone
import sqlalchemy as sa

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaCoderReview,
    VaForms,
    VaProjectSites,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
)
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.services.attachment_storage_name_service import legacy_attachment_storage_name
from tests.base import BaseTestCase

# Blueprint prefix for va_form
_ATTACHMENT_BASE = "/vaform/attachment"


class ServeAttachmentTests(BaseTestCase):
    FORM_ID = "SA_TEST_FORM"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        # va_forms has FKs to va_research_projects and va_sites
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

        existing_site = db.session.scalar(
            sa.select(VaSites).where(VaSites.site_id == cls.BASE_SITE_ID)
        )
        if not existing_site:
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
            odk_form_id="SA_TEST_ODK",
            odk_project_id="99",
            form_type="WHO VA 2022",
            form_status=VaStatuses.active,
            form_registered_at=now,
            form_updated_at=now,
        ))
        db.session.flush()

        cls.submission = VaSubmissions(
            va_sid=str(uuid.uuid4()),
            va_form_id=cls.FORM_ID,
            va_data_collector="Test Collector",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=42,
            va_deceased_gender="male",
            va_uniqueid_masked="SA001",
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(cls.submission)
        db.session.commit()

    def _url(self, storage_name):
        return f"{_ATTACHMENT_BASE}/{storage_name}"

    def _make_storage_name(self, ext=".jpg"):
        return uuid.uuid4().hex + ext

    def _make_attachment_row(self, storage_name, local_path="/tmp/fake.jpg", exists_on_odk=True):
        row = VaSubmissionAttachments(
            va_sid=self.submission.va_sid,
            filename=f"original_{uuid.uuid4().hex[:6]}.jpg",
            local_path=local_path,
            mime_type="image/jpeg",
            storage_name=storage_name,
            exists_on_odk=exists_on_odk,
            etag=None,
            last_downloaded_at=datetime.now(timezone.utc),
        )
        db.session.add(row)
        db.session.flush()
        return row

    # ------------------------------------------------------------------
    # 1. Unauthenticated → 401
    # ------------------------------------------------------------------

    def test_unauthenticated_redirects_to_login(self):
        # setUp() creates a fresh test_client() with an empty cookie jar for every
        # test — no prior session cookie exists, so no session_transaction() needed.
        # Calling session_transaction() on a new client can inadvertently open a
        # stale filesystem-backed session and corrupt the intended unauthenticated state.
        storage_name = self._make_storage_name()
        response = self.client.get(self._url(storage_name))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/valogin", response.location)

    # ------------------------------------------------------------------
    # 2. Invalid token format → 404
    # ------------------------------------------------------------------

    def test_invalid_token_format_returns_404(self):
        self._login(self.base_admin_id)
        bad_tokens = [
            "not-a-valid-token.jpg",          # dashes not allowed
            "ABCD1234.jpg",                    # uppercase
            "abc123.jpg",                      # too short hex
            "a" * 32,                          # no extension
            "a" * 32 + ".toolongextension",    # extension > 5 chars
            "../etc/passwd",                   # path traversal
        ]
        for token in bad_tokens:
            response = self.client.get(f"{_ATTACHMENT_BASE}/{token}")
            self.assertEqual(response.status_code, 404, f"Expected 404 for token: {token!r}")

    # ------------------------------------------------------------------
    # 3. Valid format, no DB record → 404
    # ------------------------------------------------------------------

    def test_no_db_record_returns_404(self):
        self._login(self.base_admin_id)
        storage_name = self._make_storage_name()
        response = self.client.get(self._url(storage_name))
        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------
    # 4. exists_on_odk=False record → 404
    # ------------------------------------------------------------------

    def test_removed_attachment_returns_404(self):
        self._login(self.base_admin_id)
        storage_name = self._make_storage_name()
        self._make_attachment_row(storage_name, exists_on_odk=False)
        response = self.client.get(self._url(storage_name))
        self.assertEqual(response.status_code, 404)

    def _media_dir(self):
        """Return the media directory for the test form (creates it if needed)."""
        from flask import current_app
        media_dir = os.path.join(current_app.config["APP_DATA"], self.FORM_ID, "media")
        os.makedirs(media_dir, exist_ok=True)
        return media_dir

    # ------------------------------------------------------------------
    # 5. Authenticated + no form access → 403
    # ------------------------------------------------------------------

    def test_no_form_access_returns_403(self):
        no_access_user = self._make_user(
            f"noaccess.{uuid.uuid4().hex[:6]}@test.local", "NoAccess123"
        )
        db.session.flush()
        self._login(str(no_access_user.user_id))

        storage_name = self._make_storage_name()
        # Path guard is not reached (abort(403) happens first), so any local_path is fine.
        self._make_attachment_row(storage_name, local_path="/tmp/irrelevant.jpg")

        response = self.client.get(self._url(storage_name))
        self.assertEqual(response.status_code, 403)

    # ------------------------------------------------------------------
    # 6. File missing on disk → 404
    # ------------------------------------------------------------------

    def test_file_missing_on_disk_returns_404(self):
        self._login(self.base_admin_id)
        storage_name = self._make_storage_name()
        # Use a path under APP_DATA/FORM/media so the path guard passes,
        # but a name that doesn't exist on disk so os.path.isfile returns False.
        local_path = os.path.join(self._media_dir(), f"nonexistent_{storage_name}")
        self._make_attachment_row(storage_name, local_path=local_path)
        response = self.client.get(self._url(storage_name))
        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------
    # 7. Happy path → 200
    # ------------------------------------------------------------------

    def test_valid_attachment_returns_200(self):
        self._login(self.base_admin_id)
        storage_name = self._make_storage_name()
        media_dir = self._media_dir()

        # Create the file under APP_DATA/FORM/media so path guard passes
        tmp_path = os.path.join(media_dir, storage_name)
        with open(tmp_path, "wb") as f:
            f.write(b"fake-image-data")

        try:
            self._make_attachment_row(storage_name, local_path=tmp_path)
            response = self.client.get(self._url(storage_name))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"fake-image-data")
            self.assertIn("no-store", response.headers.get("Cache-Control", ""))
            self.assertIn("private", response.headers.get("Cache-Control", ""))
            self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


    # ------------------------------------------------------------------
    # 8. Submission-level matrix
    # ------------------------------------------------------------------

    def _write_file(self, storage_name, payload=b"img"):
        path = os.path.join(self._media_dir(), storage_name)
        with open(path, "wb") as f:
            f.write(payload)
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        return path

    def _allocate(self, user, va_sid=None, status=VaStatuses.active):
        db.session.add(VaAllocations(
            va_sid=va_sid or self.submission.va_sid,
            va_allocated_to=user.user_id,
            va_allocation_for=VaAllocation.coding,
            va_allocation_status=status,
        ))
        db.session.flush()

    def _grant_reviewer(self, user):
        project_site_id = db.session.scalar(
            sa.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == self.BASE_PROJECT_ID,
                VaProjectSites.site_id == self.BASE_SITE_ID,
            )
        )
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=VaAccessRoles.reviewer,
            scope_type=VaAccessScopeTypes.project_site,
            project_site_id=project_site_id,
            notes="attachment route test",
            grant_status=VaStatuses.active,
        ))
        db.session.flush()

    def test_coder_with_form_access_but_no_allocation_is_refused(self):
        # base_coder_user holds a coder grant for BASE_SITE_ID → form access,
        # but no allocation for this submission (plan Finding 1).
        storage_name = self._make_storage_name()
        self._make_attachment_row(storage_name, local_path=self._write_file(storage_name))
        self._login(str(self.base_coder_user.user_id))

        response = self.client.get(self._url(storage_name))
        self.assertEqual(response.status_code, 403)

    def test_coder_with_active_allocation_is_served(self):
        storage_name = self._make_storage_name()
        self._make_attachment_row(storage_name, local_path=self._write_file(storage_name))
        self._allocate(self.base_coder_user)
        self._login(str(self.base_coder_user.user_id))

        response = self.client.get(self._url(storage_name))
        self.assertEqual(response.status_code, 200)

    def test_coder_with_inactive_allocation_is_refused(self):
        storage_name = self._make_storage_name()
        self._make_attachment_row(storage_name, local_path=self._write_file(storage_name))
        self._allocate(self.base_coder_user, status=VaStatuses.deactive)
        self._login(str(self.base_coder_user.user_id))

        response = self.client.get(self._url(storage_name))
        self.assertEqual(response.status_code, 403)

    def test_coder_with_own_active_coder_review_is_served(self):
        # Mirrors the coder ``vaview`` page rule (va_permission_ensureviewable).
        storage_name = self._make_storage_name()
        self._make_attachment_row(storage_name, local_path=self._write_file(storage_name))
        db.session.add(VaCoderReview(
            va_sid=self.submission.va_sid,
            va_creview_by=self.base_coder_user.user_id,
            va_creview_reason="test",
            va_creview_status=VaStatuses.active,
        ))
        db.session.flush()
        self._login(str(self.base_coder_user.user_id))

        response = self.client.get(self._url(storage_name))
        self.assertEqual(response.status_code, 200)

    def test_allocation_on_another_submission_does_not_transfer(self):
        other = VaSubmissions(
            va_sid=str(uuid.uuid4()),
            va_form_id=self.FORM_ID,
            va_data_collector="Test Collector",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=50,
            va_deceased_gender="female",
            va_uniqueid_masked="SA002",
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(other)
        db.session.flush()
        storage_name = self._make_storage_name()
        self._make_attachment_row(storage_name, local_path=self._write_file(storage_name))
        self._allocate(self.base_coder_user, va_sid=other.va_sid)
        self._login(str(self.base_coder_user.user_id))

        response = self.client.get(self._url(storage_name))
        self.assertEqual(response.status_code, 403)

    def test_legacy_deterministic_token_grants_nothing_on_its_own(self):
        # Legacy backfill tokens are uuid5(va_sid, filename): derivable from two
        # values a coder already sees. Possession must not equal authorization.
        filename = "md_im1.jpg"
        storage_name = legacy_attachment_storage_name(self.submission.va_sid, filename)
        row = VaSubmissionAttachments(
            va_sid=self.submission.va_sid,
            filename=filename,
            local_path=self._write_file(storage_name),
            mime_type="image/jpeg",
            storage_name=storage_name,
            exists_on_odk=True,
            last_downloaded_at=datetime.now(timezone.utc),
        )
        db.session.add(row)
        db.session.flush()
        self._login(str(self.base_coder_user.user_id))

        response = self.client.get(self._url(storage_name))
        self.assertEqual(response.status_code, 403)

    def test_reviewer_with_form_access_is_served_read_only(self):
        reviewer = self._make_user(
            f"reviewer.{uuid.uuid4().hex[:6]}@test.local", "Reviewer123"
        )
        self._grant_reviewer(reviewer)
        storage_name = self._make_storage_name()
        self._make_attachment_row(storage_name, local_path=self._write_file(storage_name))
        self._login(str(reviewer.user_id))

        response = self.client.get(self._url(storage_name))
        self.assertEqual(response.status_code, 200)

    def test_admin_is_served_without_allocation(self):
        storage_name = self._make_storage_name()
        self._make_attachment_row(storage_name, local_path=self._write_file(storage_name))
        self._login(self.base_admin_id)

        response = self.client.get(self._url(storage_name))
        self.assertEqual(response.status_code, 200)

    def test_stale_cache_entry_without_ownership_is_ignored(self):
        # Entries written by the pre-authorization-fix route lack va_sid; they
        # must never short-circuit the ownership lookup.
        from app import cache as flask_cache

        storage_name = self._make_storage_name()
        self._make_attachment_row(storage_name, local_path=self._write_file(storage_name))
        flask_cache.set(f"att:{storage_name}", {
            "local_path": "/tmp/stale.jpg",
            "mime_type": "image/jpeg",
            "va_form_id": self.FORM_ID,
        }, timeout=60)
        self.addCleanup(lambda: flask_cache.delete(f"att:{storage_name}"))
        self._login(str(self.base_coder_user.user_id))

        response = self.client.get(self._url(storage_name))
        self.assertEqual(response.status_code, 403)

    # ------------------------------------------------------------------
    # Legacy /media route uses the same matrix and rejects unknown ownership
    # ------------------------------------------------------------------

    def test_legacy_media_route_rejects_unknown_ownership(self):
        self._login(self.base_admin_id)
        response = self.client.get(f"/vaform/media/{self.FORM_ID}/{uuid.uuid4().hex}.jpg")
        self.assertEqual(response.status_code, 404)

    def test_legacy_media_route_refuses_unallocated_coder(self):
        filename = f"legacy_{uuid.uuid4().hex[:6]}.jpg"
        path = self._write_file(filename)
        db.session.add(VaSubmissionAttachments(
            va_sid=self.submission.va_sid,
            filename=filename,
            local_path=path,
            mime_type="image/jpeg",
            storage_name=None,
            exists_on_odk=True,
            last_downloaded_at=datetime.now(timezone.utc),
        ))
        db.session.flush()
        self._login(str(self.base_coder_user.user_id))

        response = self.client.get(f"/vaform/media/{self.FORM_ID}/{filename}")
        self.assertEqual(response.status_code, 403)

        self._allocate(self.base_coder_user)
        response = self.client.get(f"/vaform/media/{self.FORM_ID}/{filename}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers.get("Cache-Control", ""))
