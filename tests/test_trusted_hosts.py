"""Production answers only its public host (digitva-5jp)."""

import unittest

from app import create_app
from config import TestConfig, trusted_hosts_for


class _ProductionLikeConfig(TestConfig):
    TESTING = False
    DEBUG = False
    MAIL_BASE_URL = "https://digitva.causeofdeathindia.com"
    CAPTCHA_HMAC_KEY = "production-captcha-hmac-key-do-not-use-in-tests"


class _ProductionLikeConfigMissingCaptchaKey(_ProductionLikeConfig):
    CAPTCHA_HMAC_KEY = ""


class TrustedHostsTests(unittest.TestCase):
    def test_hosts_come_from_mail_base_url(self):
        self.assertEqual(
            trusted_hosts_for("https://digitva.causeofdeathindia.com"),
            ["digitva.causeofdeathindia.com", "localhost", "127.0.0.1"],
        )

    def test_bare_host_and_port_are_accepted(self):
        for value in (
            "digitva.causeofdeathindia.com",
            "https://digitva.causeofdeathindia.com:443/",
        ):
            self.assertEqual(
                trusted_hosts_for(value)[0], "digitva.causeofdeathindia.com"
            )

    def test_missing_base_url_fails_at_startup(self):
        for value in ("", None, "  ", "https://"):
            with self.assertRaises(RuntimeError):
                trusted_hosts_for(value)

    def test_production_refuses_other_hosts(self):
        app = create_app(_ProductionLikeConfig)
        self.assertEqual(
            app.config["TRUSTED_HOSTS"],
            ["digitva.causeofdeathindia.com", "localhost", "127.0.0.1"],
        )
        client = app.test_client()
        forged = client.get("/health", headers={"Host": "evil.example.com"})
        self.assertEqual(forged.status_code, 400)
        public = client.get(
            "/health", headers={"Host": "digitva.causeofdeathindia.com"}
        )
        self.assertNotEqual(public.status_code, 400)

    def test_test_config_accepts_any_host(self):
        app = create_app(TestConfig)
        self.assertIsNone(app.config["TRUSTED_HOSTS"])

    def test_production_requires_captcha_hmac_key(self):
        """docs/policy/authentication-factors.md section 5: production must
        sign the login CAPTCHA with its own key, not the SECRET_KEY-derived
        development fallback."""
        with self.assertRaises(RuntimeError):
            create_app(_ProductionLikeConfigMissingCaptchaKey)


if __name__ == "__main__":
    unittest.main()
