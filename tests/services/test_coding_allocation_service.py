import uuid
from datetime import datetime, timedelta, timezone

from app import db
from app.models import (
    VaAllocations,
    VaAllocation,
    VaCodingEpisode,
    VaFinalCodAuthority,
    VaForms,
    VaInitialAssessments,
    VaNarrativeAssessment,
    VaSocialAutopsyAnalysis,
    VaSocialAutopsyAnalysisOption,
    VaFinalAssessments,
    VaResearchProjects,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflowEvent,
    VaSubmissionWorkflow,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
from app.services.coding_allocation_service import (
    cleanup_expired_demo_coding_artifacts,
    release_stale_coding_allocations,
)
from app.services.coder_workflow_service import (
    mark_reviewer_eligible_after_recode_window_submissions,
)
from app.services.final_cod_authority_service import (
    EPISODE_STATUS_ACTIVE,
    EPISODE_TYPE_RECODE,
    upsert_final_cod_authority,
)
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_REVIEWER_ELIGIBLE,
)
from app.services.workflow.state_store import (
    set_submission_workflow_state,
)
from tests.base import BaseTestCase


_RUN_SUFFIX = uuid.uuid4().hex[:4].upper()


class TestCodingAllocationService(BaseTestCase):
    BASE_PROJECT_ID = f"CD{_RUN_SUFFIX}"
    BASE_SITE_ID = f"S{_RUN_SUFFIX[:3]}"
    FORM_ID = f"F{_RUN_SUFFIX}000001"
    USER_EMAIL_SUFFIX = f"+codingalloc{_RUN_SUFFIX.lower()}"

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
                project_name="Legacy Test Project",
                project_nickname="LegacyBase",
                project_status=VaStatuses.active,
            )
        )
        db.session.commit()
        db.session.add(
            VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="Legacy Test Site",
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
                odk_form_id="TEST_FORM",
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

    def test_release_stale_coding_allocations_reverts_first_pass_artifacts(self):
        stale_sid = "uuid:stale"
        fresh_sid = "uuid:fresh"
        self._add_submission(stale_sid)
        self._add_submission(fresh_sid)
        db.session.flush()

        stale_allocation_id = uuid.uuid4()
        fresh_allocation_id = uuid.uuid4()

        db.session.add_all(
            [
                VaAllocations(
                    va_allocation_id=stale_allocation_id,
                    va_sid=stale_sid,
                    va_allocated_to=self.base_coder_user.user_id,
                    va_allocation_for=VaAllocation.coding,
                    va_allocation_status=VaStatuses.active,
                    va_allocation_createdat=datetime.now(timezone.utc)
                    - timedelta(hours=2),
                ),
                VaAllocations(
                    va_allocation_id=fresh_allocation_id,
                    va_sid=fresh_sid,
                    va_allocated_to=self.base_coder_user.user_id,
                    va_allocation_for=VaAllocation.coding,
                    va_allocation_status=VaStatuses.active,
                    va_allocation_createdat=datetime.now(timezone.utc)
                    - timedelta(minutes=15),
                ),
                VaInitialAssessments(
                    va_sid=stale_sid,
                    va_iniassess_by=self.base_coder_user.user_id,
                    va_immediate_cod="R99",
                    va_antecedent_cod="R99",
                    va_other_conditions=None,
                    va_iniassess_status=VaStatuses.active,
                ),
                VaNarrativeAssessment(
                    va_sid=stale_sid,
                    va_nqa_by=self.base_coder_user.user_id,
                    va_nqa_length=2,
                    va_nqa_pos_symptoms=2,
                    va_nqa_neg_symptoms=1,
                    va_nqa_chronology=1,
                    va_nqa_doc_review=1,
                    va_nqa_comorbidity=1,
                    va_nqa_score=8,
                    va_nqa_status=VaStatuses.active,
                ),
                VaSocialAutopsyAnalysis(
                    va_sid=stale_sid,
                    va_saa_by=self.base_coder_user.user_id,
                    va_saa_remark="first pass",
                    va_saa_status=VaStatuses.active,
                ),
            ]
        )
        db.session.commit()
        social_analysis = db.session.scalar(
            db.select(VaSocialAutopsyAnalysis).where(
                VaSocialAutopsyAnalysis.va_sid == stale_sid
            )
        )
        social_analysis.selected_options.append(
            VaSocialAutopsyAnalysisOption(
                delay_level="delay_1_decision",
                option_code="none",
            )
        )
        db.session.commit()

        released = release_stale_coding_allocations(timeout_hours=1)
        self.assertEqual(released, 1)

        stale_allocation = db.session.get(VaAllocations, stale_allocation_id)
        fresh_allocation = db.session.get(VaAllocations, fresh_allocation_id)
        initial_assessment = db.session.scalar(
            db.select(VaInitialAssessments).where(
                VaInitialAssessments.va_sid == stale_sid
            )
        )
        narrative_assessment = db.session.scalar(
            db.select(VaNarrativeAssessment).where(
                VaNarrativeAssessment.va_sid == stale_sid
            )
        )
        social_analysis = db.session.scalar(
            db.select(VaSocialAutopsyAnalysis).where(
                VaSocialAutopsyAnalysis.va_sid == stale_sid
            )
        )
        audit_log = db.session.scalar(
            db.select(VaSubmissionsAuditlog).where(
                VaSubmissionsAuditlog.va_sid == stale_sid,
                VaSubmissionsAuditlog.va_audit_action
                == "va_allocation_released_due_to_timeout",
            )
        )
        workflow = db.session.scalar(
            db.select(VaSubmissionWorkflow).where(
                VaSubmissionWorkflow.va_sid == stale_sid
            )
        )

        self.assertEqual(stale_allocation.va_allocation_status, VaStatuses.deactive)
        self.assertEqual(fresh_allocation.va_allocation_status, VaStatuses.active)
        self.assertIsNotNone(initial_assessment)
        self.assertEqual(initial_assessment.va_iniassess_status, VaStatuses.deactive)
        self.assertEqual(narrative_assessment.va_nqa_status, VaStatuses.deactive)
        self.assertEqual(social_analysis.va_saa_status, VaStatuses.deactive)
        self.assertIsNotNone(audit_log)
        self.assertIsNotNone(workflow)
        self.assertEqual(workflow.workflow_state, "ready_for_coding")

    def test_release_stale_coding_allocations_preserves_recode_analysis_artifacts(self):
        stale_sid = "uuid:recode"
        self._add_submission(stale_sid)
        db.session.flush()

        stale_allocation_id = uuid.uuid4()
        final_assessment = VaFinalAssessments(
            va_sid=stale_sid,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="R99",
            va_finassess_remark="final",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add(final_assessment)
        db.session.flush()

        db.session.add(
            VaCodingEpisode(
                episode_id=uuid.uuid4(),
                va_sid=stale_sid,
                episode_type=EPISODE_TYPE_RECODE,
                episode_status=EPISODE_STATUS_ACTIVE,
                started_by=self.base_coder_user.user_id,
                base_final_assessment_id=final_assessment.va_finassess_id,
            )
        )

        db.session.add_all(
            [
                VaAllocations(
                    va_allocation_id=stale_allocation_id,
                    va_sid=stale_sid,
                    va_allocated_to=self.base_coder_user.user_id,
                    va_allocation_for=VaAllocation.coding,
                    va_allocation_status=VaStatuses.active,
                    va_allocation_createdat=datetime.now(timezone.utc)
                    - timedelta(hours=2),
                ),
                VaInitialAssessments(
                    va_sid=stale_sid,
                    va_iniassess_by=self.base_coder_user.user_id,
                    va_immediate_cod="R99",
                    va_antecedent_cod="R99",
                    va_other_conditions=None,
                    va_iniassess_status=VaStatuses.active,
                ),
                VaNarrativeAssessment(
                    va_sid=stale_sid,
                    va_nqa_by=self.base_coder_user.user_id,
                    va_nqa_length=2,
                    va_nqa_pos_symptoms=2,
                    va_nqa_neg_symptoms=1,
                    va_nqa_chronology=1,
                    va_nqa_doc_review=1,
                    va_nqa_comorbidity=1,
                    va_nqa_score=8,
                    va_nqa_status=VaStatuses.active,
                ),
                VaSocialAutopsyAnalysis(
                    va_sid=stale_sid,
                    va_saa_by=self.base_coder_user.user_id,
                    va_saa_remark="recode",
                    va_saa_status=VaStatuses.active,
                ),
            ]
        )
        db.session.commit()
        social_analysis = db.session.scalar(
            db.select(VaSocialAutopsyAnalysis).where(
                VaSocialAutopsyAnalysis.va_sid == stale_sid
            )
        )
        social_analysis.selected_options.append(
            VaSocialAutopsyAnalysisOption(
                delay_level="delay_1_decision",
                option_code="none",
            )
        )
        db.session.commit()

        released = release_stale_coding_allocations(timeout_hours=1)

        self.assertEqual(released, 1)
        initial_assessment = db.session.scalar(
            db.select(VaInitialAssessments).where(
                VaInitialAssessments.va_sid == stale_sid
            )
        )
        narrative_assessment = db.session.scalar(
            db.select(VaNarrativeAssessment).where(
                VaNarrativeAssessment.va_sid == stale_sid
            )
        )
        social_analysis = db.session.scalar(
            db.select(VaSocialAutopsyAnalysis).where(
                VaSocialAutopsyAnalysis.va_sid == stale_sid
            )
        )
        workflow = db.session.scalar(
            db.select(VaSubmissionWorkflow).where(
                VaSubmissionWorkflow.va_sid == stale_sid
            )
        )
        recode_audit = db.session.scalar(
            db.select(VaSubmissionsAuditlog).where(
                VaSubmissionsAuditlog.va_sid == stale_sid,
                VaSubmissionsAuditlog.va_audit_action
                == "recode episode abandoned due to timeout",
            )
        )

        self.assertEqual(initial_assessment.va_iniassess_status, VaStatuses.deactive)
        self.assertEqual(narrative_assessment.va_nqa_status, VaStatuses.active)
        self.assertEqual(social_analysis.va_saa_status, VaStatuses.active)
        self.assertEqual(workflow.workflow_state, "coder_finalized")
        self.assertIsNotNone(recode_audit)

    def test_cleanup_expired_demo_coding_artifacts_deactivates_demo_records(self):
        stale_sid = "uuid:demo-expired"
        self._add_submission(stale_sid)
        db.session.flush()

        expired_at = datetime.now(timezone.utc) - timedelta(hours=7)
        final_assessment = VaFinalAssessments(
            va_sid=stale_sid,
            va_finassess_by=self.base_admin_user.user_id,
            va_conclusive_cod="R99",
            va_finassess_remark="demo final",
            va_finassess_status=VaStatuses.active,
            demo_expires_at=expired_at,
        )
        narrative = VaNarrativeAssessment(
            va_sid=stale_sid,
            va_nqa_by=self.base_admin_user.user_id,
            va_nqa_length=2,
            va_nqa_pos_symptoms=2,
            va_nqa_neg_symptoms=1,
            va_nqa_chronology=1,
            va_nqa_doc_review=1,
            va_nqa_comorbidity=1,
            va_nqa_score=8,
            va_nqa_status=VaStatuses.active,
            demo_expires_at=expired_at,
        )
        social = VaSocialAutopsyAnalysis(
            va_sid=stale_sid,
            va_saa_by=self.base_admin_user.user_id,
            va_saa_remark="demo social",
            va_saa_status=VaStatuses.active,
            demo_expires_at=expired_at,
        )
        db.session.add_all([final_assessment, narrative, social])
        db.session.flush()
        social.selected_options.append(
            VaSocialAutopsyAnalysisOption(
                delay_level="delay_1_decision",
                option_code="none",
            )
        )
        upsert_final_cod_authority(
            stale_sid,
            final_assessment,
            reason="final_cod_submitted",
            source_role="vacoder",
            updated_by=self.base_admin_user.user_id,
        )
        set_submission_workflow_state(
            stale_sid,
            WORKFLOW_CODER_FINALIZED,
            by_user_id=self.base_admin_user.user_id,
            by_role="vaadmin",
        )
        db.session.commit()

        expired = cleanup_expired_demo_coding_artifacts()

        self.assertEqual(expired, 3)
        stored_final = db.session.get(VaFinalAssessments, final_assessment.va_finassess_id)
        stored_narrative = db.session.get(VaNarrativeAssessment, narrative.va_nqa_id)
        stored_social = db.session.get(VaSocialAutopsyAnalysis, social.va_saa_id)
        authority = db.session.scalar(
            db.select(VaFinalCodAuthority).where(
                VaFinalCodAuthority.va_sid == stale_sid
            )
        )
        workflow = db.session.scalar(
            db.select(VaSubmissionWorkflow).where(
                VaSubmissionWorkflow.va_sid == stale_sid
            )
        )

        self.assertEqual(stored_final.va_finassess_status, VaStatuses.deactive)
        self.assertEqual(stored_narrative.va_nqa_status, VaStatuses.deactive)
        self.assertEqual(stored_social.va_saa_status, VaStatuses.deactive)
        self.assertIsNotNone(authority)
        self.assertIsNone(authority.authoritative_final_assessment_id)
        self.assertEqual(workflow.workflow_state, "ready_for_coding")

    def test_release_stale_coding_allocations_uses_shorter_timeout_for_demo_sessions(self):
        demo_project = VaProjectMaster(
            project_id="DMT015",
            project_code="DMT015",
            project_name="Demo Timeout Project",
            project_nickname="DemoTimeout",
            project_status=VaStatuses.active,
            demo_training_enabled=True,
            demo_retention_minutes=10,
        )
        db.session.add(demo_project)
        db.session.add(
            VaResearchProjects(
                project_id="DMT015",
                project_code="DMT015",
                project_name="Demo Timeout Project",
                project_nickname="DemoTimeout",
                project_status=VaStatuses.active,
            )
        )
        db.session.add(
            VaSiteMaster(
                site_id="DT01",
                site_name="Demo Timeout Site",
                site_abbr="DT01",
                site_status=VaStatuses.active,
            )
        )
        db.session.add(
            VaSites(
                site_id="DT01",
                project_id="DMT015",
                site_name="Demo Timeout Site",
                site_abbr="DT01",
                site_status=VaStatuses.active,
            )
        )
        db.session.flush()
        db.session.add(
            VaProjectSites(
                project_id="DMT015",
                site_id="DT01",
                project_site_status=VaStatuses.active,
            )
        )
        form = VaForms(
            form_id="DMT015DT0101",
            project_id="DMT015",
            site_id="DT01",
            odk_form_id="DEMO_TIMEOUT_FORM",
            odk_project_id="1",
            form_type="WHO VA 2022",
            form_status=VaStatuses.active,
        )
        db.session.add(form)
        db.session.flush()

        now = datetime.now(timezone.utc)
        sid = "uuid:test-demo-timeout"
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id=form.form_id,
                va_submission_date=now,
                va_odk_updatedat=now,
                va_data_collector="tester",
                va_instance_name="DEMO-TIMEOUT-1",
                va_uniqueid_real="DEMO-TIMEOUT-1",
                va_uniqueid_masked="DEMO-TIMEOUT-1",
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=40,
                va_deceased_gender="Male",
                va_data={},
                va_summary=[],
                va_catcount={},
                va_category_list=["vademographicdetails"],
            )
        )
        db.session.flush()
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=sid,
                workflow_state="coding_in_progress",
                workflow_reason="test_seed",
                workflow_updated_by_role="vasystem",
            )
        )
        event_time = now - timedelta(minutes=20)
        db.session.add(
            VaSubmissionWorkflowEvent(
                va_sid=sid,
                from_state="ready_for_coding",
                to_state="coding_in_progress",
                transition_id="demo_started",
                actor_kind="vacoder",
                actor_id=self.base_coder_user.user_id,
                reason="test_seed",
                event_created_at=event_time,
            )
        )
        allocation = VaAllocations(
            va_sid=sid,
            va_allocated_to=self.base_coder_user.user_id,
            va_allocation_for=VaAllocation.coding,
            va_allocation_status=VaStatuses.active,
            va_allocation_createdat=event_time,
        )
        db.session.add(allocation)
        db.session.commit()

        released = release_stale_coding_allocations(timeout_hours=1)

        self.assertEqual(released, 1)
        db.session.refresh(allocation)
        self.assertEqual(allocation.va_allocation_status, VaStatuses.deactive)

    def test_mark_reviewer_eligible_after_recode_window_submissions_transitions_old_finalized_cases(self):
        stale_sid = "uuid:close-expired"
        fresh_sid = "uuid:close-fresh"
        self._add_submission(stale_sid)
        self._add_submission(fresh_sid)
        db.session.flush()

        stale_final = VaFinalAssessments(
            va_sid=stale_sid,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="R99",
            va_finassess_status=VaStatuses.active,
        )
        fresh_final = VaFinalAssessments(
            va_sid=fresh_sid,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="R99",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add_all([stale_final, fresh_final])
        db.session.flush()

        stale_final.va_finassess_createdat = datetime.now(timezone.utc) - timedelta(days=2)
        upsert_final_cod_authority(
            stale_sid,
            stale_final,
            reason="test_authority",
            source_role="vacoder",
            updated_by=self.base_coder_user.user_id,
        )
        upsert_final_cod_authority(
            fresh_sid,
            fresh_final,
            reason="test_authority",
            source_role="vacoder",
            updated_by=self.base_coder_user.user_id,
        )
        set_submission_workflow_state(
            stale_sid,
            WORKFLOW_CODER_FINALIZED,
            reason="test_setup",
            by_user_id=self.base_coder_user.user_id,
            by_role="vacoder",
        )
        set_submission_workflow_state(
            fresh_sid,
            WORKFLOW_CODER_FINALIZED,
            reason="test_setup",
            by_user_id=self.base_coder_user.user_id,
            by_role="vacoder",
        )
        db.session.commit()

        transitioned = mark_reviewer_eligible_after_recode_window_submissions()

        self.assertEqual(transitioned, 1)
        self.assertEqual(
            db.session.scalar(
                db.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == stale_sid
                )
            ),
            WORKFLOW_REVIEWER_ELIGIBLE,
        )
        self.assertEqual(
            db.session.scalar(
                db.select(VaSubmissionWorkflow.workflow_state).where(
                    VaSubmissionWorkflow.va_sid == fresh_sid
                )
            ),
            WORKFLOW_CODER_FINALIZED,
        )

        event = db.session.scalar(
            db.select(VaSubmissionWorkflowEvent).where(
                VaSubmissionWorkflowEvent.va_sid == stale_sid,
                VaSubmissionWorkflowEvent.transition_id
                == "reviewer_eligible_after_recode_window",
            )
        )
        self.assertIsNotNone(event)
        self.assertEqual(event.previous_state, WORKFLOW_CODER_FINALIZED)
        self.assertEqual(event.current_state, WORKFLOW_REVIEWER_ELIGIBLE)

    def test_no_commit_path_when_nothing_is_stale(self):
        fresh_sid = "uuid:no_stale"
        self._add_submission(fresh_sid)
        db.session.flush()

        allocation_id = uuid.uuid4()
        db.session.add(
            VaAllocations(
                va_allocation_id=allocation_id,
                va_sid=fresh_sid,
                va_allocated_to=self.base_coder_user.user_id,
                va_allocation_for=VaAllocation.coding,
                va_allocation_status=VaStatuses.active,
                va_allocation_createdat=datetime.now(timezone.utc)
                - timedelta(minutes=10),
            )
        )
        db.session.commit()

        released = release_stale_coding_allocations(timeout_hours=1)

        self.assertEqual(released, 0)
        allocation = db.session.get(VaAllocations, allocation_id)
        self.assertEqual(allocation.va_allocation_status, VaStatuses.active)
