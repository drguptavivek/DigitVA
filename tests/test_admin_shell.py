"""
Tests for the /admin shell page and panel routing (DigitVA-vgz.1).

Covers:
- Access control: unauthenticated → redirect, no role → 403
- Admin and project_pi can access the shell
- Panel fragment routes respond correctly
"""

import uuid
import unittest
from datetime import datetime, timezone

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)

from tests.base import BaseTestCase


class AdminShellAccessTests(BaseTestCase):
    """Access control for the /admin shell."""

    def _make_plain_user(self, email):
        user = VaUsers(
            user_id=uuid.uuid4(),
            name=email,
            email=email,
            vacode_language=["English"],
            permission={},
            landing_page="coder",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status=VaStatuses.active,
        )
        user.set_password("Test123")
        db.session.add(user)
        db.session.flush()
        return user

    # tearDown not needed: BaseTestCase savepoint rollback cleans up automatically.

    def test_admin_page_redirects_unauthenticated(self):
        response = self.client.get("/admin/")
        self.assertIn(response.status_code, [301, 302])

    def test_admin_page_denies_user_without_admin_or_project_pi_role(self):
        user = self._make_plain_user("shell.plain@example.com")
        self._login(str(user.user_id))

        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 403)

    def test_admin_page_renders_for_admin(self):
        self._login(self.base_admin_id)

        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"admin", response.data.lower())

    def test_admin_page_renders_for_project_pi(self):
        self._login(self.base_project_pi_id)

        response = self.client.get("/admin/")

        self.assertEqual(response.status_code, 200)

    def test_admin_page_accessible_without_trailing_slash(self):
        self._login(self.base_admin_id)

        response = self.client.get("/admin")

        self.assertIn(response.status_code, [200, 301, 308])


class AdminPanelRoutingTests(BaseTestCase):
    """Panel fragment routes are accessible to authorised users."""

    PANELS = [
        "/admin/panels/access-grants",
        "/admin/panels/project-sites",
        "/admin/panels/activity",
        "/admin/panels/projects",
    ]

    # Panels behind role_required("admin"): a project_pi gets 403, not a page.
    ADMIN_ONLY_PANELS = {"/admin/panels/activity", "/admin/panels/projects"}

    def test_panel_redirects_unauthenticated(self):
        for url in self.PANELS:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertIn(response.status_code, [301, 302])

    def test_panels_render_for_admin(self):
        self._login(self.base_admin_id)
        for url in self.PANELS:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_panels_render_for_project_pi(self):
        self._login(self.base_project_pi_id)
        for url in self.PANELS:
            with self.subTest(url=url):
                response = self.client.get(url)
                if url in self.ADMIN_ONLY_PANELS:
                    self.assertEqual(response.status_code, 403)
                else:
                    self.assertEqual(response.status_code, 200)

    def test_panels_accept_project_id_query_param(self):
        self._login(self.base_admin_id)
        for url in self.PANELS:
            with self.subTest(url=url):
                response = self.client.get(f"{url}?project_id={self.BASE_PROJECT_ID}")
                self.assertEqual(response.status_code, 200)

    def test_projects_panel_renders_the_web_form_language_inputs(self):
        """The tier-2 web form options are editable from the Projects panel.

        docs/policy/va-web-form-options.md: three of the four columns are set
        from here. The available web form languages come from the bundled
        questionnaire (/admin/api/web-form-locales) and the narration languages
        from mas_languages (/admin/api/languages). There is no per-project
        default locale to edit — it is always "en".
        """
        self._login(self.base_admin_id)

        response = self.client.get("/admin/panels/projects")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        for marker in (
            "project-web-intake-all-locales-input",
            "project-web-intake-available-locales-list",
            "project-web-intake-narration-languages-list",
            "project-web-intake-show-guidance-input",
            "/admin/api/web-form-locales",
            "/admin/api/languages",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, body)
        self.assertNotIn("project-web-intake-default-locale-input", body)

    def test_projects_panel_renders_the_web_questionnaire_inputs(self):
        """The web form type and the two extensions are edited from here.

        WP1 of docs/planning/web-capture-project-configuration-plan.md. The
        form types come from /admin/api/web-form-types, which also carries the
        default welcome note: the panel is a JSON client, so nothing about
        these settings is rendered into the page.
        """
        self._login(self.base_admin_id)

        response = self.client.get("/admin/panels/projects")

        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        # The id is asserted in its `id="..."` form: the panel's JavaScript
        # mentions every id it reads, so a bare substring would pass even if
        # the input itself were gone.
        for marker in (
            'id="project-web-intake-form-type-input"',
            'id="project-web-intake-intake-note-input"',
            'id="project-web-intake-intake-note-default-btn"',
            'id="project-web-intake-death-summary-input"',
            "/admin/api/web-form-types",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, body)

    def test_panel_response_is_html_fragment(self):
        """Panel responses must be HTML, not JSON — they are HTMX targets."""
        self._login(self.base_admin_id)
        for url in self.PANELS:
            with self.subTest(url=url):
                response = self.client.get(url)
                ct = response.content_type
                self.assertIn("text/html", ct, f"{url} returned {ct}")
