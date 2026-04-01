from tests.base import BaseTestCase
from config import Config

class SecurityHeadersTests(BaseTestCase):
    def test_security_headers_present(self):
        """Verify that basic security headers are present in the response."""
        response = self.client.get("/")
        
        # Check for Flask-Talisman headers
        self.assertIn("Content-Security-Policy", response.headers)
        # HSTS is only sent by Talisman when force_https=True.
        # In our TestConfig, app.testing=True, so force_https=False by default.
        # self.assertIn("Strict-Transport-Security", response.headers)
        
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(response.headers.get("X-Frame-Options"), "DENY")
        self.assertEqual(response.headers.get("X-XSS-Protection"), "1; mode=block")
        self.assertIn("Referrer-Policy", response.headers)

    def test_csp_policy(self):
        """Verify the Content-Security-Policy content."""
        response = self.client.get("/")
        csp = response.headers.get("Content-Security-Policy")
        
        # Check for essential CSP directives
        self.assertIn("default-src 'self'", csp)
        self.assertIn("script-src 'self' 'unsafe-inline'", csp)
        self.assertIn("style-src 'self' 'unsafe-inline'", csp)
        self.assertIn("img-src 'self' data:", csp)

    def test_static_assets_are_served_with_long_cache_ttl(self):
        response = self.client.get("/static/css/base.css")

        self.assertEqual(response.status_code, 200)
        cache_control = response.headers.get("Cache-Control", "")
        self.assertIn("public", cache_control)
        self.assertIn("max-age=2592000", cache_control)

    def test_default_cookie_security_policy(self):
        self.assertTrue(Config.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(Config.SESSION_COOKIE_SAMESITE, "Lax")
        self.assertTrue(Config.SESSION_COOKIE_SECURE)
        self.assertTrue(Config.REMEMBER_COOKIE_HTTPONLY)
        self.assertEqual(Config.REMEMBER_COOKIE_SAMESITE, "Lax")
        self.assertTrue(Config.REMEMBER_COOKIE_SECURE)
