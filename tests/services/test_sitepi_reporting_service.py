import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    VaFinalAssessments,
    VaFinalCodAuthority,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaReviewerFinalAssessments,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissionWorkflowEvent,
    VaSubmissions,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaUserAccessGrants,
)
from app.services.coding.authority.final_cod import (
    upsert_final_cod_authority,
    upsert_reviewer_final_cod_authority,
)
from app.services.reporting.sitepi import get_sitepi_dashboard_data
from app.services.workflow.definition import (
    TRANSITION_ADMIN_OVERRIDE_TO_RECODE,
    TRANSITION_CODER_FINALIZED,
    TRANSITION_RECODE_FINALIZED,
    TRANSITION_RECODE_STARTED,
    TRANSITION_REVIEWER_CODING_STARTED,
    TRANSITION_REVIEWER_FINALIZED,
    TRANSITION_UPSTREAM_CHANGE_ACCEPTED,
    TRANSITION_UPSTREAM_CHANGE_DETECTED,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
)
from tests.base import BaseTestCase


class SitePiReportingServiceTests(BaseTestCase):
    BASE_PROJECT_ID = "BSPIP1"
    BASE_SITE_ID = "BSP1"
    FORM_ID = "BSPIFORM01"
    OTHER_PROJECT_ID = "BSPIO2"
    OTHER_FORM_ID = "BSPIFORM02"

    def setUp(self):
        super().setUp()
        sitepi_sids = list(
            db.session.scalars(
                sa.select(VaSubmissions.va_sid).where(VaSubmissions.va_sid.like("uuid:sitepi-%"))
            ).all()
        )
        if sitepi_sids:
            db.session.execute(
                sa.delete(VaFinalCodAuthority).where(VaFinalCodAuthority.va_sid.in_(sitepi_sids))
            )
            db.session.execute(
                sa.delete(VaReviewerFinalAssessments).where(
                    VaReviewerFinalAssessments.va_sid.in_(sitepi_sids)
                )
            )
            db.session.execute(
                sa.delete(VaFinalAssessments).where(VaFinalAssessments.va_sid.in_(sitepi_sids))
            )
            db.session.execute(
                sa.delete(VaSubmissionWorkflowEvent).where(
                    VaSubmissionWorkflowEvent.va_sid.in_(sitepi_sids)
                )
            )
            db.session.execute(
                sa.delete(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid.in_(sitepi_sids))
            )
            db.session.execute(
                sa.delete(VaSubmissions).where(VaSubmissions.va_sid.in_(sitepi_sids))
            )
            db.session.flush()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        project_site = cls._ensure_project_site_fixture(
            project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID,
            project_name="Base Reporting Project",
            project_nickname="BaseReporting",
            site_name="Base Reporting Site",
        )
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="SITE_PI_FORM",
                odk_project_id="1",
                form_type="WHO_2022_VA",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.add(
            VaUserAccessGrants(
                user_id=cls.base_coder_user.user_id,
                role=VaAccessRoles.coder,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site.project_site_id,
                notes="site pi reporting coder fixture grant",
                grant_status=VaStatuses.active,
            )
        )
        db.session.add(
            VaResearchProjects(
                project_id=cls.OTHER_PROJECT_ID,
                project_code=cls.OTHER_PROJECT_ID,
                project_name="Other Reporting Project",
                project_nickname="OtherReporting",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.add(
            VaProjectMaster(
                project_id=cls.OTHER_PROJECT_ID,
                project_code=cls.OTHER_PROJECT_ID,
                project_name="Other Reporting Project",
                project_nickname="OtherReporting",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaForms(
                form_id=cls.OTHER_FORM_ID,
                project_id=cls.OTHER_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="SITE_PI_FORM_OTHER",
                odk_project_id="2",
                form_type="WHO_2022_VA",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            )
        )
        db.session.add(
            VaProjectSites(
                project_id=cls.OTHER_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                project_site_status=VaStatuses.active,
            )
        )
        db.session.commit()

    def _add_submission(self, sid: str, workflow_state: str) -> None:
        self._add_submission_for_form(sid, self.FORM_ID, workflow_state)

    def _add_submission_for_form(self, sid: str, form_id: str, workflow_state: str) -> None:
        now = datetime.now(timezone.utc)
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id=form_id,
                va_submission_date=now,
                va_odk_updatedat=now,
                va_data_collector="sitepi",
                va_instance_name=sid,
                va_uniqueid_real=sid,
                va_uniqueid_masked=sid,
                va_consent="yes",
                va_narration_language="English",
                va_deceased_age=42,
                va_deceased_gender="male",
                va_summary=[],
                va_catcount={},
                va_category_list=[],
            )
        )
        db.session.flush()
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=sid,
                workflow_state=workflow_state,
                workflow_reason="test",
                workflow_updated_by_role="vasystem",
            )
        )
        db.session.flush()

    def _add_event(
        self,
        sid: str,
        transition_id: str,
        previous_state: str | None,
        current_state: str,
        *,
        minutes_ago: int = 0,
    ) -> None:
        db.session.add(
            VaSubmissionWorkflowEvent(
                va_sid=sid,
                transition_id=transition_id,
                previous_state=previous_state,
                current_state=current_state,
                actor_kind="system",
                actor_role="vasystem",
                event_created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
            )
        )

    def test_sitepi_dashboard_data_reports_workflow_outcomes_and_cycles(self):
        reviewer_user = self._make_user(
            "reviewer.sitepi@test.local",
            "ReviewerSitePi123",
        )

        sid_reviewer_eligible = "uuid:sitepi-reviewer-eligible"
        sid_reviewer_finalized = "uuid:sitepi-reviewer-finalized"
        sid_upstream = "uuid:sitepi-upstream"
        sid_not_codeable = "uuid:sitepi-not-codeable"

        self._add_submission(sid_reviewer_eligible, WORKFLOW_REVIEWER_ELIGIBLE)
        self._add_submission(sid_reviewer_finalized, WORKFLOW_REVIEWER_FINALIZED)
        self._add_submission(sid_upstream, WORKFLOW_FINALIZED_UPSTREAM_CHANGED)
        self._add_submission(sid_not_codeable, WORKFLOW_NOT_CODEABLE_BY_CODER)

        coder_final_1 = VaFinalAssessments(
            va_sid=sid_reviewer_eligible,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="I21-Acute myocardial infarction",
            va_finassess_status=VaStatuses.active,
        )
        coder_final_2 = VaFinalAssessments(
            va_sid=sid_reviewer_finalized,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="I21-Acute myocardial infarction",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add_all([coder_final_1, coder_final_2])
        db.session.flush()

        upsert_final_cod_authority(
            sid_reviewer_eligible,
            coder_final_1,
            reason="sitepi_test",
            source_role="vacoder",
            updated_by=self.base_coder_user.user_id,
        )
        upsert_final_cod_authority(
            sid_reviewer_finalized,
            coder_final_2,
            reason="sitepi_test",
            source_role="vacoder",
            updated_by=self.base_coder_user.user_id,
        )

        reviewer_final = VaReviewerFinalAssessments(
            va_sid=sid_reviewer_finalized,
            va_rfinassess_by=reviewer_user.user_id,
            va_conclusive_cod="J18-Pneumonia, unspecified organism",
            supersedes_coder_final_assessment_id=coder_final_2.va_finassess_id,
            va_rfinassess_status=VaStatuses.active,
        )
        db.session.add(reviewer_final)
        db.session.flush()
        upsert_reviewer_final_cod_authority(
            sid_reviewer_finalized,
            reviewer_final,
            reason="sitepi_test_reviewer",
            updated_by=reviewer_user.user_id,
        )

        self._add_event(
            sid_reviewer_eligible,
            TRANSITION_CODER_FINALIZED,
            WORKFLOW_READY_FOR_CODING,
            "coder_finalized",
            minutes_ago=30,
        )
        self._add_event(
            sid_reviewer_eligible,
            TRANSITION_RECODE_STARTED,
            "coder_finalized",
            "coding_in_progress",
            minutes_ago=20,
        )
        self._add_event(
            sid_reviewer_eligible,
            TRANSITION_RECODE_FINALIZED,
            "coding_in_progress",
            "coder_finalized",
            minutes_ago=10,
        )
        self._add_event(
            sid_reviewer_finalized,
            TRANSITION_CODER_FINALIZED,
            WORKFLOW_READY_FOR_CODING,
            "coder_finalized",
            minutes_ago=40,
        )
        self._add_event(
            sid_reviewer_finalized,
            TRANSITION_REVIEWER_CODING_STARTED,
            WORKFLOW_REVIEWER_ELIGIBLE,
            "reviewer_coding_in_progress",
            minutes_ago=5,
        )
        self._add_event(
            sid_reviewer_finalized,
            TRANSITION_REVIEWER_FINALIZED,
            "reviewer_coding_in_progress",
            WORKFLOW_REVIEWER_FINALIZED,
            minutes_ago=1,
        )
        self._add_event(
            sid_upstream,
            TRANSITION_UPSTREAM_CHANGE_DETECTED,
            "coder_finalized",
            WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
            minutes_ago=15,
        )
        self._add_event(
            sid_upstream,
            TRANSITION_UPSTREAM_CHANGE_ACCEPTED,
            WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
            "smartva_pending",
            minutes_ago=14,
        )
        self._add_event(
            sid_upstream,
            TRANSITION_ADMIN_OVERRIDE_TO_RECODE,
            "coder_finalized",
            WORKFLOW_READY_FOR_CODING,
            minutes_ago=13,
        )
        db.session.commit()

        project_site_id = db.session.scalar(
            sa.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == self.BASE_PROJECT_ID,
                VaProjectSites.site_id == self.BASE_SITE_ID,
            )
        )
        data = get_sitepi_dashboard_data(project_site_id)

        self.assertEqual(data["total_submissions"], 4)
        self.assertEqual(data["total_coded"], 2)
        self.assertEqual(data["total_not_codeable"], 1)
        self.assertEqual(data["current_state_kpis"]["reviewer_eligible"], 1)
        self.assertEqual(data["current_state_kpis"]["reviewer_finalized"], 1)
        self.assertEqual(data["current_state_kpis"]["post_coder_complete"], 2)
        self.assertEqual(data["current_state_kpis"]["upstream_changed"], 1)
        self.assertEqual(data["authority_kpis"]["coder_authority"], 1)
        self.assertEqual(data["authority_kpis"]["reviewer_authority"], 1)
        self.assertEqual(data["cycle_kpis"]["admin_resets"], 1)
        self.assertEqual(data["cycle_kpis"]["upstream_changes"], 1)
        self.assertEqual(data["cycle_kpis"]["upstream_accepts"], 1)
        self.assertEqual(data["cycle_kpis"]["recode_started"], 1)
        self.assertEqual(data["cycle_kpis"]["recode_finalized"], 1)
        self.assertEqual(data["cycle_kpis"]["reviewer_started"], 1)
        self.assertEqual(data["cycle_kpis"]["reviewer_finalized"], 1)

        by_sid = {row["va_sid"]: row for row in data["submission_rows"]}
        self.assertEqual(by_sid[sid_reviewer_eligible]["authority_source"], "coder")
        self.assertEqual(by_sid[sid_reviewer_eligible]["recode_started_count"], 1)
        self.assertEqual(by_sid[sid_reviewer_eligible]["recode_finalized_count"], 1)
        self.assertEqual(by_sid[sid_reviewer_finalized]["authority_source"], "reviewer")
        self.assertEqual(by_sid[sid_reviewer_finalized]["reviewer_finalized_count"], 1)
        self.assertEqual(by_sid[sid_upstream]["admin_reset_count"], 1)
        self.assertEqual(by_sid[sid_upstream]["upstream_change_count"], 1)
        self.assertEqual(by_sid[sid_upstream]["upstream_accept_count"], 1)

        coder_row = next(row for row in data["coder_kpis"] if row["coder_name"] == self.base_coder_user.name)
        self.assertEqual(coder_row["total_done"], 2)

    def test_sitepi_dashboard_data_is_scoped_to_project_site(self):
        self._add_submission("uuid:sitepi-base", WORKFLOW_READY_FOR_CODING)
        self._add_submission_for_form(
            "uuid:sitepi-other-project",
            self.OTHER_FORM_ID,
            WORKFLOW_REVIEWER_FINALIZED,
        )
        db.session.commit()

        project_site_id = db.session.scalar(
            sa.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == self.BASE_PROJECT_ID,
                VaProjectSites.site_id == self.BASE_SITE_ID,
            )
        )

        data = get_sitepi_dashboard_data(project_site_id)

        self.assertEqual(data["total_submissions"], 1)
        self.assertEqual({row["va_sid"] for row in data["submission_rows"]}, {"uuid:sitepi-base"})
