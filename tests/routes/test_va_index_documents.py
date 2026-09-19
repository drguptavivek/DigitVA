from tests.base import BaseTestCase


class VaIndexDocumentLinksTests(BaseTestCase):
    def test_vaindex_shows_who_related_document_links(self):
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
