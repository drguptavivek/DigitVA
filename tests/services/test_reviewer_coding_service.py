import uuid
from datetime import datetime, timezone

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaFinalAssessments,
    VaFinalCodAuthority,
    VaForms,
    VaProjectSites,
    VaResearchProjects,
    VaReviewerFinalAssessments,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissionWorkflowEvent,
    VaSubmissions,
    VaUserAccessGrants,
)
from app.services.reviewer_coding_service import (
    ReviewerCodingError,
    start_reviewer_coding,
    submit_reviewer_final_cod,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import (
    TRANSITION_REVIEWER_CODING_STARTED,
    TRANSITION_REVIEWER_FINALIZED,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
)
from app.services.workflow.state_store import set_submission_workflow_state
from tests.base import BaseTestCase


_RUN_SUFFIX = uuid.uuid4().hex[:4].upper()


class TestReviewerCodingService(BaseTestCase):
    BASE_PROJECT_ID = f"RC{_RUN_SUFFIX}"
    BASE_SITE_ID = f"S{_RUN_SUFFIX[:3]}"
    FORM_ID = f"V{_RUN_SUFFIX}000001"
    USER_EMAIL_SUFFIX = f"+reviewercoding{_RUN_SUFFIX.lower()}"

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
                project_name="Reviewer Coding Project",
                project_nickname="ReviewerCoding",
                project_status=VaStatuses.active,
            )
        )
        db.session.commit()
        db.session.add(
            VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="Reviewer Coding Site",
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
                odk_form_id="REVIEWER_CODING_FORM",
                odk_project_id="1",
                form_type="WHO_2022_VA",
                form_status=VaStatuses.active,
            )
        )
        db.session.commit()

        project_site_id = db.session.scalar(
            db.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == cls.BASE_PROJECT_ID,
                VaProjectSites.site_id == cls.BASE_SITE_ID,
            )
        )
        cls.base_reviewer_user = cls._make_user(
            "base.reviewer.coding@test.local",
            "BaseReviewerCoding123",
        )
        cls.base_reviewer_user.landing_page = "reviewer"
        db.session.add(
            VaUserAccessGrants(
                user_id=cls.base_reviewer_user.user_id,
                role=VaAccessRoles.reviewer,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site_id,
                notes="base reviewer coding grant",
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()

    def _add_submission(self, sid: str):
        now = datetime.now(timezone.utc)
        submission = VaSubmissions(
            va_sid=sid,
            va_form_id=self.FORM_ID,
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name=sid,
            va_uniqueid_real=None,
            va_uniqueid_masked=sid,
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=42,
            va_deceased_gender="male",
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(submission)
        db.session.flush()
        ensure_active_payload_version(
            submission,
            payload_data={},
            source_updated_at=submission.va_odk_updatedat,
        )
        db.session.commit()
        return submission

    def test_start_reviewer_coding_requires_reviewer_eligible_state(self):
        sid = "uuid:reviewer-coding-blocked"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_READY_FOR_CODING,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        with self.assertRaises(ReviewerCodingError):
            start_reviewer_coding(self.base_reviewer_user, sid)

    def test_start_reviewer_coding_creates_reviewing_allocation_and_transition(self):
        sid = "uuid:reviewer-coding-start"
        self._add_submission(sid)
        set_submission_workflow_state(
            sid,
            WORKFLOW_REVIEWER_ELIGIBLE,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()

        result = start_reviewer_coding(self.base_reviewer_user, sid)

        self.assertEqual(result.actiontype, "vastartreviewing")
        workflow_state = db.session.scalar(
            db.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == sid
            )
        )
        allocation = db.session.scalar(
            db.select(VaAllocations).where(
                VaAllocations.va_sid == sid,
                VaAllocations.va_allocation_for == VaAllocation.reviewing,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        )
        event = db.session.scalar(
            db.select(VaSubmissionWorkflowEvent).where(
                VaSubmissionWorkflowEvent.va_sid == sid,
                VaSubmissionWorkflowEvent.transition_id
                == TRANSITION_REVIEWER_CODING_STARTED,
            )
        )

        self.assertEqual(workflow_state, WORKFLOW_REVIEWER_CODING_IN_PROGRESS)
        self.assertIsNotNone(allocation)
        self.assertIsNotNone(event)

    def test_submit_reviewer_final_cod_creates_artifact_and_releases_allocation(self):
        sid = "uuid:reviewer-coding-finalize"
        submission = self._add_submission(sid)
        coder_final = VaFinalAssessments(
            va_sid=sid,
            payload_version_id=submission.active_payload_version_id,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="R99",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add(coder_final)
        db.session.commit()

        set_submission_workflow_state(
            sid,
            WORKFLOW_REVIEWER_ELIGIBLE,
            reason="test_setup",
            by_role="vasystem",
        )
        db.session.commit()
        for allocation in db.session.scalars(
            db.select(VaAllocations).where(
                VaAllocations.va_allocated_to == self.base_reviewer_user.user_id,
                VaAllocations.va_allocation_for == VaAllocation.reviewing,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        ).all():
            allocation.va_allocation_status = VaStatuses.deactive
        db.session.commit()
        start_reviewer_coding(self.base_reviewer_user, sid)

        reviewer_final = submit_reviewer_final_cod(
            self.base_reviewer_user,
            sid,
            conclusive_cod="I21",
            remark="reviewer cod",
        )

        self.assertIsNotNone(reviewer_final.va_rfinassess_id)
        self.assertEqual(
            reviewer_final.supersedes_coder_final_assessment_id,
            coder_final.va_finassess_id,
        )
        workflow_state = db.session.scalar(
            db.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == sid
            )
        )
        active_allocation = db.session.scalar(
            db.select(VaAllocations).where(
                VaAllocations.va_sid == sid,
                VaAllocations.va_allocation_for == VaAllocation.reviewing,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        )
        stored_reviewer_final = db.session.get(
            VaReviewerFinalAssessments, reviewer_final.va_rfinassess_id
        )
        event = db.session.scalar(
            db.select(VaSubmissionWorkflowEvent).where(
                VaSubmissionWorkflowEvent.va_sid == sid,
                VaSubmissionWorkflowEvent.transition_id
                == TRANSITION_REVIEWER_FINALIZED,
            )
        )
        authority = db.session.scalar(
            db.select(VaFinalCodAuthority).where(VaFinalCodAuthority.va_sid == sid)
        )

        self.assertEqual(workflow_state, WORKFLOW_REVIEWER_FINALIZED)
        self.assertIsNone(active_allocation)
        self.assertIsNotNone(stored_reviewer_final)
        self.assertIsNotNone(event)
        self.assertEqual(
            authority.authoritative_reviewer_final_assessment_id,
            reviewer_final.va_rfinassess_id,
        )
        self.assertIsNone(authority.authoritative_final_assessment_id)
