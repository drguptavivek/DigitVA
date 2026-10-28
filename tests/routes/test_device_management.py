"""Account and Users-page native-device management (digitva-65m5).

The routes end only the selected account's sessions; the shared AuthDevice row
and another account's session on the same physical phone remain intact.
"""

import uuid
from unittest.mock import patch

import sqlalchemy as sa

from app import db, limiter
from app.models import AuthDevice, AuthDeviceSession, VaAccessRoles, VaAccessScopeTypes, VaProjectMaster
from app.services import device_auth_service as devices
from tests.authz.fixture import SP, AuthzFixtureMixin
from tests.base import BaseTestCase

ME = "/api/v1/me/devices"
USERS = "/api/v1/users"


class DeviceManagementRouteTests(AuthzFixtureMixin, BaseTestCase):
    def setUp(self):
        super().setUp()
        limiter.reset()
        # The shared authz fixture intentionally leaves web intake off for
        # most tests. Device sign-in must use a real active interviewing
        # surface, so enable the existing AZTA01 fixture project before the
        # session is opened (its legacy research/site rows and active form
        # are seeded by AuthzFixtureMixin).
        project = db.session.get(VaProjectMaster, "AZTA01")
        self.assertIsNotNone(project)
        project.web_intake_mode = "both"
        db.session.flush()

    def _device(self, user_key="interviewer_p1", name="Pixel"):
        user = self.users[user_key]
        device, _secret = devices._add_device("AZTA01", name, "android", "1.2.3", None)
        issued, _user = devices._open_authorized_session(device, user)
        db.session.flush()
        return device, issued

    def _add_target_grant(self, user_key, role, scope, where):
        row = self._grant_row(self.users[user_key], role, scope, where)
        db.session.add(row)
        db.session.commit()

    def test_self_cookie_list_and_delete_require_csrf(self):
        device, _issued = self._device()
        self._login(str(self.users["interviewer_p1"].user_id))
        listed = self.client.get(ME)
        self.assertEqual(listed.status_code, 200, listed.get_json())
        self.assertEqual(listed.get_json()["devices"][0]["device_id"], str(device.device_id))
        with patch.dict(self.app.config, {"WTF_CSRF_ENABLED": True}):
            refused = self.client.delete(f"{ME}/{device.device_id}")
        self.assertEqual(refused.status_code, 400)
        session = db.session.scalar(sa.select(AuthDeviceSession).where(AuthDeviceSession.device_id == device.device_id))
        self.assertIsNone(session.revoked_at)
        with patch.dict(self.app.config, {"WTF_CSRF_ENABLED": True}):
            ended = self.client.delete(f"{ME}/{device.device_id}", headers=self._csrf_headers())
        self.assertEqual(ended.get_json(), {
            "decommissioned": True, "sessions_ended": 1, "current": False,
        })

    def test_bearer_marks_current_and_keeps_shared_other_account_session(self):
        device, issued = self._device()
        other_issued, _user = devices._open_authorized_session(device, self.users["coder_p1"])
        self._login(str(self.users["interviewer_p1"].user_id))
        bearer = {"Authorization": f"Bearer {issued.access_token}"}
        listed = self.client.get(ME, headers=bearer)
        self.assertEqual(listed.status_code, 200, listed.get_json())
        self.assertTrue(listed.get_json()["devices"][0]["current"])
        ended = self.client.delete(f"{ME}/{device.device_id}", headers=bearer)
        self.assertEqual(ended.get_json()["current"], True)
        self.assertEqual(ended.get_json()["sessions_ended"], 1)
        other_session = db.session.scalar(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.user_id == self.users["coder_p1"].user_id,
            AuthDeviceSession.device_id == device.device_id,
        ))
        self.assertIsNone(other_session.revoked_at)
        self.assertTrue(other_issued.access_token)

    def test_admin_manages_any_target_and_no_history_delete_is_idempotent(self):
        device, _issued = self._device()
        self._login(str(self.users["admin"].user_id))
        listed = self.client.get(f"{USERS}/{self.users['interviewer_p1'].user_id}/devices")
        self.assertEqual(listed.status_code, 200, listed.get_json())
        with patch.dict(self.app.config, {"WTF_CSRF_ENABLED": True}):
            ended = self.client.delete(
                f"{USERS}/{self.users['interviewer_p1'].user_id}/devices/{device.device_id}",
                headers=self._csrf_headers(),
            )
        self.assertEqual(ended.get_json()["sessions_ended"], 1)
        empty_device = AuthDevice(project_id="AZTA01", name="Unused", platform="android", secret_hash=uuid.uuid4().hex)
        db.session.add(empty_device)
        db.session.flush()
        with patch.dict(self.app.config, {"WTF_CSRF_ENABLED": True}):
            again = self.client.delete(
                f"{USERS}/{self.users['interviewer_p1'].user_id}/devices/{empty_device.device_id}",
                headers=self._csrf_headers(),
            )
        self.assertEqual(again.get_json(), {
            "decommissioned": True, "sessions_ended": 0, "current": False,
        })

    def test_full_scope_dm_can_manage_but_partial_scope_and_project_pi_cannot(self):
        device, _issued = self._device()
        target = str(self.users["interviewer_p1"].user_id)
        self._login(str(self.users["dm_c1"].user_id))
        allowed = self.client.get(f"{USERS}/{target}/devices")
        self.assertEqual(allowed.status_code, 200, allowed.get_json())
        with patch.dict(self.app.config, {"WTF_CSRF_ENABLED": True}):
            ended = self.client.delete(f"{USERS}/{target}/devices/{device.device_id}", headers=self._csrf_headers())
        self.assertEqual(ended.get_json()["sessions_ended"], 1)

        self._add_target_grant("interviewer_p1", VaAccessRoles.interviewer, VaAccessScopeTypes.project, SP)
        self._login(str(self.users["dm_c1"].user_id))
        self.assertEqual(self.client.get(f"{USERS}/{target}/devices").status_code, 404)
        self._add_target_grant("dm_c1", VaAccessRoles.project_pi, VaAccessScopeTypes.project, SP)
        self.assertEqual(self.client.get(f"{USERS}/{target}/devices").status_code, 404)
        with patch.dict(self.app.config, {"WTF_CSRF_ENABLED": True}):
            self.assertEqual(
                self.client.delete(f"{USERS}/{target}/devices/{device.device_id}", headers=self._csrf_headers()).status_code,
                404,
            )
        self._login(str(self.users["pi_ta"].user_id))
        self.assertEqual(self.client.get(f"{USERS}/{target}/devices").status_code, 404)
