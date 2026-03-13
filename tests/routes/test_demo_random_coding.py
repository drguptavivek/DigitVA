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
    VaSubmissions,
    VaUserAccessGrants,
)
from tests.base import BaseTestCase


class DemoRandomCodingRouteTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._seed_demo_projects()

    @classmethod
    def _seed_demo_projects(cls):
        now = datetime.now(timezone.utc)
        fixtures = [
            ("DMO01", "D101", "DMO01D10101", "sid-demo-1"),
            ("DMO02", "D201", "DMO02D20101", "sid-demo-2"),
            ("BLK01", "B101", "BLK01B10101", "sid-blocked-1"),
        ]

        for project_id, site_id, form_id, sid in fixtures:
            db.session.add(
                VaProjectMaster(
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

        db.session.flush()

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

        response = self.client.get(
            "/vacta/vacode/vademo_start_coding/vademo_start_coding"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(self._active_demo_allocation_sid(), {"sid-demo-1", "sid-demo-2"})

    def test_demo_random_coding_honours_optional_project_filter(self):
        self._login(self.base_admin_id)

        response = self.client.get(
            "/vacta/vacode/vademo_start_coding/vademo_start_coding?project_id=DMO02"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._active_demo_allocation_sid(), "sid-demo-2")
