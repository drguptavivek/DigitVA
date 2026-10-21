"""Production answers only its public host (digitva-5jp)."""

import os
import unittest
from unittest import mock

from app import create_app
from app.utils import pii_crypto
from config import TestConfig, trusted_hosts_for

# Production start needs a well-formed PII public key, key id and blind key.
_PII_PUBLIC, _ = pii_crypto.generate_keyset()


class _ProductionLikeConfig(TestConfig):
    TESTING = False
    DEBUG = False
    PII_KEM_PUBLIC_KEY = _PII_PUBLIC.to_config()
    PII_KEM_KEY_ID = _PII_PUBLIC.key_id
    PII_BLIND_INDEX_KEY = os.urandom(32).hex()
    PUBLIC_BASE_URL = "https://digitva.example.org"
    CAPTCHA_HMAC_KEY = "production-captcha-hmac-key-do-not-use-in-tests"


class _ProductionLikeConfigMissingCaptchaKey(_ProductionLikeConfig):
    CAPTCHA_HMAC_KEY = ""


class TrustedHostsTests(unittest.TestCase):
    def test_hosts_come_from_mail_base_url(self):
        self.assertEqual(
            trusted_hosts_for("https://digitva.example.org"),
            ["digitva.example.org", "localhost", "127.0.0.1"],
        )

    def test_bare_host_and_port_are_accepted(self):
        for value in (
            "digitva.example.org",
            "https://digitva.example.org:443/",
        ):
            self.assertEqual(
                trusted_hosts_for(value)[0], "digitva.example.org"
            )

    def test_missing_base_url_fails_at_startup(self):
        for value in ("", None, "  ", "https://"):
            with self.assertRaises(RuntimeError):
                trusted_hosts_for(value)

    def test_production_refuses_other_hosts(self):
        # A production-like app built in the dev container would otherwise see
        # the dev PII key under /app/private and refuse to start (the stray-key
        # guard, owner decision 13, has its own tests in tests/test_pii_crypto.py).
        with mock.patch("app.utils.pii_crypto.stray_private_key_files", return_value=[]):
            app = create_app(_ProductionLikeConfig)
        self.assertEqual(
            app.config["TRUSTED_HOSTS"],
            ["digitva.example.org", "localhost", "127.0.0.1"],
        )
        client = app.test_client()
        forged = client.get("/health", headers={"Host": "evil.example.com"})
        self.assertEqual(forged.status_code, 400)
        public = client.get(
            "/health", headers={"Host": "digitva.example.org"}
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
