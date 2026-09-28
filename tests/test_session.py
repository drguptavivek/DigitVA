import uuid
from datetime import timedelta
from flask import session, url_for
from app import db, limiter
from app.models.va_users import VaUsers
from tests.base import BaseTestCase

class SessionTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        # The login route is rate limited per IP; another test class in the
        # same process (e.g. test_rate_limiting.py) may have already spent
        # part of that budget on 127.0.0.1.
        limiter.reset()
    def test_session_timeout_config(self):
        """Idle session lifetime is 30 minutes; remember-me lasts 30 days."""
        self.assertEqual(
            self.app.config["PERMANENT_SESSION_LIFETIME"],
            timedelta(minutes=30)
        )
        # SEC-010 (commit f5c359f) deliberately extended REMEMBER_COOKIE_DURATION
        # from 30 minutes to 30 days; config.py:28 is the baseline.
        self.assertEqual(
            self.app.config["REMEMBER_COOKIE_DURATION"],
            timedelta(days=30)
        )

    def test_login_redirects_to_next_page(self):
        """Verify that login redirects to the 'next' page if provided."""
        # Create a test user
        email = f"test.next.{uuid.uuid4().hex[:8]}@example.com"
        password = "testpassword123"
        user = VaUsers(
            user_id=uuid.uuid4(),
            name=email,
            email=email,
            vacode_language=["English"],
            permission={},
            landing_page="coder",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status="active",
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        # Target a page that requires login (or any page we want to return to)
        with self.app.test_request_context():
            next_url = url_for("coding.dashboard")

        # Attempt to login
        resp = self._login_via_form(email, password, next_url=next_url, remember=True)

        # Should redirect to the next_url
        self.assertEqual(resp.status_code, 302)
        self.assertIn(next_url, resp.location)

    def test_login_sets_permanent_session(self):
        """Verify that logging in sets session.permanent = True."""
        # Create a test user
        email = f"test.session.{uuid.uuid4().hex[:8]}@example.com"
        password = "testpassword123"
        user = VaUsers(
            user_id=uuid.uuid4(),
            name=email,
            email=email,
            vacode_language=["English"],
            permission={},
            landing_page="coder",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status="active",
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        # Attempt to login via the route
        resp = self._login_via_form(email, password, remember=True)

        # Should be a redirect to dashboard
        self.assertEqual(resp.status_code, 302)
        
        # Check if session.permanent is True
        with self.client.session_transaction() as sess:
            self.assertTrue(sess.permanent)
