from datetime import datetime, timezone
import uuid

from flask import Response

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocation,
    VaAllocations,
    VaForms,
    VaNarrativeAssessment,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUserAccessGrants,
)
from app.routes.va_form import _apply_partial_cache_policy
from app.services.submission_payload_version_service import ensure_active_payload_version
from tests.base import BaseTestCase


class TestNarrativeQaRoute(BaseTestCase):
    _RUN_SUFFIX = uuid.uuid4().hex[:4].upper()
    BASE_PROJECT_ID = f"NQ{_RUN_SUFFIX}"
    BASE_SITE_ID = f"Q{_RUN_SUFFIX[:3]}"
    @classmethod
    def _make_user(cls, email, password):
        local_part, domain = email.split("@", 1)
        scoped_email = f"{local_part}.{cls.BASE_PROJECT_ID.lower()}@{domain}"
        return super()._make_user(scoped_email, password)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        cls._ensure_project_site_fixture(
            project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID,
            project_name="Narrative QA Legacy Project",
            project_nickname="NarrativeQALegacy",
            site_name="Narrative QA Legacy Site",
            create_research_project=True,
            now=now,
        )
        project = db.session.get(VaProjectMaster, cls.BASE_PROJECT_ID)
        project.narrative_qa_enabled = True
        form = cls._ensure_form_fixture(
            form_id=f"{cls.BASE_PROJECT_ID}{cls.BASE_SITE_ID}01",
            project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID,
            odk_form_id="NQA_FORM",
            odk_project_id="1",
            form_type="WHO 2022 VA",
            now=now,
        )

        submission = VaSubmissions(
            va_sid=f"uuid:test-nqa-{cls.BASE_PROJECT_ID.lower()}{cls.BASE_SITE_ID.lower()}01",
            va_form_id=form.form_id,
            va_submission_date=now,
            va_odk_updatedat=now,
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name="NQA-1",
            va_uniqueid_real="NQA-1",
            va_uniqueid_masked="NQA-1",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=60,
            va_deceased_gender="Male",
            va_summary=[],
            va_catcount={},
            va_category_list=["vanarrationanddocuments"],
        )
        db.session.add(submission)
        db.session.flush()
        ensure_active_payload_version(
            submission,
            payload_data={"sid": submission.va_sid},
            source_updated_at=submission.va_odk_updatedat,
            created_by_role="vasystem",
        )
        project_site_id = db.session.scalar(
            db.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == cls.BASE_PROJECT_ID,
                VaProjectSites.site_id == cls.BASE_SITE_ID,
            )
        )
        cls.reviewer_user = cls._make_user(
            "nqa.reviewer@test.local",
            "NqaReviewer123",
        )
        db.session.add(
            VaUserAccessGrants(
                user_id=cls.reviewer_user.user_id,
                role=VaAccessRoles.reviewer,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=project_site_id,
                notes="nqa reviewer grant",
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()
        cls.sid = submission.va_sid
        cls.reviewer_id = str(cls.reviewer_user.user_id)

    def test_save_nqa_creates_assessment_and_audit_entry(self):
        self._login(self.base_admin_id)
        response = self.client.post(
            f"/api/v1/va/{self.sid}/narrative-qa",
            json={
                "va_actiontype": "vademo_start_coding",
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
                VaNarrativeAssessment.va_nqa_by == self.base_admin_user.user_id,
            )
        )
        self.assertIsNotNone(nqa)
        self.assertEqual(nqa.va_nqa_score, 8)
        self.assertIsNotNone(nqa.payload_version_id)

        audit = db.session.scalar(
            db.select(VaSubmissionsAuditlog).where(
                VaSubmissionsAuditlog.va_sid == self.sid,
                VaSubmissionsAuditlog.va_audit_action
                == "narrative quality assessment saved",
            )
        )
        self.assertIsNotNone(audit)

    def test_save_after_payload_change_creates_new_current_payload_row(self):
        self._login(self.base_admin_id)
        payload = {
            "va_actiontype": "vademo_start_coding",
            "length": 2,
            "pos_symptoms": 2,
            "neg_symptoms": 1,
            "chronology": 1,
            "doc_review": 1,
            "comorbidity": 1,
        }
        response = self.client.post(
            f"/api/v1/va/{self.sid}/narrative-qa",
            json=payload,
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)

        submission = db.session.get(VaSubmissions, self.sid)
        first_payload_version_id = submission.active_payload_version_id

        submission.va_odk_updatedat = datetime.now(timezone.utc)
        new_payload_version = ensure_active_payload_version(
            submission,
            payload_data={"changed": True},
            source_updated_at=submission.va_odk_updatedat,
            created_by_role="vasystem",
        )
        db.session.commit()

        response = self.client.post(
            f"/api/v1/va/{self.sid}/narrative-qa",
            json={**payload, "length": 3},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)

        rows = db.session.scalars(
            db.select(VaNarrativeAssessment)
            .where(
                VaNarrativeAssessment.va_sid == self.sid,
                VaNarrativeAssessment.va_nqa_by == self.base_admin_user.user_id,
            )
            .order_by(VaNarrativeAssessment.va_nqa_createdat.asc())
        ).all()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0].payload_version_id, first_payload_version_id)
        self.assertEqual(rows[0].va_nqa_status, VaStatuses.deactive)
        self.assertEqual(rows[1].payload_version_id, new_payload_version.payload_version_id)
        self.assertEqual(rows[1].va_nqa_status, VaStatuses.active)

    def test_reviewer_can_save_nqa_with_active_reviewing_allocation(self):
        self._login(self.reviewer_id)
        db.session.add(
            VaAllocations(
                va_sid=self.sid,
                va_allocated_to=self.reviewer_user.user_id,
                va_allocation_for=VaAllocation.reviewing,
                va_allocation_status=VaStatuses.active,
            )
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

        self.assertEqual(response.status_code, 200)

    def test_narration_partial_is_not_http_cached_in_coding_mode(self):
        response = _apply_partial_cache_policy(
            Response("ok", status=200),
            "vanarrationanddocuments",
            "vacode",
        )

        self.assertEqual(response.status_code, 200)
        cache_control = response.headers.get("Cache-Control", "")
        self.assertIn("private", cache_control)
        self.assertIn("no-store", cache_control)
