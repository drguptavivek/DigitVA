import uuid
from datetime import datetime, timedelta, timezone

from app import db
from app.models import (
    VaAllocations,
    VaAllocation,
    VaForms,
    VaInitialAssessments,
    VaResearchProjects,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
from app.services.coding_allocation_service import release_stale_coding_allocations
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

    def test_release_stale_coding_allocations_preserves_initial_assessment(self):
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
            ]
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
        self.assertEqual(initial_assessment.va_iniassess_status, VaStatuses.active)
        self.assertIsNotNone(audit_log)
        self.assertIsNotNone(workflow)
        self.assertEqual(workflow.workflow_state, "coder_step1_saved")

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
