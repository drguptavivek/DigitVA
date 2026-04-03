import os
import tempfile
from datetime import datetime, timezone

from app import db
from app.models import (
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissionAttachments,
    VaSubmissions,
)
from app.services.attachment_cache_backfill_service import backfill_attachment_cache
from app.services.submission_payload_version_service import ensure_active_payload_version
from tests.base import BaseTestCase


class AttachmentCacheBackfillServiceTests(BaseTestCase):
    PROJECT_ID = "ATB001"
    SITE_ID = "AT01"
    FORM_ID = "ATB001AT0101"
    SID = "uuid:attachment-backfill-case-atb001at0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        db.session.add_all(
            [
                VaProjectMaster(
                    project_id=cls.PROJECT_ID,
                    project_code=cls.PROJECT_ID,
                    project_name="Attachment Backfill Project",
                    project_nickname="AttachBackfill",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaResearchProjects(
                    project_id=cls.PROJECT_ID,
                    project_code=cls.PROJECT_ID,
                    project_name="Attachment Backfill Project",
                    project_nickname="AttachBackfill",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaSiteMaster(
                    site_id=cls.SITE_ID,
                    site_name="Attachment Backfill Site",
                    site_abbr=cls.SITE_ID,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
            ]
        )
        db.session.commit()
        db.session.add_all(
            [
                VaSites(
                    site_id=cls.SITE_ID,
                    project_id=cls.PROJECT_ID,
                    site_name="Attachment Backfill Site",
                    site_abbr=cls.SITE_ID,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
                VaProjectSites(
                    project_id=cls.PROJECT_ID,
                    site_id=cls.SITE_ID,
                    project_site_status=VaStatuses.active,
                    project_site_registered_at=now,
                    project_site_updated_at=now,
                ),
            ]
        )
        db.session.commit()
        db.session.add_all(
            [
                VaForms(
                    form_id=cls.FORM_ID,
                    project_id=cls.PROJECT_ID,
                    site_id=cls.SITE_ID,
                    odk_form_id="ATTACHMENT_BACKFILL_FORM",
                    odk_project_id="99",
                    form_type="WHO VA 2022",
                    form_status=VaStatuses.active,
                    form_registered_at=now,
                    form_updated_at=now,
                ),
                VaSubmissions(
                    va_sid=cls.SID,
                    va_form_id=cls.FORM_ID,
                    va_submission_date=now,
                    va_odk_updatedat=now,
                    va_data_collector="Collector",
                    va_odk_reviewstate=None,
                    va_consent="yes",
                    va_narration_language="English",
                    va_deceased_age=55,
                    va_deceased_gender="female",
                    va_instance_name=cls.SID,
                    va_uniqueid_real=cls.SID,
                    va_uniqueid_masked="masked-attachment-backfill",
                    va_summary=[],
                    va_catcount={},
                    va_category_list=[],
                ),
            ]
        )
        db.session.flush()
        submission = db.session.get(VaSubmissions, cls.SID)
        ensure_active_payload_version(
            submission,
            payload_data={
                "Id10476_audio": "voice.amr",
                "imagenarr": "photo.jpg",
                "md_im1": "missing.png",
            },
            source_updated_at=now,
            created_by_role="vasystem",
        )
        db.session.commit()

    def setUp(self):
        super().setUp()
        db.session.execute(
            db.delete(VaSubmissionAttachments).where(
                VaSubmissionAttachments.va_sid == self.SID
            )
        )
        db.session.flush()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app.config["APP_DATA"] = self.temp_dir.name
        self.media_dir = os.path.join(self.temp_dir.name, self.FORM_ID, "media")
        os.makedirs(self.media_dir, exist_ok=True)
        with open(os.path.join(self.media_dir, "voice.mp3"), "wb") as handle:
            handle.write(b"mp3")
        with open(os.path.join(self.media_dir, "photo.jpg"), "wb") as handle:
            handle.write(b"jpg")

    def tearDown(self):
        self.temp_dir.cleanup()
        super().tearDown()

    def test_backfill_creates_rows_from_existing_local_files(self):
        result = backfill_attachment_cache(form_id=self.FORM_ID)

        self.assertEqual(result["forms_scanned"], 1)
        self.assertEqual(result["submissions_scanned"], 1)
        self.assertEqual(result["attachments_created"], 2)
        self.assertEqual(result["missing_files"], 1)

        rows = db.session.scalars(
            db.select(VaSubmissionAttachments).where(
                VaSubmissionAttachments.va_sid == self.SID
            )
        ).all()
        self.assertEqual(len(rows), 2)
        row_map = {row.filename: row for row in rows}
        self.assertIn("voice.amr", row_map)
        self.assertTrue(row_map["voice.amr"].local_path.endswith("voice.mp3"))
        self.assertEqual(row_map["voice.amr"].mime_type, "audio/mpeg")
        self.assertIn("photo.jpg", row_map)

    def test_backfill_is_idempotent(self):
        first = backfill_attachment_cache(form_id=self.FORM_ID)
        second = backfill_attachment_cache(form_id=self.FORM_ID)

        self.assertEqual(first["attachments_created"], 2)
        self.assertEqual(second["attachments_created"], 0)
        self.assertEqual(second["attachments_skipped"], 2)
