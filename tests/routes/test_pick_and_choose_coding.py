from datetime import datetime, timedelta, timezone

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocations,
    VaAllocation,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissions,
    VaUserAccessGrants,
)
from tests.base import BaseTestCase


class PickAndChooseCodingRouteTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_pick_and_random_projects()

    @classmethod
    def _seed_pick_and_random_projects(cls):
        now = datetime.now(timezone.utc)
        fixtures = [
            ("PCK01", "PC01", "PCK01PC0101", "sid-pick-1", "pick_and_choose"),
            (
                "RND01",
                "RN01",
                "RND01RN0101",
                "sid-random-1",
                "random_form_allocation",
            ),
        ]

        for project_id, site_id, form_id, sid, intake_mode in fixtures:
            db.session.add(
                VaProjectMaster(
                    project_id=project_id,
                    project_code=project_id,
                    project_name=f"Project {project_id}",
                    project_nickname=project_id,
                    coding_intake_mode=intake_mode,
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                )
            )
            db.session.add(
                VaResearchProjects(
                    project_id=project_id,
                    project_code=project_id,
                    project_name=f"Project {project_id}",
                    project_nickname=project_id,
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                )
            )
            db.session.add(
                VaSiteMaster(
                    site_id=site_id,
                    site_name=f"Site {site_id}",
                    site_abbr=site_id,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )
            db.session.add(
                VaSites(
                    site_id=site_id,
                    project_id=project_id,
                    site_name=f"Site {site_id}",
                    site_abbr=site_id,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                )
            )
            db.session.flush()
            db.session.add(
                VaProjectSites(
                    project_id=project_id,
                    site_id=site_id,
                    project_site_status=VaStatuses.active,
                    project_site_registered_at=now,
                    project_site_updated_at=now,
                    coding_enabled=True,
                    coding_start_date=None,
                    coding_end_date=None,
                    daily_coder_limit=100,
                )
            )
            db.session.add(
                VaForms(
                    form_id=form_id,
                    project_id=project_id,
                    site_id=site_id,
                    odk_form_id=f"FORM_{project_id}",
                    odk_project_id="11",
                    form_type="WHO VA 2022",
                    form_status=VaStatuses.active,
                    form_registered_at=now,
                    form_updated_at=now,
                )
            )
            db.session.add(
                VaSubmissions(
                    va_sid=sid,
                    va_form_id=form_id,
                    va_submission_date=now,
                    va_odk_updatedat=now,
                    va_data_collector="Collector",
                    va_odk_reviewstate=None,
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
                    workflow_state="ready_for_coding",
                    workflow_reason="test_seed",
                    workflow_updated_by_role="vasystem",
                )
            )

        db.session.flush()

        for project_id, site_id in [("PCK01", "PC01"), ("RND01", "RN01")]:
            project_site_id = db.session.scalar(
                db.select(VaProjectSites.project_site_id).where(
                    VaProjectSites.project_id == project_id,
                    VaProjectSites.site_id == site_id,
                )
            )
            db.session.add(
                VaUserAccessGrants(
                    user_id=cls.base_coder_user.user_id,
                    role=VaAccessRoles.coder,
                    scope_type=VaAccessScopeTypes.project_site,
                    project_site_id=project_site_id,
                    notes=f"coder grant {project_id}",
                    grant_status=VaStatuses.active,
                )
            )

        cls.coding_tester_user = cls._make_user(
            "pick.tester@test.local",
            "PickTester123",
        )
        tester_project_site_id = db.session.scalar(
            db.select(VaProjectSites.project_site_id).where(
                VaProjectSites.project_id == "RND01",
                VaProjectSites.site_id == "RN01",
            )
        )
        db.session.add(
            VaUserAccessGrants(
                user_id=cls.coding_tester_user.user_id,
                role=VaAccessRoles.coding_tester,
                scope_type=VaAccessScopeTypes.project_site,
                project_site_id=tester_project_site_id,
                notes="coding tester grant RND01",
                grant_status=VaStatuses.active,
            )
        )
        db.session.commit()
        cls.coding_tester_id = str(cls.coding_tester_user.user_id)

    def setUp(self):
        super().setUp()
        db.session.query(VaAllocations).filter(
            VaAllocations.va_allocated_to == self.base_coder_user.user_id,
            VaAllocations.va_allocation_for == VaAllocation.coding,
        ).update(
            {"va_allocation_status": VaStatuses.deactive},
            synchronize_session=False,
        )
        db.session.commit()

    def _active_coding_sid(self):
        return db.session.scalar(
            db.select(VaAllocations.va_sid).where(
                VaAllocations.va_allocated_to == self.base_coder_user.user_id,
                VaAllocations.va_allocation_for == VaAllocation.coding,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        )

    def test_dashboard_shows_pick_and_choose_section(self):
        self._login(self.base_coder_id)

        response = self.client.get("/coding/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Random Allocation Submissions Available", response.data)
        self.assertIn(b"Selection Based Submissions Available", response.data)
        self.assertIn(b"Start Random Allocation Coding", response.data)
        self.assertIn(b"Pick And Choose Coding", response.data)
        self.assertIn(b'id="pick-section"', response.data)
        self.assertIn(b'id="pickCodingTable"', response.data)

    def test_startcoding_uses_only_random_projects(self):
        self._login(self.base_coder_id)
        project_site = db.session.scalar(
            db.select(VaProjectSites).where(
                VaProjectSites.project_id == "RND01",
                VaProjectSites.site_id == "RN01",
            )
        )
        project_site.coding_enabled = True
        project_site.coding_start_date = None
        project_site.coding_end_date = None
        project_site.daily_coder_limit = 100
        db.session.query(VaAllocations).filter(
            VaAllocations.va_allocated_to == self.base_coder_user.user_id,
            VaAllocations.va_allocation_for == VaAllocation.coding,
        ).update(
            {"va_allocation_status": VaStatuses.deactive},
            synchronize_session=False,
        )
        db.session.commit()

        response = self.client.post(
            "/coding/start",
            headers=self._csrf_headers(),
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._active_coding_sid(), "sid-random-1")

    def test_pickcoding_allocates_selected_ready_submission(self):
        self._login(self.base_coder_id)

        response = self.client.post(
            "/coding/pick/sid-pick-1",
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._active_coding_sid(), "sid-pick-1")
        workflow_state = db.session.scalar(
            db.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == "sid-pick-1"
            )
        )
        self.assertEqual(workflow_state, "coding_in_progress")

    def test_pickcoding_post_resumes_same_active_submission(self):
        workflow = db.session.scalar(
            db.select(VaSubmissionWorkflow).where(
                VaSubmissionWorkflow.va_sid == "sid-pick-1"
            )
        )
        workflow.workflow_state = "ready_for_coding"
        workflow.workflow_reason = "test_reset"
        db.session.commit()

        self._login(self.base_coder_id)

        first_response = self.client.post(
            "/coding/pick/sid-pick-1",
            headers=self._csrf_headers(),
        )
        second_response = self.client.post(
            "/coding/pick/sid-pick-1",
            headers=self._csrf_headers(),
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        active_allocations = db.session.scalars(
            db.select(VaAllocations).where(
                VaAllocations.va_allocated_to == self.base_coder_user.user_id,
                VaAllocations.va_allocation_for == VaAllocation.coding,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        ).all()
        self.assertEqual(len(active_allocations), 1)
        self.assertEqual(active_allocations[0].va_sid, "sid-pick-1")
        workflow_state = db.session.scalar(
            db.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == "sid-pick-1"
            )
        )
        self.assertEqual(workflow_state, "coding_in_progress")

    def test_pickcoding_post_rejects_different_submission_when_active_allocation_exists(self):
        now = datetime.now(timezone.utc)
        workflow = db.session.scalar(
            db.select(VaSubmissionWorkflow).where(
                VaSubmissionWorkflow.va_sid == "sid-pick-1"
            )
        )
        workflow.workflow_state = "ready_for_coding"
        workflow.workflow_reason = "test_reset"
        db.session.add(
            VaSubmissions(
                va_sid="sid-pick-2",
                va_form_id="PCK01PC0101",
                va_submission_date=now,
                va_odk_updatedat=now,
                va_data_collector="Collector",
                va_odk_reviewstate=None,
                va_instance_name="sid-pick-2",
                va_uniqueid_real="sid-pick-2",
                va_uniqueid_masked="sid-pick-2",
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
                va_sid="sid-pick-2",
                workflow_state="ready_for_coding",
                workflow_reason="test_seed",
                workflow_updated_by_role="vasystem",
            )
        )
        db.session.commit()

        self._login(self.base_coder_id)

        first_response = self.client.post(
            "/coding/pick/sid-pick-1",
            headers=self._csrf_headers(),
        )
        second_response = self.client.post(
            "/coding/pick/sid-pick-2",
            headers=self._csrf_headers(),
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 403)
        self.assertIn(b"You already have an active coding allocation.", second_response.data)
        active_allocations = db.session.scalars(
            db.select(VaAllocations).where(
                VaAllocations.va_allocated_to == self.base_coder_user.user_id,
                VaAllocations.va_allocation_for == VaAllocation.coding,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        ).all()
        self.assertEqual(len(active_allocations), 1)
        self.assertEqual(active_allocations[0].va_sid, "sid-pick-1")

    def test_pickcoding_post_rejects_random_mode_submission(self):
        self._login(self.base_coder_id)

        response = self.client.post(
            "/coding/pick/sid-random-1",
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 403)
        self.assertIn(
            b"This project does not use pick-and-choose coding.",
            response.data,
        )

    def test_pickcoding_post_rejects_non_ready_submission_without_server_error(self):
        workflow = db.session.scalar(
            db.select(VaSubmissionWorkflow).where(
                VaSubmissionWorkflow.va_sid == "sid-pick-1"
            )
        )
        workflow.workflow_state = "coding_in_progress"
        workflow.workflow_reason = "test_non_ready"
        db.session.commit()

        self._login(self.base_coder_id)

        response = self.client.post(
            "/coding/pick/sid-pick-1",
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 409)
        self.assertIsNone(self._active_coding_sid())

    def test_pickcoding_post_releases_stale_active_allocation_before_new_pick(self):
        stale_alloc = VaAllocations(
            va_sid="sid-random-1",
            va_allocated_to=self.base_coder_user.user_id,
            va_allocation_for=VaAllocation.coding,
            va_allocation_status=VaStatuses.active,
            va_allocation_createdat=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        db.session.add(stale_alloc)
        random_workflow = db.session.scalar(
            db.select(VaSubmissionWorkflow).where(
                VaSubmissionWorkflow.va_sid == "sid-random-1"
            )
        )
        random_workflow.workflow_state = "coding_in_progress"
        random_workflow.workflow_reason = "test_stale_active"
        pick_workflow = db.session.scalar(
            db.select(VaSubmissionWorkflow).where(
                VaSubmissionWorkflow.va_sid == "sid-pick-1"
            )
        )
        pick_workflow.workflow_state = "ready_for_coding"
        pick_workflow.workflow_reason = "test_reset"
        db.session.commit()

        self._login(self.base_coder_id)

        response = self.client.post(
            "/coding/pick/sid-pick-1",
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200)
        stale_status = db.session.scalar(
            db.select(VaAllocations.va_allocation_status).where(
                VaAllocations.va_sid == "sid-random-1",
                VaAllocations.va_allocated_to == self.base_coder_user.user_id,
            )
        )
        self.assertEqual(stale_status, VaStatuses.deactive)
        self.assertEqual(self._active_coding_sid(), "sid-pick-1")
        random_state = db.session.scalar(
            db.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == "sid-random-1"
            )
        )
        self.assertEqual(random_state, "ready_for_coding")

    def test_pickcoding_rejects_random_mode_submission(self):
        self._login(self.base_coder_id)

        response = self.client.post(
            "/coding/pick/sid-random-1",
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 403)

    def test_coding_tester_bypasses_all_project_site_gates(self):
        project_site = db.session.scalar(
            db.select(VaProjectSites).where(
                VaProjectSites.project_id == "RND01",
                VaProjectSites.site_id == "RN01",
            )
        )
        self.assertIsNotNone(project_site)
        today = datetime.now(timezone.utc).date()
        project_site.coding_enabled = False
        project_site.coding_start_date = today + timedelta(days=7)
        project_site.coding_end_date = today - timedelta(days=7)
        project_site.daily_coder_limit = 0
        db.session.commit()

        self._login(self.coding_tester_id)
        response = self.client.post(
            "/coding/start?project_id=RND01",
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200)
        active_sid = db.session.scalar(
            db.select(VaAllocations.va_sid).where(
                VaAllocations.va_allocated_to == self.coding_tester_user.user_id,
                VaAllocations.va_allocation_for == VaAllocation.coding,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        )
        self.assertEqual(active_sid, "sid-random-1")

    def test_coding_tester_can_allocate_via_coding_api(self):
        self._login(self.coding_tester_id)
        response = self.client.post(
            "/api/v1/coding/allocation",
            json={"project_id": "RND01"},
            headers={
                "Content-Type": "application/json",
                **self._csrf_headers(),
            },
        )

        self.assertEqual(response.status_code, 201)
        payload = response.get_json()
        self.assertEqual(payload["va_sid"], "sid-random-1")
