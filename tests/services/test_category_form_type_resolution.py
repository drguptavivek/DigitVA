import uuid

from app import db
from app.models import (
    MasCategoryOrder,
    MasFieldDisplayConfig,
    MasFormTypes,
    MasSubcategoryOrder,
    VaForms,
    VaResearchProjects,
    VaSites,
    VaStatuses,
)
from app.utils.va_form.va_form_02_formtyperesolution import (
    va_get_form_type_code_for_form,
)
from app.utils.va_preprocess.va_preprocess_03_categoriestodisplay import (
    va_preprocess_categoriestodisplay,
)
from tests.base import BaseTestCase


class TestCategoryFormTypeResolution(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        db.session.add(
            VaResearchProjects(
                project_id="TRF001",
                project_code="TRF001",
                project_name="Test Research Project",
                project_nickname="TestRP",
                project_status=VaStatuses.active,
            )
        )
        db.session.add(
            VaSites(
                site_id="TS01",
                project_id="TRF001",
                site_name="Test Site",
                site_abbr="TS01",
                site_status=VaStatuses.active,
            )
        )
        cls.social_form_type = MasFormTypes(
            form_type_id=uuid.uuid4(),
            form_type_code="WHO_2022_VA_SOCIAL",
            form_type_name="WHO 2022 VA Social",
            is_active=True,
        )
        db.session.add(cls.social_form_type)
        db.session.flush()

        db.session.add(
            MasCategoryOrder(
                form_type_id=cls.social_form_type.form_type_id,
                category_code="vademographicdetails",
                category_name="Demographic / Risk Factors",
                display_order=1,
                is_active=True,
            )
        )
        db.session.add(
            MasSubcategoryOrder(
                form_type_id=cls.social_form_type.form_type_id,
                category_code="vademographicdetails",
                subcategory_code="general",
                subcategory_name="General",
                display_order=1,
                is_active=True,
            )
        )
        db.session.add(
            MasFieldDisplayConfig(
                form_type_id=cls.social_form_type.form_type_id,
                field_id="social_demo_field",
                category_code="vademographicdetails",
                subcategory_code="general",
                short_label="Social Demo Field",
                display_order=1,
                is_active=True,
            )
        )
        db.session.commit()

    def test_resolves_form_type_from_form_type_id(self):
        form = VaForms(
            form_id="FORM900001",
            project_id="TRF001",
            site_id="TS01",
            odk_form_id="odk-social-1",
            odk_project_id="1",
            form_type="legacy_value",
            form_status=VaStatuses.active,
            form_type_id=self.social_form_type.form_type_id,
        )
        db.session.add(form)
        db.session.commit()

        self.assertEqual(
            va_get_form_type_code_for_form("FORM900001"),
            "WHO_2022_VA_SOCIAL",
        )

    def test_resolves_form_type_from_legacy_form_type_when_id_missing(self):
        form = VaForms(
            form_id="FORM900002",
            project_id="TRF001",
            site_id="TS01",
            odk_form_id="odk-social-2",
            odk_project_id="1",
            form_type="WHO_2022_VA_SOCIAL",
            form_status=VaStatuses.active,
            form_type_id=None,
        )
        db.session.add(form)
        db.session.commit()

        self.assertEqual(
            va_get_form_type_code_for_form("FORM900002"),
            "WHO_2022_VA_SOCIAL",
        )

    def test_preprocess_uses_non_default_form_type_mapping(self):
        form = VaForms(
            form_id="FORM900003",
            project_id="TRF001",
            site_id="TS01",
            odk_form_id="odk-social-3",
            odk_project_id="1",
            form_type="WHO_2022_VA_SOCIAL",
            form_status=VaStatuses.active,
            form_type_id=self.social_form_type.form_type_id,
        )
        db.session.add(form)
        db.session.commit()

        category_list = va_preprocess_categoriestodisplay(
            {"social_demo_field": "present"},
            "FORM900003",
        )

        self.assertIn("vademographicdetails", category_list)
        self.assertIn("vanarrationanddocuments", category_list)
