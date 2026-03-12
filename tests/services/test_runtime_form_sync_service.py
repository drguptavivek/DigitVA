import uuid

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
from app.services.runtime_form_sync_service import sync_runtime_forms_from_site_mappings
from tests.base import BaseTestCase


class TestRuntimeFormSyncService(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db.session.add(
            VaResearchProjects(
                project_id=cls.BASE_PROJECT_ID,
                project_code=cls.BASE_PROJECT_ID,
                project_name="Base Test Project",
                project_nickname="BaseTest",
                project_status=VaStatuses.active,
            )
        )
        db.session.add(
            VaSites(
                site_id=cls.BASE_SITE_ID,
                project_id=cls.BASE_PROJECT_ID,
                site_name="Base Test Site",
                site_abbr=cls.BASE_SITE_ID,
                site_status=VaStatuses.active,
            )
        )
        db.session.commit()

        cls.form_type = MasFormTypes(
            form_type_id=uuid.uuid4(),
            form_type_code="WHO_2022_VA_SOCIAL",
            form_type_name="WHO 2022 VA with Social Autopsy",
            is_active=True,
        )
        db.session.add(cls.form_type)

        project_master = VaProjectMaster(
            project_id="SYNC01",
            project_code="SYNC01",
            project_name="Sync Test Project",
            project_nickname="SyncTest",
            project_status=VaStatuses.active,
        )
        project = VaResearchProjects(
            project_id="SYNC01",
            project_code="SYNC01",
            project_name="Sync Test Project",
            project_nickname="SyncTest",
            project_status=VaStatuses.active,
        )
        site_master = VaSiteMaster(
            site_id="S101",
            site_name="Sync Site 1",
            site_abbr="S101",
            site_status=VaStatuses.active,
        )
        site_legacy = VaSites(
            site_id="S101",
            project_id="SYNC01",
            site_name="Sync Site 1",
            site_abbr="S101",
            site_status=VaStatuses.active,
        )
        db.session.add_all([project_master, project, site_master, site_legacy])
        db.session.commit()

        project_site = VaProjectSites(
            project_id="SYNC01",
            site_id="S101",
            project_site_status=VaStatuses.active,
        )
        db.session.add(project_site)
        db.session.commit()

    def test_creates_runtime_form_for_mapped_site(self):
        db.session.add(
            MapProjectSiteOdk(
                project_id="SYNC01",
                site_id="S101",
                odk_project_id=11,
                odk_form_id="social_form",
                form_type_id=self.form_type.form_type_id,
            )
        )
        db.session.commit()

        runtime_forms = sync_runtime_forms_from_site_mappings()
        db.session.commit()

        runtime_form = next(
            form
            for form in runtime_forms
            if form.project_id == "SYNC01" and form.site_id == "S101"
        )
        self.assertEqual(runtime_form.form_id, "SYNC01S10101")
        self.assertEqual(runtime_form.odk_project_id, "11")
        self.assertEqual(runtime_form.odk_form_id, "social_form")
        self.assertEqual(runtime_form.form_type_id, self.form_type.form_type_id)
        self.assertEqual(runtime_form.form_type, "WHO 2022 VA with Social Autopsy")

    def test_reuses_existing_runtime_form_for_same_project_site(self):
        db.session.add(
            MapProjectSiteOdk(
                project_id=self.BASE_PROJECT_ID,
                site_id=self.BASE_SITE_ID,
                odk_project_id=12,
                odk_form_id="new_social_form",
                form_type_id=self.form_type.form_type_id,
            )
        )
        existing = VaForms(
            form_id="BASE01BS0109",
            project_id=self.BASE_PROJECT_ID,
            site_id=self.BASE_SITE_ID,
            odk_project_id="3",
            odk_form_id="old_form",
            form_type="WHO VA 2022",
            form_status=VaStatuses.deactive,
        )
        db.session.add(existing)
        db.session.commit()

        runtime_forms = sync_runtime_forms_from_site_mappings()
        db.session.commit()

        runtime_form = next(
            form
            for form in runtime_forms
            if form.project_id == self.BASE_PROJECT_ID and form.site_id == self.BASE_SITE_ID
        )
        self.assertEqual(runtime_form.form_id, "BASE01BS0109")
        self.assertEqual(runtime_form.odk_project_id, "12")
        self.assertEqual(runtime_form.odk_form_id, "new_social_form")
        self.assertEqual(runtime_form.form_status, VaStatuses.active)
        self.assertEqual(runtime_form.form_type_id, self.form_type.form_type_id)
