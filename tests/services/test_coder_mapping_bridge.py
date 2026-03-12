import uuid

from app import db
from app.models import (
    MasCategoryOrder,
    MasCategoryDisplayConfig,
    MasFieldDisplayConfig,
    MasFormTypes,
    MasSubcategoryOrder,
)
from app.utils.va_routes.va_api_helpers import va_get_render_datalevel
from tests.base import BaseTestCase


class TestCoderMappingBridge(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.form_type = MasFormTypes(
            form_type_id=uuid.uuid4(),
            form_type_code="WHO_2022_VA_SOCIAL_BRIDGE",
            form_type_name="WHO 2022 VA Social Bridge",
            is_active=True,
        )
        db.session.add(cls.form_type)
        db.session.flush()

        db.session.add(
            MasCategoryOrder(
                form_type_id=cls.form_type.form_type_id,
                category_code="social_autopsy",
                category_name="Social Autopsy",
                display_order=1,
                is_active=True,
            )
        )
        db.session.add(
            MasCategoryDisplayConfig(
                form_type_id=cls.form_type.form_type_id,
                category_code="social_autopsy",
                display_label="Social Autopsy",
                nav_label="Social Autopsy",
                icon_name="fa-users",
                display_order=1,
                render_mode="table_sections",
                show_to_coder=True,
                show_to_reviewer=True,
                show_to_site_pi=True,
                always_include=False,
                is_default_start=False,
                is_active=True,
            )
        )
        db.session.add(
            MasSubcategoryOrder(
                form_type_id=cls.form_type.form_type_id,
                category_code="social_autopsy",
                subcategory_code="social-autopsy",
                subcategory_name="Social Autopsy",
                display_order=1,
                is_active=True,
            )
        )
        db.session.add(
            MasFieldDisplayConfig(
                form_type_id=cls.form_type.form_type_id,
                field_id="sa01",
                category_code="social_autopsy",
                subcategory_code="social-autopsy",
                short_label="Social Question 1",
                display_order=1,
                is_active=True,
            )
        )
        db.session.commit()

    def test_db_only_coder_visible_category_falls_back_to_db_mapping(self):
        datalevel = va_get_render_datalevel(
            "vacode",
            "WHO_2022_VA_SOCIAL_BRIDGE",
            ["social_autopsy"],
        )

        self.assertIn("social_autopsy", datalevel)
        self.assertEqual(
            datalevel["social_autopsy"]["social-autopsy"]["sa01"],
            "Social Question 1",
        )

    def test_existing_static_coder_categories_remain_available(self):
        datalevel = va_get_render_datalevel(
            "vacode",
            "WHO_2022_VA_SOCIAL_BRIDGE",
            ["social_autopsy", "vademographicdetails"],
        )

        self.assertIn("vademographicdetails", datalevel)
