from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
import uuid

from app import db
from app.models import VaForms, VaResearchProjects, VaSites, VaStatuses, VaSubmissions
from app.services.odk_review_service import (
    ODK_REVIEW_STATE_HAS_ISSUES,
    build_not_codeable_review_comment,
    mark_submission_needs_revision,
    resolve_odk_instance_id,
    sync_not_codeable_review_state,
)
from tests.base import BaseTestCase


_RUN_SUFFIX = uuid.uuid4().hex[:4].upper()


class TestOdkReviewService(BaseTestCase):
    BASE_PROJECT_ID = f"OR{_RUN_SUFFIX}"
    BASE_SITE_ID = f"R{_RUN_SUFFIX[:3]}"
    FORM_ID = f"O{_RUN_SUFFIX}000001"

    @classmethod
    def _make_user(cls, email, password):
        local_part, domain = email.split("@", 1)
        return super()._make_user(f"{local_part}+odkr{_RUN_SUFFIX.lower()}@{domain}", password)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db.session.add(
            VaResearchProjects(
                project_id=cls.BASE_PROJECT_ID,
                project_code=cls.BASE_PROJECT_ID,
                project_name="ODK Review Legacy Project",
                project_nickname="ODKReviewLegacy",
                project_status=VaStatuses.active,
                project_registered_at=datetime.now(timezone.utc),
                project_updated_at=datetime.now(timezone.utc),
            )
        )
        db.session.commit()
        db.session.add(
            VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="ODK Review Legacy Site",
                site_abbr=cls.BASE_SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=datetime.now(timezone.utc),
                site_updated_at=datetime.now(timezone.utc),
            )
        )
        db.session.commit()
        db.session.add(
            VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_id=cls.BASE_SITE_ID,
                odk_form_id="TEST_ODK_FORM",
                odk_project_id="11",
                form_type="WHO_2022_VA",
                form_status=VaStatuses.active,
            )
        )
        db.session.commit()

    def test_build_not_codeable_review_comment(self):
        comment = build_not_codeable_review_comment(
            "narration_language",
            "Audio is only in an unsupported language.",
        )
        self.assertIn("not codeable", comment.lower())
        self.assertIn("Narrative language is not readable by the coder.", comment)
        self.assertIn("Audio is only in an unsupported language.", comment)

    def test_build_not_codeable_review_comment_for_data_manager(self):
        comment = build_not_codeable_review_comment(
            "duplicate_submission",
            "Duplicate of another household record.",
            actor_role="data_manager",
        )
        self.assertIn("data manager marked this submission as not codeable", comment)
        self.assertIn("This appears to be a duplicate submission.", comment)
        self.assertIn("Duplicate of another household record.", comment)

    def test_resolve_odk_instance_id_strips_local_form_suffix(self):
        self.assertEqual(
            resolve_odk_instance_id(
                "uuid:b2b35c80-4634-4bd1-bb1b-ba5f19dd288a-icmr01nc0201"
            ),
            "uuid:b2b35c80-4634-4bd1-bb1b-ba5f19dd288a",
        )

    def test_mark_submission_needs_revision_calls_odk_review(self):
        instance_id = "uuid:b2b35c80-4634-4bd1-bb1b-ba5f19dd288a"
        sid = f"{instance_id}-{self.FORM_ID.lower()}"
        submission = VaSubmissions(
            va_sid=sid,
            va_form_id=self.FORM_ID,
            va_submission_date=datetime.now(timezone.utc),
            va_odk_updatedat=datetime.now(timezone.utc),
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name=sid,
            va_uniqueid_real=sid,
            va_uniqueid_masked=sid,
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=50,
            va_deceased_gender="male",
            va_data={},
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(submission)
        db.session.commit()

        fake_client = MagicMock()
        with patch("app.services.odk_review_service.va_odk_clientsetup", return_value=fake_client):
            review_state, comment = mark_submission_needs_revision(
                sid,
                "no_info",
                "No symptom detail present.",
            )

        self.assertEqual(review_state, ODK_REVIEW_STATE_HAS_ISSUES)
        self.assertIn("No symptom detail present.", comment)
        fake_client.submissions.review.assert_called_once_with(
            instance_id=instance_id,
            review_state=ODK_REVIEW_STATE_HAS_ISSUES,
            form_id="TEST_ODK_FORM",
            project_id=11,
            comment=comment,
        )
        refreshed = db.session.get(VaSubmissions, sid)
        self.assertEqual(refreshed.va_odk_reviewstate, ODK_REVIEW_STATE_HAS_ISSUES)

    def test_sync_not_codeable_review_state_returns_success_result(self):
        sid = f"uuid:test-odk-sync-ok-{_RUN_SUFFIX.lower()}"
        submission = VaSubmissions(
            va_sid=sid,
            va_form_id=self.FORM_ID,
            va_submission_date=datetime.now(timezone.utc),
            va_odk_updatedat=datetime.now(timezone.utc),
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name=sid,
            va_uniqueid_real=sid,
            va_uniqueid_masked=sid,
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=50,
            va_deceased_gender="male",
            va_data={},
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(submission)
        db.session.commit()

        fake_client = MagicMock()
        with patch("app.services.odk_review_service.va_odk_clientsetup", return_value=fake_client):
            result = sync_not_codeable_review_state(
                sid,
                "form_is_empty",
                None,
            )

        self.assertTrue(result.success)
        self.assertEqual(result.review_state, ODK_REVIEW_STATE_HAS_ISSUES)
        self.assertIsNotNone(result.comment)
        self.assertIsNone(result.error_message)

    def test_sync_not_codeable_review_state_supports_data_manager_actor(self):
        sid = f"uuid:test-odk-sync-dm-{_RUN_SUFFIX.lower()}"
        submission = VaSubmissions(
            va_sid=sid,
            va_form_id=self.FORM_ID,
            va_submission_date=datetime.now(timezone.utc),
            va_odk_updatedat=datetime.now(timezone.utc),
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name=sid,
            va_uniqueid_real=sid,
            va_uniqueid_masked=sid,
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=50,
            va_deceased_gender="male",
            va_data={},
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(submission)
        db.session.commit()

        fake_client = MagicMock()
        with patch("app.services.odk_review_service.va_odk_clientsetup", return_value=fake_client):
            result = sync_not_codeable_review_state(
                sid,
                "duplicate_submission",
                "Duplicate in site register.",
                actor_role="data_manager",
            )

        self.assertTrue(result.success)
        self.assertIn("data manager marked this submission as not codeable", result.comment)
        self.assertIn("Duplicate in site register.", result.comment)

    def test_sync_not_codeable_review_state_returns_failure_result(self):
        sid = f"uuid:test-odk-sync-fail-{_RUN_SUFFIX.lower()}"
        submission = VaSubmissions(
            va_sid=sid,
            va_form_id=self.FORM_ID,
            va_submission_date=datetime.now(timezone.utc),
            va_odk_updatedat=datetime.now(timezone.utc),
            va_data_collector="tester",
            va_odk_reviewstate=None,
            va_instance_name=sid,
            va_uniqueid_real=sid,
            va_uniqueid_masked=sid,
            va_consent="yes",
            va_narration_language="English",
            va_deceased_age=50,
            va_deceased_gender="male",
            va_data={},
            va_summary=[],
            va_catcount={},
            va_category_list=[],
        )
        db.session.add(submission)
        db.session.commit()

        with patch(
            "app.services.odk_review_service.va_odk_clientsetup",
            side_effect=RuntimeError("Central unavailable"),
        ):
            result = sync_not_codeable_review_state(
                sid,
                "no_info",
                None,
            )

        self.assertFalse(result.success)
        self.assertEqual(result.error_message, "Central unavailable")
