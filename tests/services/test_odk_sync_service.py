from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from app import db
from app.models import (
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
)
from app.services.va_data_sync.va_data_sync_01_odkcentral import (
    SYNC_ISSUE_MISSING_IN_ODK,
    _attach_all_odk_comments,
    _mark_form_sync_issues,
    _upsert_form_submissions,
)
from app.services.submission_workflow_service import WORKFLOW_SMARTVA_PENDING
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
            "isNeonatal": "0",
            "isChild": "0",
            "isAdult": "1",
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

    def test_upsert_sets_consented_submission_to_smartva_pending(self):
        amended_sids = set()
        sid = f"uuid:sync-consent-yes-{self.FORM_ID.lower()}"

        _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID),
            [self._record("uuid:sync-consent-yes", "yes")],
            amended_sids,
            {},
        )
        db.session.commit()

        workflow_state = db.session.scalar(
            db.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == sid
            )
        )
        self.assertEqual(workflow_state, WORKFLOW_SMARTVA_PENDING)

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
                va_deceased_age_normalized_days=Decimal("15340.5"),
                va_deceased_age_normalized_years=Decimal("42"),
                va_deceased_age_source="finalAgeInYears",
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

    def test_attach_all_odk_comments_adds_all_has_issues_comments(self):
        client = Mock()
        client.submissions.list_comments.return_value = [
            SimpleNamespace(
                body="Older review note",
                createdAt=datetime(2026, 3, 17, 10, 0, tzinfo=timezone.utc),
            ),
            SimpleNamespace(
                body="Newest review note",
                createdAt=datetime(2026, 3, 18, 12, 0, tzinfo=timezone.utc),
            ),
        ]

        submissions = _attach_all_odk_comments(
            db.session.get(VaForms, self.FORM_ID),
            [self._record("uuid:sync-comment", "yes")],
            client=client,
        )

        self.assertEqual(
            submissions[0]["OdkReviewComments"],
            [
                {
                    "body": "Newest review note",
                    "created_at": "2026-03-18T12:00:00+00:00",
                },
                {
                    "body": "Older review note",
                    "created_at": "2026-03-17T10:00:00+00:00",
                },
            ],
        )

    def test_upsert_persists_all_odk_review_comments(self):
        amended_sids = set()
        record = self._record("uuid:sync-comment-store", "yes")
        record["OdkReviewComments"] = [
            {"body": "Field team should fix respondent age."},
            {"body": "Village name is missing."},
        ]

        _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID),
            [record],
            amended_sids,
            {},
        )
        db.session.commit()

        stored = db.session.get(
            VaSubmissions,
            f"uuid:sync-comment-store-{self.FORM_ID.lower()}",
        )
        self.assertEqual(
            stored.va_odk_reviewcomments,
            [
                {"body": "Field team should fix respondent age."},
                {"body": "Village name is missing."},
            ],
        )

    def test_upsert_populates_normalized_age_fields_with_policy_precedence(self):
        amended_sids = set()
        record = self._record("uuid:sync-age-normalized", "yes")
        record.update(
            {
                "age_neonate_days": "",
                "age_neonate_hours": "",
                "ageInDays": "45",
                "ageInMonths": "1",
                "ageInYears": "99",
                "ageInYears2": "2",
                "finalAgeInYears": "2.0",
                "isNeonatal": "0",
                "isChild": "1",
                "isAdult": "0",
            }
        )

        _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID),
            [record],
            amended_sids,
            {},
        )
        db.session.commit()

        stored = db.session.get(
            VaSubmissions,
            f"uuid:sync-age-normalized-{self.FORM_ID.lower()}",
        )
        self.assertEqual(stored.va_deceased_age, 2)
        self.assertEqual(stored.va_deceased_age_source, "ageInDays")
        self.assertEqual(stored.va_deceased_age_normalized_days, Decimal("45"))
        self.assertEqual(
            stored.va_deceased_age_normalized_years,
            Decimal("45") / Decimal("365.25"),
        )
