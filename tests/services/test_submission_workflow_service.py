import uuid
from datetime import datetime, timezone

from app import db
from app.models import (
    VaAllocations,
    VaAllocation,
    VaCoderReview,
    VaDataManagerReview,
    VaFinalAssessments,
    VaForms,
    VaInitialAssessments,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
)
from app.services.submission_workflow_service import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_READY_FOR_CODING,
    infer_workflow_state_from_legacy_records,
    set_submission_workflow_state,
    sync_submission_workflow_from_legacy_records,
)
from tests.base import BaseTestCase


_RUN_SUFFIX = uuid.uuid4().hex[:4].upper()


class TestSubmissionWorkflowService(BaseTestCase):
    BASE_PROJECT_ID = f"WF{_RUN_SUFFIX}"
    BASE_SITE_ID = f"S{_RUN_SUFFIX[:3]}"
    FORM_ID = f"W{_RUN_SUFFIX}000001"
    USER_EMAIL_SUFFIX = f"+workflow{_RUN_SUFFIX.lower()}"

    @classmethod
    def _make_user(cls, email, password):
        local_part, domain = email.split("@", 1)
        return super()._make_user(
            f"{local_part}{cls.USER_EMAIL_SUFFIX}@{domain}",
            password,
        )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db.session.add(
            VaResearchProjects(
                project_id=cls.BASE_PROJECT_ID,
                project_code=cls.BASE_PROJECT_ID,
                project_name="Workflow Project",
                project_nickname="WorkflowProject",
                project_status=VaStatuses.active,
            )
        )
        db.session.commit()
        db.session.add(
            VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="Workflow Site",
                site_abbr=cls.BASE_SITE_ID,
                site_status=VaStatuses.active,
            )
        )
        db.session.commit()
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="WORKFLOW_FORM",
                odk_project_id="1",
                form_type="WHO_2022_VA",
                form_status=VaStatuses.active,
            )
        )
        db.session.commit()

    def _add_submission(self, sid: str) -> None:
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id=self.FORM_ID,
                va_submission_date=datetime.now(timezone.utc),
                va_odk_updatedat=datetime.now(timezone.utc),
                va_data_collector="tester",
                va_odk_reviewstate=None,
                va_instance_name=sid,
                va_uniqueid_real=None,
                va_uniqueid_masked=sid,
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=42,
                va_deceased_gender="male",
                va_data={},
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.commit()

    def test_infer_ready_for_coding_when_no_active_workflow_records(self):
        sid = "uuid:wf-ready"
        self._add_submission(sid)

        inferred = infer_workflow_state_from_legacy_records(sid)

        self.assertEqual(inferred, WORKFLOW_READY_FOR_CODING)

    def test_infer_coding_in_progress_from_active_allocation(self):
        sid = "uuid:wf-alloc"
        self._add_submission(sid)
        db.session.add(
            VaAllocations(
                va_sid=sid,
                va_allocated_to=self.base_coder_user.user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
            )
        )
        db.session.commit()

        inferred = infer_workflow_state_from_legacy_records(sid)

        self.assertEqual(inferred, WORKFLOW_CODING_IN_PROGRESS)

    def test_infer_step1_saved_from_active_initial_assessment(self):
        sid = "uuid:wf-step1"
        self._add_submission(sid)
        db.session.add(
            VaInitialAssessments(
                va_sid=sid,
                va_iniassess_by=self.base_coder_user.user_id,
                va_immediate_cod="R99",
                va_antecedent_cod="R99",
                va_other_conditions=None,
                va_iniassess_status=VaStatuses.active,
            )
        )
        db.session.commit()

        inferred = infer_workflow_state_from_legacy_records(sid)

        self.assertEqual(inferred, WORKFLOW_CODER_STEP1_SAVED)

    def test_infer_finalized_and_not_codeable_precedence(self):
        sid_final = "uuid:wf-final"
        self._add_submission(sid_final)
        db.session.add(
            VaFinalAssessments(
                va_sid=sid_final,
                va_finassess_by=self.base_coder_user.user_id,
                va_conclusive_cod="R99",
                va_finassess_status=VaStatuses.active,
            )
        )

        sid_error = "uuid:wf-error"
        self._add_submission(sid_error)
        db.session.add(
            VaCoderReview(
                va_sid=sid_error,
                va_creview_by=self.base_coder_user.user_id,
                va_creview_reason="form_is_empty",
                va_creview_other=None,
                va_creview_status=VaStatuses.active,
            )
        )
        db.session.commit()

        self.assertEqual(
            infer_workflow_state_from_legacy_records(sid_final),
            WORKFLOW_CODER_FINALIZED,
        )
        self.assertEqual(
            infer_workflow_state_from_legacy_records(sid_error),
            WORKFLOW_NOT_CODEABLE_BY_CODER,
        )

    def test_infer_data_manager_not_codeable_before_coder_pool(self):
        sid = "uuid:wf-dm"
        self._add_submission(sid)
        db.session.add(
            VaDataManagerReview(
                va_sid=sid,
                va_dmreview_by=self.base_admin_user.user_id,
                va_dmreview_reason="submission_incomplete",
                va_dmreview_other=None,
                va_dmreview_status=VaStatuses.active,
            )
        )
        db.session.commit()

        self.assertEqual(
            infer_workflow_state_from_legacy_records(sid),
            WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
        )

    def test_sync_submission_workflow_creates_and_updates_record(self):
        sid = "uuid:wf-sync"
        self._add_submission(sid)

        workflow = sync_submission_workflow_from_legacy_records(
            sid,
            reason="initial_backfill",
            by_role="vasystem",
        )
        db.session.commit()

        self.assertIsNotNone(workflow.workflow_id)
        self.assertEqual(workflow.workflow_state, WORKFLOW_READY_FOR_CODING)

        updated = set_submission_workflow_state(
            sid,
            WORKFLOW_CODING_IN_PROGRESS,
            reason="manual_transition",
            by_user_id=self.base_coder_user.user_id,
            by_role="vacoder",
        )
        db.session.commit()

        stored = db.session.scalar(
            db.select(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid == sid)
        )
        self.assertEqual(updated.workflow_id, stored.workflow_id)
        self.assertEqual(stored.workflow_state, WORKFLOW_CODING_IN_PROGRESS)
        self.assertEqual(stored.workflow_reason, "manual_transition")
