"""What an anonymous visitor may and may not reach.

`tests/test_route_auth_coverage.py` proves each route *declares* a guard or is
on `PUBLIC_BY_DESIGN`. That is a statement about decorators; this module is the
runtime counterpart, exercising the two halves of the 2026-09-19 decision
recorded in docs/policy/auth-decorator-rbac.md section 3:

  - the landing page (`/`, `/index`, `/vaindex`) is the public home page; the
    system has a dedicated login page, so `/` must answer an anonymous visitor
    with 200, never bounce them to the login form;
  - the help/docs surface and the WHO reference PDFs stay reachable logged out.
"""
from tests.base import BaseTestCase

LOGIN_PATH = "/vaauth/valogin"


class LandingPageIsPublicTests(BaseTestCase):
    def test_anonymous_get_root_renders_home_page(self):
        for path in ("/", "/index", "/vaindex"):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("Location", response.headers)

    def test_logged_in_get_root_renders(self):
        self._login(self.base_coder_id)
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)

    def test_login_page_answers_anonymous_visitors(self):
        """The dedicated login page must render for an anonymous visitor; it
        redirects only when `current_user.is_authenticated`."""
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
