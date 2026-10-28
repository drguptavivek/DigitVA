"""Account native-device cap and pair lifecycle (digitva-65m5).

These tests exercise the service boundary directly. Route authorization and
the Profile management endpoints are covered by their owning route tests.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import AuthDevice, AuthDeviceSession, AuthSecurityEvent
from app.services import device_auth_service as devices
from tests.base import BaseTestCase


class DeviceLimitServiceTests(BaseTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.user = cls.base_coder_user
        cls.other_user = cls._get_or_make_user("device.limit.other@test.local", "DeviceLimit123!")
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.access = patch.object(devices, "has_device_access", return_value=True)
        self.access.start()
        self.addCleanup(self.access.stop)

    def _device(self, label="phone"):
        secret = f"secret-{label}"
        device = AuthDevice(
            project_id=self.BASE_PROJECT_ID,
            name=label,
            platform="android",
            app_version="0.3.0",
            secret_hash=devices.hash_token(secret),
        )
        db.session.add(device)
        db.session.flush()
        return device, secret

    def _session(self, user, device, *, refresh="refresh", refresh_expires_at=None):
        now = datetime.now(UTC)
        session = AuthDeviceSession(
            device_id=device.device_id,
            user_id=user.user_id,
            access_hash=devices.hash_token(f"access-{refresh}"),
            access_expires_at=now + devices.ACCESS_TTL,
            refresh_hash=devices.hash_token(refresh),
            refresh_expires_at=refresh_expires_at or now + timedelta(days=30),
            user_session_version=user.auth_session_version or 0,
            last_seen_at=now,
        )
        db.session.add(session)
        db.session.flush()
        return session

    def test_three_live_pairs_block_fourth_without_creating_a_device(self):
        for index in range(3):
            devices.check_device_slot(self.user)
            device, _secret = self._device(f"phone-{index}")
            self._session(self.user, device, refresh=f"refresh-{index}")

        with self.assertRaises(devices.DeviceAuthError) as refused:
            devices.check_device_slot(self.user)

        self.assertEqual((refused.exception.code, refused.exception.status_code), ("device_limit", 409))
        self.assertIn("Profile", str(refused.exception))
        self.assertIn("another signed-in phone", str(refused.exception))
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count()).select_from(AuthDevice).where(AuthDevice.name.like("phone-%"))
            ),
            3,
        )

    def test_same_phone_relogin_keeps_slot_and_ends_old_session_with_data(self):
        device, secret = self._device()
        first, _user = devices._open_authorized_session(device, self.user)
        old_session_id = first.session.session_id
        second, _user = devices._open_authorized_session(device, self.user)

        old = db.session.get(AuthDeviceSession, old_session_id)
        self.assertIsNotNone(old)
        self.assertEqual(old.revoked_reason, "signed_in_again")
        self.assertEqual(devices._revoked_error(old).code, "session_ended")
        with self.assertRaises(devices.DeviceAuthError) as refused:
            devices.refresh_session(first.refresh_token, device_id=device.device_id, device_secret=secret)
        self.assertEqual(refused.exception.code, "session_ended")
        self.assertIsNone(second.session.revoked_at)
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count(sa.distinct(AuthDeviceSession.device_id))).where(
                    AuthDeviceSession.user_id == self.user.user_id,
                    AuthDeviceSession.revoked_at.is_(None),
                )
            ),
            1,
        )

    def test_refresh_at_cap_rotates_without_creating_a_fourth_pair(self):
        rows = []
        for index in range(3):
            device, secret = self._device(f"refresh-phone-{index}")
            rows.append((device, secret, self._session(self.user, device, refresh=f"refresh-{index}")))

        issued, _user = devices.refresh_session(
            "refresh-0", device_id=rows[0][0].device_id, device_secret=rows[0][1]
        )

        self.assertTrue(issued.refresh_token)
        self.assertEqual(
            db.session.scalar(
                sa.select(sa.func.count(sa.distinct(AuthDeviceSession.device_id))).where(
                    AuthDeviceSession.user_id == self.user.user_id,
                    AuthDeviceSession.revoked_at.is_(None),
                    AuthDeviceSession.refresh_expires_at > datetime.now(UTC),
                )
            ),
            3,
        )

    def test_expired_and_revoked_slots_are_free(self):
        expired, _secret = self._device("expired")
        self._session(
            self.user,
            expired,
            refresh="expired-refresh",
            refresh_expires_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        revoked, _secret = self._device("revoked")
        self._session(self.user, revoked, refresh="revoked-refresh")
        revoked.revoked_at = datetime.now(UTC)
        live, _secret = self._device("live")
        self._session(self.user, live, refresh="live-refresh")

        devices.check_device_slot(self.user)

    def test_shared_phone_only_ends_the_signing_in_users_pair(self):
        device, _secret = self._device("shared")
        other_session = self._session(self.other_user, device, refresh="other-refresh")

        devices._open_authorized_session(device, self.user)

        self.assertIsNone(other_session.revoked_at)
        self.assertEqual(other_session.user_id, self.other_user.user_id)

    def test_pair_decommission_keeps_device_and_session_work_metadata(self):
        device, _secret = self._device("decommission")
        session = self._session(self.user, device, refresh="decommission-refresh")
        session.outstanding_count = 2
        session.outstanding_unique_ids = ["case-1"]
        db.session.flush()

        ended = devices.decommission_account_device(self.user.user_id, device.device_id, self.base_admin_user)
        again = devices.decommission_account_device(self.user.user_id, device.device_id, self.base_admin_user)

        self.assertEqual((ended, again), (1, 0))
        self.assertIsNone(device.revoked_at)
        self.assertEqual((session.revoked_reason, session.outstanding_count, session.outstanding_unique_ids),
                         ("device_decommissioned", 2, ["case-1"]))
        event = db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "device_decommissioned",
            AuthSecurityEvent.actor_user_id == self.base_admin_user.user_id,
        ).order_by(AuthSecurityEvent.occurred_at.desc())).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.detail["device_id"], str(device.device_id))

    def test_slot_check_locks_account_before_counting(self):
        device, _secret = self._device("lock")
        self._session(self.user, device, refresh="lock-refresh")
        with patch.object(db.session, "execute", wraps=db.session.execute) as execute:
            devices.check_device_slot(self.user)

        first_statement = execute.call_args_list[0].args[0]
        self.assertIsNotNone(first_statement._for_update_arg)
