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
                    va_data={"sid": sid},
                    va_summary=[],
                    va_catcount={},
                    va_category_list=[],
                )
            )
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

        response = self.client.get("/vadashboard/coder")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Pick And Choose Coding", response.data)
        self.assertIn(b"sid-pick-1", response.data)
        self.assertIn(b"vapickcoding/sid-pick-1", response.data)

    def test_startcoding_uses_only_random_projects(self):
        self._login(self.base_coder_id)

        response = self.client.get("/vacta/vacode/vastartcoding/vastartcoding")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._active_coding_sid(), "sid-random-1")

    def test_pickcoding_allocates_selected_ready_submission(self):
        self._login(self.base_coder_id)

        response = self.client.get("/vacta/vacode/vapickcoding/sid-pick-1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._active_coding_sid(), "sid-pick-1")
        workflow_state = db.session.scalar(
            db.select(VaSubmissionWorkflow.workflow_state).where(
                VaSubmissionWorkflow.va_sid == "sid-pick-1"
            )
        )
        self.assertEqual(workflow_state, "coding_in_progress")

    def test_pickcoding_rejects_random_mode_submission(self):
        self._login(self.base_coder_id)

        response = self.client.get("/vacta/vacode/vapickcoding/sid-random-1")

        self.assertEqual(response.status_code, 403)
