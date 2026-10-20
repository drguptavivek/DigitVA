"""Public Data Collection help page, navigation order, and contextual help API."""

from app.routes import help as help_routes
from app.services.contextual_help_service import (
    CONTEXTUAL_HELP_PAGES,
    resolve_flask_page_key,
)
from tests.base import BaseTestCase


class HelpDataCollectionTests(BaseTestCase):
    def test_data_collection_is_between_roles_and_coding_in_help_navigation(self):
        response = self.client.get("/help")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        user_roles = html.index('href="/help/user-roles"')
        data_collection = html.index('href="/help/data-collection"')
        coding = html.index('data-category="Coding Workflow"')
        self.assertLess(user_roles, data_collection)
        self.assertLess(data_collection, coding)

        slugs = [page[0] for page in help_routes.HELP_PAGES]
        self.assertLess(slugs.index("user-roles"), slugs.index("data-collection"))
        self.assertLess(slugs.index("data-collection"), slugs.index("demo-coding"))

    def test_page_is_public_and_covers_form_sources_workflow_and_matrix(self):
        response = self.client.get("/help/data-collection")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        for anchor in (
            'id="who-can-collect"',
            'id="interviewer-steps"',
            'id="odk-and-web"',
            'id="identifiers"',
            'id="form-matrix"',
            'id="form-field-legend"',
            'id="extensions"',
            'id="adaptations"',
        ):
            self.assertIn(anchor, html)

        for phrase in (
            "WHO_2022_VA",
            "2026081401",
            "interviewer",
            "death_reporter",
            "interview_supervisor",
            "org_&lt;level_code&gt;_code",
            "ND01_ICMRVA_WHOVA2022.xlsx",
            "UNSW01KA0101",
            "UNSW01KL0101",
            "UNSW01TR0101",
            "NC01 workbook was unavailable",
            "No JIPMER workbook is treated as an UNSW source",
            "Id10476",
            "DORIS",
            "sourceType",
            "no question-level relevance",
            "ancestor group's relevance gate",
        ):
            self.assertIn(phrase, html)
        self.assertNotIn("Answer-gated", html)
        self.assertNotIn("Workflow-gated", html)
        self.assertNotIn(">Conditional<", html)

        self.assertIn(
            'href="/static/help/digitva-form-field-matrix.xlsx"',
            html,
        )
        self.assertIn('href="/help/docs/who-form-overrides"', html)

    def test_override_policy_is_available_through_engineering_docs(self):
        response = self.client.get("/help/docs/who-form-overrides")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("DigitVA WHO Form Overrides", html)
        self.assertIn("DigitVA overrides and extensions to the WHO VA form", html)

    def test_contextual_help_api_returns_all_pages_and_single_page(self):
        self._login(self.base_coder_id)

        all_resp = self.client.get("/api/v1/help/contextual")
        self.assertEqual(all_resp.status_code, 200)
        payload = all_resp.get_json()
        self.assertIn("pages", payload)
        for expected_key in (
            "home",
            "deathRegistration",
            "myRegisteredDeaths",
            "collection",
            "interview",
            "caseDetail",
            "coding",
            "caseCoding",
            "reviewing",
            "caseReviewing",
            "caseView",
            "supervision",
            "mentoring",
            "organization",
            "settings",
            "area",
            "sitepi",
            "dataManagement",
            "dmKpi",
            "codBuckets",
            "peopleRoles",
            "translations",
            "profile",
            "admin",
            "admin_projects",
            "admin_project-setup",
            "admin_organization",
            "admin_access-grants",
            "admin_project-sites",
            "admin_mentor-institutes",
            "admin_project-forms",
            "admin_project-pi",
            "admin_sites",
            "admin_users",
            "admin_languages",
            "admin_odk-connections",
            "admin_field-mapping",
            "admin_cod-buckets",
            "admin_icd10-browser",
            "admin_icd11-browser",
            "admin_icd-search-vocabulary",
            "admin_va-definitions",
            "admin_instrument-translations",
            "admin_ui-strings",
            "admin_sync",
            "admin_attachments",
            "admin_activity",
            "admin_system-health",
        ):
            self.assertIn(expected_key, payload["pages"])

        single_resp = self.client.get("/api/v1/help/contextual/coding")
        self.assertEqual(single_resp.status_code, 200)
        entry = single_resp.get_json()
        self.assertEqual(entry["page_key"], "coding")
        self.assertIn("Stage 3 of 5", entry["stage_badge"])
        self.assertTrue(len(entry["bullets"]) >= 3)
        self.assertTrue(len(entry["sections"]) >= 1)
        self.assertEqual(entry["help_slug"], "/help/coding-workflow")

        admin_panel_resp = self.client.get("/api/v1/help/contextual/admin_organization")
        self.assertEqual(admin_panel_resp.status_code, 200)
        admin_panel_entry = admin_panel_resp.get_json()
        self.assertEqual(admin_panel_entry["page_key"], "admin_organization")
        self.assertEqual(admin_panel_entry["stage_badge"], "Admin · Health Hierarchy")
        self.assertTrue(len(admin_panel_entry["bullets"]) >= 3)
        self.assertTrue(len(admin_panel_entry["sections"]) >= 2)

        missing_resp = self.client.get("/api/v1/help/contextual/nonexistentPage")
        self.assertEqual(missing_resp.status_code, 404)

    def test_flask_pages_render_in_page_contextual_help_banner(self):
        self.assertEqual(resolve_flask_page_key("profile.view", "/profile"), "profile")
        self.assertEqual(resolve_flask_page_key("admin.index", "/admin"), "admin")
        self.assertEqual(
            resolve_flask_page_key("admin.index", "/admin", "/admin/panels/organization"),
            "admin_organization",
        )
        self.assertEqual(
            resolve_flask_page_key("admin.index", "/admin", "/admin/panels/project-setup/PRJ01"),
            "admin_project-setup",
        )
        self.assertEqual(
            resolve_flask_page_key("data_management.kpi_dashboard", "/data-management/kpi"),
            "dmKpi",
        )
        self.assertIsNone(resolve_flask_page_key("help.index", "/help"))
        self.assertIsNone(resolve_flask_page_key("va_auth.va_login", "/vaauth/valogin"))

        self._login(self.base_admin_id)
        profile_resp = self.client.get("/profile/")
        self.assertEqual(profile_resp.status_code, 200)
        profile_html = profile_resp.get_data(as_text=True)
        self.assertIn('id="contextual-page-help"', profile_html)
        self.assertIn('data-page-key="profile"', profile_html)
        self.assertIn(CONTEXTUAL_HELP_PAGES["profile"]["summary"], profile_html)

        admin_resp = self.client.get("/admin/")
        self.assertEqual(admin_resp.status_code, 200)
        admin_html = admin_resp.get_data(as_text=True)
        self.assertIn('id="contextual-page-help"', admin_html)
        self.assertEqual(admin_html.count('id="contextual-page-help"'), 1)
        self.assertIn('data-page-key="admin"', admin_html)
        self.assertIn(CONTEXTUAL_HELP_PAGES["admin"]["summary"], admin_html)

        admin_panel_page = self.client.get("/admin/?panel=/admin/panels/mentor-institutes")
        self.assertEqual(admin_panel_page.status_code, 200)
        admin_panel_html = admin_panel_page.get_data(as_text=True)
        self.assertIn('data-page-key="admin_mentor-institutes"', admin_panel_html)
        self.assertIn(
            CONTEXTUAL_HELP_PAGES["admin_mentor-institutes"]["summary"],
            admin_panel_html,
        )

