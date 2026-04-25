import uuid

from app import db
from app.models import (
    MapProjectSiteOdk,
    MasFormTypes,
    VaForms,
    VaStatuses,
)
from app.services.forms.runtime_form_sync import sync_runtime_forms_from_site_mappings
from tests.base import BaseTestCase


class TestRuntimeFormSyncService(BaseTestCase):
    _RUN_SUFFIX = uuid.uuid4().hex[:4].upper()
    BASE_PROJECT_ID = "RTF001"
    BASE_SITE_ID = "RTF1"
    SYNC_PROJECT_ID = f"RN{_RUN_SUFFIX}"
    SYNC_SITE_ID = f"RN{_RUN_SUFFIX[:2]}"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._ensure_project_site_fixture(
            project_id=cls.BASE_PROJECT_ID,
            site_id=cls.BASE_SITE_ID,
            project_name="Base Test Project",
            project_nickname="BaseTest",
            site_name="Base Test Site",
        )

        cls.form_type = db.session.scalar(
            db.select(MasFormTypes).where(MasFormTypes.form_type_code == "WHO_2022_VA_SOCIAL")
        )
        if not cls.form_type:
            cls.form_type = MasFormTypes(
                form_type_id=uuid.uuid4(),
                form_type_code="WHO_2022_VA_SOCIAL",
                form_type_name="WHO 2022 VA with Social Autopsy",
                is_active=True,
            )
            db.session.add(cls.form_type)

        cls._ensure_project_site_fixture(
            project_id=cls.SYNC_PROJECT_ID,
            site_id=cls.SYNC_SITE_ID,
            project_name="Sync Test Project",
            project_nickname="SyncTest",
            site_name="Sync Site 1",
        )
        db.session.commit()

    def test_creates_runtime_form_for_mapped_site(self):
        db.session.add(
            MapProjectSiteOdk(
                project_id=self.SYNC_PROJECT_ID,
                site_id=self.SYNC_SITE_ID,
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
            if (
                form.project_id == self.SYNC_PROJECT_ID
                and form.site_id == self.SYNC_SITE_ID
            )
        )
        self.assertEqual(
            runtime_form.form_id,
            f"{self.SYNC_PROJECT_ID}{self.SYNC_SITE_ID}01",
        )
        self.assertEqual(runtime_form.odk_project_id, "11")
        self.assertEqual(runtime_form.odk_form_id, "social_form")
        self.assertEqual(runtime_form.form_type_id, self.form_type.form_type_id)
        self.assertEqual(runtime_form.form_type, self.form_type.form_type_name)

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
            form_id="RTF001RTF109",
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
        self.assertEqual(runtime_form.form_id, "RTF001RTF109")
        self.assertEqual(runtime_form.odk_project_id, "12")
        self.assertEqual(runtime_form.odk_form_id, "new_social_form")
        self.assertEqual(runtime_form.form_status, VaStatuses.active)
        self.assertEqual(runtime_form.form_type_id, self.form_type.form_type_id)
