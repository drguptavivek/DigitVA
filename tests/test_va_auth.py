import uuid
from urllib.parse import urlparse

from app import db
from app.models import VaStatuses, VaUsers
from app.services.security.token import generate_token
from tests.base import BaseTestCase


class VaAuthVerificationTests(BaseTestCase):
    def _csrf_form_token(self):
        return self._csrf_headers()["X-CSRFToken"]

    def test_inactive_user_cannot_log_in(self):
        email = f"test.inactive.login.{uuid.uuid4().hex[:8]}@example.com"
        user = VaUsers(
            user_id=uuid.uuid4(),
            name=email,
            email=email,
            vacode_language=["English"],
            permission={},
            landing_page="coder",
            pw_reset_t_and_c=True,
            email_verified=True,
            user_status=VaStatuses.deactive,
        )
        user.set_password("TestPassword123!")
        db.session.add(user)
        db.session.commit()

        resp = self.client.post(
            "/vaauth/valogin",
            data={
                "email": email,
                "password": "TestPassword123!",
                "csrf_token": self._csrf_form_token(),
            },
            follow_redirects=False,
        )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(urlparse(resp.location).path, "/vaauth/valogin")

    def test_verify_email_redirects_new_users_to_password_setup(self):
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

        with self.app.app_context():
            token = generate_token(user.user_id, "email_verify")
            verify_url = f"/vaauth/verify-email/{token}"

        resp = self.client.get(verify_url, follow_redirects=False)

        self.assertEqual(resp.status_code, 302)
        self.assertIn("/vaauth/reset-password/", resp.location)

        refreshed = db.session.get(VaUsers, user.user_id)
        self.assertTrue(refreshed.email_verified)
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

        with self.app.app_context():
            token = generate_token(user.user_id, "email_verify")
            verify_url = f"/vaauth/verify-email/{token}"

        resp = self.client.get(verify_url, follow_redirects=False)

        self.assertEqual(resp.status_code, 302)
        location_path = urlparse(resp.location).path
        self.assertEqual(location_path, "/vaauth/valogin")

    def test_verify_email_rejects_inactive_user(self):
        email = f"test.inactive.verify.{uuid.uuid4().hex[:8]}@example.com"
        user = VaUsers(
            user_id=uuid.uuid4(),
            name=email,
            email=email,
            vacode_language=["English"],
            permission={},
            landing_page="coder",
            pw_reset_t_and_c=False,
            email_verified=False,
            user_status=VaStatuses.deactive,
        )
        user.set_password("TestPassword123!")
        db.session.add(user)
        db.session.commit()

        with self.app.app_context():
            token = generate_token(user.user_id, "email_verify")

        resp = self.client.get(f"/vaauth/verify-email/{token}", follow_redirects=False)

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(urlparse(resp.location).path, "/vaauth/valogin")

        refreshed = db.session.get(VaUsers, user.user_id)
        self.assertFalse(refreshed.email_verified)

    def test_reset_password_rejects_inactive_user(self):
        email = f"test.inactive.reset.{uuid.uuid4().hex[:8]}@example.com"
        user = VaUsers(
            user_id=uuid.uuid4(),
            name=email,
            email=email,
            vacode_language=["English"],
            permission={},
            landing_page="coder",
            pw_reset_t_and_c=False,
            email_verified=True,
            user_status=VaStatuses.deactive,
        )
        user.set_password("OldPassword123!")
        db.session.add(user)
        db.session.commit()

        with self.app.app_context():
            token = generate_token(user.user_id, "password_reset")

        resp = self.client.post(
            f"/vaauth/reset-password/{token}",
            data={
                "new_password": "NewPassword123!",
                "confirm_password": "NewPassword123!",
                "csrf_token": self._csrf_form_token(),
            },
            follow_redirects=False,
        )

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(urlparse(resp.location).path, "/vaauth/valogin")

        refreshed = db.session.get(VaUsers, user.user_id)
        self.assertTrue(refreshed.check_password("OldPassword123!"))
