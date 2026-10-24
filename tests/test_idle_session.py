"""Idle sign-out of cookie sessions and the retired remember cookie.

Rules under test: app/utils/idle_session.py; policy in
docs/policy/auth-decorator-rbac.md section 5 (digitva-kc89).
"""
import time

from flask_login.utils import encode_cookie

from app import db, limiter
from app.utils.idle_session import BACKGROUND_HEADER
from tests.base import BaseTestCase

API = "/api/v1/me/access"
PAGE = "/vaauth/valogin"
IDLE = 31 * 60


class IdleSessionTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        limiter.reset()
        self.user = self._make_user("idle.user@example.com", "IdlePass123")
        db.session.commit()
        self._login(str(self.user.get_id()))

    def _stamp(self, age):
        with self.client.session_transaction() as sess:
            sess["last_activity_at"] = int(time.time()) - age

    def _stamp_value(self):
        with self.client.session_transaction() as sess:
            return sess.get("last_activity_at")

    def test_login_stamps_activity(self):
        self.client = self.app.test_client()
        resp = self._login_via_form(self.user.email, "IdlePass123")
        self.assertEqual(resp.status_code, 302)
        self.assertAlmostEqual(self._stamp_value(), time.time(), delta=5)

    def test_non_background_request_extends(self):
        self._stamp(120)
        self.assertEqual(self.client.get(API).status_code, 200)
        self.assertAlmostEqual(self._stamp_value(), time.time(), delta=5)

    def test_background_request_does_not_extend(self):
        self._stamp(120)
        before = self._stamp_value()
        resp = self.client.get(API, headers={BACKGROUND_HEADER: "1"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._stamp_value(), before)

    def test_idle_json_request_is_refused_and_signed_out(self):
        self._stamp(IDLE)
        resp = self.client.get(API)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.get_json()["code"], "session_idle")
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)
        self.assertEqual(self.client.get(API).get_json()["code"], "unauthorized")

    def test_idle_background_request_is_refused_too(self):
        self._stamp(IDLE)
        resp = self.client.get(API, headers={BACKGROUND_HEADER: "1"})
        self.assertEqual(resp.get_json()["code"], "session_idle")

    def test_idle_page_request_redirects_to_sign_in(self):
        self._stamp(IDLE)
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/vaauth/valogin", resp.location)
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)

    def test_session_without_stamp_is_stamped_not_signed_out(self):
        self.assertIsNone(self._stamp_value())
        self.assertEqual(self.client.get(API, headers={BACKGROUND_HEADER: "1"}).status_code, 200)
        self.assertIsNotNone(self._stamp_value())

    def test_bearer_request_ignores_idle_cookie(self):
        self._stamp(IDLE)
        resp = self.client.get(API, headers={"Authorization": "Bearer not-a-token"})
        self.assertEqual(resp.get_json()["code"], "unauthorized")

    def test_login_never_sets_remember_cookie(self):
        self.client = self.app.test_client()
        resp = self._login_via_form(self.user.email, "IdlePass123")
        cookies = " ".join(resp.headers.getlist("Set-Cookie"))
        self.assertNotIn("remember_token", cookies)

    def test_remember_cookie_alone_does_not_sign_in_and_is_cleared(self):
        self.client = self.app.test_client()
        self.client.set_cookie("remember_token", encode_cookie(str(self.user.get_id())))
        resp = self.client.get(API)
        self.assertEqual(resp.status_code, 401)
        deletion = [c for c in resp.headers.getlist("Set-Cookie") if c.startswith("remember_token=")]
        self.assertTrue(deletion)
        self.assertIn("Max-Age=0", deletion[0])


class AbsoluteLifetimeTests(BaseTestCase):
    """12-hour cap from sign-in (digitva-vq05)."""

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.user = self._make_user("cap.user@example.com", "CapPass123")
        db.session.commit()
        self._login(str(self.user.get_id()))

    def _signed_in(self, age):
        with self.client.session_transaction() as sess:
            sess["signed_in_at"] = int(time.time()) - age
            sess["last_activity_at"] = int(time.time())  # active: only the cap applies

    def test_login_stamps_signed_in_at(self):
        self.client = self.app.test_client()
        self._login_via_form(self.user.email, "CapPass123")
        with self.client.session_transaction() as sess:
            self.assertAlmostEqual(sess["signed_in_at"], time.time(), delta=5)

    def test_over_cap_json_is_refused_and_signed_out(self):
        self._signed_in(12 * 3600 + 60)
        resp = self.client.get(API)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.get_json()["code"], "session_expired")
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)

    def test_over_cap_page_redirects_with_reason(self):
        self._signed_in(12 * 3600 + 60)
        resp = self.client.get("/", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("reason=expired", resp.location)

    def test_login_page_shows_expired_message(self):
        self.client = self.app.test_client()
        self.assertIn(b"ended after 12 hours", self.client.get(PAGE + "?reason=expired").data)

    def test_active_session_just_under_cap_is_allowed(self):
        self._signed_in(12 * 3600 - 60)
        self.assertEqual(self.client.get(API).status_code, 200)

    def test_missing_stamp_is_stamped_not_signed_out(self):
        with self.client.session_transaction() as sess:
            self.assertNotIn("signed_in_at", sess)
        self.assertEqual(self.client.get(API).status_code, 200)
        with self.client.session_transaction() as sess:
            self.assertAlmostEqual(sess["signed_in_at"], time.time(), delta=5)

    def test_bearer_request_ignores_expired_cookie(self):
        self._signed_in(13 * 3600)
        resp = self.client.get(API, headers={"Authorization": "Bearer not-a-token"})
        self.assertEqual(resp.get_json()["code"], "unauthorized")

    def test_reauth_does_not_reset_the_cap(self):
        self._signed_in(12 * 3600 - 60)
        with self.client.session_transaction() as sess:
            sess["auth_verified_at"] = "2000-01-01T00:00:00+00:00"
            before = sess["signed_in_at"]
        self.client.get(API)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess["signed_in_at"], before)
