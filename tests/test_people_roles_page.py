"""People & roles page shell (digitva-nk1, part 3): GET /people-roles.

The page is a login-required shell that renders no data; the rows come from
/api/v1/projects/<id>/people-roles (tests/test_people_roles.py).
"""

from tests.base import BaseTestCase


class PeopleRolesPageTests(BaseTestCase):
    URL = "/people-roles"

    def test_anonymous_is_sent_to_sign_in(self):
        response = self.client.get(self.URL)
        self.assertIn(response.status_code, (301, 302, 401))
        self.assertNotIn("panel-people-roles", response.get_data(as_text=True))

    def test_a_grant_holder_gets_the_shell_with_no_rows(self):
        self._login(self.base_coder_id)
        response = self.client.get(self.URL)
        self.assertEqual(response.status_code, 200)
        body = response.get_data(as_text=True)
        self.assertIn('id="panel-people-roles" data-locked-project=""', body)
        # The body is filled by the script: nothing about a person is server-rendered.
        self.assertIn('<tbody id="pr-rows"></tbody>', body)
        self.assertIn('<thead id="pr-head"></thead>', body)
        for person in (self.base_admin_user, self.base_project_pi_user):
            self.assertNotIn(person.email, body)
        self.assertIn("/api/v1/projects/__PROJECT__/people-roles", body)
        self.assertIn("js/admin/people_roles.js", body)

    def test_the_navbar_links_to_it_for_a_grant_holder(self):
        self._login(self.base_coder_id)
        body = self.client.get(self.URL).get_data(as_text=True)
        self.assertIn(f'href="{self.URL}"', body)
