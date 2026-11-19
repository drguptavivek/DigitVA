"""App "Forgot password", POST /api/v1/auth/forgot-password (digitva-mb0d.3).

Baseline: docs/policy/account-onboarding-and-passwords.md sections 6 and 7.
The web page's request (shared ``request_password_reset``) as JSON: a reset
link only to a verified email, one answer per kind of identifier, 3 per hour
per IP and per identifier.
"""

import logging
from unittest import mock

from app.services import device_auth_service as devices
from app.services.authz.consulted import PUBLIC_ENDPOINTS
from app.services.user_account_service import EMAIL_FORGOT_MESSAGE, MOBILE_FORGOT_MESSAGE
from tests.routes import test_device_api as device_tests
from tests.test_account_onboarding import OnboardingTestBase, _captured_logs, _mailbox
from tests.test_mobile_sign_in import _number

URL = "/api/v1/auth/forgot-password"
ENDPOINT = "api_v1.auth_api.forgot_password"


class ForgotPasswordApiTests(OnboardingTestBase):
    def setUp(self):
        super().setUp()
        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)

    def _post(self, identifier, ip="127.0.0.1"):
        return self.client.post(URL, json={"identifier": identifier}, environ_overrides={"REMOTE_ADDR": ip})

    def _assert_message(self, response, message):
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json(), {"message": message})

    def test_verified_email_gets_a_reset_link(self):
        user = self._email_user()
        with _mailbox() as send:
            self._assert_message(self._post(f"  {user.email.upper()} "), EMAIL_FORGOT_MESSAGE)
        self.assertEqual(send.queued.call_count, 1)
        self.assertEqual(send.queued.call_args.kwargs["to"], user.email)

    def test_unverified_and_unknown_emails_get_the_same_answer_and_nothing_is_sent(self):
        unverified = self._email_user(verified=False)
        with _mailbox() as send:
            for value in (unverified.email, "nobody@example.com"):
                self._assert_message(self._post(value, ip="10.81.0.1"), EMAIL_FORGOT_MESSAGE)
        send.queued.assert_not_called()
        send.assert_not_called()

    def test_mobile_numbers_get_the_mobile_answer(self):
        number = _number()
        verified = self._email_user(phone=number)
        mobile_only = self._mobile_user()
        with _mailbox() as send:
            for i, value in enumerate((f"+91 {number}", mobile_only.mobile_login, _number())):
                self._assert_message(self._post(value, ip=f"10.82.0.{i + 1}"), MOBILE_FORGOT_MESSAGE)
        self.assertEqual(send.queued.call_count, 1)
        self.assertEqual(send.queued.call_args.kwargs["to"], verified.email)

    def test_invalid_body_is_400_before_anything_is_read(self):
        with _mailbox() as send:
            for i, body in enumerate(({}, {"identifier": ""}, {"identifier": "  "}, {"identifier": 12},
                                      {"identifier": "a" * 250 + "@x.io"})):
                response = self.client.post(URL, json=body, environ_overrides={"REMOTE_ADDR": f"10.80.0.{i + 1}"})
                self.assertEqual(response.status_code, 400, body)
                self.assertEqual(response.get_json()["code"], "invalid_request")
        send.queued.assert_not_called()

    def test_rate_limited_per_identifier_across_addresses(self):
        number = _number()
        statuses = [self._post(number if i % 2 else f"+91 {number}", ip=f"10.83.0.{i + 1}").status_code
                    for i in range(4)]
        self.assertEqual(statuses, [200, 200, 200, 429])

    def test_mobile_numbers_over_16_characters_are_refused(self):
        number = _number()
        with _mailbox() as send:
            ok = self._post(f"+91 {number[:5]} {number[5:]}", ip="10.85.0.1")  # 15 characters
            padded = self._post("  ".join(number), ip="10.85.0.2")
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(padded.status_code, 400)
        self.assertEqual(padded.get_json()["code"], "invalid_request")
        self.assertEqual(padded.get_json()["fields"], ["identifier"])
        self.assertIn("16 characters", padded.get_json()["error"])
        send.queued.assert_not_called()

    def test_a_long_email_is_not_a_mobile_number(self):
        self._assert_message(self._post("a.very.long.name.indeed@example.com", ip="10.85.0.3"),
                             EMAIL_FORGOT_MESSAGE)

    def test_rate_limited_per_address(self):
        statuses = [self._post(f"p{i}@example.com", ip="10.84.0.1").status_code for i in range(4)]
        self.assertEqual(statuses, [200, 200, 200, 429])

    def test_registered_as_unauthenticated_and_public(self):
        self.assertIn(ENDPOINT, devices.UNAUTHENTICATED_ENDPOINTS)
        self.assertIn(ENDPOINT, PUBLIC_ENDPOINTS)
        # A stale bearer and CSRF on: the app's call still answers.
        with mock.patch.dict(self.app.config, WTF_CSRF_ENABLED=True):
            response = self.client.post(URL, json={"identifier": "nobody@example.com"},
                                        headers={"Authorization": "Bearer stale-access-token"})
        self._assert_message(response, EMAIL_FORGOT_MESSAGE)

    def test_public_demo_deployment_has_no_password_reset(self):
        user = self._email_user()
        with _mailbox() as send, mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=True):
            self.assertEqual(self._post(user.email).status_code, 404)
        send.queued.assert_not_called()

    def test_identifier_is_absent_from_logs_including_the_rate_limit(self):
        user = self._email_user()
        number = _number()
        with _mailbox(), _captured_logs() as lines:
            logging.getLogger("app").info("forgot password test marker")
            self._post(user.email)
            statuses = [self._post(number, ip=f"10.85.0.{i + 1}").status_code for i in range(4)]
        self.assertEqual(statuses[-1], 429)
        text = "\n".join(lines)
        self.assertIn("forgot password test marker", text)
        for secret in (user.email, number):
            self.assertNotIn(secret, text)
