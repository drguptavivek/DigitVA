import uuid

from tests.base import BaseTestCase


class RequestMethodAbuseControlTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        suffix = uuid.uuid4().hex
        self._method_ban_config = {
            "METHOD_NOT_ALLOWED_BAN_THRESHOLD": self.app.config[
                "METHOD_NOT_ALLOWED_BAN_THRESHOLD"
            ],
            "METHOD_NOT_ALLOWED_BAN_WINDOW_SECONDS": self.app.config[
                "METHOD_NOT_ALLOWED_BAN_WINDOW_SECONDS"
            ],
            "METHOD_NOT_ALLOWED_BAN_SECONDS": self.app.config[
                "METHOD_NOT_ALLOWED_BAN_SECONDS"
            ],
            "METHOD_NOT_ALLOWED_BAN_COUNTER_PREFIX": self.app.config[
                "METHOD_NOT_ALLOWED_BAN_COUNTER_PREFIX"
            ],
            "METHOD_NOT_ALLOWED_BAN_PREFIX": self.app.config[
                "METHOD_NOT_ALLOWED_BAN_PREFIX"
            ],
        }
        self.app.config.update(
            METHOD_NOT_ALLOWED_BAN_COUNTER_PREFIX=(
                f"digitva_test_method_not_allowed:count:{suffix}:"
            ),
            METHOD_NOT_ALLOWED_BAN_PREFIX=(
                f"digitva_test_method_not_allowed:ban:{suffix}:"
            ),
        )

    def tearDown(self):
        self.app.config.update(self._method_ban_config)
        super().tearDown()

    def _request_from_ip(self, method, path, ip_address, **kwargs):
        return self.client.open(
            path,
            method=method,
            environ_base={"REMOTE_ADDR": ip_address},
            **kwargs,
        )

    def test_repeated_post_method_not_allowed_temporarily_bans_ip(self):
        self.app.config.update(
            METHOD_NOT_ALLOWED_BAN_THRESHOLD=3,
            METHOD_NOT_ALLOWED_BAN_WINDOW_SECONDS=300,
            METHOD_NOT_ALLOWED_BAN_SECONDS=600,
        )
        ip_address = "203.0.113.10"

        for _ in range(3):
            response = self._request_from_ip(
                "POST",
                "/",
                ip_address,
                headers=self._csrf_headers(),
            )
            self.assertEqual(response.status_code, 405)

        blocked = self._request_from_ip("GET", "/", ip_address)
        self.assertEqual(blocked.status_code, 403)
        self.assertIn(
            "Access temporarily blocked",
            blocked.get_data(as_text=True),
        )
        self.assertIsNotNone(blocked.headers.get("Retry-After"))

    def test_repeated_patch_method_not_allowed_blocks_api_with_json(self):
        self.app.config.update(
            METHOD_NOT_ALLOWED_BAN_THRESHOLD=2,
            METHOD_NOT_ALLOWED_BAN_WINDOW_SECONDS=300,
            METHOD_NOT_ALLOWED_BAN_SECONDS=900,
        )
        ip_address = "203.0.113.11"

        for _ in range(2):
            response = self._request_from_ip(
                "PATCH",
                "/",
                ip_address,
                headers=self._csrf_headers(),
            )
            self.assertEqual(response.status_code, 405)

        blocked = self._request_from_ip("GET", "/api/does-not-exist", ip_address)
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(
            blocked.get_json()["error"],
            self.app.config["METHOD_NOT_ALLOWED_BAN_MESSAGE"],
        )

    def test_not_found_post_does_not_trigger_method_not_allowed_ban(self):
        self.app.config.update(
            METHOD_NOT_ALLOWED_BAN_THRESHOLD=2,
            METHOD_NOT_ALLOWED_BAN_WINDOW_SECONDS=300,
            METHOD_NOT_ALLOWED_BAN_SECONDS=900,
        )
        ip_address = "203.0.113.12"

        for _ in range(2):
            response = self._request_from_ip(
                "POST",
                "/missing-route",
                ip_address,
                headers=self._csrf_headers(),
            )
            self.assertEqual(response.status_code, 404)

        # Probe a public page: "/" now requires login and would answer 302
        # whether or not the IP is banned, which proves nothing. /help goes
        # through the same before_request ban check and is public by design.
        follow_up = self._request_from_ip("GET", "/help", ip_address)
        self.assertEqual(follow_up.status_code, 200)

    def test_cache_outage_fails_open_on_every_path(self):
        # digitva-248z: Flask-Caching raises when Redis is down; the ban check
        # runs on every request and the 405 recorder on every 405.
        from unittest import mock

        with mock.patch(
            "app.services.request_abuse_service.cache.get",
            side_effect=ConnectionError("redis down"),
        ):
            ok = self._request_from_ip("GET", "/health", "203.0.113.20")
            page = self._request_from_ip("GET", "/", "203.0.113.20")
            wrong_method = self._request_from_ip("POST", "/", "203.0.113.20")

        self.assertEqual(ok.status_code, 200)
        self.assertNotEqual(page.status_code, 500)
        self.assertEqual(wrong_method.status_code, 405)

    def test_rate_limiter_swallows_storage_errors(self):
        # digitva-248z: Flask-Limiter uses Redis too; it must not 500 the app.
        self.assertTrue(self.app.config["RATELIMIT_SWALLOW_ERRORS"])
