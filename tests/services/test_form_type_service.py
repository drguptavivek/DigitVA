"""
Tests for FormTypeService (Phase 6 TDD).

Run (inside Docker):
  docker compose exec minerva_app_service uv run pytest tests/services/test_form_type_service.py -v
"""
from app import db
from app.models import MasCategoryDisplayConfig, MasFormTypes
from app.services.migrations.migrate_who_2022_va import Who2022VaMigrator
from tests.base import BaseTestCase


class TestFormTypeService(BaseTestCase):
    """Test form type registration, listing, stats, and deactivation."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Populate WHO_2022_VA data so stats tests have real data
        Who2022VaMigrator().run()

    def _service(self):
        from app.services.form_type_service import FormTypeService
        return FormTypeService()

    def test_01_register_new_form_type(self):
        """Can register a new form type."""
        svc = self._service()
        ft = svc.register_form_type(
            form_type_code="TEST_FORM_01",
            form_type_name="Test Form One",
            description="A test form",
        )
        self.assertIsNotNone(ft)
        self.assertEqual(ft.form_type_code, "TEST_FORM_01")
        self.assertEqual(ft.form_type_name, "Test Form One")
        self.assertTrue(ft.is_active)

    def test_02_cannot_register_duplicate(self):
        """Cannot register the same form_type_code twice."""
        svc = self._service()
        svc.register_form_type("TEST_DUP", "Dup Form")
        with self.assertRaises(ValueError):
            svc.register_form_type("TEST_DUP", "Another Dup")

    def test_03_list_form_types_includes_who_2022_va(self):
        """list_form_types returns WHO_2022_VA (created by migrator)."""
        svc = self._service()
        form_types = svc.list_form_types()
        self.assertGreater(len(form_types), 0)
        codes = [ft.form_type_code for ft in form_types]
        self.assertIn("WHO_2022_VA", codes)

    def test_04_get_form_type_stats_who_2022_va(self):
        """Stats for WHO_2022_VA return correct category and field counts."""
        svc = self._service()
        stats = svc.get_form_type_stats("WHO_2022_VA")
        self.assertIsNotNone(stats)
        self.assertEqual(stats["form_type_code"], "WHO_2022_VA")
        self.assertEqual(stats["category_count"], 14)
        # 410 unique fields (deduplicated from Excel)
        self.assertGreater(stats["field_count"], 0)

    def test_05_get_form_type_stats_unknown_returns_empty(self):
        """Stats for unknown form type returns empty dict."""
        svc = self._service()
        stats = svc.get_form_type_stats("DOES_NOT_EXIST")
        self.assertEqual(stats, {})

    def test_06_deactivate_form_type_with_no_forms(self):
        """Can deactivate a form type that has no associated VaForms."""
        svc = self._service()
        ft = svc.register_form_type("TO_DEACTIVATE_P6", "Will Be Deactivated")
        result = svc.deactivate_form_type("TO_DEACTIVATE_P6")
        self.assertTrue(result)
        db.session.refresh(ft)
        self.assertFalse(ft.is_active)

    def test_07_deactivate_unknown_returns_false(self):
        """deactivate_form_type returns False for unknown code."""
        svc = self._service()
        result = svc.deactivate_form_type("NO_SUCH_CODE")
        self.assertFalse(result)

    def test_08_get_form_type_returns_none_for_inactive(self):
        """get_form_type returns None after deactivation."""
        svc = self._service()
        svc.register_form_type("INACTIVE_CHECK", "Will Be Inactive")
        svc.deactivate_form_type("INACTIVE_CHECK")
        result = svc.get_form_type("INACTIVE_CHECK")
        self.assertIsNone(result)

    def test_09_list_excludes_inactive(self):
        """list_form_types does not include deactivated form types."""
        svc = self._service()
        svc.register_form_type("LIST_EXCL", "Exclude Me")
        svc.deactivate_form_type("LIST_EXCL")
        codes = [ft.form_type_code for ft in svc.list_form_types()]
        self.assertNotIn("LIST_EXCL", codes)

    def test_10_get_default_form_type(self):
        """get_default_form_type returns WHO_2022_VA."""
        from app.services.field_mapping_service import FieldMappingService
        svc = FieldMappingService()
        self.assertEqual(svc.get_default_form_type(), "WHO_2022_VA")

    def test_11_duplicate_form_type_copies_category_display_configs(self):
        """duplicate_form_type copies category display metadata to the new form type."""
        svc = self._service()
        duplicated = svc.duplicate_form_type(
            "WHO_2022_VA",
            "WHO_2022_VA_COPY",
            "WHO 2022 VA Copy",
        )

        count = db.session.scalar(
            db.select(db.func.count())
            .select_from(MasCategoryDisplayConfig)
            .where(MasCategoryDisplayConfig.form_type_id == duplicated.form_type_id)
        )
        self.assertEqual(count, 14)

    def test_12_export_includes_category_display_configs(self):
        """export_form_type serializes category display metadata."""
        svc = self._service()
        exported = svc.export_form_type("WHO_2022_VA")

        configs = exported.get("category_display_configs", [])
        self.assertEqual(len(configs), 14)
        self.assertIn(
            "vanarrationanddocuments",
            {cfg["category_code"] for cfg in configs},
        )
