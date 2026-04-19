import os
import tempfile
import uuid
from datetime import datetime, timezone

from app import db
from app.models import (
    VaForms,
    VaResearchProjects,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionAttachments,
    VaSubmissions,
    VaSubmissionPayloadVersion,
    VaSites,
)
from app.tasks.sync_tasks import _build_repair_map_for_form
from app.models.va_submission_payload_versions import PAYLOAD_VERSION_STATUS_ACTIVE
from tests.base import BaseTestCase


class SyncTaskAttachmentRepairTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._old_app_data = self.app.config.get("APP_DATA")
        self.app.config["APP_DATA"] = self._tmp_dir.name
        self.project_id = f"P{uuid.uuid4().hex[:5].upper()}"
        self.site_id = f"S{uuid.uuid4().hex[:3].upper()}"
        self.form_id = f"BS01{uuid.uuid4().hex[:8].upper()}"[:12]
        now = datetime.now(timezone.utc)
        db.session.add_all(
            [
                VaResearchProjects(
                    project_id=self.project_id,
                    project_code=self.project_id,
                    project_name="Sync Task Test Project",
                    project_nickname="SyncTaskTest",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaSites(
                    site_id=self.site_id,
                    project_id=self.project_id,
                    site_name="Sync Task Test Site",
                    site_abbr=self.site_id,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
            ]
        )
        db.session.commit()
        db.session.add(
            VaForms(
                form_id=self.form_id,
                project_id=self.project_id,
                site_id=self.site_id,
                odk_form_id=f"ODK-{self.form_id}",
                odk_project_id="1",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.commit()

    def tearDown(self):
        self.app.config["APP_DATA"] = self._old_app_data
        self._tmp_dir.cleanup()
        super().tearDown()

    def _create_submission_with_attachment(
        self,
        *,
        filename: str,
        storage_name: str | None,
        local_path: str | None,
        attachments_expected: int = 1,
    ) -> str:
        now = datetime.now(timezone.utc)
        instance_id = uuid.uuid4().hex
        va_sid = f"{instance_id}-{self.form_id.lower()}"
        submission = VaSubmissions(
            va_sid=va_sid,
            va_form_id=self.form_id,
            active_payload_version_id=None,
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="collector",
            va_odk_reviewstate=None,
            va_odk_reviewcomments=None,
            va_sync_issue_code=None,
            va_sync_issue_detail=None,
            va_sync_issue_updated_at=None,
            va_instance_name=instance_id,
            va_uniqueid_real=None,
            va_uniqueid_masked=instance_id,
            va_consent="yes",
            va_narration_language="english",
            va_deceased_age=42,
            va_deceased_age_normalized_days=None,
            va_deceased_age_normalized_years=None,
            va_deceased_age_source=None,
            va_deceased_gender="male",
            va_summary=["summary"],
            va_catcount={},
            va_category_list=["category"],
            va_created_at=now,
            va_updated_at=now,
        )
        db.session.add(submission)
        db.session.flush()

        payload = VaSubmissionPayloadVersion(
            va_sid=va_sid,
            source_updated_at=now,
            payload_fingerprint=uuid.uuid4().hex,
            payload_data={
                "KEY": instance_id,
                "instanceID": instance_id,
                "FormVersion": "1",
                "DeviceID": "device-1",
                "SubmitterID": "submitter-1",
                "AttachmentsExpected": attachments_expected,
                "AttachmentsPresent": attachments_expected,
            },
            version_status=PAYLOAD_VERSION_STATUS_ACTIVE,
            created_by_role="vasystem",
            created_by=None,
            version_created_at=now,
            version_activated_at=now,
            has_required_metadata=True,
            attachments_expected=attachments_expected,
        )
        db.session.add(payload)
        db.session.flush()

        submission.active_payload_version_id = payload.payload_version_id
        db.session.add(
            VaSubmissionAttachments(
                va_sid=va_sid,
                filename=filename,
                local_path=local_path,
                mime_type="image/jpeg",
                etag="etag-1",
                exists_on_odk=True,
                last_downloaded_at=now,
                storage_name=storage_name,
            )
        )
        db.session.add(
            VaSmartvaResults(
                va_sid=va_sid,
                payload_version_id=payload.payload_version_id,
                smartva_run_id=None,
                va_smartva_cause1="Some cause",
                va_smartva_outcome=VaSmartvaResults.OUTCOME_SUCCESS,
                va_smartva_status=VaStatuses.active,
                va_smartva_addedat=now,
                va_smartva_updatedat=now,
            )
        )
        db.session.commit()
        return va_sid

    def test_build_repair_map_marks_missing_local_attachment_files(self):
        va_sid = self._create_submission_with_attachment(
            filename="photo.jpg",
            storage_name="photo-storage.jpg",
            local_path=os.path.join(self._tmp_dir.name, self.form_id, "media", "photo.jpg"),
        )

        repair_map, summary = _build_repair_map_for_form(self.form_id, [], {})

        self.assertEqual(summary["metadata_missing"], 0)
        self.assertEqual(summary["attachments_missing"], 1)
        self.assertEqual(summary["smartva_missing"], 0)
        self.assertIn(va_sid, repair_map)
        self.assertTrue(repair_map[va_sid]["needs_attachments"])
        self.assertFalse(repair_map[va_sid]["needs_metadata"])
        self.assertFalse(repair_map[va_sid]["needs_smartva"])

    def test_build_repair_map_excludes_audit_csv_from_present_files(self):
        media_dir = os.path.join(self._tmp_dir.name, self.form_id, "media")
        os.makedirs(media_dir, exist_ok=True)
        audit_path = os.path.join(media_dir, "audit.csv")
        with open(audit_path, "w", encoding="utf-8") as handle:
            handle.write("audit")

        va_sid = self._create_submission_with_attachment(
            filename="audit.csv",
            storage_name=None,
            local_path=audit_path,
        )

        repair_map, summary = _build_repair_map_for_form(self.form_id, [], {})

        self.assertEqual(summary["attachments_missing"], 1)
        self.assertIn(va_sid, repair_map)
        self.assertTrue(repair_map[va_sid]["needs_attachments"])
