from datetime import datetime, timedelta, timezone
import unittest
import uuid

import requests

from app import create_app, db
from app.models import MasOdkConnections, VaStatuses
from app.services.odk_connection_guard_service import (
    OdkConnectionCooldownError,
    guarded_odk_call,
    record_odk_connection_failure,
    record_odk_connection_success,
    reserve_odk_request_slot,
    snapshot_connection_guard_state,
)
from app.utils.credential_crypto import encrypt_credential
from config import TestConfig


PEPPER = "test-pepper-do-not-use-in-production"


class OdkConnectionGuardServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(TestConfig)
        cls.ctx = cls.app.app_context()
        cls.ctx.push()
        db.drop_all()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.drop_all()
        cls.ctx.pop()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        db.create_all()

    def _create_connection(self, name="Guard Test"):
        username_enc, username_salt = encrypt_credential("guard@test.local", PEPPER)
        password_enc, password_salt = encrypt_credential("secret", PEPPER)
        conn = MasOdkConnections(
            connection_id=uuid.uuid4(),
            connection_name=name,
            base_url="https://guard.test",
            username_enc=username_enc,
            username_salt=username_salt,
            password_enc=password_enc,
            password_salt=password_salt,
            status=VaStatuses.active,
        )
        db.session.add(conn)
        db.session.commit()
        return conn

    def test_repeated_retryable_failures_activate_cooldown(self):
        conn = self._create_connection()
        exc = requests.exceptions.ConnectTimeout("timed out")

        for _ in range(self.app.config["ODK_CONNECTION_FAILURE_THRESHOLD"]):
            record_odk_connection_failure(conn.connection_id, exc)

        snapshot = snapshot_connection_guard_state(conn.connection_id)
        self.assertIsNotNone(snapshot)
        self.assertTrue(snapshot.cooldown_active)
        self.assertEqual(
            snapshot.consecutive_failure_count,
            self.app.config["ODK_CONNECTION_FAILURE_THRESHOLD"],
        )
        self.assertIn("timed out", snapshot.last_failure_message)

    def test_success_resets_cooldown_and_failure_count(self):
        conn = self._create_connection()
        db.session.query(MasOdkConnections).filter_by(
            connection_id=conn.connection_id
        ).update(
            {
                "cooldown_until": datetime.now(timezone.utc) + timedelta(minutes=5),
                "consecutive_failure_count": 3,
            }
        )
        db.session.commit()

        record_odk_connection_success(conn.connection_id)

        snapshot = snapshot_connection_guard_state(conn.connection_id)
        self.assertIsNotNone(snapshot)
        self.assertFalse(snapshot.cooldown_active)
        self.assertIsNone(snapshot.cooldown_until)
        self.assertEqual(snapshot.consecutive_failure_count, 0)
        self.assertIsNotNone(snapshot.last_success_at)

    def test_guarded_call_short_circuits_active_cooldown(self):
        conn = self._create_connection()
        db.session.query(MasOdkConnections).filter_by(
            connection_id=conn.connection_id
        ).update(
            {
                "cooldown_until": datetime.now(timezone.utc) + timedelta(minutes=5),
                "last_failure_message": "connect timeout",
            }
        )
        db.session.commit()

        call_count = {"count": 0}

        def _callback():
            call_count["count"] += 1
            return "unreachable"

        with self.assertRaises(OdkConnectionCooldownError):
            guarded_odk_call(_callback, connection_id=conn.connection_id)

        self.assertEqual(call_count["count"], 0)

    def test_reserve_request_slot_applies_configured_spacing(self):
        conn = self._create_connection()
        self.app.config["ODK_CONNECTION_MIN_REQUEST_INTERVAL_SECONDS"] = 0.25

        first_wait = reserve_odk_request_slot(conn.connection_id)
        second_wait = reserve_odk_request_slot(conn.connection_id)

        self.assertEqual(first_wait, 0.0)
        self.assertGreater(second_wait, 0.0)
