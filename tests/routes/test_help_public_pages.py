"""Every help page is public (owner 2026-11-06), and Help is in the
logged-out navbar. organization-demo and the live search demo stay signed-in."""

from app.routes import help as help_routes
from tests.base import BaseTestCase

_SIGNED_IN_ONLY = {"organization-demo"}


class HelpPublicPagesTests(BaseTestCase):
    def test_anonymous_visitor_opens_every_help_page(self):
        slugs = [p[0] for p in help_routes.HELP_PAGES if p[0] not in _SIGNED_IN_ONLY]
        self.assertIn("coding-workflow", slugs)
        self.assertIn("admin-overview", slugs)
        for slug in slugs:
            with self.subTest(slug=slug):
                response = self.client.get(f"/help/{slug}")
                self.assertEqual(response.status_code, 200)

    def test_help_index_lists_formerly_restricted_pages_to_anonymous(self):
        html = self.client.get("/help").get_data(as_text=True)
        self.assertIn('href="/help/dm-dashboard"', html)
        self.assertIn('href="/help/sync-behavior"', html)
        self.assertNotIn('href="/help/organization-demo"', html)

    def test_logged_out_navbar_has_help(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Login", html)
        self.assertIn('href="/help"', html)

    def test_live_search_demo_stays_signed_in(self):
        self.assertEqual(self.client.get("/help/icd-codes/search-demo").status_code, 403)
