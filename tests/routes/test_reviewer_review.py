from datetime import datetime, timezone
import uuid

from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaForms,
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
)
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
            form_type="WHO 2022 VA",
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
            va_data={"field": "one"},
            va_summary=[],
            va_catcount={},
            va_category_list=["vanarrationanddocuments"],
        )
        db.session.add(submission)
        db.session.flush()

        ensure_active_payload_version(
            submission,
            payload_data=submission.va_data,
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

        submission.va_data = {"field": "two"}
        submission.va_odk_updatedat = datetime.now(timezone.utc)
        new_payload_version = ensure_active_payload_version(
            submission,
            payload_data=submission.va_data,
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
