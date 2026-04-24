import app.routes.coding as legacy_coding
import app.routes.data_management as legacy_data_management
import app.routes.health as legacy_health
import app.routes.profile as legacy_profile
import app.routes.reviewing as legacy_reviewing
import app.routes.sitepi as legacy_sitepi
import app.routes.va_auth as legacy_auth
import app.routes.va_main as legacy_public
from pathlib import Path

from app.http import errors as http_errors
from app.routes import auth as route_auth
from app.routes import health as route_health
from app.routes import home as route_home
from app.routes import profile as route_profile
from app.routes import helpers as route_helpers
from app.routes.admin_sections import access_grants as admin_access_grants
from app.routes.admin_sections import activity as admin_activity
from app.routes.admin_sections import cod_buckets as admin_cod_buckets
from app.routes.admin_sections import icd10_browser as admin_icd10_browser
from app.routes.admin_sections import languages as admin_languages
from app.routes.admin_sections import odk_connections as admin_odk_connections
from app.routes.admin_sections import project_forms as admin_project_forms
from app.routes.admin_sections import project_sites as admin_project_sites
from app.routes.admin_sections import users as admin_users
from app.routes.api import api_v1
from app.routes.api import data_management as api_data_management
from app.routes.operations import data_management as operations_data_management
from app.routes.operations import sitepi as operations_sitepi
from app.routes.workflow import coding as workflow_coding
from app.routes.workflow import forms as workflow_forms
from app.routes.workflow import reviewing as workflow_reviewing
from app.routes.workflow.forms.partials import renderpartial as workflow_renderpartial
from tests.base import BaseTestCase


class RoutePackageExportTests(BaseTestCase):
    def test_top_level_route_shims_alias_live_modules(self):
        self.assertIs(legacy_coding, workflow_coding)
        self.assertIs(legacy_reviewing, workflow_reviewing)
        self.assertIs(legacy_data_management, operations_data_management)
        self.assertIs(legacy_sitepi, operations_sitepi)
        self.assertIs(legacy_health, route_health)
        self.assertIs(legacy_profile, route_profile)
        self.assertIs(legacy_auth, route_auth)
        self.assertIs(legacy_public, route_home)

    def test_top_level_public_route_packages_export_primary_surfaces(self):
        self.assertTrue(hasattr(route_auth, "va_auth"))
        self.assertTrue(hasattr(route_auth, "va_login"))
        self.assertTrue(hasattr(route_auth, "forgot_password"))
        self.assertTrue(hasattr(route_health, "health"))
        self.assertTrue(hasattr(route_home, "va_main"))
        self.assertTrue(hasattr(route_home, "va_index"))
        self.assertTrue(hasattr(route_profile, "profile"))
        self.assertTrue(hasattr(route_profile, "force_password_change"))
        self.assertTrue(hasattr(http_errors, "register_error_handlers"))
        self.assertTrue(hasattr(route_helpers, "active_session_required"))

    def test_deprecated_route_support_imports_are_not_reintroduced(self):
        repo_root = Path(__file__).resolve().parents[2]
        deprecated_imports = (
            "app.routes.admin_support",
            "app.admin_support.http",
            "app.admin_support.grants",
            "app.admin_support.serializers",
            "app.routes.errors",
        )
        ignored_dirs = {".git", ".venv", "__pycache__"}

        for path in repo_root.rglob("*.py"):
            if path == Path(__file__).resolve():
                continue
            if ignored_dirs.intersection(path.parts):
                continue
            text = path.read_text()
            for deprecated_import in deprecated_imports:
                self.assertNotIn(
                    deprecated_import,
                    text,
                    msg=f"{path.relative_to(repo_root)} imports {deprecated_import}",
                )

    def test_workflow_forms_package_exports_stable_patch_points(self):
        self.assertIs(workflow_forms.renderpartial, workflow_renderpartial)
        self.assertTrue(hasattr(workflow_forms, "_apply_partial_cache_policy"))
        self.assertTrue(hasattr(workflow_forms, "_get_display_initial_assessment"))
        self.assertTrue(hasattr(workflow_forms, "bust_coder_dashboard_cache"))
        self.assertTrue(hasattr(workflow_forms, "get_category_rendering_service"))
        self.assertTrue(hasattr(workflow_forms, "sync_not_codeable_review_state"))

    def test_data_management_packages_export_primary_blueprints(self):
        self.assertEqual(operations_data_management.data_management.name, "data_management")
        self.assertEqual(api_data_management.bp.name, "data_management_api")
        self.assertEqual(api_v1.name, "api_v1")

    def test_admin_section_packages_export_primary_routes(self):
        self.assertTrue(hasattr(admin_activity, "admin_panel_activity"))
        self.assertTrue(hasattr(admin_activity, "_build_activity_rows"))
        self.assertTrue(hasattr(admin_users, "admin_users"))
        self.assertTrue(hasattr(admin_users, "admin_panel_users"))
        self.assertTrue(hasattr(admin_access_grants, "admin_access_grants"))
        self.assertTrue(hasattr(admin_access_grants, "admin_panel_access_grants"))
        self.assertTrue(hasattr(admin_languages, "admin_panel_languages"))
        self.assertTrue(hasattr(admin_languages, "admin_languages_list"))
        self.assertTrue(hasattr(admin_languages, "_language_aliases_by_code"))
        self.assertTrue(hasattr(admin_odk_connections, "admin_odk_connections_list"))
        self.assertTrue(hasattr(admin_odk_connections, "admin_panel_odk_connections"))
        self.assertTrue(hasattr(admin_odk_connections, "guarded_odk_call"))
        self.assertTrue(hasattr(admin_project_sites, "admin_project_sites"))
        self.assertTrue(hasattr(admin_project_sites, "admin_panel_project_sites"))
        self.assertTrue(hasattr(admin_project_sites, "_get_active_project_site"))
        self.assertTrue(hasattr(admin_project_forms, "admin_panel_project_forms"))
        self.assertTrue(hasattr(admin_project_forms, "admin_odk_site_mappings_save"))
        self.assertTrue(hasattr(admin_icd10_browser, "admin_panel_icd10_browser"))
        self.assertTrue(hasattr(admin_icd10_browser, "admin_icd10_2019_2_children"))
        self.assertTrue(hasattr(admin_cod_buckets, "admin_panel_cod_buckets"))
        self.assertTrue(hasattr(admin_cod_buckets, "admin_cod_bucket_scheme_create"))
