import uuid
from flask import url_for
from tests.base import BaseTestCase


class RateLimitingTests(BaseTestCase):
    def test_login_rate_limiting(self):
        """Verify that the login endpoint is rate limited."""
        # 10 per minute is the limit. 11th request should be blocked.
        with self.app.test_request_context():
            login_url = url_for("va_auth.va_login")
        
        # We need to use a fresh user email each time if we were actually logging in,
        # but for rate limiting, it's based on the remote address.
        # Since we're in a test client, the address is typically 127.0.0.1.
        
        for i in range(10):
            response = self.client.post(
                login_url,
                data={"email": f"test{i}@example.com", "password": "password"},
                headers=self._csrf_headers()
            )
            # Not 429
            self.assertNotEqual(response.status_code, 429)
            
        # 11th request should be rate limited
        response = self.client.post(
            login_url,
            data={"email": "blocked@example.com", "password": "password"},
            headers=self._csrf_headers()
        )
        self.assertEqual(response.status_code, 429)

    def test_admin_sync_polling_endpoints_are_not_globally_rate_limited(self):
        """Dashboard polling endpoints should not consume the low global IP budget."""
        self._login(self.base_admin_id)

        endpoints = [
            "/admin/api/sync/status",
            "/admin/api/sync/history?limit=20",
            "/admin/api/sync/progress",
        ]

        for _ in range(25):
            for endpoint in endpoints:
                response = self.client.get(endpoint)
                self.assertNotEqual(
                    response.status_code,
                    429,
                    msg=f"{endpoint} unexpectedly hit the global rate limit",
                )
