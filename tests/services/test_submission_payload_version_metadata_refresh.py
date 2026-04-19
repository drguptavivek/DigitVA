import uuid
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
    VaSubmissions,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from tests.base import BaseTestCase


class SubmissionPayloadVersionMetadataRefreshTests(BaseTestCase):
    PROJECT_ID = "PVM01"
    SITE_ID = "PV01"
    FORM_ID = "PVM01PV0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        db.session.add_all(
            [
                VaProjectMaster(
                    project_id=cls.PROJECT_ID,
                    project_code=cls.PROJECT_ID,
                    project_name="Payload Version Metadata Project",
                    project_nickname="PVMeta",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaResearchProjects(
                    project_id=cls.PROJECT_ID,
                    project_code=cls.PROJECT_ID,
                    project_name="Payload Version Metadata Project",
                    project_nickname="PVMeta",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaSiteMaster(
                    site_id=cls.SITE_ID,
                    site_name="Payload Version Metadata Site",
                    site_abbr=cls.SITE_ID,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
            ]
        )
        db.session.flush()
        db.session.add_all(
            [
                VaSites(
                    site_id=cls.SITE_ID,
                    project_id=cls.PROJECT_ID,
                    site_name="Payload Version Metadata Site",
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
        db.session.flush()
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.PROJECT_ID,
                site_id=cls.SITE_ID,
                odk_form_id="PV_METADATA_FORM",
                odk_project_id="71",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.commit()

    def test_ensure_active_payload_version_refreshes_completeness_for_same_fingerprint(self):
        now = datetime.now(timezone.utc)
        va_sid = f"uuid:payload-version-refresh-{uuid.uuid4().hex[:8]}"
        submission = VaSubmissions(
            va_sid=va_sid,
            va_form_id=self.FORM_ID,
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name=va_sid,
            va_uniqueid_real=None,
            va_uniqueid_masked=va_sid,
            va_consent="yes",
            va_narration_language="english",
            va_deceased_age=42,
            va_deceased_gender="male",
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(submission)
        db.session.flush()

        initial_payload = {"Id10120": "10"}
        version = ensure_active_payload_version(
            submission,
            payload_data=initial_payload,
            source_updated_at=now,
            created_by_role="vasystem",
        )
        db.session.commit()

        self.assertFalse(version.has_required_metadata)
        self.assertIsNone(version.attachments_expected)

        refreshed_payload = {
            "Id10120": "10",
            "FormVersion": "1",
            "DeviceID": "device-1",
            "SubmitterID": "submitter-1",
            "instanceID": "uuid:instance-1",
            "AttachmentsExpected": "2",
            "AttachmentsPresent": "0",
        }
        refreshed = ensure_active_payload_version(
            submission,
            payload_data=refreshed_payload,
            source_updated_at=now,
            created_by_role="vasystem",
        )
        db.session.commit()

        self.assertEqual(refreshed.payload_version_id, version.payload_version_id)
        self.assertTrue(refreshed.has_required_metadata)
        self.assertEqual(refreshed.attachments_expected, 2)
        self.assertEqual(refreshed.payload_data.get("FormVersion"), "1")
        self.assertEqual(refreshed.payload_data.get("AttachmentsExpected"), "2")
