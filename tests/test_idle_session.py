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
