"""Tests for the ``flask attachments s3-upload`` / ``local-quarantine`` cutover.

Both commands run against moto. Neither may ever delete an attachment: the
upload only copies and verifies, and the quarantine only moves a verified file
aside.

Policy baseline: docs/policy/attachment-storage.md.
"""

import os
import tempfile
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from moto import mock_aws

from app import db
from app.commands.attachments import QUARANTINE_DIRNAME
from app.models import (
    VaForms,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissions,
)
from app.models.va_submission_attachments import VaSubmissionAttachments
from app.services import attachment_service as svc
from app.services import attachment_store as store_mod
from tests.base import BaseTestCase


class AttachmentsS3CliTests(BaseTestCase):
    FORM_ID = "S3CLI_FORM"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.runner = cls.app.test_cli_runner()
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
            odk_form_id="S3CLI_ODK",
            odk_project_id="96",
            form_type="WHO VA 2022",
            form_status=VaStatuses.active,
            form_registered_at=now,
            form_updated_at=now,
        ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.mock = mock_aws()
        self.mock.start()
        self.addCleanup(self.mock.stop)
        store_mod.reset_s3_clients()
        self.addCleanup(store_mod.reset_s3_clients)

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._previous = (
            self.app.config["ATTACHMENT_STORE"],
            self.app.config["APP_DATA"],
        )
        self.app.config["ATTACHMENT_STORE"] = svc.STORE_STATE_S3
        self.app.config["APP_DATA"] = self._tmp.name
        self.addCleanup(self._restore)

        with self.app.app_context():
            self.store = store_mod.get_attachment_store()
        self.store.client.create_bucket(
            Bucket=self.store.bucket,
            CreateBucketConfiguration={
                "LocationConstraint": self.app.config["S3_REGION"]
            },
        )
        self.sids = []
        self.addCleanup(self._delete_rows)

    def _restore(self):
        store, app_data = self._previous
        self.app.config["ATTACHMENT_STORE"] = store
        self.app.config["APP_DATA"] = app_data
        self.app.extensions.pop("attachment_store", None)

    def _delete_rows(self):
        """The commands commit, so the per-test savepoint cannot undo them."""
        if not self.sids:
            return
        db.session.execute(
            sa.delete(VaSubmissionAttachments).where(
                VaSubmissionAttachments.va_sid.in_(self.sids)
            )
        )
        db.session.execute(
            sa.delete(VaSubmissions).where(VaSubmissions.va_sid.in_(self.sids))
        )
        db.session.commit()

    # -- fixtures ---------------------------------------------------------

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
        self.sids.append(sub.va_sid)
        return sub

    def _media_file(self, storage_name, payload=b"payload"):
        media = os.path.join(self._tmp.name, self.FORM_ID, "media")
        os.makedirs(media, exist_ok=True)
        path = os.path.join(media, storage_name)
        with open(path, "wb") as handle:
            handle.write(payload)
        return path

    def _row(self, *, storage_name, filename="photo.jpg", with_file=True,
             store_state=svc.STORE_STATE_LOCAL, mime="image/jpeg",
             source_mime=None, derivative_mime=None,
             local_fallback_state=svc.LOCAL_PRESENT, payload=b"payload"):
        sub = self._submission()
        path = self._media_file(storage_name, payload) if with_file else None
        row = VaSubmissionAttachments(
            va_sid=sub.va_sid,
            filename=filename,
            local_path=path,
            mime_type=mime,
            storage_name=storage_name,
            exists_on_odk=True,
            last_downloaded_at=datetime.now(timezone.utc),
            store_state=store_state,
            source_mime_type=source_mime,
            derivative_mime_type=derivative_mime,
            local_fallback_state=local_fallback_state,
        )
        db.session.add(row)
        db.session.commit()
        return row

    def _upload(self, *args):
        return self.runner.invoke(
            args=["attachments", "s3-upload", "--form-id", self.FORM_ID, *args]
        )

    def _key(self, storage_name):
        return self.store.key_for(
            store_mod.StoreTarget(va_form_id=self.FORM_ID, storage_name=storage_name)
        )

    def _reload(self, row):
        db.session.expire_all()
        return db.session.get(VaSubmissionAttachments, (row.va_sid, row.filename))

    # -- s3-upload --------------------------------------------------------

    def test_dry_run_reports_and_writes_nothing(self):
        storage_name = uuid.uuid4().hex + ".jpg"
        row = self._row(storage_name=storage_name)

        result = self._upload("--dry-run")
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("would_upload=1", result.output)
        self.assertIsNone(self.store.head(self._key(storage_name)))
        self.assertEqual(self._reload(row).store_state, svc.STORE_STATE_LOCAL)

    def test_upload_verifies_and_points_the_row_at_the_object(self):
        storage_name = uuid.uuid4().hex + ".jpg"
        row = self._row(
            storage_name=storage_name, source_mime="image/jpeg", mime="null"
        )

        result = self._upload()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("uploaded=1", result.output)
        self.assertIn("failed=0", result.output)

        head = self.store.head(self._key(storage_name))
        self.assertEqual(head["ContentLength"], len(b"payload"))
        # "null" from upstream is never forwarded as a content type.
        self.assertEqual(head["ContentType"], "image/jpeg")

        refreshed = self._reload(row)
        self.assertEqual(refreshed.store_state, svc.STORE_STATE_S3)
        self.assertIsNone(refreshed.local_path)
        # The local file is untouched: the upload never deletes.
        self.assertTrue(os.path.isfile(
            os.path.join(self._tmp.name, self.FORM_ID, "media", storage_name)
        ))

    def test_amr_row_is_uploaded_as_its_mp3_derivative_type(self):
        storage_name = uuid.uuid4().hex + ".mp3"
        self._row(
            storage_name=storage_name,
            filename="narration.amr",
            mime=None,
            derivative_mime="audio/mpeg",
        )
        result = self._upload()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertEqual(
            self.store.head(self._key(storage_name))["ContentType"], "audio/mpeg"
        )

    def test_rerun_is_idempotent(self):
        self._row(storage_name=uuid.uuid4().hex + ".jpg")
        self.assertEqual(self._upload().exit_code, 0)

        second = self._upload()
        self.assertEqual(second.exit_code, 0, second.output)
        self.assertIn("scanned=0", second.output)
        self.assertIn("uploaded=0", second.output)

    def test_a_row_without_a_local_file_fails_the_run(self):
        self._row(storage_name=uuid.uuid4().hex + ".jpg", with_file=False)
        result = self._upload()
        self.assertEqual(result.exit_code, 1)
        self.assertIn("failed=1", result.output)
        self.assertIn("no local file", result.output)

    def test_the_command_refuses_to_run_on_the_local_store(self):
        self.app.config["ATTACHMENT_STORE"] = svc.STORE_STATE_LOCAL
        self.app.extensions.pop("attachment_store", None)
        result = self._upload()
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("ATTACHMENT_STORE is not 's3'", result.output)

    # -- local-quarantine -------------------------------------------------

    def _quarantine(self, *args):
        return self.runner.invoke(
            args=["attachments", "local-quarantine", "--form-id", self.FORM_ID, *args]
        )

    def test_quarantine_moves_a_verified_file_and_never_deletes_it(self):
        storage_name = uuid.uuid4().hex + ".jpg"
        row = self._row(storage_name=storage_name)
        self.assertEqual(self._upload().exit_code, 0)

        dry = self._quarantine("--dry-run")
        self.assertIn("would_move=1", dry.output)
        self.assertTrue(os.path.isfile(
            os.path.join(self._tmp.name, self.FORM_ID, "media", storage_name)
        ))

        result = self._quarantine()
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("moved=1", result.output)

        media = os.path.join(self._tmp.name, self.FORM_ID, "media")
        self.assertFalse(os.path.exists(os.path.join(media, storage_name)))
        self.assertTrue(os.path.isfile(
            os.path.join(media, QUARANTINE_DIRNAME, storage_name)
        ))
        self.assertEqual(
            self._reload(row).local_fallback_state, svc.LOCAL_QUARANTINED
        )

    def test_quarantine_leaves_a_row_whose_object_is_missing(self):
        storage_name = uuid.uuid4().hex + ".jpg"
        row = self._row(storage_name=storage_name, store_state=svc.STORE_STATE_S3)

        result = self._quarantine()
        self.assertIn("skipped_no_object=1", result.output)
        self.assertTrue(os.path.isfile(
            os.path.join(self._tmp.name, self.FORM_ID, "media", storage_name)
        ))
        self.assertEqual(self._reload(row).local_fallback_state, svc.LOCAL_PRESENT)

    def test_retained_archival_copies_are_skipped_unless_asked_for(self):
        storage_name = uuid.uuid4().hex + ".jpg"
        row = self._row(
            storage_name=storage_name,
            local_fallback_state=svc.LOCAL_RETAINED,
        )
        self.assertEqual(self._upload().exit_code, 0)

        self.assertIn("moved=0", self._quarantine().output)
        self.assertEqual(self._reload(row).local_fallback_state, svc.LOCAL_RETAINED)

        self.assertIn("moved=1", self._quarantine("--include-retained").output)
        self.assertEqual(
            self._reload(row).local_fallback_state, svc.LOCAL_QUARANTINED
        )
