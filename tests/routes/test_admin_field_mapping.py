"""
Tests for admin field mapping panel routes (Phase 7 TDD).

Run (inside Docker):
  docker compose exec minerva_app_service uv run pytest tests/routes/test_admin_field_mapping.py -v
"""
from app import db
from app.models import MasFormTypes, MasFieldDisplayConfig
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
