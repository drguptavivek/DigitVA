"""Retired factor enforcement regression tests.

TOTP and recovery records remain historical compatibility data, but they no
longer add a login requirement or a mandatory profile setup redirect.
"""

import uuid

from app import db, limiter
from app.models import VaAccessRoles, VaAccessScopeTypes, VaStatuses, VaUserAccessGrants
from tests.base import BaseTestCase


class RetiredFactorEnforcementTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        limiter.reset()
        self.user = self._make_user(
            f"retired-factor.{uuid.uuid4().hex[:8]}@example.com",
            "FactorRetired123!",
        )
        db.session.add(VaUserAccessGrants(
            user_id=self.user.user_id,
            role=VaAccessRoles.admin,
            scope_type=VaAccessScopeTypes.global_scope,
            notes="retired factor enforcement test",
            grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def test_privileged_user_has_no_factor_setup_redirect(self):
        self._login(str(self.user.user_id))

        profile = self.client.get("/profile/")
        dashboard = self.client.get("/coding/dashboard")

        self.assertEqual(profile.status_code, 200)
        self.assertNotIn("must add a passkey or authenticator app", profile.get_data(as_text=True))
        self.assertNotIn("passkey setup", dashboard.get_data(as_text=True).lower())

    def test_retired_profile_factor_endpoints_are_not_live(self):
        self._login(str(self.user.user_id))

        for path in (
            "/api/v1/profile/totp",
            "/api/v1/profile/totp/enroll",
            "/api/v1/profile/recovery-codes/regenerate",
        ):
            self.assertEqual(self.client.get(path).status_code, 404, path)
