"""Tests for the centralized SmartVA generation service.

Critical behavior under test:
- pending_smartva_sids() excludes protected workflow states
- pending_smartva_sids() excludes submissions with active SmartVA results
- generate_for_submission() skips protected states and returns 0
- generate_for_submission() proceeds for allowed states (SmartVA utilities mocked)
"""
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
import sqlalchemy as sa

from app import db
from app.models import (
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaSmartvaFormRun,
    VaSmartvaRun,
    VaSmartvaRunOutput,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.smartva_service import (
    generate_for_form,
    generate_for_submission,
    pending_smartva_sids,
)
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CONSENT_REFUSED,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_SMARTVA_PENDING,
)
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    set_submission_workflow_state,
)
from tests.base import BaseTestCase


class PendingSmartVaSidsTests(BaseTestCase):
    FORM_ID = "SVA01ST0101"
    PROJECT_ID = "SVA01"
    SITE_ID = "ST01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID,
            project_code=cls.PROJECT_ID,
            project_name="SmartVA Test Project",
            project_nickname="SvaT",
            project_status=VaStatuses.active,
            project_registered_at=now,
            project_updated_at=now,
        ))
        db.session.add(VaResearchProjects(
            project_id=cls.PROJECT_ID,
            project_code=cls.PROJECT_ID,
            project_name="SmartVA Test Project",
            project_nickname="SvaT",
            project_status=VaStatuses.active,
            project_registered_at=now,
            project_updated_at=now,
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID,
            site_name="SmartVA Test Site",
            site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active,
            site_registered_at=now,
            site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaSites(
            site_id=cls.SITE_ID,
            project_id=cls.PROJECT_ID,
            site_name="SmartVA Test Site",
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
            odk_form_id="STEST_FORM",
            odk_project_id="88",
            form_type="WHO VA 2022",
            form_status=VaStatuses.active,
            form_registered_at=now,
            form_updated_at=now,
        ))
        db.session.commit()

    # ── helpers ────────────────────────────────────────────────────────────────

    def _make_submission(self, instance_id: str) -> VaSubmissions:
        now = datetime.now(timezone.utc)
        sid = f"{instance_id}-{self.FORM_ID.lower()}"
        payload_data = {
            "sid": sid,
            "form_def": self.FORM_ID,
            "updatedAt": now.isoformat(),
        }
        sub = VaSubmissions(
            va_sid=sid,
            va_form_id=self.FORM_ID,
            va_submission_date=now,
            va_odk_updatedat=now.replace(tzinfo=None),
            va_data_collector="Collector",
            va_odk_reviewstate=None,
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=45,
            va_deceased_gender="male",
            va_uniqueid_masked="masked",
            va_data=payload_data,
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(sub)
        db.session.flush()
        ensure_active_payload_version(
            sub,
            payload_data=payload_data,
            source_updated_at=sub.va_odk_updatedat,
            created_by_role="vasystem",
        )
        return sub

    def _add_active_smartva_result(self, va_sid: str) -> VaSmartvaResults:
        submission = db.session.get(VaSubmissions, va_sid)
        result = VaSmartvaResults(
            va_smartva_id=uuid.uuid4(),
            va_sid=va_sid,
            payload_version_id=submission.active_payload_version_id if submission else None,
            va_smartva_status=VaStatuses.active,
        )
        db.session.add(result)
        db.session.flush()
        return result

    # ── pending_smartva_sids tests ─────────────────────────────────────────────

    def test_includes_submission_in_ready_for_coding_without_result(self):
        sub = self._make_submission("uuid:sva-ready")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_READY_FOR_CODING, reason="test", by_role="test"
        )
        db.session.flush()

        pending = pending_smartva_sids(self.FORM_ID)
        self.assertIn(sub.va_sid, pending)

    def test_excludes_submission_in_coder_finalized_state(self):
        sub = self._make_submission("uuid:sva-finalized")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test"
        )
        db.session.flush()

        pending = pending_smartva_sids(self.FORM_ID)
        self.assertNotIn(sub.va_sid, pending)

    def test_excludes_submission_in_finalized_upstream_changed_state(self):
        sub = self._make_submission("uuid:sva-revoked")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_FINALIZED_UPSTREAM_CHANGED, reason="test", by_role="test"
        )
        db.session.flush()

        pending = pending_smartva_sids(self.FORM_ID)
        self.assertNotIn(sub.va_sid, pending)

    def test_excludes_submission_in_reviewer_eligible_state(self):
        sub = self._make_submission("uuid:sva-reviewer-eligible")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_REVIEWER_ELIGIBLE, reason="test", by_role="test"
        )
        db.session.flush()

        pending = pending_smartva_sids(self.FORM_ID)
        self.assertNotIn(sub.va_sid, pending)

    def test_excludes_submission_in_consent_refused_state(self):
        sub = self._make_submission("uuid:sva-consent-refused")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_CONSENT_REFUSED, reason="test", by_role="test"
        )
        db.session.flush()

        pending = pending_smartva_sids(self.FORM_ID)
        self.assertNotIn(sub.va_sid, pending)

    def test_excludes_submission_in_reviewer_states(self):
        eligible = self._make_submission("uuid:sva-reviewer-eligible")
        finalized = self._make_submission("uuid:sva-reviewer-finalized")
        set_submission_workflow_state(
            eligible.va_sid, WORKFLOW_REVIEWER_ELIGIBLE, reason="test", by_role="test"
        )
        set_submission_workflow_state(
            finalized.va_sid, WORKFLOW_REVIEWER_FINALIZED, reason="test", by_role="test"
        )
        db.session.flush()

        pending = pending_smartva_sids(self.FORM_ID)
        self.assertNotIn(eligible.va_sid, pending)
        self.assertNotIn(finalized.va_sid, pending)

    def test_excludes_submission_with_active_smartva_result(self):
        sub = self._make_submission("uuid:sva-has-result")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_READY_FOR_CODING, reason="test", by_role="test"
        )
        self._add_active_smartva_result(sub.va_sid)
        db.session.flush()

        pending = pending_smartva_sids(self.FORM_ID)
        self.assertNotIn(sub.va_sid, pending)

    def test_includes_submission_with_only_inactive_smartva_result(self):
        """A deactivated result does not count — submission still needs SmartVA."""
        sub = self._make_submission("uuid:sva-old-result")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_READY_FOR_CODING, reason="test", by_role="test"
        )
        old_result = VaSmartvaResults(
            va_smartva_id=uuid.uuid4(),
            va_sid=sub.va_sid,
            payload_version_id=sub.active_payload_version_id,
            va_smartva_status=VaStatuses.deactive,
        )
        db.session.add(old_result)
        db.session.flush()

        pending = pending_smartva_sids(self.FORM_ID)
        self.assertIn(sub.va_sid, pending)

    def test_returns_empty_set_for_form_with_no_submissions(self):
        pending = pending_smartva_sids("NONEXISTENT_FORM_ID")
        self.assertEqual(pending, set())

    def test_mixed_states_only_allowed_states_returned(self):
        """Only the allowed-state submission appears in the pending set."""
        allowed = self._make_submission("uuid:sva-mix-allowed")
        protected = self._make_submission("uuid:sva-mix-protected")
        set_submission_workflow_state(
            allowed.va_sid, WORKFLOW_READY_FOR_CODING, reason="test", by_role="test"
        )
        set_submission_workflow_state(
            protected.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test"
        )
        db.session.flush()

        pending = pending_smartva_sids(self.FORM_ID)
        self.assertIn(allowed.va_sid, pending)
        self.assertNotIn(protected.va_sid, pending)


class GenerateForSubmissionTests(BaseTestCase):
    """Tests for generate_for_submission() with SmartVA utilities mocked."""

    FORM_ID = "SVA02ST0201"
    PROJECT_ID = "SVA02"
    SITE_ID = "ST02"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        db.session.add(VaProjectMaster(
            project_id=cls.PROJECT_ID,
            project_code=cls.PROJECT_ID,
            project_name="SmartVA Gen Test Project",
            project_nickname="SvaGT",
            project_status=VaStatuses.active,
            project_registered_at=now,
            project_updated_at=now,
        ))
        db.session.add(VaResearchProjects(
            project_id=cls.PROJECT_ID,
            project_code=cls.PROJECT_ID,
            project_name="SmartVA Gen Test Project",
            project_nickname="SvaGT",
            project_status=VaStatuses.active,
            project_registered_at=now,
            project_updated_at=now,
        ))
        db.session.add(VaSiteMaster(
            site_id=cls.SITE_ID,
            site_name="SmartVA Gen Test Site",
            site_abbr=cls.SITE_ID,
            site_status=VaStatuses.active,
            site_registered_at=now,
            site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaSites(
            site_id=cls.SITE_ID,
            project_id=cls.PROJECT_ID,
            site_name="SmartVA Gen Test Site",
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
            odk_form_id="STEST2_FORM",
            odk_project_id="87",
            form_type="WHO VA 2022",
            form_status=VaStatuses.active,
            form_registered_at=now,
            form_updated_at=now,
        ))
        db.session.commit()

    def _make_submission(self, instance_id: str) -> VaSubmissions:
        now = datetime.now(timezone.utc)
        sid = f"{instance_id}-{self.FORM_ID.lower()}"
        payload_data = {
            "sid": sid,
            "form_def": self.FORM_ID,
            "updatedAt": now.isoformat(),
        }
        sub = VaSubmissions(
            va_sid=sid,
            va_form_id=self.FORM_ID,
            va_submission_date=now,
            va_odk_updatedat=now.replace(tzinfo=None),
            va_data_collector="Collector",
            va_odk_reviewstate=None,
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=45,
            va_deceased_gender="male",
            va_uniqueid_masked="masked",
            va_data=payload_data,
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(sub)
        db.session.flush()
        ensure_active_payload_version(
            sub,
            payload_data=payload_data,
            source_updated_at=sub.va_odk_updatedat,
            created_by_role="vasystem",
        )
        return sub

    # ── tests ──────────────────────────────────────────────────────────────────

    def test_skips_coder_finalized_submission(self):
        sub = self._make_submission("uuid:gen-skip-finalized")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test"
        )
        db.session.commit()

        result = generate_for_submission(sub.va_sid)
        self.assertEqual(result, 0)

    def test_skips_finalized_upstream_changed_submission(self):
        sub = self._make_submission("uuid:gen-skip-revoked")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_FINALIZED_UPSTREAM_CHANGED, reason="test", by_role="test"
        )
        db.session.commit()

        result = generate_for_submission(sub.va_sid)
        self.assertEqual(result, 0)

    def test_skips_reviewer_eligible_submission(self):
        sub = self._make_submission("uuid:gen-skip-reviewer-eligible")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_REVIEWER_ELIGIBLE, reason="test", by_role="test"
        )
        db.session.commit()

        result = generate_for_submission(sub.va_sid)
        self.assertEqual(result, 0)

    def test_returns_zero_for_nonexistent_submission(self):
        result = generate_for_submission("uuid:does-not-exist-anywhere")
        self.assertEqual(result, 0)

    def test_proceeds_and_saves_result_for_allowed_state(self):
        """For an allowed state, SmartVA utilities are called and a result is saved."""
        sub = self._make_submission("uuid:gen-proceed")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_SMARTVA_PENDING, reason="test", by_role="test"
        )
        db.session.commit()

        new_result_df = pd.DataFrame([{
            "sid": sub.va_sid,
            "age": 45.0,
            "sex": "male",
            "cause1": "Cardiovascular",
            "likelihood1": "High",
            "key_symptom1": "chest pain",
            "cause2": None,
            "likelihood2": None,
            "key_symptom2": None,
            "cause3": None,
            "likelihood3": None,
            "key_symptom3": None,
            "all_symptoms": "chest pain",
            "result_for": "for_adult",
            "cause1_icd": "I21",
            "cause2_icd": None,
            "cause3_icd": None,
        }])

        with (
            patch("app.utils.va_smartva_prepdata"),
            patch("app.utils.va_smartva_runsmartva"),
            patch(
                "app.services.smartva_service._read_raw_likelihood_outputs",
                return_value={
                    sub.va_sid: [
                        (
                            "adult-likelihoods.csv",
                            {
                                "sid": sub.va_sid,
                                "cause1": "Cardiovascular",
                                "likelihood1": "High",
                                "result_for": "for_adult",
                            },
                        )
                    ]
                },
            ),
            patch(
                "app.utils.va_smartva_formatsmartvaresult",
                return_value="/fake/output.csv",
            ),
            patch(
                "app.services.smartva_service._read_formatted_results",
                return_value=new_result_df,
            ),
        ):
            saved = generate_for_submission(sub.va_sid)

        self.assertEqual(saved, 1)

        result_row = db.session.scalar(
            sa.select(VaSmartvaResults).where(
                VaSmartvaResults.va_sid == sub.va_sid,
                VaSmartvaResults.va_smartva_status == VaStatuses.active,
            )
        )
        run_row = db.session.scalar(
            sa.select(VaSmartvaRun).where(VaSmartvaRun.va_sid == sub.va_sid)
        )
        form_run = db.session.get(VaSmartvaFormRun, run_row.form_run_id)
        likelihood_row = db.session.scalar(
            sa.select(VaSmartvaRunOutput)
            .join(
                VaSmartvaRun,
                VaSmartvaRun.va_smartva_run_id
                == VaSmartvaRunOutput.va_smartva_run_id,
            )
            .where(VaSmartvaRun.va_sid == sub.va_sid)
            .where(VaSmartvaRunOutput.output_kind == "likelihood_row")
        )
        self.assertIsNotNone(result_row)
        self.assertIsNotNone(run_row)
        self.assertIsNotNone(form_run)
        self.assertIsNotNone(likelihood_row)
        self.assertEqual(result_row.va_smartva_cause1, "Cardiovascular")
        self.assertEqual(result_row.smartva_run_id, run_row.va_smartva_run_id)
        self.assertEqual(run_row.payload_version_id, sub.active_payload_version_id)
        self.assertEqual(run_row.va_smartva_outcome, VaSmartvaRun.OUTCOME_SUCCESS)
        self.assertEqual(run_row.form_run_id, form_run.form_run_id)
        self.assertEqual(form_run.form_id, self.FORM_ID)
        self.assertEqual(form_run.project_id, self.PROJECT_ID)
        self.assertEqual(form_run.pending_sid_count, 1)
        self.assertEqual(form_run.outcome, VaSmartvaFormRun.OUTCOME_SUCCESS)
        self.assertTrue(form_run.disk_path)
        self.assertEqual(likelihood_row.output_source_name, "adult-likelihoods.csv")
        self.assertEqual(likelihood_row.output_payload["result_for"], "for_adult")
        self.assertEqual(
            get_submission_workflow_state(sub.va_sid),
            WORKFLOW_READY_FOR_CODING,
        )

    def test_does_not_call_smartva_utilities_for_protected_state(self):
        """SmartVA binary must never be invoked for protected submissions."""
        sub = self._make_submission("uuid:gen-no-call")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test"
        )
        db.session.commit()

        with patch("app.utils.va_smartva_runsmartva") as mock_run:
            generate_for_submission(sub.va_sid)
            mock_run.assert_not_called()

    def test_records_failure_and_releases_pending_submission_when_run_raises(self):
        sub = self._make_submission("uuid:gen-fail-exception")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_SMARTVA_PENDING, reason="test", by_role="test"
        )
        db.session.commit()
        initial_form_run_count = db.session.scalar(
            sa.select(sa.func.count()).select_from(VaSmartvaFormRun)
        )

        with (
            patch("app.utils.va_smartva_prepdata"),
            patch("app.utils.va_smartva_runsmartva", side_effect=RuntimeError("smartva crashed")),
        ):
            saved = generate_for_submission(sub.va_sid)

        self.assertEqual(saved, 1)
        result_row = db.session.scalar(
            sa.select(VaSmartvaResults).where(
                VaSmartvaResults.va_sid == sub.va_sid,
                VaSmartvaResults.va_smartva_status == VaStatuses.active,
            )
        )
        run_row = db.session.scalar(
            sa.select(VaSmartvaRun).where(VaSmartvaRun.va_sid == sub.va_sid)
        )
        form_run = db.session.get(VaSmartvaFormRun, run_row.form_run_id)
        form_run_count = db.session.scalar(
            sa.select(sa.func.count()).select_from(VaSmartvaFormRun)
        )
        self.assertIsNotNone(result_row)
        self.assertIsNotNone(run_row)
        self.assertIsNotNone(form_run)
        self.assertEqual(result_row.va_smartva_outcome, VaSmartvaResults.OUTCOME_FAILED)
        self.assertEqual(result_row.va_smartva_failure_stage, "execution")
        self.assertIn("smartva crashed", result_row.va_smartva_failure_detail)
        self.assertEqual(result_row.smartva_run_id, run_row.va_smartva_run_id)
        self.assertEqual(run_row.va_smartva_outcome, VaSmartvaRun.OUTCOME_FAILED)
        self.assertEqual(run_row.payload_version_id, sub.active_payload_version_id)
        self.assertEqual(form_run.outcome, VaSmartvaFormRun.OUTCOME_FAILED)
        self.assertTrue(form_run.disk_path)
        self.assertEqual(form_run_count, initial_form_run_count + 1)
        self.assertEqual(
            get_submission_workflow_state(sub.va_sid),
            WORKFLOW_READY_FOR_CODING,
        )

    def test_records_failure_when_output_contains_no_matching_submission_row(self):
        sub = self._make_submission("uuid:gen-fail-missing-row")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_SMARTVA_PENDING, reason="test", by_role="test"
        )
        db.session.commit()

        other_result_df = pd.DataFrame([{
            "sid": "uuid:someone-else",
            "age": 45.0,
            "sex": "male",
            "cause1": "Cardiovascular",
            "likelihood1": "High",
            "key_symptom1": "chest pain",
            "cause2": None,
            "likelihood2": None,
            "key_symptom2": None,
            "cause3": None,
            "likelihood3": None,
            "key_symptom3": None,
            "all_symptoms": "chest pain",
            "result_for": "for_adult",
            "cause1_icd": "I21",
            "cause2_icd": None,
            "cause3_icd": None,
        }])

        with (
            patch("app.utils.va_smartva_prepdata"),
            patch("app.utils.va_smartva_runsmartva"),
            patch(
                "app.utils.va_smartva_formatsmartvaresult",
                return_value="/fake/output.csv",
            ),
            patch(
                "app.services.smartva_service._read_formatted_results",
                return_value=other_result_df,
            ),
        ):
            saved = generate_for_submission(sub.va_sid)

        self.assertEqual(saved, 1)
        result_row = db.session.scalar(
            sa.select(VaSmartvaResults).where(
                VaSmartvaResults.va_sid == sub.va_sid,
                VaSmartvaResults.va_smartva_status == VaStatuses.active,
            )
        )
        run_row = db.session.scalar(
            sa.select(VaSmartvaRun).where(VaSmartvaRun.va_sid == sub.va_sid)
        )
        self.assertIsNotNone(result_row)
        self.assertIsNotNone(run_row)
        self.assertEqual(result_row.va_smartva_outcome, VaSmartvaResults.OUTCOME_FAILED)
        self.assertEqual(result_row.va_smartva_failure_stage, "missing_row")
        self.assertEqual(
            get_submission_workflow_state(sub.va_sid),
            WORKFLOW_READY_FOR_CODING,
        )

    def test_records_report_rejection_as_smartva_rejected(self):
        sub = self._make_submission("uuid:gen-report-rejected")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_SMARTVA_PENDING, reason="test", by_role="test"
        )
        db.session.commit()
        initial_form_run_count = db.session.scalar(
            sa.select(sa.func.count()).select_from(VaSmartvaFormRun)
        )

        def fake_prepdata(_va_form, workspace_dir, pending_sids=None):
            with open(f"{workspace_dir}/smartva_input.csv", "w", newline="") as handle:
                handle.write("sid\n")
                handle.write(f"{sub.va_sid}\n")

        def fake_runsmartva(_va_form, workspace_dir):
            import os

            report_dir = os.path.join(
                workspace_dir,
                "smartva_output",
                "4-monitoring-and-quality",
            )
            os.makedirs(report_dir, exist_ok=True)
            with open(os.path.join(report_dir, "report.txt"), "w") as handle:
                handle.write("Details:\n")
                handle.write(
                    f"SID: {sub.va_sid} (row 1) "
                    "does not have valid age data and is being removed "
                    "from the analysis.\n"
                )

        with (
            patch("app.utils.va_smartva_prepdata", side_effect=fake_prepdata),
            patch("app.utils.va_smartva_runsmartva", side_effect=fake_runsmartva),
            patch("app.utils.va_smartva_formatsmartvaresult", return_value=None),
        ):
            saved = generate_for_submission(sub.va_sid)

        self.assertEqual(saved, 1)
        result_row = db.session.scalar(
            sa.select(VaSmartvaResults).where(
                VaSmartvaResults.va_sid == sub.va_sid,
                VaSmartvaResults.va_smartva_status == VaStatuses.active,
            )
        )
        run_row = db.session.scalar(
            sa.select(VaSmartvaRun).where(VaSmartvaRun.va_sid == sub.va_sid)
        )
        form_run = db.session.get(VaSmartvaFormRun, run_row.form_run_id)
        form_run_count = db.session.scalar(
            sa.select(sa.func.count()).select_from(VaSmartvaFormRun)
        )
        self.assertIsNotNone(result_row)
        self.assertIsNotNone(run_row)
        self.assertIsNotNone(form_run)
        self.assertEqual(result_row.va_smartva_outcome, VaSmartvaResults.OUTCOME_FAILED)
        self.assertEqual(result_row.va_smartva_failure_stage, "smartva_rejected")
        self.assertIn("does not have valid age data", result_row.va_smartva_failure_detail)
        self.assertEqual(run_row.va_smartva_outcome, VaSmartvaRun.OUTCOME_FAILED)
        self.assertEqual(form_run.outcome, VaSmartvaFormRun.OUTCOME_FAILED)
        self.assertEqual(form_run_count, initial_form_run_count + 1)
        self.assertEqual(
            get_submission_workflow_state(sub.va_sid),
            WORKFLOW_READY_FOR_CODING,
        )

    def test_generate_for_form_records_failure_for_pending_submission(self):
        sub = self._make_submission("uuid:form-fail-exception")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_SMARTVA_PENDING, reason="test", by_role="test"
        )
        db.session.commit()
        va_form = db.session.get(VaForms, self.FORM_ID)
        initial_form_run_count = db.session.scalar(
            sa.select(sa.func.count()).select_from(VaSmartvaFormRun)
        )

        with (
            patch("app.utils.va_smartva_prepdata"),
            patch("app.utils.va_smartva_runsmartva", side_effect=RuntimeError("form smartva crashed")),
        ):
            saved = generate_for_form(va_form, amended_sids={sub.va_sid})

        self.assertEqual(saved, 1)
        result_row = db.session.scalar(
            sa.select(VaSmartvaResults).where(
                VaSmartvaResults.va_sid == sub.va_sid,
                VaSmartvaResults.va_smartva_status == VaStatuses.active,
            )
        )
        run_row = db.session.scalar(
            sa.select(VaSmartvaRun).where(VaSmartvaRun.va_sid == sub.va_sid)
        )
        form_run = db.session.get(VaSmartvaFormRun, run_row.form_run_id)
        form_run_count = db.session.scalar(
            sa.select(sa.func.count()).select_from(VaSmartvaFormRun)
        )
        self.assertIsNotNone(result_row)
        self.assertIsNotNone(run_row)
        self.assertIsNotNone(form_run)
        self.assertEqual(result_row.va_smartva_outcome, VaSmartvaResults.OUTCOME_FAILED)
        self.assertEqual(result_row.va_smartva_failure_stage, "execution")
        self.assertIn("form smartva crashed", result_row.va_smartva_failure_detail)
        self.assertEqual(result_row.smartva_run_id, run_row.va_smartva_run_id)
        self.assertEqual(run_row.va_smartva_outcome, VaSmartvaRun.OUTCOME_FAILED)
        self.assertEqual(form_run.outcome, VaSmartvaFormRun.OUTCOME_FAILED)
        self.assertEqual(form_run_count, initial_form_run_count + 1)
        self.assertEqual(
            get_submission_workflow_state(sub.va_sid),
            WORKFLOW_READY_FOR_CODING,
        )

    def test_copies_workspace_to_disk_for_form_run(self):
        sub = self._make_submission("uuid:gen-raw-artifacts")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_SMARTVA_PENDING, reason="test", by_role="test"
        )
        db.session.commit()

        new_result_df = pd.DataFrame([{
            "sid": sub.va_sid,
            "age": 45.0,
            "sex": "male",
            "cause1": "Cardiovascular",
            "likelihood1": "High",
            "key_symptom1": "chest pain",
            "cause2": None,
            "likelihood2": None,
            "key_symptom2": None,
            "cause3": None,
            "likelihood3": None,
            "key_symptom3": None,
            "all_symptoms": "chest pain",
            "result_for": "for_adult",
            "cause1_icd": "I21",
            "cause2_icd": None,
            "cause3_icd": None,
        }])

        def fake_prepdata(_va_form, workspace_dir, pending_sids=None):
            with open(f"{workspace_dir}/smartva_input.csv", "w", newline="") as handle:
                handle.write("sid,narr\n")
                handle.write(f"{sub.va_sid},\"line1\\nline2\"\n")

        def fake_runsmartva(_va_form, workspace_dir):
            import os
            import csv
            from openpyxl import Workbook

            base = f"{workspace_dir}/smartva_output"
            os.makedirs(f"{base}/1-individual-cause-of-death", exist_ok=True)
            os.makedirs(f"{base}/2-csmf", exist_ok=True)
            os.makedirs(f"{base}/3-graphs-and-tables", exist_ok=True)
            os.makedirs(
                f"{base}/4-monitoring-and-quality/intermediate-files",
                exist_ok=True,
            )

            with open(f"{workspace_dir}/smartva_output.csv", "w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["sid", "cause1"])
                writer.writerow([sub.va_sid, "Cardiovascular"])

            with open(
                f"{base}/1-individual-cause-of-death/adult-predictions.csv",
                "w",
                newline="",
            ) as handle:
                writer = csv.writer(handle)
                writer.writerow(["sid", "cause"])
                writer.writerow([sub.va_sid, "Cardiovascular"])

            with open(
                f"{base}/4-monitoring-and-quality/intermediate-files/adult-likelihoods.csv",
                "w",
                newline="",
            ) as handle:
                writer = csv.writer(handle)
                writer.writerow(["sid", "cause1", "likelihood1"])
                writer.writerow([sub.va_sid, "Cardiovascular", "High"])

            workbook = Workbook()
            workbook.active.title = "likelihoods"
            workbook.active.append(["sid", "cause1", "likelihood1"])
            workbook.active.append([sub.va_sid, "Cardiovascular", "High"])
            workbook.save(f"{base}/4-monitoring-and-quality/adult-likelihoods.xlsx")

            with open(
                f"{base}/2-csmf/csmf.csv",
                "w",
                newline="",
            ) as handle:
                writer = csv.writer(handle)
                writer.writerow(["cause", "CSMF"])
                writer.writerow(["Cardiovascular", "0.5"])

            with open(f"{base}/3-graphs-and-tables/all-csmf-figure.png", "wb") as handle:
                handle.write(b"png")

        with (
            patch("app.utils.va_smartva_prepdata", side_effect=fake_prepdata),
            patch("app.utils.va_smartva_runsmartva", side_effect=fake_runsmartva),
            patch(
                "app.services.smartva_service._read_raw_likelihood_outputs",
                return_value={
                    sub.va_sid: [
                        (
                            "adult-likelihoods.csv",
                            {
                                "sid": sub.va_sid,
                                "cause1": "Cardiovascular",
                                "likelihood1": "High",
                                "result_for": "for_adult",
                            },
                        )
                    ]
                },
            ),
            patch(
                "app.utils.va_smartva_formatsmartvaresult",
                return_value="/fake/output.csv",
            ),
            patch(
                "app.services.smartva_service._read_formatted_results",
                return_value=new_result_df,
            ),
        ):
            saved = generate_for_submission(sub.va_sid)

        self.assertEqual(saved, 1)
        run_row = db.session.scalar(
            sa.select(VaSmartvaRun).where(VaSmartvaRun.va_sid == sub.va_sid)
        )
        form_run = db.session.get(VaSmartvaFormRun, run_row.form_run_id)
        self.assertIsNotNone(form_run)
        workspace_path = os.path.join(self.app.config["APP_DATA"], form_run.disk_path)

        self.assertTrue(os.path.exists(os.path.join(workspace_path, "smartva_input.csv")))
        self.assertTrue(os.path.exists(os.path.join(workspace_path, "smartva_output.csv")))
        self.assertTrue(
            os.path.exists(
                os.path.join(
                    workspace_path,
                    "smartva_output/1-individual-cause-of-death/adult-predictions.csv",
                )
            )
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(
                    workspace_path,
                    "smartva_output/4-monitoring-and-quality/adult-likelihoods.xlsx",
                )
            )
        )
        self.assertTrue(
            os.path.exists(
                os.path.join(
                    workspace_path,
                    "smartva_output/4-monitoring-and-quality/intermediate-files/adult-likelihoods.csv",
                )
            )
        )
        with open(
            os.path.join(workspace_path, "smartva_input.csv"),
            "rb",
        ) as handle:
            input_bytes = handle.read()
        self.assertIn(b"line1", input_bytes)
        self.assertIn(b"line2", input_bytes)
