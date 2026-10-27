"""Public privacy policy, contact us, and consent and data requests pages (digitva-gyfj)."""
from unittest.mock import patch

from tests.base import BaseTestCase

PAGES = {
    "/privacy": ["Privacy policy", "What we collect", "Consent", "If the informant says no", "Sharing", "How long we keep it", "Storage and security", "Device permissions"],
    "/contact": ["Contact", "Operated by"],
    "/data-requests": ["Withdraw or change your consent", "Request deletion of your account and data", "What is deleted", "What is kept"],
}


class PublicPagesTest(BaseTestCase):
    def test_signed_out_pages_render_with_sections_and_no_placeholders(self):
        blank = dict(PUBLIC_ORG_NAME="", PUBLIC_CONTACT_EMAIL="", PUBLIC_GRIEVANCE_OFFICER="", PUBLIC_POSTAL_ADDRESS="")
        for path, sections in PAGES.items():
            with self.subTest(path=path), patch.dict(self.app.config, blank):
                body = self.client.get(path).get_data(as_text=True)
                for text in sections:
                    self.assertIn(text, body)
                self.assertIn("the DigitVA programme team", body)
                self.assertNotIn("[", body.split("<body", 1)[1].split("<script", 1)[0])

    def test_status_200(self):
        for path in PAGES:
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_configured_details_appear(self):
        cfg = dict(
            PUBLIC_ORG_NAME="Example Org",
            PUBLIC_CONTACT_EMAIL="privacy@example.org",
            PUBLIC_GRIEVANCE_OFFICER="A. Officer",
            PUBLIC_POSTAL_ADDRESS="1 Example Road",
        )
        with patch.dict(self.app.config, cfg):
            body = self.client.get("/data-requests").get_data(as_text=True)
        for text in ("Example Org", "mailto:privacy@example.org", "A. Officer", "1 Example Road"):
            self.assertIn(text, body)

    def test_footer_links_on_login(self):
        body = self.client.get("/vaauth/va_login").get_data(as_text=True)
        for path in PAGES:
            self.assertIn(f'href="{path}"', body)

    def test_site_env_label_in_header_and_title(self):
        with patch.dict(self.app.config, SITE_ENV_LABEL="DEMO"):
            body = self.client.get("/privacy").get_data(as_text=True)
        self.assertIn(">DEMO</span>", body)
        self.assertRegex(body, r"<title>\s*DEMO - DigitVA")
        with patch.dict(self.app.config, SITE_ENV_LABEL=""):
            body = self.client.get("/privacy").get_data(as_text=True)
        self.assertIn("<title>", body)
        self.assertNotIn(">DEMO</span>", body)
        self.assertNotIn("DEMO - DigitVA", body)
