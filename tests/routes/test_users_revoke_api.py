"""Revoking an unused enrolment code and an enrolled device from the Users
page (digitva-342x): same viewers and scope as issuing a code, audited.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import sqlalchemy as sa

from app import db, limiter
from app.models import AuthDevice, AuthDeviceSession, AuthSecurityEvent
from app.models.auth_devices import AuthDeviceEnrolmentCode
from tests.authz.fixture import TA, TB, AuthzFixtureMixin
from tests.base import BaseTestCase

URL = "/api/v1/users"


class UsersRevokeApiTests(AuthzFixtureMixin, BaseTestCase):

    def setUp(self):
        super().setUp()
        limiter.reset()

    def _as(self, key):
        self._login(str(self.users[key].user_id))

    def _code(self, target="interviewer_p1", **changes):
        """A code issued for *target*: the row plus its creation event."""
        row = AuthDeviceEnrolmentCode(
            project_id=TA, code_hash=uuid.uuid4().hex, expires_at=datetime.now(UTC) + timedelta(hours=1),
            max_uses=1, created_by=self.users["admin"].user_id, **changes)
        db.session.add(row)
        db.session.flush()
        db.session.add(AuthSecurityEvent(
            user_id=self.users[target].user_id, event_type="device_enrolment_code_created",
            detail={"project_id": TA, "code_id": str(row.id)}))
        db.session.commit()
        return row

    def _session(self, device, target):
        now = datetime.now(UTC)
        session = AuthDeviceSession(
            device_id=device.device_id, user_id=self.users[target].user_id,
            access_hash=uuid.uuid4().hex, access_expires_at=now + timedelta(hours=1),
            refresh_hash=uuid.uuid4().hex, refresh_expires_at=now + timedelta(days=30))
        db.session.add(session)
        db.session.commit()
        return session

    def _device(self, target="interviewer_p1", project=TA):
        now = datetime.now(UTC)
        device = AuthDevice(project_id=project, name="Tab", platform="android", secret_hash=uuid.uuid4().hex)
        db.session.add(device)
        db.session.flush()
        session = AuthDeviceSession(
            device_id=device.device_id, user_id=self.users[target].user_id,
            access_hash=uuid.uuid4().hex, access_expires_at=now + timedelta(hours=1),
            refresh_hash=uuid.uuid4().hex, refresh_expires_at=now + timedelta(days=30))
        db.session.add(session)
        db.session.commit()
        return device, session

    def _revoke_code(self, key, row, target="interviewer_p1"):
        self._as(key)
        return self.client.post(f"{URL}/{self.users[target].user_id}/enrolment-codes/{row.id}/revoke",
                                headers=self._csrf_headers())

    def _revoke_device(self, key, device_id, target="interviewer_p1", **body):
        self._as(key)
        return self.client.post(f"{URL}/{self.users[target].user_id}/devices/{device_id}/revoke",
                                json=body, headers=self._csrf_headers())

    def _events(self, event_type):
        return db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == event_type)).all()

    # -- codes ----------------------------------------------------------------

    def test_viewers_who_may_issue_may_revoke_a_code_and_it_is_audited(self):
        for key in ("admin", "pi_ta", "dm_c1"):
            row = self._code()
            res = self._revoke_code(key, row)
            self.assertEqual(res.status_code, 200, (key, res.get_json()))
            self.assertEqual(res.get_json(), {"revoked": True})
            db.session.refresh(row)
            self.assertIsNotNone(row.revoked_at)
        events = self._events("device_enrolment_code_revoked")
        self.assertEqual({e.actor_user_id for e in events},
                         {self.users[k].user_id for k in ("admin", "pi_ta", "dm_c1")})

    def test_code_refusals(self):
        # Present first: an in-scope DM revokes a valid code.
        self.assertEqual(self._revoke_code("dm_c1", self._code()).status_code, 200)
        # Out-of-scope DM: indistinguishable from missing.
        row = self._code("coder_ta")
        self.assertEqual(self._revoke_code("dm_c1", row, "coder_ta").status_code, 404)
        db.session.refresh(row)
        self.assertIsNone(row.revoked_at)
        # A code issued for someone else is not reachable through this user.
        self.assertEqual(self._revoke_code("dm_c1", self._code("coder_c1")).status_code, 404)
        # Not a viewer role.
        self.assertEqual(self._revoke_code("coder_p1", self._code()).status_code, 403)
        self.assertEqual(len(self._events("device_enrolment_code_revoked")), 1)

    def test_used_expired_and_revoked_codes_are_refused(self):
        res = self._revoke_code("admin", self._code(use_count=1))
        self.assertEqual((res.status_code, res.get_json()["code"]), (409, "code_used"))
        expired = self._code()
        expired.expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.session.commit()
        self.assertEqual(self._revoke_code("admin", expired).get_json()["code"], "code_expired")
        again = self._code(revoked_at=datetime.now(UTC))
        self.assertEqual(self._revoke_code("admin", again).get_json()["code"], "code_revoked")
        self.assertEqual(self._events("device_enrolment_code_revoked"), [])
        self.assertEqual(self._revoke_code("admin", self._code()).status_code, 200)

    def test_code_revoke_needs_csrf(self):
        row = self._code()
        self._as("admin")
        with patch.dict(self.app.config, {"WTF_CSRF_ENABLED": True}):
            res = self.client.post(f"{URL}/{self.users['interviewer_p1'].user_id}/enrolment-codes/{row.id}/revoke")
        self.assertEqual(res.status_code, 400)
        db.session.refresh(row)
        self.assertIsNone(row.revoked_at)

    # -- devices --------------------------------------------------------------

    def test_viewers_who_may_issue_may_revoke_a_device_and_its_sessions_end(self):
        for key in ("admin", "pi_ta", "dm_c1"):
            device, session = self._device()
            res = self._revoke_device(key, device.device_id)
            self.assertEqual(res.status_code, 200, (key, res.get_json()))
            self.assertEqual(res.get_json(), {"revoked": True, "sessions_ended": 1, "compromised": False})
            db.session.refresh(device)
            db.session.refresh(session)
            self.assertIsNotNone(device.revoked_at)
            self.assertFalse(device.revoked_compromised)
            self.assertIsNotNone(session.revoked_at)
        events = self._events("device_revoked")
        self.assertEqual({e.detail["reason"] for e in events}, {"users_page"})
        self.assertEqual({e.actor_user_id for e in events},
                         {self.users[k].user_id for k in ("admin", "pi_ta", "dm_c1")})

    def test_lost_or_compromised_is_recorded(self):
        device, _session = self._device()
        res = self._revoke_device("dm_c1", device.device_id, compromised=True)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json()["compromised"])
        db.session.refresh(device)
        self.assertTrue(device.revoked_compromised)
        [event] = self._events("device_revoked")
        self.assertTrue(event.detail["compromised"])

    def test_device_refusals(self):
        device, _session = self._device()
        self.assertEqual(self._revoke_device("dm_c1", device.device_id, compromised="yes").status_code, 400)
        # Out-of-scope DM, a device the user never used, an unknown id, a non-viewer.
        far, _s = self._device("coder_ta")
        self.assertEqual(self._revoke_device("dm_c1", far.device_id, "coder_ta").status_code, 404)
        self.assertEqual(self._revoke_device("dm_c1", far.device_id).status_code, 404)
        self.assertEqual(self._revoke_device("dm_c1", uuid.uuid4()).status_code, 404)
        self.assertEqual(self._revoke_device("coder_p1", device.device_id).status_code, 403)
        db.session.refresh(device)
        self.assertIsNone(device.revoked_at)
        self.assertEqual(self._events("device_revoked"), [])
        # Present: the in-scope DM may revoke it.
        self.assertEqual(self._revoke_device("dm_c1", device.device_id).status_code, 200)

    def test_device_revoke_needs_csrf(self):
        device, _session = self._device()
        self._as("admin")
        with patch.dict(self.app.config, {"WTF_CSRF_ENABLED": True}):
            res = self.client.post(f"{URL}/{self.users['interviewer_p1'].user_id}/devices/{device.device_id}/revoke",
                                   json={})
        self.assertEqual(res.status_code, 400)
        db.session.refresh(device)
        self.assertIsNone(device.revoked_at)

    def test_status_lists_code_ids_and_devices_for_the_screen(self):
        row = self._code()
        device, _session = self._device()
        self._as("dm_c1")
        body = self.client.get(f"{URL}/{self.users['interviewer_p1'].user_id}/status").get_json()
        self.assertIn(str(row.id), [c["code_id"] for c in body["enrolment_codes"]])
        self.assertIn(str(device.device_id), [d["device_id"] for d in body["devices"]])

    # -- shared phones --------------------------------------------------------

    def test_shared_phone_plain_revoke_ends_only_the_targets_sessions(self):
        device, mine = self._device()
        other = self._session(device, "coder_ta")  # out of the data manager's scope
        res = self._revoke_device("dm_c1", device.device_id)
        self.assertEqual(res.status_code, 200, res.get_json())
        self.assertEqual(res.get_json(), {"revoked": False, "sessions_ended": 1, "compromised": False, "shared": True})
        for row in (device, mine, other):
            db.session.refresh(row)
        self.assertIsNotNone(mine.revoked_at)
        self.assertIsNone(other.revoked_at)
        self.assertIsNone(device.revoked_at)
        [event] = self._events("device_decommissioned")
        self.assertEqual((event.actor_user_id, event.user_id),
                         (self.users["dm_c1"].user_id, self.users["interviewer_p1"].user_id))
        self.assertEqual(self._events("device_revoked"), [])

    def test_shared_phone_compromised_is_refused(self):
        device, mine = self._device()
        other = self._session(device, "coder_ta")
        res = self._revoke_device("dm_c1", device.device_id, compromised=True)
        self.assertEqual((res.status_code, res.get_json()["code"]), (409, "device_shared"))
        for row in (device, mine, other):
            db.session.refresh(row)
        self.assertIsNone(device.revoked_at)
        self.assertFalse(device.revoked_compromised)
        self.assertIsNone(mine.revoked_at)
        self.assertIsNone(other.revoked_at)

    def test_admin_revokes_a_shared_phone_device_wide(self):
        device, mine = self._device()
        other = self._session(device, "coder_ta")
        res = self._revoke_device("admin", device.device_id, compromised=True)
        self.assertEqual(res.get_json(), {"revoked": True, "sessions_ended": 2, "compromised": True})
        for row in (device, mine, other):
            db.session.refresh(row)
        self.assertIsNotNone(device.revoked_at)
        self.assertIsNotNone(other.revoked_at)

    def test_phone_shared_only_with_in_scope_people_is_revoked_device_wide(self):
        device, mine = self._device()
        other = self._session(device, "coder_c1")  # someone else the data manager fully sees
        self.assertEqual(self._revoke_device("dm_c1", device.device_id, compromised=True).get_json(),
                         {"revoked": True, "sessions_ended": 2, "compromised": True})
        db.session.refresh(device)
        self.assertIsNotNone(device.revoked_at)

    def test_status_devices_exclude_out_of_scope_projects(self):
        mine, _s = self._device()
        far, _s = self._device(project=TB)
        self._as("dm_c1")
        body = self.client.get(f"{URL}/{self.users['interviewer_p1'].user_id}/status").get_json()
        ids = [d["device_id"] for d in body["devices"]]
        self.assertIn(str(mine.device_id), ids)
        self.assertNotIn(str(far.device_id), ids)
