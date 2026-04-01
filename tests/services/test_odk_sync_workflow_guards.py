"""Tests for the workflow state guard in _upsert_form_submissions.

Critical behavior under test:
- Submissions in protected states (coder_finalized, finalized_upstream_changed, closed)
  must NOT have their workflow artifacts destroyed when ODK data changes.
- They must be transitioned to finalized_upstream_changed instead.
- Non-protected submissions follow the existing destructive update path.
"""
import uuid
from datetime import datetime, timezone, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    VaFinalAssessments,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissionWorkflow,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
from app.models.va_submission_payload_versions import (
    PAYLOAD_VERSION_STATUS_ACTIVE,
    PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM,
)
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_REVIEWER_ELIGIBLE,
)
from app.services.workflow.state_store import (
    set_submission_workflow_state,
)
from app.services.va_data_sync.va_data_sync_01_odkcentral import (
    _upsert_form_submissions,
)
from tests.base import BaseTestCase


class UpsertWorkflowGuardTests(BaseTestCase):
    FORM_ID = "GRD01GD0101"
    PROJECT_ID = "GRD01"
    SITE_ID = "GD01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID,
            project_code=cls.PROJECT_ID,
            project_name="Guard Test Project",
            project_nickname="GrdTest",
            project_status=VaStatuses.active,
            project_registered_at=now,
            project_updated_at=now,
        ))
        db.session.add(VaResearchProjects(
            project_id=cls.PROJECT_ID,
            project_code=cls.PROJECT_ID,
            project_name="Guard Test Project",
            project_nickname="GrdTest",
            project_status=VaStatuses.active,
            project_registered_at=now,
            project_updated_at=now,
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID,
            site_name="Guard Test Site",
            site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active,
            site_registered_at=now,
            site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaSites(
            site_id=cls.SITE_ID,
            project_id=cls.PROJECT_ID,
            site_name="Guard Test Site",
            site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active,
            site_registered_at=now,
            site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=cls.PROJECT_ID,
            site_id=cls.SITE_ID,
            project_site_status=VaStatuses.active,
            project_site_registered_at=now,
            project_site_updated_at=now,
        ))
        db.session.add(VaForms(
            form_id=cls.FORM_ID,
            project_id=cls.PROJECT_ID,
            site_id=cls.SITE_ID,
            odk_form_id="GUARD_FORM",
            odk_project_id="99",
            form_type="WHO VA 2022",
            form_status=VaStatuses.active,
            form_registered_at=now,
            form_updated_at=now,
        ))
        db.session.commit()

    # ── helpers ────────────────────────────────────────────────────────────────

    def _make_submission(self, instance_id: str) -> VaSubmissions:
        """Insert a submission with an old updatedAt so we can trigger an update."""
        old_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        sid = f"{instance_id}-{self.FORM_ID.lower()}"
        sub = VaSubmissions(
            va_sid=sid,
            va_form_id=self.FORM_ID,
            va_submission_date=old_time,
            va_odk_updatedat=old_time.replace(tzinfo=None),
            va_data_collector="Collector",
            va_odk_reviewstate=None,
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=50,
            va_deceased_gender="female",
            va_uniqueid_masked="masked",
            va_data={"sid": sid, "form_def": self.FORM_ID},
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(sub)
        db.session.flush()
        return sub

    def _make_final_assessment(self, va_sid: str) -> VaFinalAssessments:
        fa = VaFinalAssessments(
            va_sid=va_sid,
            va_finassess_by=self.base_admin_user.user_id,
            va_conclusive_cod="Cardiovascular",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add(fa)
        db.session.flush()
        return fa

    def _updated_record(self, instance_id: str) -> dict:
        """ODK record for the same submission but with a newer updatedAt."""
        new_time = datetime.now(timezone.utc)
        sid = f"{instance_id}-{self.FORM_ID.lower()}"
        return {
            "KEY": instance_id,
            "sid": sid,
            "form_def": self.FORM_ID,
            "SubmissionDate": new_time.isoformat(),
            "updatedAt": new_time.isoformat(),
            "SubmitterName": "Collector",
            "ReviewState": None,
            "OdkReviewComments": [],
            "instanceName": instance_id,
            "unique_id": instance_id,
            "unique_id2": f"{instance_id}-masked",
            "Id10013": "yes",
            "language": "English",
            "finalAgeInYears": "52",
            "Id10019": "female",
        }

    def _metadata_only_updated_record(self, instance_id: str) -> dict:
        old_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        sid = f"{instance_id}-{self.FORM_ID.lower()}"
        return {
            "KEY": instance_id,
            "sid": sid,
            "form_def": self.FORM_ID,
            "SubmissionDate": old_time.isoformat(),
            "updatedAt": datetime.now(timezone.utc).isoformat(),
            "SubmitterName": "Collector",
            "ReviewState": None,
            "OdkReviewComments": [],
            "instanceName": instance_id,
            "unique_id": instance_id,
            "unique_id2": f"{instance_id}-masked",
            "Id10013": "yes",
            "language": "English",
            "Id10019": "female",
            "Id10120": "10",
            "finalAgeInYears": "52",
            "ageInYears": "52",
            "DeviceID": None,
            "instanceID": None,
            "survey_state": "29",
        }

    def _get_workflow_state(self, va_sid: str) -> str | None:
        return db.session.scalar(
            sa.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == va_sid
            )
        )

    # ── tests ──────────────────────────────────────────────────────────────────

    def test_coder_finalized_submission_is_not_destroyed_on_odk_data_change(self):
        """VaFinalAssessments must survive an ODK data change for a finalized submission."""
        sub = self._make_submission("uuid:guard-finalized")
        fa = self._make_final_assessment(sub.va_sid)
        fa_id = fa.va_finassess_id
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test"
        )
        db.session.flush()

        va_form = db.session.get(VaForms, self.FORM_ID)
        _upsert_form_submissions(va_form, [self._updated_record("uuid:guard-finalized")], set(), {})
        db.session.flush()

        refreshed_fa = db.session.get(VaFinalAssessments, fa_id)
        self.assertIsNotNone(refreshed_fa)
        self.assertEqual(refreshed_fa.va_finassess_status, VaStatuses.active)

    def test_coder_finalized_submission_transitions_to_revoked_on_odk_data_change(self):
        """Workflow state must be finalized_upstream_changed after upstream ODK change."""
        sub = self._make_submission("uuid:guard-finalized-state")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test"
        )
        db.session.flush()

        va_form = db.session.get(VaForms, self.FORM_ID)
        added, updated, discarded, skipped = _upsert_form_submissions(
            va_form, [self._updated_record("uuid:guard-finalized-state")], set(), {}
        )
        db.session.flush()

        self.assertEqual(updated, 1)
        self.assertEqual(self._get_workflow_state(sub.va_sid), WORKFLOW_FINALIZED_UPSTREAM_CHANGED)

    def test_coder_finalized_update_creates_audit_log_entry(self):
        """An audit entry must be created when a protected submission is flagged."""
        sub = self._make_submission("uuid:guard-audit")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test"
        )
        db.session.flush()

        va_form = db.session.get(VaForms, self.FORM_ID)
        _upsert_form_submissions(va_form, [self._updated_record("uuid:guard-audit")], set(), {})
        db.session.flush()

        audit_entry = db.session.scalar(
            sa.select(VaSubmissionsAuditlog).where(
                VaSubmissionsAuditlog.va_sid == sub.va_sid,
                VaSubmissionsAuditlog.va_audit_action
                == "upstream_odk_data_changed_on_protected_submission",
            )
        )
        self.assertIsNotNone(audit_entry)

    def test_already_revoked_submission_stays_revoked_on_further_odk_change(self):
        """A finalized_upstream_changed submission encountering another ODK change
        must remain in revoked state, not be double-reset."""
        sub = self._make_submission("uuid:guard-already-revoked")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_FINALIZED_UPSTREAM_CHANGED, reason="test", by_role="test"
        )
        db.session.flush()

        va_form = db.session.get(VaForms, self.FORM_ID)
        _upsert_form_submissions(
            va_form, [self._updated_record("uuid:guard-already-revoked")], set(), {}
        )
        db.session.flush()

        self.assertEqual(
            self._get_workflow_state(sub.va_sid), WORKFLOW_FINALIZED_UPSTREAM_CHANGED
        )

    def test_reviewer_eligible_submission_creates_pending_upstream_payload_version(self):
        sub = self._make_submission("uuid:guard-reviewer-eligible")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_REVIEWER_ELIGIBLE, reason="test", by_role="test"
        )
        db.session.flush()

        va_form = db.session.get(VaForms, self.FORM_ID)
        _upsert_form_submissions(
            va_form, [self._updated_record("uuid:guard-reviewer-eligible")], set(), {}
        )
        db.session.flush()

        versions = db.session.scalars(
            sa.select(VaSubmissionPayloadVersion)
            .where(VaSubmissionPayloadVersion.va_sid == sub.va_sid)
            .order_by(VaSubmissionPayloadVersion.version_created_at.asc())
        ).all()

        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[0].version_status, PAYLOAD_VERSION_STATUS_ACTIVE)
        self.assertEqual(
            versions[1].version_status, PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM
        )
        self.assertEqual(
            self._get_workflow_state(sub.va_sid), WORKFLOW_FINALIZED_UPSTREAM_CHANGED
        )

    def test_ready_for_coding_submission_is_updated_normally(self):
        """Non-protected submissions must follow the normal destructive update path."""
        sub = self._make_submission("uuid:guard-normal")
        fa = self._make_final_assessment(sub.va_sid)
        fa_id = fa.va_finassess_id
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_READY_FOR_CODING, reason="test", by_role="test"
        )
        db.session.flush()

        va_form = db.session.get(VaForms, self.FORM_ID)
        added, updated, discarded, skipped = _upsert_form_submissions(
            va_form, [self._updated_record("uuid:guard-normal")], set(), {}
        )
        db.session.flush()

        self.assertEqual(updated, 1)
        # Workflow state must NOT be revoked — it reinfers from cleared artifacts
        self.assertNotEqual(
            self._get_workflow_state(sub.va_sid), WORKFLOW_FINALIZED_UPSTREAM_CHANGED
        )
        # Final assessment must be deactivated on normal update path
        refreshed_fa = db.session.get(VaFinalAssessments, fa_id)
        self.assertEqual(refreshed_fa.va_finassess_status, VaStatuses.deactive)

    def test_no_workflow_record_submission_treated_as_non_protected(self):
        """A submission with no workflow record (None state) is not protected."""
        sub = self._make_submission("uuid:guard-no-workflow")
        # Do NOT set any workflow state
        db.session.flush()

        va_form = db.session.get(VaForms, self.FORM_ID)
        added, updated, discarded, skipped = _upsert_form_submissions(
            va_form, [self._updated_record("uuid:guard-no-workflow")], set(), {}
        )
        db.session.flush()

        self.assertEqual(updated, 1)
        self.assertNotEqual(
            self._get_workflow_state(sub.va_sid), WORKFLOW_FINALIZED_UPSTREAM_CHANGED
        )

    def test_metadata_only_payload_churn_does_not_revoke_protected_submission(self):
        sub = self._make_submission("uuid:guard-metadata-only")
        sub.va_data = {
            "sid": sub.va_sid,
            "form_def": self.FORM_ID,
            "KEY": "uuid:guard-metadata-only",
            "SubmissionDate": datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc).isoformat(),
            "SubmitterName": "Collector",
            "ReviewState": None,
            "OdkReviewComments": None,
            "instanceName": "uuid:guard-metadata-only",
            "unique_id": "uuid:guard-metadata-only",
            "unique_id2": "uuid:guard-metadata-only-masked",
            "Id10013": "yes",
            "language": "English",
            "Id10019": "female",
            "Id10120": 10.0,
            "finalAgeInYears": 52,
            "ageInYears": 52.0,
            "DeviceID": "collect:legacy",
            "instanceID": "uuid:guard-metadata-only",
            "survey_state": 29,
        }
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test"
        )
        db.session.flush()

        va_form = db.session.get(VaForms, self.FORM_ID)
        added, updated, discarded, skipped = _upsert_form_submissions(
            va_form,
            [self._metadata_only_updated_record("uuid:guard-metadata-only")],
            set(),
            {},
        )
        db.session.flush()

        self.assertEqual(updated, 1)
        self.assertEqual(discarded, 0)
        self.assertEqual(
            self._get_workflow_state(sub.va_sid), WORKFLOW_CODER_FINALIZED
        )
