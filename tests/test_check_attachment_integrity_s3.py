"""``scripts/check_attachment_integrity.py --store s3``.

The S3 mode compares the rows recorded as S3-stored against the keys actually
in the bucket. It reports and never writes: an orphan key is named, not
removed.
"""

import io
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import sqlalchemy as sa
from moto import mock_aws

import scripts.check_attachment_integrity as integrity
from app import db
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


class IntegrityS3ModeTests(BaseTestCase):
    """The script opens its own app context, so its session is a second
    connection that cannot see uncommitted rows. This class therefore writes
    for real and deletes what it created."""

    FORM_ID = "INTS3_FORM"
    isolate_in_transaction = False

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
            odk_form_id="INTS3_ODK",
            odk_project_id="95",
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

        self._previous = self.app.config["ATTACHMENT_STORE"]
        self.app.config["ATTACHMENT_STORE"] = svc.STORE_STATE_S3
        self.addCleanup(self._restore)

        with self.app.app_context():
            self.store = store_mod.get_attachment_store()
        self.store.client.create_bucket(
            Bucket=self.store.bucket,
            CreateBucketConfiguration={
                "LocationConstraint": self.app.config["S3_REGION"]
            },
        )
        patcher = patch.object(integrity, "create_app", return_value=self.app)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.sids = []
        self.addCleanup(self._delete_rows)

    def _delete_rows(self):
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

    def _restore(self):
        self.app.config["ATTACHMENT_STORE"] = self._previous
        self.app.extensions.pop("attachment_store", None)

    def _row(self, storage_name, *, store_state=svc.STORE_STATE_S3):
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
        db.session.add(VaSubmissionAttachments(
            va_sid=sub.va_sid,
            filename="photo.jpg",
            mime_type="image/jpeg",
            storage_name=storage_name,
            exists_on_odk=True,
            store_state=store_state,
        ))
        db.session.commit()
        self.sids.append(sub.va_sid)
        return sub.va_sid

    def _put(self, storage_name):
        target = store_mod.StoreTarget(
            va_form_id=self.FORM_ID, storage_name=storage_name
        )
        self.store.put(target, io.BytesIO(b"bytes"), content_type="image/jpeg")
        return self.store.key_for(target)

    def _run(self):
        with patch("sys.stdout", new=io.StringIO()) as out:
            code = integrity.run_s3_check(self.FORM_ID, 10)
        return code, out.getvalue()

    def test_a_complete_bucket_reports_clean(self):
        storage_name = uuid.uuid4().hex + ".jpg"
        self._row(storage_name)
        self._put(storage_name)

        code, output = self._run()
        self.assertEqual(code, 0, output)
        self.assertIn("Rows recorded as s3 with no object: 0", output)
        self.assertIn("Orphan keys not referenced by any row: 0", output)

    def test_a_row_without_its_object_is_reported(self):
        storage_name = uuid.uuid4().hex + ".jpg"
        self._row(storage_name)

        code, output = self._run()
        self.assertEqual(code, 2)
        self.assertIn("Rows recorded as s3 with no object: 1", output)
        self.assertIn(storage_name, output)

    def test_an_orphan_key_is_reported_and_never_removed(self):
        orphan_key = self._put(uuid.uuid4().hex + ".jpg")

        code, output = self._run()
        self.assertEqual(code, 2)
        self.assertIn("Orphan keys not referenced by any row: 1", output)
        self.assertIn(orphan_key, output)
        self.assertIsNotNone(self.store.head(orphan_key))

    def test_rows_awaiting_the_cutover_are_counted_separately(self):
        storage_name = uuid.uuid4().hex + ".jpg"
        self._row(storage_name, store_state=svc.STORE_STATE_LOCAL)

        code, output = self._run()
        self.assertEqual(code, 0, output)
        self.assertIn("Rows still awaiting the cutover: 1", output)

    def test_the_s3_mode_refuses_to_run_on_the_local_store(self):
        self.app.config["ATTACHMENT_STORE"] = svc.STORE_STATE_LOCAL
        self.app.extensions.pop("attachment_store", None)
        code, output = self._run()
        self.assertEqual(code, 1)
        self.assertIn("ATTACHMENT_STORE is not 's3'", output)
