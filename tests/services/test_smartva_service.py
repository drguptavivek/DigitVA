"""Tests for the centralized SmartVA generation service.

Critical behavior under test:
- pending_smartva_sids() excludes protected workflow states
- pending_smartva_sids() excludes submissions with active SmartVA results
- generate_for_submission() skips protected states and returns 0
- generate_for_submission() proceeds for allowed states (SmartVA utilities mocked)
"""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
)
from app.services.smartva_service import (
    generate_for_submission,
    pending_smartva_sids,
)
from app.services.submission_workflow_service import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CLOSED,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVOKED_VA_DATA_CHANGED,
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
            va_data={"sid": sid},
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(sub)
        db.session.flush()
        return sub

    def _add_active_smartva_result(self, va_sid: str) -> VaSmartvaResults:
        result = VaSmartvaResults(
            va_smartva_id=uuid.uuid4(),
            va_sid=va_sid,
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

    def test_excludes_submission_in_revoked_va_data_changed_state(self):
        sub = self._make_submission("uuid:sva-revoked")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_REVOKED_VA_DATA_CHANGED, reason="test", by_role="test"
        )
        db.session.flush()

        pending = pending_smartva_sids(self.FORM_ID)
        self.assertNotIn(sub.va_sid, pending)

    def test_excludes_submission_in_closed_state(self):
        sub = self._make_submission("uuid:sva-closed")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_CLOSED, reason="test", by_role="test"
        )
        db.session.flush()

        pending = pending_smartva_sids(self.FORM_ID)
        self.assertNotIn(sub.va_sid, pending)

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
            va_data={"sid": sid},
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(sub)
        db.session.flush()
        return sub

    # ── tests ──────────────────────────────────────────────────────────────────

    def test_skips_coder_finalized_submission(self):
        sub = self._make_submission("uuid:gen-skip-finalized")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test"
        )
        db.session.flush()

        result = generate_for_submission(sub.va_sid)
        self.assertEqual(result, 0)

    def test_skips_revoked_va_data_changed_submission(self):
        sub = self._make_submission("uuid:gen-skip-revoked")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_REVOKED_VA_DATA_CHANGED, reason="test", by_role="test"
        )
        db.session.flush()

        result = generate_for_submission(sub.va_sid)
        self.assertEqual(result, 0)

    def test_skips_closed_submission(self):
        sub = self._make_submission("uuid:gen-skip-closed")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_CLOSED, reason="test", by_role="test"
        )
        db.session.flush()

        result = generate_for_submission(sub.va_sid)
        self.assertEqual(result, 0)

    def test_returns_zero_for_nonexistent_submission(self):
        result = generate_for_submission("uuid:does-not-exist-anywhere")
        self.assertEqual(result, 0)

    def test_proceeds_and_saves_result_for_allowed_state(self):
        """For an allowed state, SmartVA utilities are called and a result is saved."""
        sub = self._make_submission("uuid:gen-proceed")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_READY_FOR_CODING, reason="test", by_role="test"
        )
        db.session.flush()

        # Build a minimal DataFrame row that generate_for_submission expects
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
            patch("app.utils.va_smartva_formatsmartvaresult", return_value="/fake/output.csv"),
            patch(
                "app.utils.va_smartva_appendsmartvaresults",
                return_value=(new_result_df, {}),
            ),
        ):
            saved = generate_for_submission(sub.va_sid)

        self.assertEqual(saved, 1)

        # Confirm the result was persisted
        result_row = db.session.scalar(
            sa.select(VaSmartvaResults).where(
                VaSmartvaResults.va_sid == sub.va_sid,
                VaSmartvaResults.va_smartva_status == VaStatuses.active,
            )
        )
        self.assertIsNotNone(result_row)
        self.assertEqual(result_row.va_smartva_cause1, "Cardiovascular")

    def test_does_not_call_smartva_utilities_for_protected_state(self):
        """SmartVA binary must never be invoked for protected submissions."""
        sub = self._make_submission("uuid:gen-no-call")
        set_submission_workflow_state(
            sub.va_sid, WORKFLOW_CODER_FINALIZED, reason="test", by_role="test"
        )
        db.session.flush()

        with patch("app.utils.va_smartva_runsmartva") as mock_run:
            generate_for_submission(sub.va_sid)
            mock_run.assert_not_called()
