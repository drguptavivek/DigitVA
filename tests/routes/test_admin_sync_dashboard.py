from datetime import datetime, timezone
from unittest.mock import patch

import uuid
import sqlalchemy as sa

from app import db
from app.models import (
    MapProjectSiteOdk,
    MasFormTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaResearchProjects,
    VaSiteMaster,
    VaSites,
    VaStatuses,
)
from tests.base import BaseTestCase


class AdminSyncDashboardTests(BaseTestCase):
    PROJECT_ID = "SADEMO"
    SITE_ID = "SA01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)

        db.session.add(
            VaProjectMaster(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="Social Autopsy Demo",
                project_nickname="SADemo",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaSiteMaster(
                site_id=cls.SITE_ID,
                site_name="Social Autopsy Site",
                site_abbr=cls.SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            )
        )
        db.session.flush()
        db.session.add(
            VaResearchProjects(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="Social Autopsy Demo",
                project_nickname="SADemo",
                project_status=VaStatuses.active,
            )
        )
        db.session.add(
            VaSites(
                site_id=cls.SITE_ID,
                project_id=cls.PROJECT_ID,
                site_name="Social Autopsy Site",
                site_abbr=cls.SITE_ID,
                site_status=VaStatuses.active,
            )
        )
        db.session.flush()
        db.session.add(
            VaProjectSites(
                project_id=cls.PROJECT_ID,
                site_id=cls.SITE_ID,
                project_site_status=VaStatuses.active,
            )
        )
        db.session.flush()

        social_form_type = db.session.scalar(
            db.select(MasFormTypes).where(MasFormTypes.form_type_code == "WHO_2022_VA_SOCIAL")
        )
        if not social_form_type:
            social_form_type = MasFormTypes(
                form_type_id=uuid.uuid4(),
                form_type_code="WHO_2022_VA_SOCIAL",
                form_type_name="WHO VA Social Autopsy",
                form_type_description="Social autopsy form",
                is_active=True,
            )
            db.session.add(social_form_type)
            db.session.flush()
        cls.social_form_type_id = social_form_type.form_type_id

        db.session.add(
            MapProjectSiteOdk(
                project_id=cls.PROJECT_ID,
                site_id=cls.SITE_ID,
                odk_project_id=17,
                odk_form_id="SA01_SOCIAL_AUTOPSY",
                form_type_id=cls.social_form_type_id,
            )
        )
        db.session.commit()

    def test_admin_sync_coverage_includes_site_without_local_form(self):
        self._login(self.base_admin_id)
        db.session.execute(
            sa.delete(VaForms).where(
                VaForms.project_id == self.PROJECT_ID,
                VaForms.site_id == self.SITE_ID,
            )
        )
        db.session.commit()

        with patch(
            "app.utils.va_odk.va_odk_04_submissioncount.va_odk_submissioncount",
            return_value=12,
        ):
            response = self.client.get("/admin/api/sync/coverage")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        row = next(
            item
            for item in payload["mappings"]
            if item["project_id"] == self.PROJECT_ID and item["site_id"] == self.SITE_ID
        )
        self.assertEqual(row["form_id"], f"{self.PROJECT_ID}{self.SITE_ID}01")
        self.assertTrue(row["can_site_sync"])
        self.assertEqual(row["odk_total"], 12)
        self.assertEqual(row["local_total"], 0)
        self.assertEqual(row["missing"], 12)

    def test_admin_sync_project_site_materializes_runtime_form_and_dispatches_sync(self):
        self._login(self.base_admin_id)

        with patch(
            "app.tasks.sync_tasks.run_single_form_sync.delay",
            return_value=type("TaskResult", (), {"id": "task-123"})(),
        ) as delay_mock:
            response = self.client.post(
                f"/admin/api/sync/project-site/{self.PROJECT_ID}/{self.SITE_ID}",
                headers=self._csrf_headers(),
            )

        self.assertEqual(response.status_code, 202)
        payload = response.get_json()
        self.assertEqual(payload["task_id"], "task-123")
        self.assertEqual(payload["form_id"], f"{self.PROJECT_ID}{self.SITE_ID}01")

        delay_mock.assert_called_once_with(
            form_id=f"{self.PROJECT_ID}{self.SITE_ID}01",
            triggered_by="manual",
            user_id=self.base_admin_id,
        )

        form_id = db.session.scalar(
            sa.select(VaForms.form_id).where(
                VaForms.project_id == self.PROJECT_ID,
                VaForms.site_id == self.SITE_ID,
            )
        )
        self.assertEqual(form_id, f"{self.PROJECT_ID}{self.SITE_ID}01")

    def test_admin_sync_project_site_rejects_inactive_project_site(self):
        self._login(self.base_admin_id)
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
                f"/admin/api/sync/project-site/{self.PROJECT_ID}/{self.SITE_ID}",
                headers=self._csrf_headers(),
            )
        finally:
            project_site.project_site_status = original_status
            db.session.commit()

        self.assertEqual(response.status_code, 404)
        self.assertIn(
            "Active runtime mapping not found",
            response.get_json()["error"],
        )
