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
from app.services.va_data_sync.va_data_sync_01_odkcentral import (
    SYNC_ISSUE_MISSING_IN_ODK,
    _mark_form_sync_issues,
    _upsert_form_submissions,
)
from tests.base import BaseTestCase


class OdkSyncServiceTests(BaseTestCase):
    FORM_ID = "SYNC01BS0101"
    PROJECT_ID = "SYNC01"
    SITE_ID = "BS02"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        db.session.add(
            VaProjectMaster(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="Sync Test Project",
                project_nickname="SyncTest",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.add(
            VaResearchProjects(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="Sync Test Project",
                project_nickname="SyncTest",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.add(
            VaSiteMaster(
                site_id=cls.SITE_ID,
                site_name="Sync Test Site",
                site_abbr=cls.SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSites(
                site_id=cls.SITE_ID,
                project_id=cls.PROJECT_ID,
                site_name="Sync Test Site",
                site_abbr=cls.SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaProjectSites(
                project_id=cls.PROJECT_ID,
                site_id=cls.SITE_ID,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
        )
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.PROJECT_ID,
                site_id=cls.SITE_ID,
                odk_form_id="SYNC_TEST_FORM",
                odk_project_id="11",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.commit()

    def _record(self, instance_id: str, consent):
        now = datetime.now(timezone.utc)
        return {
            "KEY": instance_id,
            "sid": f"{instance_id}-{self.FORM_ID.lower()}",
            "form_def": self.FORM_ID,
            "SubmissionDate": now.isoformat(),
            "updatedAt": now.isoformat(),
            "SubmitterName": "Collector",
            "ReviewState": "hasIssues",
            "instanceName": instance_id,
            "unique_id": instance_id,
            "unique_id2": f"{instance_id}-masked",
            "Id10013": consent,
            "language": "English",
            "finalAgeInYears": "42",
            "Id10019": "male",
        }

    def test_upsert_includes_submissions_without_positive_consent(self):
        amended_sids = set()
        added, updated, discarded, skipped = _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID),
            [
                self._record("uuid:sync-consent-no", "no"),
                self._record("uuid:sync-consent-missing", None),
            ],
            amended_sids,
            {},
        )
        db.session.commit()

        self.assertEqual((added, updated, discarded, skipped), (2, 0, 0, 0))
        rows = db.session.execute(
            db.select(VaSubmissions.va_sid, VaSubmissions.va_consent).where(
                VaSubmissions.va_sid.in_(
                    [
                        f"uuid:sync-consent-no-{self.FORM_ID.lower()}",
                        f"uuid:sync-consent-missing-{self.FORM_ID.lower()}",
                    ]
                )
            )
        ).all()
        self.assertEqual(len(rows), 2)
        consent_map = {sid: consent for sid, consent in rows}
        self.assertEqual(
            consent_map[f"uuid:sync-consent-no-{self.FORM_ID.lower()}"], "no"
        )
        self.assertEqual(
            consent_map[f"uuid:sync-consent-missing-{self.FORM_ID.lower()}"], ""
        )

    def test_mark_form_sync_issues_flags_local_records_missing_in_odk(self):
        sid = f"uuid:sync-orphan-{self.FORM_ID.lower()}"
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id=self.FORM_ID,
                va_submission_date=datetime.now(timezone.utc),
                va_odk_updatedat=datetime.now(timezone.utc),
                va_data_collector="Collector",
                va_odk_reviewstate=None,
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=42,
                va_deceased_gender="male",
                va_uniqueid_masked="masked",
                va_data={"sid": sid},
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.commit()

        _mark_form_sync_issues(
            db.session.get(VaForms, self.FORM_ID),
            ["uuid:some-other-instance"],
        )
        db.session.commit()

        stored = db.session.get(VaSubmissions, sid)
        self.assertEqual(stored.va_sync_issue_code, SYNC_ISSUE_MISSING_IN_ODK)
