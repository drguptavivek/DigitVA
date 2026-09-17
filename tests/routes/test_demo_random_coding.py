from datetime import datetime, timezone

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
from app.services.odk_retirement_service import MISSING_IN_ODK
from tests.base import BaseTestCase


class DemoRandomCodingRouteTests(BaseTestCase):
    BASE_PROJECT_ID = "DBM01"
    BASE_SITE_ID = "DBM1"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_demo_projects()

    @classmethod
    def _seed_demo_projects(cls):
        now = datetime.now(timezone.utc)
        fixtures = [
            ("DMO01", "D101", "DMO01D10101", "sid-demo-1", True),
            ("DMO02", "D201", "DMO02D20101", "sid-demo-2", True),
            ("BLK01", "B101", "BLK01B10101", "sid-blocked-1", False),
        ]
        workflow_sids = []

        for project_id, site_id, form_id, sid, is_demo in fixtures:
            db.session.add(
                VaProjectMaster(
                    project_id=project_id,
                    project_code=project_id,
                    project_name=f"Project {project_id}",
                    project_nickname=project_id,
                    project_status=VaStatuses.active,
                    demo_training_enabled=is_demo,
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
            workflow_sids.append(sid)

        db.session.flush()

        for sid in workflow_sids:
            db.session.add(
                VaSubmissionWorkflow(
                    va_sid=sid,
                    workflow_state="ready_for_coding",
                    workflow_reason="test_seed",
                    workflow_updated_by_role="vasystem",
                )
            )

        for project_id, site_id in [("DMO01", "D101"), ("DMO02", "D201")]:
            project_site_id = db.session.scalar(
                db.select(VaProjectSites.project_site_id).where(
                    VaProjectSites.project_id == project_id,
                    VaProjectSites.site_id == site_id,
                )
            )
            db.session.add(
                VaUserAccessGrants(
                    user_id=cls.base_admin_user.user_id,
                    role=VaAccessRoles.coder,
                    scope_type=VaAccessScopeTypes.project_site,
                    project_site_id=project_site_id,
                    notes=f"demo coder grant {project_id}",
                    grant_status=VaStatuses.active,
                )
            )

        db.session.commit()

    def _active_demo_allocation_sid(self):
        return db.session.scalar(
            db.select(VaAllocations.va_sid).where(
                VaAllocations.va_allocated_to == self.base_admin_user.user_id,
                VaAllocations.va_allocation_for == VaAllocation.coding,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        )

    def test_demo_random_coding_uses_only_coder_accessible_forms(self):
        self._login(self.base_admin_id)

        response = self.client.post(
            "/coding/demo",
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(self._active_demo_allocation_sid(), {"sid-demo-1", "sid-demo-2"})

    def test_demo_random_coding_honours_optional_project_filter(self):
        self._login(self.base_admin_id)

        response = self.client.post(
            "/coding/demo?project_id=DMO02",
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._active_demo_allocation_sid(), "sid-demo-2")

    def test_demo_random_coding_skips_non_ready_workflow_states(self):
        self._login(self.base_admin_id)
        workflow = db.session.scalar(
            db.select(VaSubmissionWorkflow).where(
                VaSubmissionWorkflow.va_sid == "sid-demo-1"
            )
        )
        workflow.workflow_state = "coder_finalized"
        workflow.workflow_reason = "test_not_ready"
        db.session.commit()

        response = self.client.post(
            "/coding/demo",
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._active_demo_allocation_sid(), "sid-demo-2")

    def test_demo_random_coding_skips_retired_submission(self):
        """The demo/training pool never offers a retired submission.

        Policy: docs/policy/odk-retired-submissions.md.
        """
        self._login(self.base_admin_id)
        retired = db.session.get(VaSubmissions, "sid-demo-1")
        retired.va_sync_issue_code = MISSING_IN_ODK
        db.session.commit()
        self.addCleanup(self._clear_sync_issue_code, "sid-demo-1")

        response = self.client.post(
            "/coding/demo",
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._active_demo_allocation_sid(), "sid-demo-2")

    def test_demo_random_coding_refuses_when_every_form_is_retired(self):
        self._login(self.base_admin_id)
        for sid in ("sid-demo-1", "sid-demo-2"):
            db.session.get(VaSubmissions, sid).va_sync_issue_code = MISSING_IN_ODK
            self.addCleanup(self._clear_sync_issue_code, sid)
        db.session.commit()

        response = self.client.post(
            "/coding/demo",
            headers=self._csrf_headers(),
        )

        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self._active_demo_allocation_sid())

    def _clear_sync_issue_code(self, va_sid):
        db.session.get(VaSubmissions, va_sid).va_sync_issue_code = None
        db.session.commit()

    def test_coder_dashboard_matches_narration_language_case_insensitively(self):
        submission = db.session.scalar(
            db.select(VaSubmissions).where(VaSubmissions.va_sid == "sid-demo-1")
        )
        submission.va_narration_language = "english"
        db.session.commit()

        self._login(self.base_admin_id)

        dashboard = self.client.get("/coding/")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("Start Random Allocation Coding", dashboard.get_data(as_text=True))

        # Scope the pool to DMO01, whose only submission is the lowercased
        # "english" one: a case-sensitive language match would leave nothing
        # allocatable.  With per-test isolation this user starts with no
        # allocation, so /coding/start allocates and renders the coding page
        # (a 302 to /coding/resume only happens when one already exists).
        start = self.client.post(
            "/coding/start?project_id=DMO01", headers=self._csrf_headers()
        )
        self.assertEqual(start.status_code, 200)
        self.assertEqual(self._active_demo_allocation_sid(), "sid-demo-1")

    def test_coder_dashboard_hides_deactivated_project_sites_from_eligibility(self):
        project_site = db.session.scalar(
            db.select(VaProjectSites).where(
                VaProjectSites.project_id == "DMO02",
                VaProjectSites.site_id == "D201",
            )
        )
        self.assertIsNotNone(project_site)
        project_site.project_site_status = VaStatuses.deactive
        db.session.commit()

        self._login(self.base_admin_id)

        dashboard = self.client.get("/coding/")
        self.assertEqual(dashboard.status_code, 200)

        html = dashboard.get_data(as_text=True)
        self.assertIn("DMO01D10101", html)
        self.assertNotIn("DMO02D20101", html)
        self.assertNotIn("Site D201", html)

    def test_api_demo_allocation_can_be_started_twice(self):
        self._login(self.base_admin_id)
        headers = {
            "Content-Type": "application/json",
            **self._csrf_headers(),
        }

        first = self.client.post(
            "/api/v1/coding/allocation",
            json={"demo": True},
            headers=headers,
        )
        self.assertEqual(first.status_code, 201)

        second = self.client.post(
            "/api/v1/coding/allocation",
            json={"demo": True},
            headers=headers,
        )
        self.assertEqual(second.status_code, 201)
        self.assertIn(self._active_demo_allocation_sid(), {"sid-demo-1", "sid-demo-2"})

    def test_api_debug_stats_returns_runtime_visibility_breakdown(self):
        self._login(self.base_admin_id)

        response = self.client.get("/api/v1/coding/debug-stats")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()

        self.assertEqual(payload["user"]["email"], self.base_admin_user.email)
        self.assertIn("coder_scope", payload)
        self.assertIn("workflow_visibility", payload)
        self.assertIn("form_mapping_status", payload)
        self.assertIn("DMO01D10101", payload["coder_scope"]["form_ids"])
        self.assertIn("DMO02D20101", payload["coder_scope"]["form_ids"])
        self.assertIn(
            "ready_for_coding",
            payload["workflow_visibility"]["coder_ready_pool_states"],
        )
