import uuid
from datetime import datetime, timedelta, timezone

from app import db
from app.models import (
    VaCoderReview,
    VaFinalAssessments,
    VaForms,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissions,
)
from app.services.coder_dashboard_service import (
    get_coder_completed_count,
    get_coder_completed_history,
    get_coder_recodeable_sids,
)
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_READY_FOR_CODING,
)
from app.services.workflow.state_store import (
    set_submission_workflow_state,
)
from tests.base import BaseTestCase


_RUN_SUFFIX = uuid.uuid4().hex[:4].upper()


class TestCoderDashboardService(BaseTestCase):
    BASE_PROJECT_ID = f"CD{_RUN_SUFFIX}"
    BASE_SITE_ID = f"C{_RUN_SUFFIX[:3]}"
    FORM_ID = f"C{_RUN_SUFFIX}000001"
    OTHER_FORM_ID = f"C{_RUN_SUFFIX}000002"
    USER_EMAIL_SUFFIX = f"+coderdash{_RUN_SUFFIX.lower()}"

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
                project_name="Coder Dashboard Project",
                project_nickname="CoderDash",
                project_status=VaStatuses.active,
            )
        )
        db.session.commit()
        db.session.add(
            VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="Coder Dashboard Site",
                site_abbr=cls.BASE_SITE_ID,
                site_status=VaStatuses.active,
            )
        )
        db.session.commit()
        db.session.add_all(
            [
                VaForms(
                    form_id=cls.FORM_ID,
                    project_id=cls.BASE_PROJECT_ID,
                    site_id=cls.BASE_SITE_ID,
                    odk_form_id="CODER_DASHBOARD_FORM",
                    odk_project_id="1",
                    form_type="WHO_2022_VA",
                    form_status=VaStatuses.active,
                ),
                VaForms(
                    form_id=cls.OTHER_FORM_ID,
                    project_id=cls.BASE_PROJECT_ID,
                    site_id=cls.BASE_SITE_ID,
                    odk_form_id="CODER_DASHBOARD_OTHER",
                    odk_project_id="1",
                    form_type="WHO_2022_VA",
                    form_status=VaStatuses.active,
                ),
            ]
        )
        db.session.commit()

    def _add_submission(self, sid: str, form_id: str | None = None):
        now = datetime.now(timezone.utc)
        db.session.add(
            VaSubmissions(
                va_sid=sid,
                va_form_id=form_id or self.FORM_ID,
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
        )
        db.session.commit()

    def test_completed_count_uses_canonical_workflow_state(self):
        final_sid = "uuid:coderdash-final"
        review_sid = "uuid:coderdash-review"
        ready_sid = "uuid:coderdash-ready"

        self._add_submission(final_sid)
        self._add_submission(review_sid)
        self._add_submission(ready_sid)

        db.session.add(
            VaFinalAssessments(
                va_sid=final_sid,
                va_finassess_by=self.base_coder_user.user_id,
                va_conclusive_cod="R99",
                va_finassess_status=VaStatuses.active,
            )
        )
        db.session.add(
            VaCoderReview(
                va_sid=review_sid,
                va_creview_by=self.base_coder_user.user_id,
                va_creview_reason="form_is_empty",
                va_creview_other=None,
                va_creview_status=VaStatuses.active,
            )
        )
        db.session.commit()

        set_submission_workflow_state(
            final_sid,
            WORKFLOW_CODER_FINALIZED,
            by_user_id=self.base_coder_user.user_id,
            by_role="vacoder",
        )
        set_submission_workflow_state(
            review_sid,
            WORKFLOW_NOT_CODEABLE_BY_CODER,
            by_user_id=self.base_coder_user.user_id,
            by_role="vacoder",
        )
        set_submission_workflow_state(
            ready_sid,
            WORKFLOW_READY_FOR_CODING,
            by_user_id=self.base_coder_user.user_id,
            by_role="vacoder",
        )
        db.session.commit()

        self.assertEqual(
            get_coder_completed_count(self.base_coder_user.user_id, [self.FORM_ID]),
            2,
        )

    def test_completed_history_uses_workflow_state_to_label_rows(self):
        final_sid = "uuid:coderdash-history-final"
        review_sid = "uuid:coderdash-history-review"

        self._add_submission(final_sid)
        self._add_submission(review_sid)

        final_row = VaFinalAssessments(
            va_sid=final_sid,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="R99",
            va_finassess_status=VaStatuses.active,
        )
        review_row = VaCoderReview(
            va_sid=review_sid,
            va_creview_by=self.base_coder_user.user_id,
            va_creview_reason="form_is_empty",
            va_creview_other=None,
            va_creview_status=VaStatuses.active,
        )
        db.session.add_all([final_row, review_row])
        db.session.commit()

        set_submission_workflow_state(
            final_sid,
            WORKFLOW_CODER_FINALIZED,
            by_user_id=self.base_coder_user.user_id,
            by_role="vacoder",
        )
        set_submission_workflow_state(
            review_sid,
            WORKFLOW_NOT_CODEABLE_BY_CODER,
            by_user_id=self.base_coder_user.user_id,
            by_role="vacoder",
        )
        db.session.commit()

        rows = get_coder_completed_history(
            self.base_coder_user.user_id,
            [self.FORM_ID],
        )
        labels = {row["va_sid"]: row["va_code_status"] for row in rows}
        row_by_sid = {row["va_sid"]: row for row in rows}

        self.assertEqual(labels[final_sid], "VA Coding Completed")
        self.assertEqual(labels[review_sid], "Not Codeable")
        self.assertEqual(row_by_sid[final_sid]["project_id"], self.BASE_PROJECT_ID)
        self.assertEqual(row_by_sid[final_sid]["site_id"], self.BASE_SITE_ID)

    def test_recodeable_sids_require_recent_matching_terminal_state(self):
        recent_final_sid = "uuid:coderdash-recode-final"
        old_review_sid = "uuid:coderdash-recode-review"
        mismatched_sid = "uuid:coderdash-recode-mismatch"

        self._add_submission(recent_final_sid)
        self._add_submission(old_review_sid)
        self._add_submission(mismatched_sid)

        recent_final = VaFinalAssessments(
            va_sid=recent_final_sid,
            va_finassess_by=self.base_coder_user.user_id,
            va_conclusive_cod="R99",
            va_finassess_status=VaStatuses.active,
        )
        old_review = VaCoderReview(
            va_sid=old_review_sid,
            va_creview_by=self.base_coder_user.user_id,
            va_creview_reason="form_is_empty",
            va_creview_other=None,
            va_creview_status=VaStatuses.active,
        )
        mismatched_review = VaCoderReview(
            va_sid=mismatched_sid,
            va_creview_by=self.base_coder_user.user_id,
            va_creview_reason="form_is_empty",
            va_creview_other=None,
            va_creview_status=VaStatuses.active,
        )
        db.session.add_all([recent_final, old_review, mismatched_review])
        db.session.commit()

        old_review.va_creview_createdat = datetime.now(timezone.utc) - timedelta(days=2)
        db.session.commit()

        set_submission_workflow_state(
            recent_final_sid,
            WORKFLOW_CODER_FINALIZED,
            by_user_id=self.base_coder_user.user_id,
            by_role="vacoder",
        )
        set_submission_workflow_state(
            old_review_sid,
            WORKFLOW_NOT_CODEABLE_BY_CODER,
            by_user_id=self.base_coder_user.user_id,
            by_role="vacoder",
        )
        set_submission_workflow_state(
            mismatched_sid,
            WORKFLOW_CODER_FINALIZED,
            by_user_id=self.base_coder_user.user_id,
            by_role="vacoder",
        )
        db.session.commit()

        recodeable = get_coder_recodeable_sids(
            self.base_coder_user.user_id,
            [self.FORM_ID],
        )

        self.assertIn(recent_final_sid, recodeable)
        self.assertNotIn(old_review_sid, recodeable)
        self.assertNotIn(mismatched_sid, recodeable)
