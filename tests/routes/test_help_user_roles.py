"""Public User Roles help page: one anchored section per role."""

from app.models import VaAccessRoles
from tests.base import BaseTestCase


class HelpUserRolesTests(BaseTestCase):
    def test_page_has_an_anchor_for_every_role(self):
        response = self.client.get("/help/user-roles")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('id="role-coder"', html)
        for role in VaAccessRoles:
            self.assertIn(f'id="role-{role.value}"', html)
        self.assertIn('id="role-death_reporter"', html)
        self.assertIn("Planned &mdash; not available yet", html)

    def test_data_manager_section_has_no_stale_unit_gap(self):
        html = self.client.get("/help/user-roles").get_data(as_text=True)
        start = html.index('id="role-data_manager"')
        section = html[start:html.index("</section>", start)]

        self.assertIn("covers that unit and everything below it", section)
        self.assertNotIn("Known gap", section)
