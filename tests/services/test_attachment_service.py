"""Tests for the attachment module boundary (app/services/attachment_service.py).

Policy baseline: docs/policy/attachment-storage.md.
"""

import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import sqlalchemy as sa

from app import db, cache as flask_cache
from app.models import (
    VaAllocation,
    VaAllocations,
    VaForms,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissions,
)
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.services import attachment_service as svc
from tests.base import BaseTestCase


def _fake_user(**overrides):
    """Minimal VaUsers stand-in for exercising the role matrix without a DB."""
    base = dict(
        user_id=uuid.uuid4(),
        permission={},
        is_admin=lambda: False,
        has_data_manager_form_access=lambda form: False,
        is_site_pi=lambda form=None: False,
        is_reviewer=lambda form=None: False,
        is_coder=lambda form=None: False,
        is_coding_tester=lambda form=None: False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class AuthorizationMatrixTests(TestCase):
    FORM = "FORM01"
    SID = "sid-1"

    def _allowed(self, user, holds=False):
        with patch.object(svc, "_user_holds_submission", return_value=holds):
            return svc.can_access_submission_attachment(
                user, va_form_id=self.FORM, va_sid=self.SID
            )

    def test_unresolved_ownership_is_denied_for_everyone(self):
        admin = _fake_user(is_admin=lambda: True)
        self.assertFalse(svc.can_access_submission_attachment(admin, va_form_id=self.FORM, va_sid=""))
        self.assertFalse(svc.can_access_submission_attachment(admin, va_form_id="", va_sid=self.SID))

    def test_admin_allowed(self):
        self.assertTrue(self._allowed(_fake_user(is_admin=lambda: True)))

    def test_data_manager_scope_allowed(self):
        user = _fake_user(has_data_manager_form_access=lambda form: form == self.FORM)
        self.assertTrue(self._allowed(user))

    def test_site_pi_scope_allowed(self):
        self.assertTrue(self._allowed(_fake_user(is_site_pi=lambda form=None: form == self.FORM)))

    def test_reviewer_form_scope_allowed_without_allocation(self):
        user = _fake_user(is_reviewer=lambda form=None: form == self.FORM)
        self.assertTrue(self._allowed(user, holds=False))

    def test_coder_requires_submission_entitlement(self):
        user = _fake_user(is_coder=lambda form=None: form == self.FORM)
        self.assertFalse(self._allowed(user, holds=False))
        self.assertTrue(self._allowed(user, holds=True))

    def test_coding_tester_requires_submission_entitlement(self):
        user = _fake_user(is_coding_tester=lambda form=None: form == self.FORM)
        self.assertFalse(self._allowed(user, holds=False))
        self.assertTrue(self._allowed(user, holds=True))

    def test_coder_on_other_form_denied(self):
        user = _fake_user(is_coder=lambda form=None: form == "OTHER")
        self.assertFalse(self._allowed(user, holds=True))

    def test_legacy_non_scoped_permission_dict_allowed(self):
        user = _fake_user(permission={"collab": [self.FORM]})
        self.assertTrue(self._allowed(user))

    def test_legacy_scoped_permission_dict_keys_ignored(self):
        user = _fake_user(permission={"coder": [self.FORM], "reviewer": [self.FORM], "sitepi": [self.FORM]})
        self.assertFalse(self._allowed(user, holds=True))

    def test_project_pi_without_other_scope_denied(self):
        # No project-PI submission view exists; the matrix does not add one.
        user = _fake_user(get_project_pi_projects=lambda: {"P1"})
        self.assertFalse(self._allowed(user))


class LocalPresenceTests(TestCase):
    def test_resolve_prefers_storage_name_under_media(self):
        with tempfile.TemporaryDirectory() as root:
            media = os.path.join(root, "F1", "media")
            os.makedirs(media)
            with open(os.path.join(media, "abc.jpg"), "wb") as f:
                f.write(b"x")
            legacy = os.path.join(root, "legacy.jpg")
            with open(legacy, "wb") as f:
                f.write(b"y")
            resolved = svc.resolve_local_attachment_path(
                app_data_root=root, form_id="F1", local_path=legacy, storage_name="abc.jpg"
            )
            self.assertEqual(resolved, os.path.abspath(os.path.join(media, "abc.jpg")))

    def test_resolve_falls_back_to_local_path(self):
        with tempfile.TemporaryDirectory() as root:
            legacy = os.path.join(root, "legacy.jpg")
            with open(legacy, "wb") as f:
                f.write(b"y")
            resolved = svc.resolve_local_attachment_path(
                app_data_root=root, form_id="F1", local_path=legacy, storage_name="missing.jpg"
            )
            self.assertEqual(resolved, os.path.abspath(legacy))

    def test_resolve_returns_none_when_absent(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertIsNone(svc.resolve_local_attachment_path(
                app_data_root=root, form_id="F1", local_path=os.path.join(root, "no.jpg"), storage_name="no.jpg"
            ))
            self.assertIsNone(svc.resolve_local_attachment_path(
                app_data_root=root, form_id="F1", local_path=None, storage_name=None
            ))

    def test_audit_csv_excluded_unless_requested(self):
        with tempfile.TemporaryDirectory() as root:
            audit = os.path.join(root, "audit.csv")
            with open(audit, "w", encoding="utf-8") as f:
                f.write("a")
            kwargs = dict(app_data_root=root, form_id="F1", local_path=audit, storage_name=None)
            self.assertIsNone(svc.resolve_local_attachment_path(**kwargs))
            self.assertEqual(
                svc.resolve_local_attachment_path(include_audit=True, **kwargs),
                os.path.abspath(audit),
            )

    def test_scan_skips_quarantined_subtree(self):
        with tempfile.TemporaryDirectory() as root:
            app_data = Path(root)
            media = app_data / "F1" / "media"
            (media / ".orphaned").mkdir(parents=True)
            (media / "live.jpg").write_bytes(b"1")
            (media / ".orphaned" / "old.jpg").write_bytes(b"2")
            total, files = svc.scan_local_media_files(app_data)
            self.assertEqual(total, 1)
            self.assertEqual(files, [(media / "live.jpg").resolve(strict=False)])

    def test_remove_local_file_if_present(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "f.bin")
            with open(path, "wb") as f:
                f.write(b"1")
            self.assertTrue(svc.remove_local_file_if_present(path))
            self.assertFalse(svc.remove_local_file_if_present(path))
            self.assertFalse(svc.remove_local_file_if_present(None))


class MimeTests(TestCase):
    def test_safe_mime_type(self):
        self.assertEqual(svc.safe_mime_type("image/jpeg; charset=binary"), "image/jpeg")
        self.assertIsNone(svc.safe_mime_type("null"))
        self.assertIsNone(svc.safe_mime_type("NULL"))
        self.assertIsNone(svc.safe_mime_type(""))
        self.assertIsNone(svc.safe_mime_type(None))
        self.assertIsNone(svc.safe_mime_type("garbage"))


class AttachmentServiceDbTests(BaseTestCase):
    FORM_ID = "ATTSVC_FORM"

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
            odk_form_id="ATTSVC_ODK",
            odk_project_id="98",
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

    def _submission(self):
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
        )
        db.session.add(sub)
        db.session.flush()
        return sub

    def _row(self, va_sid, filename, storage_name, local_path=None, exists_on_odk=True, mime="image/jpeg"):
        row = VaSubmissionAttachments(
            va_sid=va_sid,
            filename=filename,
            local_path=local_path,
            mime_type=mime,
            storage_name=storage_name,
            exists_on_odk=exists_on_odk,
            last_downloaded_at=datetime.now(timezone.utc),
        )
        db.session.add(row)
        db.session.flush()
        return row

    def _media_file(self, name, payload=b"data"):
        media = os.path.join(self._tmp_dir.name, self.FORM_ID, "media")
        os.makedirs(media, exist_ok=True)
        path = os.path.join(media, name)
        with open(path, "wb") as f:
            f.write(payload)
        return path

    def test_resolve_record_returns_ownership(self):
        sub = self._submission()
        name = uuid.uuid4().hex + ".jpg"
        self._row(sub.va_sid, "photo.jpg", name, local_path="/x/y.jpg")
        record = svc.resolve_attachment_record(name)
        self.assertIsNotNone(record)
        self.assertEqual(record.va_sid, sub.va_sid)
        self.assertEqual(record.va_form_id, self.FORM_ID)
        self.assertEqual(record.local_path, "/x/y.jpg")

    def test_resolve_record_ignores_removed_rows_and_unknown_tokens(self):
        sub = self._submission()
        name = uuid.uuid4().hex + ".jpg"
        self._row(sub.va_sid, "photo.jpg", name, exists_on_odk=False)
        self.assertIsNone(svc.resolve_attachment_record(name))
        self.assertIsNone(svc.resolve_attachment_record(uuid.uuid4().hex + ".jpg"))

    def test_record_cache_round_trip_and_stale_entry(self):
        sub = self._submission()
        name = uuid.uuid4().hex + ".jpg"
        self.addCleanup(lambda: flask_cache.delete(f"att:{name}"))
        record = svc.resolve_attachment_record(name)
        self.assertIsNone(record)
        self._row(sub.va_sid, "photo.jpg", name, local_path="/x/y.jpg")
        record = svc.resolve_attachment_record(name)
        svc.cache_attachment_record(record)
        cached = flask_cache.get(f"att:{name}")
        self.assertEqual(cached["va_sid"], sub.va_sid)
        # A stale pre-fix entry without ownership is a miss, not a hit.
        flask_cache.set(f"att:{name}", {"local_path": "/stale", "mime_type": "x", "va_form_id": self.FORM_ID})
        self.assertEqual(svc.resolve_attachment_record(name).local_path, "/x/y.jpg")
        svc.invalidate_attachment_record(name)
        self.assertIsNone(flask_cache.get(f"att:{name}"))

    def test_user_holds_submission_via_allocation(self):
        sub = self._submission()
        self.assertFalse(svc._user_holds_submission(self.base_coder_user.user_id, sub.va_sid))
        db.session.add(VaAllocations(
            va_sid=sub.va_sid,
            va_allocated_to=self.base_coder_user.user_id,
            va_allocation_for=VaAllocation.coding,
            va_allocation_status=VaStatuses.active,
        ))
        db.session.flush()
        self.assertTrue(svc._user_holds_submission(self.base_coder_user.user_id, sub.va_sid))
        self.assertFalse(svc._user_holds_submission(self.base_admin_user.user_id, sub.va_sid))

    def test_present_files_by_submission_is_bulk_and_disk_backed(self):
        sub_present = self._submission()
        sub_missing = self._submission()
        sub_audit = self._submission()
        present_name = uuid.uuid4().hex + ".jpg"
        self._media_file(present_name)
        self._row(sub_present.va_sid, "a.jpg", present_name)
        self._row(sub_missing.va_sid, "b.jpg", uuid.uuid4().hex + ".jpg")
        self._row(sub_audit.va_sid, "audit.csv", None, local_path=self._media_file("audit.csv"))

        result = svc.present_attachment_files_by_submission(self.FORM_ID)
        self.assertIn(sub_present.va_sid, result)
        self.assertNotIn(sub_missing.va_sid, result)
        self.assertNotIn(sub_audit.va_sid, result)

        scoped = svc.present_attachment_files_by_submission(
            self.FORM_ID, target_sids=[sub_missing.va_sid]
        )
        self.assertEqual(scoped, {})

    def test_is_attachment_present_for_form_maps_amr_to_mp3(self):
        self._media_file("narration.mp3")
        self.assertTrue(svc.is_attachment_present_for_form(self.FORM_ID, "narration.amr"))
        self.assertTrue(svc.is_attachment_present_for_form(self.FORM_ID, "narration.mp3"))
        self.assertFalse(svc.is_attachment_present_for_form(self.FORM_ID, "other.jpg"))

    def test_deliver_guards_path_and_sets_no_store(self):
        from werkzeug.exceptions import NotFound

        sub = self._submission()
        name = uuid.uuid4().hex + ".jpg"
        path = self._media_file(name, b"bytes")
        record = svc.AttachmentRecord(
            va_sid=sub.va_sid, va_form_id=self.FORM_ID, storage_name=name,
            local_path=path, mime_type="null",
        )
        self.addCleanup(lambda: flask_cache.delete(f"att:{name}"))
        with self.app.test_request_context("/"):
            response = svc.deliver_local_attachment(record)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Content-Type"], "image/jpeg")
            self.assertIn("no-store", response.headers["Cache-Control"])
            response.close()

            outside = svc.AttachmentRecord(
                va_sid=sub.va_sid, va_form_id=self.FORM_ID, storage_name=name,
                local_path=os.path.join(self._tmp_dir.name, "escape.jpg"), mime_type=None,
            )
            with self.assertRaises(NotFound):
                svc.deliver_local_attachment(outside)

            os.unlink(path)
            with self.assertRaises(NotFound):
                svc.deliver_local_attachment(record)
            self.assertIsNone(flask_cache.get(f"att:{name}"))
