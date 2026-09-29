"""``flask devices create-enrolment-code``: same service and audit as the admin API."""
import json

import sqlalchemy as sa

from app import db
from app.models import AuthDeviceEnrolmentCode, AuthSecurityEvent
from app.services.device_auth_service import hash_token
from tests.base import BaseTestCase


class DevicesCliTestCase(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.runner = self.app.test_cli_runner()

    def _invoke(self, *extra, actor=None):
        return self.runner.invoke(args=[
            "devices", "create-enrolment-code", "--project", self.BASE_PROJECT_ID,
            "--actor", actor or self.base_admin_user.email, *extra,
        ])

    def test_prints_only_the_qr_payload_and_stores_the_code_hashed(self):
        result = self._invoke("--minutes", "30", "--uses", "2")

        self.assertEqual(result.exit_code, 0, result.output)
        payload = json.loads(result.output)
        self.assertEqual(set(payload), {"v", "server", "enroll", "project"})
        self.assertEqual(payload["server"], self.app.config["DEVICE_PUBLIC_URL"])
        self.assertEqual(payload["project"], self.BASE_PROJECT_ID)
        row = db.session.scalar(sa.select(AuthDeviceEnrolmentCode).where(
            AuthDeviceEnrolmentCode.code_hash == hash_token(payload["enroll"])))
        self.assertIsNotNone(row)
        self.assertEqual(row.max_uses, 2)
        self.assertEqual(row.created_by, self.base_admin_user.user_id)
        event = db.session.scalar(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "device_enrolment_code_created",
            AuthSecurityEvent.actor_user_id == self.base_admin_user.user_id,
        ).order_by(AuthSecurityEvent.occurred_at.desc()).limit(1))
        self.assertIsNotNone(event)
        self.assertEqual(event.detail["expires_in_minutes"], 30)

    def test_refuses_a_non_admin_actor(self):
        before = db.session.scalar(sa.select(sa.func.count()).select_from(AuthDeviceEnrolmentCode))

        result = self._invoke(actor=self.base_coder_user.email)

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("active global admin", result.output)
        after = db.session.scalar(sa.select(sa.func.count()).select_from(AuthDeviceEnrolmentCode))
        self.assertEqual(before, after)

    def test_refuses_out_of_range_uses_with_the_service_message(self):
        result = self._invoke("--uses", "0")

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("max_uses", result.output)
