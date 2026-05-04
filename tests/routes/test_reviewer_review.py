from datetime import datetime, timezone
import uuid

from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaForms,
    VaNarrativeAssessment,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaReviewerReview,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUserAccessGrants,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaFinalAssessments,
    VaFinalCodAuthority,
    VaReviewerInitialAssessments,
    VaReviewerFinalAssessments,
    MasIcd1020192,
    MasCategoryDisplayConfig,
    MasFormTypes,
)
from app.services.reviewer_coding_service import submit_reviewer_final_cod
from app.services.reviewer_coding_service import submit_reviewer_initial_cod
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.workflow.definition import WORKFLOW_REVIEWER_CODING_IN_PROGRESS
from tests.base import BaseTestCase


class TestReviewerReviewRoute(BaseTestCase):
    _RUN_SUFFIX = uuid.uuid4().hex[:4].upper()
    BASE_PROJECT_ID = f"RR{_RUN_SUFFIX}"
    BASE_SITE_ID = _RUN_SUFFIX

    @classmethod
    def _make_user(cls, email, password):
        local_part, domain = email.split("@", 1)
        scoped_email = f"{local_part}.{cls.BASE_PROJECT_ID.lower()}@{domain}"
        return super()._make_user(scoped_email, password)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)

        project = db.session.get(VaProjectMaster, cls.BASE_PROJECT_ID)
        if project is not None:
            project.narrative_qa_enabled = False
        site_master = db.session.get(VaSiteMaster, cls.BASE_SITE_ID)
        if site_master is None:
            db.session.add(
                VaSiteMaster(
                    site_id=cls.BASE_SITE_ID,
                    site_name="Reviewer Review Site",
                    site_abbr=cls.BASE_SITE_ID,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )
        research_project = db.session.get(VaResearchProjects, cls.BASE_PROJECT_ID)
        if research_project is None:
            db.session.add(
                VaResearchProjects(
                    project_id=cls.BASE_PROJECT_ID,
                    project_code=cls.BASE_PROJECT_ID,
                    project_name="Reviewer Review Project",
                    project_nickname="ReviewerReview",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                )
            )
        site = db.session.scalar(
            db.select(VaSites).where(
                VaSites.site_id == cls.BASE_SITE_ID,
                VaSites.project_id == cls.BASE_PROJECT_ID,
            )
        )
        if site is None:
            db.session.add(
                VaSites(
                    site_id=cls.BASE_SITE_ID,
                    project_id=cls.BASE_PROJECT_ID,
                    site_name="Reviewer Review Site",
                    site_abbr=cls.BASE_SITE_ID,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )

        project_site = db.session.scalar(
            db.select(VaProjectSites).where(
                VaProjectSites.project_id == cls.BASE_PROJECT_ID,
                VaProjectSites.site_id == cls.BASE_SITE_ID,
            )
        )
        if project_site is None:
            project_site = VaProjectSites(
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                project_site_status=VaStatuses.active,
                project_site_registered_at=now,
                project_site_updated_at=now,
            )
            db.session.add(project_site)
        db.session.flush()
        cls.project_site_id = project_site.project_site_id

        form_type = MasFormTypes(
            form_type_id=uuid.uuid4(),
            form_type_code=f"REVIEWER_REVIEW_{cls.BASE_PROJECT_ID}",
            form_type_name="Reviewer Review Test Form",
            is_active=True,
        )
        db.session.add(form_type)
        db.session.flush()
        db.session.add(
            MasCategoryDisplayConfig(
                form_type_id=form_type.form_type_id,
                category_code="vanarrationanddocuments",
                display_label="Narration / Documents / COD",
                nav_label="Narration / Documents / COD",
                icon_name="fa-file-medical-alt",
                display_order=1,
                render_mode="attachments",
                show_to_coder=True,
                show_to_reviewer=True,
                show_to_site_pi_datamanager=True,
                always_include=True,
                is_default_start=True,
                is_active=True,
            )
        )

        reviewer = cls._make_user("reviewer@test.local", "Reviewer123")
        reviewer.landing_page = "reviewer"
        db.session.add(
            VaUserAccessGrants(
                user_id=reviewer.user_id,
                role=VaAccessRoles.reviewer,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site.project_site_id,
                grant_status=VaStatuses.active,
            )
        )

        form = VaForms(
            form_id=f"{cls.BASE_PROJECT_ID}{cls.BASE_SITE_ID}01",
            project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID,
            odk_form_id="REVIEW_FORM",
            odk_project_id="1",
            form_type_id=form_type.form_type_id,
            form_type=form_type.form_type_code,
            form_status=VaStatuses.active,
            form_registered_at=now,
            form_updated_at=now,
        )
        db.session.add(form)

        submission = VaSubmissions(
            va_sid=f"uuid:test-reviewer-review-{cls.BASE_PROJECT_ID.lower()}",
            va_form_id=form.form_id,
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name="REVIEW-1",
            va_uniqueid_real="REVIEW-1",
            va_uniqueid_masked="REVIEW-1",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=55,
            va_deceased_gender="Female",
            va_summary=[],
            va_catcount={},
            va_category_list=["vanarrationanddocuments"],
        )
        db.session.add(submission)
        db.session.flush()

        ensure_active_payload_version(
            submission,
            payload_data={
                "narr_language": "English",
                "Id10476": "Narrative text",
            },
            source_updated_at=submission.va_odk_updatedat,
            created_by_role="vasystem",
        )
        db.session.add(
            VaSubmissionWorkflow(
                va_sid=submission.va_sid,
                workflow_state=WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
                workflow_created_at=now,
                workflow_updated_at=now,
            )
        )
        db.session.commit()

        cls.reviewer_user = reviewer
        cls.sid = submission.va_sid

    def setUp(self):
        super().setUp()
        self._login(str(self.reviewer_user.user_id))
        now = datetime.now(timezone.utc)
        db.session.add(
            VaAllocations(
                va_sid=self.sid,
                va_allocated_to=self.reviewer_user.user_id,
                va_allocation_for=VaAllocation.reviewing,
                va_allocation_status=VaStatuses.active,
                va_allocation_createdat=now,
                va_allocation_updatedat=now,
            )
        )
        db.session.commit()

    def _post_review(self, **overrides):
        payload = {
            "va_rreview_narrpos": "3_5_symptoms",
            "va_rreview_narrneg": "present",
            "va_rreview_narrchrono": "can_be_established",
            "va_rreview_narrdoc": "provides_data",
            "va_rreview_narrcomorb": "present",
            "va_rreview": "accepted",
            "va_rreview_fail": "",
            "va_rreview_remark": "review ok",
        }
        payload.update(overrides)
        headers = self._csrf_headers()
        headers["HX-Request"] = "true"
        return self.client.post(
            f"/vaform/{self.sid}/vareviewform?action=vareview&actiontype=varesumereviewing",
            data=payload,
            headers=headers,
        )

    def _ensure_selectable_icd(self, code, title):
        row = db.session.get(MasIcd1020192, code)
        if row is None:
            row = MasIcd1020192(
                code=code,
                title=title,
                node_type="code",
                semantic_level="three_character",
                sort_order=0,
                three_character_code=code,
                three_character_title=title,
                has_children=False,
                is_leaf=True,
                is_three_character_code=True,
                is_detailed_code=False,
                source_version="test",
                policy_status="allowed",
            )
            db.session.add(row)
        row.is_active = True
        row.is_coding_selectable = True
        row.sex_selectable = "both"
        row.age_group_selectable = "all"
        return row

    def test_reviewer_narration_section_keeps_nested_qa_swap_local(self):
        response = self.client.get(
            f"/vaform/{self.sid}/vanarrationanddocuments"
            "?action=vareview&actiontype=varesumereviewing"
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("NARRATION / DOCUMENTS / COD", body)
        self.assertIn("Narrative text", body)
        self.assertIn("Assign COD", body)
        self.assertNotIn("vareviewform?action=vareview", body)

    def test_reviewer_narration_section_uses_shared_nqa_form(self):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.narrative_qa_enabled = True
        db.session.commit()

        response = self.client.get(
            f"/vaform/{self.sid}/vanarrationanddocuments"
            "?action=vareview&actiontype=varesumereviewing"
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn("Narrative Quality Assessment", body)
        self.assertIn("Q1. Length of Narrative", body)
        self.assertIn("Q6. Comorbidities / Risk Factors", body)
        self.assertIn("/api/v1/va/", body)
        self.assertNotIn("Does the VA form have any serious issues", body)
        self.assertNotIn("therefore should not be allocated to VA coders", body)

    def test_reviewer_can_save_shared_nqa_with_active_reviewing_allocation(self):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.narrative_qa_enabled = True
        db.session.commit()

        response = self.client.post(
            f"/api/v1/va/{self.sid}/narrative-qa",
            json={
                "va_actiontype": "varesumereviewing",
                "length": 2,
                "pos_symptoms": 2,
                "neg_symptoms": 1,
                "chronology": 1,
                "doc_review": 1,
                "comorbidity": 1,
            },
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200)
        nqa = db.session.scalar(
            db.select(VaNarrativeAssessment).where(
                VaNarrativeAssessment.va_sid == self.sid,
                VaNarrativeAssessment.va_nqa_by == self.reviewer_user.user_id,
                VaNarrativeAssessment.va_nqa_status == VaStatuses.active,
            )
        )
        self.assertIsNotNone(nqa)
        self.assertEqual(nqa.va_nqa_score, 8)
        audit = db.session.scalar(
            db.select(VaSubmissionsAuditlog).where(
                VaSubmissionsAuditlog.va_sid == self.sid,
                VaSubmissionsAuditlog.va_audit_action
                == "narrative quality assessment saved",
            )
        )
        self.assertIsNotNone(audit)
        self.assertEqual(audit.va_audit_byrole, "reviewer")

    def test_reviewer_nqa_save_requires_active_reviewing_allocation(self):
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.narrative_qa_enabled = True
        db.session.execute(
            db.update(VaAllocations)
            .where(
                VaAllocations.va_sid == self.sid,
                VaAllocations.va_allocated_to == self.reviewer_user.user_id,
                VaAllocations.va_allocation_for == VaAllocation.reviewing,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
            .values(va_allocation_status=VaStatuses.deactive)
        )
        db.session.commit()

        response = self.client.post(
            f"/api/v1/va/{self.sid}/narrative-qa",
            json={
                "va_actiontype": "varesumereviewing",
                "length": 2,
                "pos_symptoms": 2,
                "neg_symptoms": 1,
                "chronology": 1,
                "doc_review": 1,
                "comorbidity": 1,
            },
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.get_json()["error"],
            "Active reviewer allocation required.",
        )

    def test_save_reviewer_review_creates_payload_bound_row(self):
        response = self._post_review()
        self.assertEqual(response.status_code, 200)

        review = db.session.scalar(
            db.select(VaReviewerReview).where(
                VaReviewerReview.va_sid == self.sid,
                VaReviewerReview.va_rreview_by == self.reviewer_user.user_id,
                VaReviewerReview.va_rreview_status == VaStatuses.active,
            )
        )
        self.assertIsNotNone(review)
        self.assertIsNotNone(review.payload_version_id)
        self.assertEqual(review.va_rreview, "accepted")

        audit = db.session.scalar(
            db.select(VaSubmissionsAuditlog).where(
                VaSubmissionsAuditlog.va_sid == self.sid,
                VaSubmissionsAuditlog.va_audit_action == "reviewer review saved",
            )
        )
        self.assertIsNotNone(audit)

    def test_save_after_payload_change_creates_new_current_payload_row(self):
        response = self._post_review()
        self.assertEqual(response.status_code, 200)

        submission = db.session.get(VaSubmissions, self.sid)
        first_payload_version_id = submission.active_payload_version_id

        submission.va_odk_updatedat = datetime.now(timezone.utc)
        new_payload_version = ensure_active_payload_version(
            submission,
            payload_data={"field": "two"},
            source_updated_at=submission.va_odk_updatedat,
            created_by_role="vasystem",
        )
        db.session.commit()

        response = self._post_review(va_rreview_remark="review updated")
        self.assertEqual(response.status_code, 200)

        rows = db.session.scalars(
            db.select(VaReviewerReview)
            .where(
                VaReviewerReview.va_sid == self.sid,
                VaReviewerReview.va_rreview_by == self.reviewer_user.user_id,
            )
            .order_by(VaReviewerReview.va_rreview_createdat.asc())
        ).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].payload_version_id, first_payload_version_id)
        self.assertEqual(rows[0].va_rreview_status, VaStatuses.deactive)
        self.assertEqual(rows[1].payload_version_id, new_payload_version.payload_version_id)
        self.assertEqual(rows[1].va_rreview_status, VaStatuses.active)

    def test_reviewer_final_cod_preserves_coder_final_cod_row_and_authority_pointer(self):
        submission = db.session.get(VaSubmissions, self.sid)
        project = db.session.get(VaProjectMaster, self.BASE_PROJECT_ID)
        project.reviewer_social_autopsy_enabled = False
        self._ensure_selectable_icd("I10", "Essential Hypertension")
        self._ensure_selectable_icd("I21", "Acute myocardial infarction")
        self._ensure_selectable_icd("R99", "Other ill-defined and unspecified causes")
        coder_user = self._make_user("coder@test.local", "Coder123")
        db.session.flush()

        coder_final = VaFinalAssessments(
            va_sid=self.sid,
            payload_version_id=submission.active_payload_version_id,
            va_finassess_by=coder_user.user_id,
            va_conclusive_cod="I10 - Essential Hypertension",
            va_finassess_remark="Coder final COD",
        )
        db.session.add(coder_final)
        db.session.flush()
        db.session.add(
            VaFinalCodAuthority(
                va_sid=self.sid,
                authoritative_final_assessment_id=coder_final.va_finassess_id,
                authority_source_role="vacoder",
                authority_reason="final_cod_submitted",
                updated_by=coder_user.user_id,
            )
        )
        db.session.commit()

        reviewer_initial = submit_reviewer_initial_cod(
            self.reviewer_user,
            self.sid,
            immediate_cod="I10 - Essential Hypertension",
            antecedent_cod="R99 - Other ill-defined and unspecified causes",
            other_conditions="Reviewer other condition",
        )
        reviewer_final = submit_reviewer_final_cod(
            self.reviewer_user,
            self.sid,
            conclusive_cod="I21-Acute myocardial infarction",
            remark="Reviewer final COD",
        )

        db.session.refresh(coder_final)
        authority = db.session.scalar(
            db.select(VaFinalCodAuthority).where(
                VaFinalCodAuthority.va_sid == self.sid
            )
        )
        reviewer_rows = db.session.scalars(
            db.select(VaReviewerFinalAssessments).where(
                VaReviewerFinalAssessments.va_sid == self.sid
            )
        ).all()
        reviewer_initial_rows = db.session.scalars(
            db.select(VaReviewerInitialAssessments).where(
                VaReviewerInitialAssessments.va_sid == self.sid
            )
        ).all()

        self.assertEqual(coder_final.va_finassess_status, VaStatuses.active)
        self.assertEqual(coder_final.va_conclusive_cod, "I10 - Essential Hypertension")
        self.assertEqual(len(reviewer_initial_rows), 1)
        self.assertEqual(
            reviewer_initial_rows[0].va_riniassess_id,
            reviewer_initial.va_riniassess_id,
        )
        self.assertEqual(len(reviewer_rows), 1)
        self.assertEqual(reviewer_rows[0].va_rfinassess_id, reviewer_final.va_rfinassess_id)
        self.assertEqual(
            reviewer_rows[0].supersedes_coder_final_assessment_id,
            coder_final.va_finassess_id,
        )
        self.assertEqual(
            reviewer_rows[0].source_reviewer_initial_assessment_id,
            reviewer_initial.va_riniassess_id,
        )
        self.assertEqual(authority.authoritative_final_assessment_id, coder_final.va_finassess_id)
        self.assertEqual(
            authority.authoritative_reviewer_final_assessment_id,
            reviewer_final.va_rfinassess_id,
        )
