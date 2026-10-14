"""A logged-out htmx panel load answers 401, not the login page.

The admin console loads each panel into its right pane with htmx. A redirect
to the login page is followed by the browser, so the login form used to be
swapped into the pane beside a still-visible menu. A 401 instead lets base.js
show the Session Expired modal (owner, 2026-10-14).
"""

from tests.base import BaseTestCase

PANEL = "/admin/panels/project-sites"


class HtmxSessionExpiryTests(BaseTestCase):
    def test_a_full_page_request_still_redirects_to_login(self):
        response = self.client.get(PANEL)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/vaauth/valogin", response.headers["Location"])

    def test_an_htmx_panel_request_gets_401_without_the_login_page(self):
        response = self.client.get(PANEL, headers={"HX-Request": "true"})

        self.assertEqual(response.status_code, 401)
        self.assertNotIn("Location", response.headers)
        self.assertNotIn(b"password", response.data.lower())
