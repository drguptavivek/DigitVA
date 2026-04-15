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

        follow_up = self._request_from_ip("GET", "/", ip_address)
        self.assertEqual(follow_up.status_code, 200)
