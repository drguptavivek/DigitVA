"""Enrolment enforcement: the pre-deadline banner and the post-deadline
setup-redirect guard -- digitva-sn1.1.6. Baseline:
docs/policy/authentication-factors.md sections 6, 9.
"""

import uuid

from app import db, limiter
from app.models import (
    AuthWebauthnCredential,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaStatuses,
    VaUserAccessGrants,
)
from tests.base import BaseTestCase

PASSWORD = "FactorEnforce123!"
BANNER_TEXT = "must add a passkey or authenticator app by"


class FactorEnforcementTestBase(BaseTestCase):
    def setUp(self):
        super().setUp()
        limiter.reset()
        self.user = self._make_user(f"enforce.{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
        db.session.commit()
        # AUTH_FACTOR_ENFORCE_FROM lives on the shared app config, not inside
        # the per-test transaction -- restore it so a later test class (which
        # may run in the same process) never sees this test's date.
        self._original_enforce_from = self.app.config.get("AUTH_FACTOR_ENFORCE_FROM")
        self.addCleanup(
            lambda: self.app.config.__setitem__(
                "AUTH_FACTOR_ENFORCE_FROM", self._original_enforce_from
            )
        )

    def _grant_admin(self, user):
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=VaAccessRoles.admin,
            scope_type=VaAccessScopeTypes.global_scope,
            notes="test admin grant",
            grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def _grant_data_manager(self, user):
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.BASE_PROJECT_ID,
            notes="test data manager grant",
            grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def _add_passkey(self, user):
        cred = AuthWebauthnCredential(
            user_id=user.user_id,
            credential_id=uuid.uuid4().bytes,
            public_key=b"fake-public-key",
            sign_count=0,
            name="Test key",
        )
        db.session.add(cred)
        db.session.commit()
        return cred


# ---------------------------------------------------------------------------
# Banner (before the deadline / unset)
# ---------------------------------------------------------------------------

class FactorEnrollmentBannerTests(FactorEnforcementTestBase):
    def test_banner_shown_for_privileged_user_without_factor(self):
        self.app.config["AUTH_FACTOR_ENFORCE_FROM"] = "2099-01-01"
        self._grant_admin(self.user)
        self._login(str(self.user.user_id))

        resp = self.client.get("/profile/")

        self.assertEqual(resp.status_code, 200)
        self.assertIn(BANNER_TEXT, resp.get_data(as_text=True))
        self.assertIn("January 01, 2099", resp.get_data(as_text=True))

    def test_banner_not_shown_for_coder(self):
        self.app.config["AUTH_FACTOR_ENFORCE_FROM"] = "2099-01-01"
        self._login(str(self.user.user_id))

        resp = self.client.get("/profile/")

        self.assertNotIn(BANNER_TEXT, resp.get_data(as_text=True))

    def test_banner_not_shown_for_privileged_user_with_factor(self):
        self.app.config["AUTH_FACTOR_ENFORCE_FROM"] = "2099-01-01"
        self._grant_admin(self.user)
        self._add_passkey(self.user)
        self._login(str(self.user.user_id))

        resp = self.client.get("/profile/")

        self.assertNotIn(BANNER_TEXT, resp.get_data(as_text=True))

    def test_banner_not_shown_when_unset(self):
        self.app.config["AUTH_FACTOR_ENFORCE_FROM"] = ""
        self._grant_admin(self.user)
        self._login(str(self.user.user_id))

        resp = self.client.get("/profile/")

        self.assertNotIn(BANNER_TEXT, resp.get_data(as_text=True))

    def test_banner_not_shown_once_deadline_has_passed(self):
        # The redirect guard takes over once the date has passed; the banner
        # only covers the pre-deadline period.
        self.app.config["AUTH_FACTOR_ENFORCE_FROM"] = "2020-01-01"
        self._grant_admin(self.user)
        self._login(str(self.user.user_id))

        resp = self.client.get("/profile/")

        self.assertNotIn(BANNER_TEXT, resp.get_data(as_text=True))


# ---------------------------------------------------------------------------
# Redirect guard (on/after the deadline)
# ---------------------------------------------------------------------------

class FactorSetupGuardTests(FactorEnforcementTestBase):
    def setUp(self):
        super().setUp()
        self.app.config["AUTH_FACTOR_ENFORCE_FROM"] = "2020-01-01"

    def test_privileged_without_factor_redirected_from_html_page(self):
        self._grant_admin(self.user)
        self._login(str(self.user.user_id))

        resp = self.client.get("/coding/dashboard")

        self.assertEqual(resp.status_code, 302)
        self.assertIn("/profile/", resp.headers["Location"])
        self.assertIn("passkeys-card", resp.headers["Location"])

    def test_privileged_without_factor_gets_403_json_from_api(self):
        self._grant_data_manager(self.user)
        self._login(str(self.user.user_id))

        resp = self.client.get("/api/v1/data-management/submissions")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json().get("error"), "factor_setup_required")

    def test_pending_password_change_is_reachable_not_looped(self):
        # force_password_update sends a user with pw_reset_t_and_c=False (as
        # every forgot-password reset leaves them) to force_password_change;
        # the factor guard must not bounce that page back to Profile.
        self._grant_admin(self.user)
        self.user.pw_reset_t_and_c = False
        db.session.commit()
        self._login(str(self.user.user_id))

        first = self.client.get("/profile/", follow_redirects=False)
        self.assertEqual(first.status_code, 302)
        self.assertIn("force-password-change", first.headers["Location"])
        landing = self.client.get(first.headers["Location"], follow_redirects=False)
        self.assertEqual(landing.status_code, 200)

    def test_held_user_gets_403_json_from_data_management_api(self):
        self._grant_data_manager(self.user)
        self._login(str(self.user.user_id))

        resp = self.client.get("/data-management/api/does-not-matter")

        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.get_json().get("error"), "factor_setup_required")

    def test_can_still_reach_profile_page(self):
        self._grant_admin(self.user)
        self._login(str(self.user.user_id))

        resp = self.client.get("/profile/")

        self.assertEqual(resp.status_code, 200)

    def test_can_still_reach_factor_apis(self):
        self._grant_admin(self.user)
        self._login(str(self.user.user_id))

        resp = self.client.get("/api/v1/profile/totp")

        self.assertEqual(resp.status_code, 200)

    def test_can_still_reach_logout(self):
        self._grant_admin(self.user)
        self._login(str(self.user.user_id))

        resp = self.client.post("/vaauth/valogout", headers=self._csrf_headers())

        self.assertEqual(resp.status_code, 302)

    def test_can_still_reach_static(self):
        self._grant_admin(self.user)
        self._login(str(self.user.user_id))

        resp = self.client.get("/static/css/base.css")

        self.assertIn(resp.status_code, (200, 304))

    def test_privileged_with_factor_never_redirected(self):
        self._grant_admin(self.user)
        self._add_passkey(self.user)
        self._login(str(self.user.user_id))

        resp = self.client.get("/coding/dashboard")

        self.assertNotEqual(resp.status_code, 302)

    def test_coder_never_guarded(self):
        self._login(str(self.user.user_id))

        resp = self.client.get("/coding/dashboard")

        self.assertNotEqual(resp.status_code, 302)

    def test_enrolment_lifts_guard_in_same_session(self):
        import pyotp
        from datetime import datetime, timezone

        self._grant_admin(self.user)
        self._login(str(self.user.user_id))

        blocked = self.client.get("/coding/dashboard")
        self.assertEqual(blocked.status_code, 302)

        # Enrol through the real API (not a direct DB write) so the guard's
        # session cache is invalidated the same way a real user's would be.
        with self.client.session_transaction() as sess:
            sess["auth_verified_at"] = datetime.now(timezone.utc).isoformat()
        headers = self._csrf_headers()
        enroll_resp = self.client.post("/api/v1/profile/totp/enroll", headers=headers)
        secret = enroll_resp.get_json()["secret"]
        code = pyotp.TOTP(secret).now()
        confirm_resp = self.client.post(
            "/api/v1/profile/totp/confirm", json={"code": code}, headers=headers
        )
        self.assertEqual(confirm_resp.status_code, 200, confirm_resp.get_json())

        allowed = self.client.get("/coding/dashboard")
        self.assertNotEqual(allowed.status_code, 302)
