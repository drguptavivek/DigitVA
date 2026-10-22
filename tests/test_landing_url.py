"""Post-login landing: /app/ for everyone while the Expo export is present.

Policy: docs/policy/expo-client.md, "Role home and login landing".
"""
import uuid
from unittest import mock

from app import db
from app.models.va_users import VaUsers
from tests.base import BaseTestCase

EXPORT = "app.routes.expo_client.export_ready"


class LandingUrlTests(BaseTestCase):
    def _user(self, landing_page):
        sfx = uuid.uuid4().hex[:8]
        user = VaUsers(
            user_id=uuid.uuid4(), name=f"landing.{sfx}", email=f"landing.{sfx}@example.com",
            vacode_language=["English"], vacode_formcount=0, permission={},
            landing_page=landing_page, pw_reset_t_and_c=True, email_verified=True,
            user_status="active",
        )
        user.set_password("password123")
        db.session.add(user)
        db.session.commit()
        return user

    def test_every_stored_landing_page_lands_on_app_when_export_ready(self):
        # landing_page is ignored for login landing; roles never choose it.
        for page in ("admin", "data_manager", "coder", "reviewer", "sitepi", "intake", "viewer"):
            user = self._user(page)
            with self.subTest(landing_page=page), mock.patch(EXPORT, return_value=True), \
                    self.app.test_request_context():
                self.assertEqual(user.landing_url(), "/app/")

    def test_fallbacks_without_export(self):
        admin, nobody = self._user("admin"), self._user("coder")
        with mock.patch(EXPORT, return_value=False), self.app.test_request_context():
            self.assertEqual(admin.landing_url(), "/admin/")
            # A coder landing_page without a coder grant falls through to the index.
            self.assertEqual(nobody.landing_url(), "/vaindex")

    def test_signed_in_routes_go_to_app(self):
        user = self._user("admin")
        self._login(str(user.user_id))
        with mock.patch(EXPORT, return_value=True):
            for url in ("/vaauth/valogin", "/", "/profile/force-password-change"):
                with self.subTest(url=url):
                    resp = self.client.get(url)
                    self.assertEqual(resp.status_code, 302)
                    self.assertTrue(resp.headers["Location"].endswith("/app/"))
        with mock.patch(EXPORT, return_value=False):
            self.assertEqual(self.client.get("/").status_code, 200)
