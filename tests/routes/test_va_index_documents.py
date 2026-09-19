"""The landing page and the WHO VA reference documents it links to.

`va_main.va_index` requires a login as of 2026-09-19 (see
docs/policy/auth-decorator-rbac.md section 3), so these render it as a
logged-in user. `va_main.who_va_document` stays public by design -- published
WHO material -- and is covered unauthenticated in
tests/routes/test_public_route_access.py.
"""
from tests.base import BaseTestCase


class VaIndexDocumentLinksTests(BaseTestCase):
    def test_vaindex_shows_who_related_document_links(self):
        self._login(self.base_coder_id)
        response = self.client.get("/vaindex")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Related Documents", html)
        self.assertIn("WHO VA Standards", html)
        self.assertIn("WHO VA 2022 Instrument", html)
        self.assertIn("Field Interviewer Manual", html)
        self.assertIn("Manual for Physician Reviewers", html)
        self.assertIn(
            "https://www.who.int/standards/classifications/other-classifications/"
            "verbal-autopsy-standards-ascertaining-and-attributing-causes-of-death-tool",
            html,
        )

    def test_who_va_document_route_serves_known_pdf(self):
        response = self.client.get("/who-va-documents/2022-va-field-interviewer-manual.pdf")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
