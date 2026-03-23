import uuid
from datetime import datetime, timezone

from app import db
from app.models import (
    VaFinalAssessments,
    VaForms,
    VaResearchProjects,
    VaReviewerFinalAssessments,
    VaSites,
    VaStatuses,
    VaSubmissions,
)
from app.services.reviewer_final_assessment_service import (
    create_reviewer_final_assessment,
    get_latest_active_reviewer_final_assessment,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from tests.base import BaseTestCase


_RUN_SUFFIX = uuid.uuid4().hex[:4].upper()


class TestReviewerFinalAssessmentService(BaseTestCase):
    BASE_PROJECT_ID = f"RF{_RUN_SUFFIX}"
    BASE_SITE_ID = f"S{_RUN_SUFFIX[:3]}"
    FORM_ID = f"R{_RUN_SUFFIX}000001"
    USER_EMAIL_SUFFIX = f"+reviewerfinal{_RUN_SUFFIX.lower()}"

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
                project_name="Reviewer Final Project",
                project_nickname="ReviewerFinal",
                project_status=VaStatuses.active,
            )
        )
        db.session.commit()
        db.session.add(
            VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="Reviewer Final Site",
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
                odk_form_id="REVIEWER_FINAL_FORM",
                odk_project_id="1",
                form_type="WHO_2022_VA",
                form_status=VaStatuses.active,
            )
        )
        db.session.commit()
        cls.base_reviewer_user = cls._make_user(
            "base.reviewer.final@test.local",
            "BaseReviewerFinal123",
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
            va_data={},
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(submission)
        db.session.flush()
        ensure_active_payload_version(
            submission,
            payload_data=submission.va_data or {},
            source_updated_at=submission.va_odk_updatedat,
        )
        db.session.commit()
        return submission

    def test_create_reviewer_final_assessment_preserves_coder_final(self):
        sid = "uuid:reviewer-final-coexist"
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

        reviewer_final = create_reviewer_final_assessment(
            va_sid=sid,
            reviewer_user_id=self.base_reviewer_user.user_id,
            conclusive_cod="I21",
            remark="reviewer final cod",
            supersedes_coder_final_assessment=coder_final,
        )
        db.session.commit()

        stored_reviewer = db.session.get(
            VaReviewerFinalAssessments, reviewer_final.va_rfinassess_id
        )
        stored_coder = db.session.get(VaFinalAssessments, coder_final.va_finassess_id)

        self.assertIsNotNone(stored_reviewer)
        self.assertEqual(stored_reviewer.va_sid, sid)
        self.assertEqual(
            stored_reviewer.payload_version_id,
            stored_coder.payload_version_id,
        )
        self.assertEqual(stored_reviewer.va_conclusive_cod, "I21")
        self.assertEqual(
            stored_reviewer.supersedes_coder_final_assessment_id,
            coder_final.va_finassess_id,
        )
        self.assertEqual(stored_coder.va_finassess_status, VaStatuses.active)

    def test_get_latest_active_reviewer_final_assessment_returns_newest_active(self):
        sid = "uuid:reviewer-final-latest"
        self._add_submission(sid)

        first = create_reviewer_final_assessment(
            va_sid=sid,
            reviewer_user_id=self.base_reviewer_user.user_id,
            conclusive_cod="A41",
            remark="first",
        )
        db.session.flush()
        second = create_reviewer_final_assessment(
            va_sid=sid,
            reviewer_user_id=self.base_reviewer_user.user_id,
            conclusive_cod="I21",
            remark="second",
        )
        db.session.commit()

        latest = get_latest_active_reviewer_final_assessment(sid)

        self.assertEqual(latest.va_rfinassess_id, second.va_rfinassess_id)
        self.assertNotEqual(latest.va_rfinassess_id, first.va_rfinassess_id)

    def test_create_reviewer_final_assessment_rejects_cross_submission_supersede_link(self):
        sid_one = "uuid:reviewer-final-one"
        sid_two = "uuid:reviewer-final-two"
        submission_one = self._add_submission(sid_one)
        self._add_submission(sid_two)

        coder_final = VaFinalAssessments(
            va_sid=sid_one,
            payload_version_id=submission_one.active_payload_version_id,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="R99",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add(coder_final)
        db.session.commit()

        with self.assertRaises(ValueError):
            create_reviewer_final_assessment(
                va_sid=sid_two,
                reviewer_user_id=self.base_reviewer_user.user_id,
                conclusive_cod="I21",
                supersedes_coder_final_assessment=coder_final,
            )
