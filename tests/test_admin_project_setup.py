"""Project Setup home panel (epic digitva-r1p, phase 1).

One page per project: admin only (the Projects panel's gate), 404 for an
unknown project, and the Basics section embeds the Projects panel's edit form
locked to that project rather than a second copy of it.
"""

from tests.base import BaseTestCase


class ProjectSetupPanelTests(BaseTestCase):

    def _url(self, project_id=None):
        return f"/admin/panels/project-setup/{project_id or self.BASE_PROJECT_ID}"

    def test_it_redirects_unauthenticated(self):
        self.assertIn(self.client.get(self._url()).status_code, [301, 302])

    def test_a_project_pi_is_refused_even_for_their_own_project(self):
        self._login(self.base_project_pi_id)
        self.assertEqual(self.client.get(self._url()).status_code, 403)

    def test_a_coder_is_refused(self):
        self._login(self.base_coder_id)
        self.assertEqual(self.client.get(self._url()).status_code, 403)

    def test_an_unknown_project_is_404(self):
        self._login(self.base_admin_id)
        self.assertEqual(self.client.get(self._url("NOPE99")).status_code, 404)

    def test_it_renders_for_an_admin(self):
        self._login(self.base_admin_id)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.content_type)
        body = response.get_data(as_text=True)
        for marker in (
            'id="panel-project-setup"',
            f'data-project-id="{self.BASE_PROJECT_ID}"',
            "/web-intake-readiness",
            "Active sites",
            'data-section="overview"',
            'data-section="basics"',
            'data-section="sync"',
            # Placeholder sections hand over to the existing panels.
            'data-panel-link="/admin/panels/project-forms"',
            'data-panel-link="/admin/panels/access-grants"',
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, body)

    def test_basics_embeds_the_projects_form_locked_to_the_project(self):
        self._login(self.base_admin_id)
        body = self.client.get(self._url()).get_data(as_text=True)
        self.assertIn(f'data-locked-project="{self.BASE_PROJECT_ID}"', body)
        self.assertIn('id="project-submit-btn"', body)
        # One form, not a copy: the Projects panel's form ids appear once.
        self.assertEqual(body.count('id="project-name-input"'), 1)

    def test_the_projects_panel_itself_is_not_locked(self):
        self._login(self.base_admin_id)
        body = self.client.get("/admin/panels/projects").get_data(as_text=True)
        self.assertIn('data-locked-project=""', body)
        self.assertIn("project-setup-btn", body)

    def test_the_shell_restores_a_setup_panel_from_the_url(self):
        self._login(self.base_admin_id)
        body = self.client.get("/admin/").get_data(as_text=True)
        self.assertIn(r"^\/admin\/panels\/project-setup\/[A-Za-z0-9_-]+$", body)
