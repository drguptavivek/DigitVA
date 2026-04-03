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
from app.services.final_cod_authority_service import (
    EPISODE_STATUS_ABANDONED,
    EPISODE_STATUS_COMPLETED,
    get_authoritative_final_cod_record,
    get_active_recode_episode,
    get_authoritative_final_assessment,
    start_recode_episode,
    complete_recode_episode,
    abandon_active_recode_episode,
    upsert_final_cod_authority,
    upsert_reviewer_final_cod_authority,
)
from app.services.submission_payload_version_service import ensure_active_payload_version
from tests.base import BaseTestCase


_RUN_SUFFIX = uuid.uuid4().hex[:4].upper()


class TestFinalCodAuthorityService(BaseTestCase):
    BASE_PROJECT_ID = f"FA{_RUN_SUFFIX}"
    BASE_SITE_ID = f"F{_RUN_SUFFIX[:3]}"
    FORM_ID = f"F{_RUN_SUFFIX}000001"
    USER_EMAIL_SUFFIX = f"+finalauth{_RUN_SUFFIX.lower()}"

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
                project_name="Final Authority Project",
                project_nickname="FinalAuthority",
                project_status=VaStatuses.active,
            )
        )
        db.session.commit()
        db.session.add(
            VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="Final Authority Site",
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
                odk_form_id="FINAL_AUTHORITY_FORM",
                odk_project_id="1",
                form_type="WHO_2022_VA",
                form_status=VaStatuses.active,
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

    def test_authority_prefers_explicit_authority_row(self):
        sid = "uuid:final-authority"
        submission = self._add_submission(sid)

        final_one = VaFinalAssessments(
            va_sid=sid,
            payload_version_id=submission.active_payload_version_id,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="R99",
            va_finassess_status=VaStatuses.active,
        )
        final_two = VaFinalAssessments(
            va_sid=sid,
            payload_version_id=submission.active_payload_version_id,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="I21",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add_all([final_one, final_two])
        db.session.flush()
        upsert_final_cod_authority(
            sid,
            final_two,
            reason="test_authority",
            source_role="vacoder",
            updated_by=self.base_coder_user.user_id,
        )
        db.session.commit()

        authoritative = get_authoritative_final_assessment(sid)

        self.assertEqual(authoritative.va_finassess_id, final_two.va_finassess_id)
        self.assertEqual(authoritative.va_conclusive_cod, "I21")

    def test_recode_episode_lifecycle(self):
        sid = "uuid:recode-episode"
        submission = self._add_submission(sid)

        final_row = VaFinalAssessments(
            va_sid=sid,
            payload_version_id=submission.active_payload_version_id,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="R99",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add(final_row)
        db.session.commit()

        episode = start_recode_episode(
            sid,
            self.base_coder_user.user_id,
            base_final_assessment=final_row,
        )
        db.session.commit()

        self.assertEqual(get_active_recode_episode(sid).episode_id, episode.episode_id)

        replacement = VaFinalAssessments(
            va_sid=sid,
            payload_version_id=submission.active_payload_version_id,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="I21",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add(replacement)
        db.session.flush()
        complete_recode_episode(episode, replacement)
        db.session.commit()

        self.assertIsNone(get_active_recode_episode(sid))
        self.assertEqual(episode.episode_status, EPISODE_STATUS_COMPLETED)
        self.assertEqual(
            episode.replacement_final_assessment_id,
            replacement.va_finassess_id,
        )

    def test_authoritative_final_cod_record_prefers_reviewer_final(self):
        sid = "uuid:reviewer-authority"
        submission = self._add_submission(sid)

        coder_final = VaFinalAssessments(
            va_sid=sid,
            payload_version_id=submission.active_payload_version_id,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="R99",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add(coder_final)
        db.session.flush()
        upsert_final_cod_authority(
            sid,
            coder_final,
            reason="coder_final_cod_submitted",
            source_role="vacoder",
            updated_by=self.base_coder_user.user_id,
        )

        reviewer_final = VaReviewerFinalAssessments(
            va_sid=sid,
            payload_version_id=submission.active_payload_version_id,
            va_rfinassess_by=self.base_admin_user.user_id,
            va_conclusive_cod="I21",
            va_rfinassess_remark="reviewer cod",
            supersedes_coder_final_assessment_id=coder_final.va_finassess_id,
            va_rfinassess_status=VaStatuses.active,
        )
        db.session.add(reviewer_final)
        db.session.flush()
        upsert_reviewer_final_cod_authority(
            sid,
            reviewer_final,
            reason="reviewer_final_cod_submitted",
            updated_by=self.base_admin_user.user_id,
        )
        db.session.commit()

        record = get_authoritative_final_cod_record(sid)

        self.assertEqual(record.source_role, "reviewer")
        self.assertEqual(record.va_conclusive_cod, "I21")
        self.assertEqual(record.reviewer_final_assessment_id, reviewer_final.va_rfinassess_id)
        self.assertEqual(record.coder_final_assessment_id, coder_final.va_finassess_id)

    def test_authority_ignores_stale_payload_version_rows(self):
        sid = "uuid:stale-payload-authority"
        submission = self._add_submission(sid)
        old_payload_version_id = submission.active_payload_version_id

        stale_final = VaFinalAssessments(
            va_sid=sid,
            payload_version_id=old_payload_version_id,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="R99",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add(stale_final)
        db.session.flush()
        upsert_final_cod_authority(
            sid,
            stale_final,
            reason="stale_test_setup",
            source_role="vacoder",
            updated_by=self.base_coder_user.user_id,
        )

        submission.va_odk_updatedat = datetime.now(timezone.utc)
        ensure_active_payload_version(
            submission,
            payload_data={"updated": True},
            source_updated_at=submission.va_odk_updatedat,
        )
        db.session.flush()

        fresh_final = VaFinalAssessments(
            va_sid=sid,
            payload_version_id=submission.active_payload_version_id,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="I21",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add(fresh_final)
        db.session.commit()

        authoritative = get_authoritative_final_assessment(sid)
        record = get_authoritative_final_cod_record(sid)

        self.assertEqual(authoritative.va_finassess_id, fresh_final.va_finassess_id)
        self.assertEqual(record.coder_final_assessment_id, fresh_final.va_finassess_id)
        self.assertEqual(record.payload_version_id, submission.active_payload_version_id)

    def test_abandon_active_recode_episode(self):
        sid = "uuid:recode-abandon"
        submission = self._add_submission(sid)

        final_row = VaFinalAssessments(
            va_sid=sid,
            payload_version_id=submission.active_payload_version_id,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="R99",
            va_finassess_status=VaStatuses.active,
        )
        db.session.add(final_row)
        db.session.commit()

        episode = start_recode_episode(
            sid,
            self.base_coder_user.user_id,
            base_final_assessment=final_row,
        )
        db.session.commit()

        changed = abandon_active_recode_episode(
            sid,
            by_role="vasystem",
            by_user_id=self.base_admin_user.user_id,
        )
        db.session.commit()

        self.assertTrue(changed)
        self.assertEqual(episode.episode_status, EPISODE_STATUS_ABANDONED)
        self.assertIsNone(get_active_recode_episode(sid))
