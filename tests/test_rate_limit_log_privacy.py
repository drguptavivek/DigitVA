"""Rate-limit breaches never log the identifier a limit is keyed on (digitva-4koe).

Flask-Limiter logs every breach with its limit key; per-identifier limits key
on an email or mobile number. app/__init__.py's filter on the "flask-limiter"
logger keeps the line and drops the key.
"""

import logging
from unittest import mock

from tests.routes import test_device_api as device_tests
from tests.test_account_onboarding import OnboardingTestBase, _captured_logs
from tests.test_mobile_sign_in import _number


class RateLimitLogPrivacyTests(OnboardingTestBase):
    def test_sign_in_code_breach_logs_no_identifier(self):
        client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        number = _number()
        with _captured_logs() as lines:
            statuses = [
                client.post(
                    "/api/v1/auth/sign-in-code/redeem",
                    json={"identifier": number, "code": "WRONGCODE", "accept_terms": True},
                    environ_overrides={"REMOTE_ADDR": f"10.86.0.{i + 1}"},
                ).status_code
                for i in range(11)
            ]
        self.assertEqual(statuses[-1], 429)
        text = "\n".join(lines)
        # The breach line is still there, without its key.
        self.assertIn("ratelimit 10 per 1 hour (key hidden) exceeded", text)
        self.assertNotIn(number, text)

    def test_filter_leaves_other_limiter_lines_alone(self):
        records = []

        class Keep(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        logger = logging.getLogger("flask-limiter")
        handler, level = Keep(), logger.level
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            logger.info("Rate limit storage recovered")
            logger.info("ratelimit %s (%s) exceeded at endpoint: %s", "3 per 1 hour", "user@example.com", "x.y")
        finally:
            logger.removeHandler(handler)
            logger.setLevel(level)
        self.assertEqual(records, ["Rate limit storage recovered",
                                   "ratelimit 3 per 1 hour (key hidden) exceeded at endpoint: x.y"])


class MobileLengthTests(OnboardingTestBase):
    """Sign-in screens take a mobile number of at most 16 characters (owner
    2026-11-19); the API and the web forms refuse longer the same way."""

    TOO_LONG = "+91 98765 43210 0"  # 17 characters

    def test_api_sign_in_endpoints_refuse_a_long_mobile_number(self):
        client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        cases = (
            ("/api/v1/auth/sessions", {"email": self.TOO_LONG, "password": "x", "device_id": "d", "device_secret": "s"}, "email"),
            ("/api/v1/auth/password-enroll", {"identifier": self.TOO_LONG, "password": "x"}, "identifier"),
            ("/api/v1/auth/sign-in-code/redeem", {"identifier": self.TOO_LONG, "code": "ABCD", "accept_terms": True}, "identifier"),
            ("/api/v1/auth/forgot-password", {"identifier": self.TOO_LONG}, "identifier"),
        )
        for i, (url, body, field) in enumerate(cases):
            with self.subTest(url=url):
                response = client.post(url, json=body, environ_overrides={"REMOTE_ADDR": f"10.87.0.{i + 1}"})
                self.assertEqual(response.status_code, 400, response.get_json())
                self.assertEqual(response.get_json()["code"], "invalid_request")
                self.assertEqual(response.get_json()["fields"], [field])

    def test_web_forms_refuse_a_long_mobile_number(self):
        from app.forms.password_reset_form import ForgotPasswordForm
        from app.forms.va_login_form import EmailStepForm, RedeemCodeForm

        with self.app.test_request_context(method="POST"):
            for form_class, field in ((EmailStepForm, "email"), (RedeemCodeForm, "mobile"), (ForgotPasswordForm, "email")):
                with self.subTest(form=form_class.__name__):
                    long_form = form_class(meta={"csrf": False}, data={field: self.TOO_LONG})
                    long_form.validate()
                    self.assertIn("A mobile number has at most 16 characters.", getattr(long_form, field).errors)
                    ok_form = form_class(meta={"csrf": False}, data={field: "+91 98765 43210"})
                    ok_form.validate()
                    self.assertEqual(getattr(ok_form, field).errors, [])


class RateLimitKeyPrivacyTests(OnboardingTestBase):
    """Per-identifier limit keys are Redis keys: they hold an HMAC of the
    email, mobile number or username, never the value (digitva-mu7m)."""

    def _keys(self):
        from app import limiter
        return [str(k) for k in limiter.storage.storage]

    def test_identifier_limit_keys_hold_no_raw_identifier(self):
        client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        email, number, username = "mu7m.private@example.com", _number(), "mu7m_private_user"
        posts = (
            ("/api/v1/auth/sessions", {"json": {"email": email, "password": "x", "device_id": "d", "device_secret": "s"}}),
            ("/api/v1/auth/password-enroll", {"json": {"identifier": number, "password": "x"}}),
            ("/api/v1/auth/sign-in-code/redeem", {"json": {"identifier": number, "code": "ABCD", "accept_terms": True}}),
            ("/api/v1/auth/forgot-password", {"json": {"identifier": email}}),
            ("/api/v1/auth/demo-enroll", {"json": {"username": username, "password": "x"}}),
            ("/vaauth/valogin", {"data": {"email": email}}),
            ("/vaauth/valogin/code", {"data": {"mobile": number, "code": "ABCD"}}),
        )
        # CSRF refuses a bare web POST before the limiter counts it.
        with mock.patch.dict(self.app.config, WTF_CSRF_ENABLED=False):
            for i, (url, kwargs) in enumerate(posts):
                client.post(url, environ_overrides={"REMOTE_ADDR": f"10.88.0.{i + 1}"}, **kwargs)
        keys = self._keys()
        # The subject is there: every identifier limit counted, as a digest.
        for endpoint in ("open_session", "password_enroll", "redeem_sign_in_code", "forgot_password",
                         "demo_enroll", "va_auth.va_login/", "va_login_redeem_code"):
            with self.subTest(endpoint=endpoint):
                self.assertTrue([k for k in keys if "digest:" in k and endpoint in k], keys)
        canonical = number[-10:]
        for raw in (email, number, canonical, username):
            with self.subTest(raw=raw):
                self.assertFalse([k for k in keys if raw in k])
