"""
Tests for admin field mapping panel routes (Phase 7 TDD).

Run (inside Docker):
  docker compose exec minerva_app_service uv run pytest tests/routes/test_admin_field_mapping.py -v
"""
from decimal import Decimal

from app import db
from app.models import MasFormTypes, MasFieldDisplayConfig
from app.models.va_field_mapping import MasChoiceMappings
from app.services.migrations.migrate_who_2022_va import Who2022VaMigrator
from tests.base import BaseTestCase


class TestAdminFieldMappingRoutes(BaseTestCase):
    """Test admin field mapping panel routes."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Populate mapping data
        Who2022VaMigrator().run()

    def test_01_panel_redirects_when_not_logged_in(self):
        """Field mapping panel redirects unauthenticated users to login."""
        resp = self.client.get("/admin/panels/field-mapping")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp.headers["Location"])

    def test_02_panel_returns_403_for_non_admin(self):
        """Field mapping panel returns 403 for non-admin users."""
        self._login(self.base_coder_id)
        resp = self.client.get("/admin/panels/field-mapping")
        self.assertEqual(resp.status_code, 403)

    def test_03_panel_loads_for_admin(self):
        """Field mapping panel loads successfully for admin user."""
        self._login(self.base_admin_id)
        resp = self.client.get("/admin/panels/field-mapping")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"WHO_2022_VA", resp.data)

    def test_04_fields_subpanel_requires_admin(self):
        """Fields subpanel requires admin role."""
        self._login(self.base_coder_id)
        resp = self.client.get("/admin/panels/field-mapping/fields?form_type=WHO_2022_VA")
        self.assertEqual(resp.status_code, 403)

    def test_05_fields_subpanel_loads(self):
        """Fields subpanel loads with field data."""
        self._login(self.base_admin_id)
        resp = self.client.get(
            "/admin/panels/field-mapping/fields?form_type=WHO_2022_VA",
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)

    def test_06_field_edit_get_returns_form(self):
        """Field edit GET returns the edit form."""
        self._login(self.base_admin_id)
        resp = self.client.get(
            "/admin/panels/field-mapping/field/WHO_2022_VA/Id10010",
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Id10010", resp.data)

    def test_07_field_edit_get_404_for_unknown(self):
        """Field edit returns 404 for unknown field."""
        self._login(self.base_admin_id)
        resp = self.client.get(
            "/admin/panels/field-mapping/field/WHO_2022_VA/NO_SUCH_FIELD",
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_08_field_edit_post_updates_label(self):
        """POST to field edit updates the short_label."""
        self._login(self.base_admin_id)
        csrf_headers = self._csrf_headers()

        resp = self.client.post(
            "/admin/panels/field-mapping/field/WHO_2022_VA/Id10010",
            data={
                "short_label": "Updated Label Test",
                "full_label": "",
                "flip_color": "",
                "is_info": "",
                "summary_include": "",
                "is_pii": "",
            },
            headers={**csrf_headers, "HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)

        # Verify in DB
        from app.models import MasFormTypes, MasFieldDisplayConfig
        from sqlalchemy import select
        form_type = db.session.scalar(
            select(MasFormTypes).where(MasFormTypes.form_type_code == "WHO_2022_VA")
        )
        field = db.session.scalar(
            select(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                MasFieldDisplayConfig.field_id == "Id10010",
            )
        )
        self.assertEqual(field.short_label, "Updated Label Test")

    def test_08b_field_edit_post_updates_choice_labels(self):
        """POST to field edit updates DigitVA choice labels for the field."""
        self._login(self.base_admin_id)
        csrf_headers = self._csrf_headers()

        form_type = db.session.scalar(
            db.select(MasFormTypes).where(MasFormTypes.form_type_code == "WHO_2022_VA")
        )
        choice = db.session.scalar(
            db.select(MasChoiceMappings)
            .join(
                MasFieldDisplayConfig,
                db.and_(
                    MasFieldDisplayConfig.form_type_id == MasChoiceMappings.form_type_id,
                    MasFieldDisplayConfig.field_id == MasChoiceMappings.field_id,
                ),
            )
            .where(
                MasChoiceMappings.form_type_id == form_type.form_type_id,
                MasChoiceMappings.is_active == True,
            )
            .order_by(MasChoiceMappings.field_id, MasChoiceMappings.display_order)
        )
        self.assertIsNotNone(choice)

        resp = self.client.post(
            f"/admin/panels/field-mapping/field/WHO_2022_VA/{choice.field_id}",
            data={
                "short_label": "Date of birth known",
                "full_label": "",
                f"choice_label__{choice.choice_id}": "Affirmative",
                "flip_color": "",
                "is_info": "",
                "summary_include": "",
                "is_pii": "",
            },
            headers={**csrf_headers, "HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)

        refreshed = db.session.scalar(
            db.select(MasChoiceMappings).where(
                MasChoiceMappings.choice_id == choice.choice_id
            )
        )
        self.assertEqual(refreshed.choice_label, "Affirmative")

    def test_09_sync_panel_loads(self):
        """ODK sync subpanel loads for admin."""
        self._login(self.base_admin_id)
        resp = self.client.get(
            "/admin/panels/field-mapping/sync?form_type=WHO_2022_VA",
            headers={"HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"WHO_2022_VA", resp.data)

    def test_10_panel_shows_all_form_types(self):
        """Main panel lists all active form types."""
        self._login(self.base_admin_id)
        resp = self.client.get("/admin/panels/field-mapping")
        self.assertEqual(resp.status_code, 200)
        # WHO_2022_VA must appear
        self.assertIn(b"WHO_2022_VA", resp.data)

    def test_11_quick_order_patch_accepts_decimal(self):
        """Inline field order update accepts decimal values."""
        self._login(self.base_admin_id)
        csrf_headers = self._csrf_headers()

        resp = self.client.patch(
            "/admin/panels/field-mapping/field/WHO_2022_VA/Id10010/order",
            data={"display_order": "2.1"},
            headers={**csrf_headers, "HX-Request": "true"},
        )
        self.assertEqual(resp.status_code, 200)

        form_type = db.session.scalar(
            db.select(MasFormTypes).where(MasFormTypes.form_type_code == "WHO_2022_VA")
        )
        field = db.session.scalar(
            db.select(MasFieldDisplayConfig).where(
                MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
                MasFieldDisplayConfig.field_id == "Id10010",
            )
        )
        self.assertEqual(field.display_order, Decimal("2.1"))

    def test_12_subcategory_update_persists_render_mode(self):
        """Subcategory update stores render mode for special attachment sections."""
        self._login(self.base_admin_id)
        csrf_headers = self._csrf_headers()

        resp = self.client.put(
            "/admin/api/form-types/WHO_2022_VA/categories/vanarrationanddocuments/subcategories/medical_documents",
            json={
                "subcategory_name": "Medical Documents",
                "display_order": 20,
                "render_mode": "media_gallery",
            },
            headers=csrf_headers,
        )
        self.assertEqual(resp.status_code, 200)

        form_type = db.session.scalar(
            db.select(MasFormTypes).where(MasFormTypes.form_type_code == "WHO_2022_VA")
        )
        from app.models.va_field_mapping import MasSubcategoryOrder
        subcategory = db.session.scalar(
            db.select(MasSubcategoryOrder).where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == "vanarrationanddocuments",
                MasSubcategoryOrder.subcategory_code == "medical_documents",
            )
        )
        self.assertEqual(subcategory.render_mode, "media_gallery")
