import uuid
from urllib.parse import urlparse

from app import db
from app.models import VaUsers
from app.services.token_service import generate_token
from tests.base import BaseTestCase


class VaAuthVerificationTests(BaseTestCase):
    def test_verify_email_shows_a_button_and_changes_nothing_on_get(self):
        """digitva-kmoy: the link opens a confirm page (mail scanners prefetch
        links); pressing it is what verifies and emails the password, covered
        in tests/test_account_onboarding.py."""
        email = f"test.verify.{uuid.uuid4().hex[:8]}@example.com"
        user = VaUsers(
            user_id=uuid.uuid4(),
            name=email,
            email=email,
            vacode_language=["English"],
            permission={},
            landing_page="coder",
            pw_reset_t_and_c=False,
            email_verified=False,
            user_status="active",
        )
        user.set_password("TestPassword123!")
        db.session.add(user)
        db.session.commit()

        # The email_verify token now reads the user (email fingerprint), so it
        # is made in the test's own session, not a fresh app context.
        token = generate_token(user.user_id, "email_verify")
        verify_url = f"/vaauth/verify-email/{token}"

        resp = self.client.get(verify_url, follow_redirects=False)

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Verify my email", resp.data)
        self.assertNotIn(b"/vaauth/reset-password/", resp.data)

        refreshed = db.session.get(VaUsers, user.user_id)
        self.assertFalse(refreshed.email_verified)
        self.assertFalse(refreshed.pw_reset_t_and_c)

    def test_verify_email_redirects_onboarded_users_to_login(self):
        email = f"test.verified.{uuid.uuid4().hex[:8]}@example.com"
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
        user.set_password("TestPassword123!")
        db.session.add(user)
        db.session.commit()

        # The email_verify token now reads the user (email fingerprint), so it
        # is made in the test's own session, not a fresh app context.
        token = generate_token(user.user_id, "email_verify")
        verify_url = f"/vaauth/verify-email/{token}"

        resp = self.client.get(verify_url, follow_redirects=False)

        self.assertEqual(resp.status_code, 302)
        location_path = urlparse(resp.location).path
        self.assertEqual(location_path, "/vaauth/valogin")
