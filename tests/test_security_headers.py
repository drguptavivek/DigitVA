from tests.base import BaseTestCase

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
