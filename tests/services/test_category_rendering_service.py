import uuid

from app import db
from app.models import MasCategoryDisplayConfig, MasFormTypes
from app.services.category_rendering_service import get_category_rendering_service
from tests.base import BaseTestCase


class TestCategoryRenderingService(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.form_type = MasFormTypes(
            form_type_id=uuid.uuid4(),
            form_type_code="TEST_RENDERING_FORM",
            form_type_name="Test Rendering Form",
            is_active=True,
        )
        db.session.add(cls.form_type)
        db.session.flush()

        db.session.add_all(
            [
                MasCategoryDisplayConfig(
                    form_type_id=cls.form_type.form_type_id,
                    category_code="vainterviewdetails",
                    display_label="Interview Details",
                    nav_label="Interview Details",
                    icon_name="fa-info-circle",
                    display_order=1,
                    render_mode="table_sections",
                    show_to_coder=False,
                    show_to_reviewer=False,
                    show_to_site_pi=True,
                    always_include=False,
                    is_default_start=False,
                    is_active=True,
                ),
                MasCategoryDisplayConfig(
                    form_type_id=cls.form_type.form_type_id,
                    category_code="vademographicdetails",
                    display_label="Demographic / Risk Factors",
                    nav_label="Demographic / Risk Factors",
                    icon_name="fa-user",
                    display_order=2,
                    render_mode="table_sections",
                    show_to_coder=True,
                    show_to_reviewer=True,
                    show_to_site_pi=True,
                    always_include=False,
                    is_default_start=True,
                    is_active=True,
                ),
                MasCategoryDisplayConfig(
                    form_type_id=cls.form_type.form_type_id,
                    category_code="vanarrationanddocuments",
                    display_label="Narration / Documents / COD",
                    nav_label="Narration / Documents / COD",
                    icon_name="fa-file-medical-alt",
                    display_order=3,
                    render_mode="attachments",
                    show_to_coder=True,
                    show_to_reviewer=True,
                    show_to_site_pi=True,
                    always_include=True,
                    is_default_start=False,
                    is_active=True,
                ),
            ]
        )
        db.session.commit()

    def setUp(self):
        super().setUp()
        get_category_rendering_service().clear_cache()

    def test_coder_nav_hides_site_pi_only_categories(self):
        nav = get_category_rendering_service().get_category_nav(
            "TEST_RENDERING_FORM",
            "vacode",
            ["vainterviewdetails", "vademographicdetails"],
        )

        self.assertEqual(
            [item.category_code for item in nav],
            ["vademographicdetails", "vanarrationanddocuments", "vacodassessment"],
        )

    def test_site_pi_nav_includes_interview_when_visible(self):
        nav = get_category_rendering_service().get_category_nav(
            "TEST_RENDERING_FORM",
            "vasitepi",
            ["vainterviewdetails", "vademographicdetails"],
        )

        self.assertEqual(
            [item.category_code for item in nav],
            [
                "vainterviewdetails",
                "vademographicdetails",
                "vanarrationanddocuments",
            ],
        )

    def test_default_category_prefers_default_start_when_visible(self):
        default_code = get_category_rendering_service().get_default_category_code(
            "TEST_RENDERING_FORM",
            "vacode",
            ["vademographicdetails"],
        )

        self.assertEqual(default_code, "vademographicdetails")

    def test_category_neighbours_follow_visible_nav_order(self):
        previous_code, next_code = get_category_rendering_service().get_category_neighbours(
            "TEST_RENDERING_FORM",
            "vacode",
            ["vademographicdetails"],
            "vademographicdetails",
        )

        self.assertIsNone(previous_code)
        self.assertEqual(next_code, "vanarrationanddocuments")

    def test_cod_assessment_is_final_coder_workflow_item(self):
        previous_code, next_code = get_category_rendering_service().get_category_neighbours(
            "TEST_RENDERING_FORM",
            "vacode",
            ["vademographicdetails"],
            "vanarrationanddocuments",
        )

        self.assertEqual(previous_code, "vademographicdetails")
        self.assertEqual(next_code, "vacodassessment")

    def test_all_active_categories_returns_only_configured_categories(self):
        items = get_category_rendering_service().get_all_active_categories(
            "TEST_RENDERING_FORM"
        )

        self.assertEqual(
            [item.category_code for item in items],
            [
                "vainterviewdetails",
                "vademographicdetails",
                "vanarrationanddocuments",
            ],
        )
