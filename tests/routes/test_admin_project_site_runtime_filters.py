from datetime import datetime, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    MapProjectSiteOdk,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
)
from tests.base import BaseTestCase


class AdminProjectSiteRuntimeFilterTests(BaseTestCase):
    PROJECT_ID = "APR001"
    SITE_ID = "AS01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        db.session.add_all(
            [
                VaProjectMaster(
                    project_id=cls.PROJECT_ID,
                    project_code=cls.PROJECT_ID,
                    project_name="Admin Project Runtime Filter",
                    project_nickname="AdminRuntime",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
                VaSiteMaster(
                    site_id=cls.SITE_ID,
                    site_name="Admin Runtime Site",
                    site_abbr=cls.SITE_ID,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
                VaResearchProjects(
                    project_id=cls.PROJECT_ID,
                    project_code=cls.PROJECT_ID,
                    project_name="Admin Project Runtime Filter",
                    project_nickname="AdminRuntime",
                    project_status=VaStatuses.active,
                    project_registered_at=now,
                    project_updated_at=now,
                ),
            ]
        )
        db.session.commit()
        db.session.add_all(
            [
                VaSites(
                    site_id=cls.SITE_ID,
                    project_id=cls.PROJECT_ID,
                    site_name="Admin Runtime Site",
                    site_abbr=cls.SITE_ID,
                    site_status=VaStatuses.active,
                    site_registered_at=now,
                    site_updated_at=now,
                ),
                VaProjectSites(
                    project_id=cls.PROJECT_ID,
                    site_id=cls.SITE_ID,
                    project_site_status=VaStatuses.active,
                    project_site_registered_at=now,
                    project_site_updated_at=now,
                ),
            ]
        )
        db.session.commit()
        db.session.add_all(
            [
                MapProjectSiteOdk(
                    project_id=cls.PROJECT_ID,
                    site_id=cls.SITE_ID,
                    odk_project_id=31,
                    odk_form_id="ADMIN_RUNTIME_FORM",
                    form_type_id=None,
                ),
                VaForms(
                    form_id=f"{cls.PROJECT_ID}{cls.SITE_ID}01",
                    project_id=cls.PROJECT_ID,
                    site_id=cls.SITE_ID,
                    odk_form_id="ADMIN_RUNTIME_FORM",
                    odk_project_id="31",
                    form_type="WHO VA 2022",
                    form_status=VaStatuses.active,
                    form_registered_at=now,
                    form_updated_at=now,
                ),
            ]
        )
        db.session.commit()

    def test_odk_site_mappings_list_excludes_inactive_site_master(self):
        self._login(self.base_admin_id)

        site = db.session.get(VaSiteMaster, self.SITE_ID)
        self.assertIsNotNone(site)
        original_status = site.site_status
        site.site_status = VaStatuses.deactive
        db.session.commit()
        try:
            response = self.client.get(
                f"/admin/api/projects/{self.PROJECT_ID}/odk-site-mappings"
            )
        finally:
            site.site_status = original_status
            db.session.commit()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            any(
                row["site_id"] == self.SITE_ID
                for row in response.get_json()["mappings"]
            )
        )

    def test_odk_site_mappings_save_rejects_inactive_project_site(self):
        self._login(self.base_admin_id)
        headers = self._csrf_headers()

        project_site = db.session.scalar(
            sa.select(VaProjectSites).where(
                VaProjectSites.project_id == self.PROJECT_ID,
                VaProjectSites.site_id == self.SITE_ID,
            )
        )
        self.assertIsNotNone(project_site)
        original_status = project_site.project_site_status
        project_site.project_site_status = VaStatuses.deactive
        db.session.commit()
        try:
            response = self.client.post(
                f"/admin/api/projects/{self.PROJECT_ID}/odk-site-mappings",
                json={
                    "site_id": self.SITE_ID,
                    "odk_project_id": 31,
                    "odk_form_id": "ADMIN_RUNTIME_FORM",
                },
                headers=headers,
            )
        finally:
            project_site.project_site_status = original_status
            db.session.commit()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json()["error"],
            "Active project-site mapping not found.",
        )

    def test_project_site_coding_settings_rejects_inactive_project_site(self):
        self._login(self.base_admin_id)
        headers = self._csrf_headers()

        project_site = db.session.scalar(
            sa.select(VaProjectSites).where(
                VaProjectSites.project_id == self.PROJECT_ID,
                VaProjectSites.site_id == self.SITE_ID,
            )
        )
        self.assertIsNotNone(project_site)
        original_status = project_site.project_site_status
        project_site.project_site_status = VaStatuses.deactive
        db.session.commit()
        try:
            response = self.client.put(
                f"/admin/api/project-sites/{self.PROJECT_ID}/{self.SITE_ID}/coding-settings",
                json={
                    "coding_enabled": True,
                    "coding_start_date": None,
                    "coding_end_date": None,
                    "daily_coder_limit": 25,
                },
                headers=headers,
            )
        finally:
            project_site.project_site_status = original_status
            db.session.commit()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json()["error"],
            "Active project-site mapping not found.",
        )

    def test_single_form_sync_rejects_inactive_project_site(self):
        self._login(self.base_admin_id)
        headers = self._csrf_headers()

        project_site = db.session.scalar(
            sa.select(VaProjectSites).where(
                VaProjectSites.project_id == self.PROJECT_ID,
                VaProjectSites.site_id == self.SITE_ID,
            )
        )
        self.assertIsNotNone(project_site)
        original_status = project_site.project_site_status
        project_site.project_site_status = VaStatuses.deactive
        db.session.commit()
        try:
            response = self.client.post(
                f"/admin/api/sync/form/{self.PROJECT_ID}{self.SITE_ID}01",
                headers=headers,
            )
        finally:
            project_site.project_site_status = original_status
            db.session.commit()

        self.assertEqual(response.status_code, 404)
        self.assertEqual(
            response.get_json()["error"],
            f"Active runtime mapping not found for form '{self.PROJECT_ID}{self.SITE_ID}01'.",
        )
