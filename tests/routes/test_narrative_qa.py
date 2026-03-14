from datetime import datetime, timezone
import uuid

from app import db
from app.models import (
    VaForms,
    VaNarrativeAssessment,
    VaProjectMaster,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
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
        project = db.session.get(VaProjectMaster, cls.BASE_PROJECT_ID)
        project.narrative_qa_enabled = True
        db.session.add(
            VaResearchProjects(
                project_id=cls.BASE_PROJECT_ID,
                project_code=cls.BASE_PROJECT_ID,
                project_name="Narrative QA Legacy Project",
                project_nickname="NarrativeQALegacy",
                project_status=VaStatuses.active,
                project_registered_at=datetime.now(timezone.utc),
                project_updated_at=datetime.now(timezone.utc),
            )
        )
        db.session.add(
            VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="Narrative QA Legacy Site",
                site_abbr=cls.BASE_SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=datetime.now(timezone.utc),
                site_updated_at=datetime.now(timezone.utc),
            )
        )
        db.session.flush()

        form = VaForms(
            form_id=f"{cls.BASE_PROJECT_ID}{cls.BASE_SITE_ID}01",
            project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID,
            odk_form_id="NQA_FORM",
            odk_project_id="1",
            form_type="WHO 2022 VA",
            form_status=VaStatuses.active,
            form_registered_at=datetime.now(timezone.utc),
            form_updated_at=datetime.now(timezone.utc),
        )
        db.session.add(form)

        submission = VaSubmissions(
            va_sid=f"uuid:test-nqa-{cls.BASE_PROJECT_ID.lower()}{cls.BASE_SITE_ID.lower()}01",
            va_form_id=form.form_id,
            va_submission_date=datetime.now(timezone.utc),
            va_odk_updatedat=datetime.now(timezone.utc),
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name="NQA-1",
            va_uniqueid_real="NQA-1",
            va_uniqueid_masked="NQA-1",
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=60,
            va_deceased_gender="Male",
            va_data={},
            va_summary=[],
            va_catcount={},
            va_category_list=["vanarrationanddocuments"],
        )
        db.session.add(submission)
        db.session.commit()
        cls.sid = submission.va_sid

    def test_save_nqa_creates_assessment_and_audit_entry(self):
        self._login(self.base_admin_id)
        response = self.client.post(
            f"/vaapi/vacode/vademo_start_coding/{self.sid}/narrative-qa",
            json={
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

        audit = db.session.scalar(
            db.select(VaSubmissionsAuditlog).where(
                VaSubmissionsAuditlog.va_sid == self.sid,
                VaSubmissionsAuditlog.va_audit_action
                == "narrative quality assessment saved",
            )
        )
        self.assertIsNotNone(audit)
