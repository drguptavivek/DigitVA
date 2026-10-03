"""Login redirect safety, inactive-user lockout and single-use reset tokens."""

import uuid
from unittest.mock import patch
from urllib.parse import urlparse

from flask import g

from app import db, limiter
from app.models import VaUsers
from app.models.va_selectives import VaStatuses
from app.services.token_service import generate_token, validate_token
from tests.base import BaseTestCase

PASSWORD = "LoginSecurity123!"
LOGIN_PATH = "/vaauth/valogin"
RESET_FORM_MARKER = b"We will email you a new password."
INVALID_LOGIN_MESSAGE = b"Invalid email or password."


class VaAuthSecurityTestBase(BaseTestCase):
    def setUp(self):
        super().setUp()
        # Login and reset POSTs are rate limited per IP; start each test clean.
        limiter.reset()
        self.user = self._make_user(
            f"auth.security.{uuid.uuid4().hex[:8]}@example.com", PASSWORD
        )
        db.session.commit()

    def _fresh_client(self):
        if hasattr(g, "_login_user"):
            del g._login_user
        self.client = self.app.test_client()

    def _post_login(self, next_url=None, password=PASSWORD):
        limiter.reset()
        self._fresh_client()
        return self._login_via_form(self.user.email, password, next_url=next_url)

    def _landing_url(self):
        with self.app.test_request_context():
            return db.session.get(VaUsers, self.user.user_id).landing_url()


class LoginNextRedirectTests(VaAuthSecurityTestBase):
    def test_unsafe_next_values_fall_back_to_landing_url(self):
        landing = self._landing_url()
        unsafe = [
            "/\\evil.com",
            "///evil.com",
            "//evil.com",
            "https://evil.com/x",
            "http://localhost.evil.com",
            "javascript:alert(1)",
            " /x",
            "/x\t",
            "relative/path",
        ]
        for next_url in unsafe:
            with self.subTest(next_url=next_url):
                resp = self._post_login(next_url)
                self.assertEqual(resp.status_code, 302)
                self.assertEqual(resp.headers["Location"], landing)

    def test_relative_path_next_is_followed(self):
        resp = self._post_login("/some/path?q=1")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["Location"], "/some/path?q=1")

    def test_same_host_absolute_next_is_followed(self):
        # role_required sends next=request.url, an absolute same-host URL.
        resp = self._post_login("http://localhost/profile/?tab=1")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["Location"], "http://localhost/profile/?tab=1")

    def test_percent_encoded_backslash_stays_on_host(self):
        resp = self._post_login("/%5Cevil.com")
        self.assertEqual(resp.status_code, 302)
        location = resp.headers["Location"]
        self.assertTrue(location.startswith("/"))
        self.assertFalse(location.startswith("//"))
        self.assertIn(urlparse(location).netloc, ("", "localhost"))


class InactiveUserLoginTests(VaAuthSecurityTestBase):
    def test_inactive_user_with_correct_password_gets_generic_error(self):
        # The account exists and the password is right while active.
        self.assertTrue(self.user.check_password(PASSWORD))
        self.user.user_status = VaStatuses.deactive
        # Unverified too: the inactive check must fire before the verify check.
        self.user.email_verified = False
        db.session.commit()

        self._fresh_client()
        resp = self._post_login()
        self.assertEqual(resp.status_code, 302)
        resp = self.client.get(resp.headers["Location"], follow_redirects=True)

        self.assertEqual(resp.status_code, 200)
        self.assertIn(INVALID_LOGIN_MESSAGE, resp.data)
        self.assertNotIn(b"verify your email", resp.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)

    def test_deactivated_user_session_stops_working(self):
        resp = self._post_login()
        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("_user_id"), str(self.user.user_id))

        if hasattr(g, "_login_user"):
            del g._login_user
        resp = self.client.get("/profile/", follow_redirects=False)
        self.assertEqual(resp.status_code, 200)

        self.user.user_status = VaStatuses.deactive
        db.session.commit()
        if hasattr(g, "_login_user"):
            del g._login_user

        resp = self.client.get("/profile/", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(urlparse(resp.headers["Location"]).path, LOGIN_PATH)

    def test_is_active_tracks_user_status(self):
        self.assertTrue(self.user.is_active)
        self.user.user_status = VaStatuses.deactive
        self.assertFalse(self.user.is_active)


class PasswordResetTokenTests(VaAuthSecurityTestBase):
    def _reset_url(self, token):
        return f"/vaauth/reset-password/{token}"

    def _post_reset(self, token):
        # The new password is generated and emailed (digitva-kmoy); the mail
        # transport is mocked so the test does not depend on SMTP config.
        with patch("app.services.email_service.is_mail_configured", return_value=True), \
                patch("app.services.email_service.mail.send"):
            return self.client.post(
                self._reset_url(token), headers=self._csrf_headers(), follow_redirects=False,
            )

    def test_reset_token_is_single_use(self):
        token = generate_token(self.user.user_id, "password_reset")
        self._fresh_client()

        resp = self.client.get(self._reset_url(token))
        self.assertIn(RESET_FORM_MARKER, resp.data)

        resp = self._post_reset(token)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(urlparse(resp.headers["Location"]).path, LOGIN_PATH)
        user = db.session.get(VaUsers, self.user.user_id)
        self.assertFalse(user.check_password(PASSWORD))
        first_hash = user.password

        resp = self.client.get(self._reset_url(token))
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(RESET_FORM_MARKER, resp.data)

        resp = self._post_reset(token)
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn(RESET_FORM_MARKER, resp.data)
        db.session.expire_all()
        user = db.session.get(VaUsers, self.user.user_id)
        self.assertEqual(user.password, first_hash)

    def test_token_rejected_after_password_changed_elsewhere(self):
        token = generate_token(self.user.user_id, "password_reset")
        self.assertEqual(validate_token(token, "password_reset"), str(self.user.user_id))

        self.user.set_password("ChangedByAdmin123!")
        db.session.commit()

        self.assertIsNone(validate_token(token, "password_reset"))

    def test_token_without_fingerprint_is_rejected(self):
        from app.services.token_service import TOKEN_PURPOSES, _serializer

        legacy = _serializer().dumps(
            {"user_id": str(self.user.user_id), "purpose": "password_reset"},
            salt=TOKEN_PURPOSES["password_reset"]["salt"],
        )
        self.assertIsNone(validate_token(legacy, "password_reset"))

    def test_email_verify_token_unchanged(self):
        token = generate_token(self.user.user_id, "email_verify")
        self.assertEqual(validate_token(token, "email_verify"), str(self.user.user_id))
