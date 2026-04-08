import hashlib
from flask import Flask
from unittest import TestCase
from unittest.mock import Mock, patch

from app.utils import password_policy


class PasswordPolicyTests(TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["HIBP_PASSWORD_BREACH_CHECK_ENABLED"] = True
        password_policy._hibp_range_query.cache_clear()

    def tearDown(self):
        password_policy._hibp_range_query.cache_clear()

    def test_password_error_message_rejects_breached_password(self):
        password = "DigitVA-Breached-Password-123!"
        sha1_hex = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
        prefix, suffix = sha1_hex[:5], sha1_hex[5:]
        mock_response = Mock()
        mock_response.text = f"{suffix}:42\nOTHER:1\n"
        mock_response.raise_for_status.return_value = None

        with self.app.app_context(), patch(
            "app.utils.password_policy.requests.get", return_value=mock_response
        ) as mock_get:
            error = password_policy.password_error_message(password)

        self.assertEqual(
            error,
            "Password has been found in known breach data. Choose a different password.",
        )
        mock_get.assert_called_once()
        self.assertIn(f"/range/{prefix}", mock_get.call_args.args[0])
        self.assertEqual(mock_get.call_args.kwargs["headers"]["Add-Padding"], "true")

    def test_password_error_message_skips_breach_lookup_for_weak_password(self):
        with self.app.app_context(), patch(
            "app.utils.password_policy.requests.get"
        ) as mock_get:
            error = password_policy.password_error_message("short")

        self.assertEqual(
            error,
            "Password must have at least 12 characters, at least one uppercase letter, at least one digit, at least one special character.",
        )
        mock_get.assert_not_called()

    def test_password_error_message_returns_retryable_error_when_hibp_unavailable(self):
        with self.app.app_context(), patch(
            "app.utils.password_policy.requests.get",
            side_effect=password_policy.requests.RequestException("boom"),
        ):
            error = password_policy.password_error_message("DigitVA-Healthy-Password-123!")

        self.assertEqual(
            error,
            "Password breach check is temporarily unavailable. Please try again.",
        )
