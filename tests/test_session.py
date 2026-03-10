import uuid
from datetime import timedelta
from flask import session, url_for
from app import db
from app.models.va_users import VaUsers
from tests.base import BaseTestCase

class SessionTests(BaseTestCase):
    def test_session_timeout_config(self):
        """Verify that PERMANENT_SESSION_LIFETIME is set to 30 minutes."""
        self.assertEqual(
            self.app.config["PERMANENT_SESSION_LIFETIME"], 
            timedelta(minutes=30)
        )
        self.assertEqual(
            self.app.config["REMEMBER_COOKIE_DURATION"], 
            timedelta(minutes=30)
        )

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

        # Get login URL
        with self.app.test_request_context():
            login_url = url_for("va_auth.va_login")

        # Attempt to login via the route
        resp = self.client.post(
            login_url,
            data={
                "email": email,
                "password": password,
                "remember_me": "y"
            },
            headers=self._csrf_headers(),
            follow_redirects=False
        )
        
        # Should be a redirect to dashboard
        self.assertEqual(resp.status_code, 302)
        
        # Check if session.permanent is True
        with self.client.session_transaction() as sess:
            self.assertTrue(sess.permanent)
