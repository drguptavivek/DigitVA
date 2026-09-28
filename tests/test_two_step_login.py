"""Two-step login contract: no enumeration at the email step, pre-auth state
expiry, and session-version invalidation. Password-path checks that reuse the
existing single-step assertions (wrong password, inactive, unverified,
maintenance, next redirect) live in test_va_auth_security.py and
test_site_maintenance.py; this file covers what is new in digitva-sn1.1.3."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import event

from app import db, limiter
from tests.base import BaseTestCase

PASSWORD = "TwoStepLogin123!"


class TwoStepLoginTestBase(BaseTestCase):
    def setUp(self):
        super().setUp()
        limiter.reset()
        self.user = self._make_user(
            f"two.step.{uuid.uuid4().hex[:8]}@example.com", PASSWORD
        )
        db.session.commit()


class EmailStepEnumerationTests(TwoStepLoginTestBase):
    def test_known_and_unknown_email_get_identical_response(self):
        known_resp = self._login_via_form(self.user.email, "wrong-password")
        limiter.reset()
        unknown_resp = self._login_via_form(
            f"nobody.{uuid.uuid4().hex[:8]}@example.com", "wrong-password"
        )

        # Both responses are the email-step's redirect to the password page
        # (not the password page's own outcome, which does differ later) --
        # compare the two *email-step* responses directly.
        self.assertEqual(known_resp.status_code, unknown_resp.status_code)


class EmailStepNoLookupTests(TwoStepLoginTestBase):
    def test_email_step_post_alone_does_not_query_va_users(self):
        from app.services.pow_captcha_service import issue_challenge

        with self.app.app_context():
            challenge = issue_challenge()
        solution = self._solve_pow_captcha(challenge["salt"], challenge["difficulty"])
        # Read before attaching the listener: accessing an ORM attribute on an
        # expired instance (post-commit) issues its own SELECT by primary key,
        # which would otherwise be mistaken for a query the route made.
        email = self.user.email

        statements = []

        def _capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", _capture)
        try:
            resp = self.client.post(
                "/vaauth/valogin",
                data={
                    "email": email,
                    "captcha_salt": challenge["salt"],
                    "captcha_difficulty": challenge["difficulty"],
                    "captcha_expires": challenge["expires"],
                    "captcha_signature": challenge["signature"],
                    "captcha_solution": solution,
                },
                headers=self._csrf_headers(),
                follow_redirects=False,
            )
        finally:
            event.remove(db.engine, "before_cursor_execute", _capture)

        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            any("va_users" in statement.lower() for statement in statements),
            "Email step queried va_users; it must not branch on account existence.",
        )


class PasswordStepPreauthTests(TwoStepLoginTestBase):
    def test_password_page_without_preauth_redirects_to_email_step(self):
        resp = self.client.get("/vaauth/valogin/password", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/vaauth/valogin", resp.headers["Location"])

    def test_expired_preauth_redirects_to_email_step(self):
        with self.client.session_transaction() as sess:
            sess["preauth"] = {
                "email": self.user.email,
                "issued_at": (datetime.now(timezone.utc) - timedelta(minutes=6)).isoformat(),
                "next": None,
            }
        resp = self.client.get("/vaauth/valogin/password", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/vaauth/valogin", resp.headers["Location"])

    def test_unknown_email_at_password_step_gets_generic_message(self):
        unknown_email = f"nobody.{uuid.uuid4().hex[:8]}@example.com"
        resp = self._login_via_form(unknown_email, "whatever-password")
        self.assertEqual(resp.status_code, 302)
        resp = self.client.get(resp.headers["Location"], follow_redirects=True)
        self.assertIn(b"Invalid email or password", resp.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)


class SessionVersionTests(TwoStepLoginTestBase):
    def test_legacy_bare_id_still_loads(self):
        self.assertEqual(self.user.auth_session_version, 0)
        self._login(str(self.user.user_id))
        resp = self.client.get("/profile/", follow_redirects=False)
        self.assertEqual(resp.status_code, 200)

    def test_bumped_version_invalidates_the_old_session_id(self):
        from flask import g

        self._login(str(self.user.user_id))
        resp = self.client.get("/profile/", follow_redirects=False)
        self.assertEqual(resp.status_code, 200)

        self.user.bump_session_version()
        db.session.commit()
        # Flask-Login caches the loaded user on g, which in this test setup
        # outlives a single request (see BaseTestCase._login's docstring).
        if hasattr(g, "_login_user"):
            del g._login_user

        resp = self.client.get("/profile/", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)

    def test_versioned_get_id_round_trips_through_login(self):
        self.user.bump_session_version()
        db.session.commit()
        self.assertEqual(
            self.user.get_id(), f"{self.user.user_id}:{self.user.auth_session_version}"
        )

        resp = self._login_via_form(self.user.email, PASSWORD)
        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertEqual(sess.get("_user_id"), self.user.get_id())

    def test_password_reset_bumps_session_version(self):
        from app.services.token_service import generate_token

        before = self.user.auth_session_version
        token = generate_token(self.user.user_id, "password_reset")
        resp = self.client.post(
            f"/vaauth/reset-password/{token}",
            data={"new_password": "BrandNewSecret789!", "confirm_password": "BrandNewSecret789!"},
            headers=self._csrf_headers(),
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        db.session.refresh(self.user)
        self.assertEqual(self.user.auth_session_version, before + 1)


class SessionFixationTests(TwoStepLoginTestBase):
    def _session_cookie(self):
        cookie = self.client.get_cookie(self.app.config.get("SESSION_COOKIE_NAME", "session"))
        return cookie.value if cookie else None

    def test_login_issues_a_new_session_id(self):
        self.client.get("/vaauth/valogin")
        self._csrf_headers()
        anonymous_sid = self._session_cookie()
        self.assertIsNotNone(anonymous_sid)

        resp = self._login_via_form(self.user.email, PASSWORD)

        self.assertEqual(resp.status_code, 302)
        authenticated_sid = self._session_cookie()
        self.assertIsNotNone(authenticated_sid)
        self.assertNotEqual(authenticated_sid, anonymous_sid)
