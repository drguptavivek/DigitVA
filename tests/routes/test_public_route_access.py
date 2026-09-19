"""What an anonymous visitor may and may not reach.

`tests/test_route_auth_coverage.py` proves each route *declares* a guard or is
on `PUBLIC_BY_DESIGN`. That is a statement about decorators; this module is the
runtime counterpart, exercising the two halves of the 2026-09-19 decision
recorded in docs/policy/auth-decorator-rbac.md section 3:

  - the landing page (`/`, `/index`, `/vaindex`) now requires a login, and an
    anonymous GET must *redirect to the login form* rather than 401 -- which is
    what `login_manager.login_view = "va_auth.va_login"` buys, and what would
    silently regress if that setting were dropped;
  - the help/docs surface and the WHO reference PDFs stay reachable logged out.
"""
from tests.base import BaseTestCase

LOGIN_PATH = "/vaauth/valogin"


class LandingPageRequiresLoginTests(BaseTestCase):
    def test_anonymous_get_root_redirects_to_login(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 302)
        self.assertIn(LOGIN_PATH, response.headers["Location"])

    def test_logged_in_get_root_renders(self):
        self._login(self.base_coder_id)
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)

    def test_login_page_does_not_redirect_anonymous_visitors(self):
        """No loop: `/` sends an anonymous visitor to the login form, so the
        login form itself must answer them with 200. It redirects only when
        `current_user.is_authenticated`."""
        response = self.client.get(LOGIN_PATH)

        self.assertEqual(response.status_code, 200)


class PublicByDesignRoutesTests(BaseTestCase):
    def test_anonymous_get_help_docs_index(self):
        response = self.client.get("/help/docs")

        self.assertEqual(response.status_code, 200)

    def test_anonymous_get_roleless_help_page(self):
        """`getting-started` is registered with `roles=None`, so `help.page`'s
        in-body `_user_has_role` check admits an anonymous visitor."""
        response = self.client.get("/help/getting-started")

        self.assertEqual(response.status_code, 200)

    def test_anonymous_get_role_restricted_help_page_is_forbidden(self):
        """The other half of `help.page` being public: its in-body role filter
        is the guard, and dropping it would open every admin help page."""
        response = self.client.get("/help/admin-overview")

        self.assertEqual(response.status_code, 403)

    def test_anonymous_get_forgot_password_form(self):
        """Account recovery runs, by definition, with no session. The view
        redirects only when `current_user.is_authenticated`."""
        response = self.client.get("/vaauth/forgot-password")

        self.assertEqual(response.status_code, 200)

    def test_anonymous_get_who_va_document(self):
        response = self.client.get(
            "/who-va-documents/2022-va-field-interviewer-manual.pdf"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
