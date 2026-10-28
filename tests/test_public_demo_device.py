"""Public-demo device enrolment (digitva-77v5.5): POST /api/v1/auth/demo-enroll.

Policy: docs/policy/public-demo.md section 10. Uses the public-demo fixtures of
tests/test_public_demo.py.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

import sqlalchemy as sa

from app import db, limiter
from app.models import AuthDevice, AuthDeviceEnrolmentCode, AuthDeviceSession, AuthSecurityEvent, VaUsers
from app.services import device_auth_service as devices
from app.services import public_demo_purge_service as purge
from app.services import public_demo_service as demo
from tests.routes import test_device_api as device_tests
from tests.test_public_demo import PASSWORD, PROJECT, PublicDemoBase

URL = "/api/v1/auth/demo-enroll"
UNIFORM = {"error": "Invalid username or password.", "code": "invalid_credentials"}


class DemoEnrolTests(PublicDemoBase):
    def setUp(self):
        super().setUp()
        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self.user = self._account("demo.enrol")

    def _enrol(self, username="demo.enrol", password=PASSWORD, **fields):
        body = {"username": username, "password": password, "device_name": "Phone",
                "platform": "android", "app_version": "0.3.0", **fields}
        return self.client.post(URL, json=body)

    def _devices(self, user=None):
        user = user or self.user
        return db.session.scalars(
            sa.select(AuthDevice)
            .join(AuthDeviceEnrolmentCode, AuthDeviceEnrolmentCode.id == AuthDevice.enrolled_via)
            .where(AuthDeviceEnrolmentCode.created_by == user.user_id)
        ).all()

    def test_enrols_a_device_on_the_demo_project_and_the_device_can_sign_in(self):
        response = self._enrol(username="Demo.Enrol")
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        self.assertEqual(body["project"]["project_id"], PROJECT)
        self.assertTrue(body["device_id"] and body["device_secret"] and body["server_time"])
        device = db.session.get(AuthDevice, body["device_id"])
        self.assertEqual((device.project_id, device.platform, device.app_version), (PROJECT, "android", "0.3.0"))
        self.assertEqual(self._devices(), [device])
        # The hidden per-account code can never be redeemed as an enrolment code.
        row = db.session.get(AuthDeviceEnrolmentCode, device.enrolled_via)
        self.assertIsNotNone(row.revoked_at)
        with self.assertRaises(devices.DeviceAuthError) as refused:
            devices.enrol_device("public_demo:" + str(self.user.user_id), device_name="x", platform="android",
                                 app_version=None)
        self.assertEqual(refused.exception.code, "enrolment_invalid")
        # The secret works at sign-in, by username.
        signed_in = self.client.post("/api/v1/auth/sessions", json={
            "device_id": body["device_id"], "device_secret": body["device_secret"],
            "email": "demo.enrol", "password": PASSWORD})
        self.assertEqual(signed_in.status_code, 201, signed_in.get_json())

    def test_has_device_access_for_a_demo_account(self):
        self.assertTrue(devices.has_device_access(self.user))

    def test_wrong_password_unknown_name_and_non_demo_account_share_one_answer(self):
        other = self._get_or_make_user("demo.enrol.main@test.local", "Main-Password-123")
        cases = {
            "wrong password": self._enrol(password="wrong-demo-password"),
            "unknown name": self._enrol(username="demo.nobody"),
            "non-demo account": self._enrol(username=other.email, password="Main-Password-123"),
        }
        for label, response in cases.items():
            with self.subTest(label):
                self.assertEqual((response.status_code, response.get_json()), (401, UNIFORM))
        self.assertEqual(self._devices(), [])
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(AuthDevice).where(
            AuthDevice.enrolled_via.is_(None))) or 0, 0)

    def test_inactive_account_is_refused_like_a_wrong_password(self):
        self.user.user_status = "deactive"
        db.session.commit()
        response = self._enrol()
        self.assertEqual((response.status_code, response.get_json()), (401, UNIFORM))

    def test_invalid_device_fields_are_400(self):
        self.assertEqual(self._enrol(platform="symbian").status_code, 400)
        self.assertEqual(self._enrol(device_name="").status_code, 400)
        self.assertEqual(self._devices(), [])

    def test_demo_enrolment_stores_optional_client_device_uuid(self):
        client_uuid = uuid.uuid4()
        response = self._enrol(client_device_uuid=str(client_uuid).upper())
        self.assertEqual(response.status_code, 201, response.get_json())
        device = db.session.get(AuthDevice, response.get_json()["device_id"])
        self.assertEqual(device.client_device_uuid, client_uuid)

    def test_demo_enrolment_rejects_malformed_client_device_uuid_before_writing(self):
        response = self._enrol(client_device_uuid="not-a-uuid")
        self.assertEqual((response.status_code, response.get_json()["code"]), (400, "invalid_request"))
        self.assertEqual(self._devices(), [])

    def test_at_the_cap_demo_enrolment_is_refused_without_lru_eviction(self):
        bodies = [self._enrol().get_json() for _ in range(3)]
        for body in bodies:
            signed_in = self.client.post("/api/v1/auth/sessions", json={
                "device_id": body["device_id"], "device_secret": body["device_secret"],
                "email": self.user.username, "password": PASSWORD,
            })
            self.assertEqual(signed_in.status_code, 201, signed_in.get_json())

        fourth = self.client.post(URL, json={
            "username": self.user.username, "password": PASSWORD,
            "device_name": "Phone", "platform": "android", "app_version": "0.3.0",
        })
        self.assertEqual((fourth.status_code, fourth.get_json()["code"]), (409, "device_limit"))
        self.assertEqual(len([d for d in self._devices() if d.revoked_at is None]), 3)
        self.assertEqual(db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "device_revoked",
            AuthSecurityEvent.actor_user_id == self.user.user_id,
        )).all(), [])
        # Another account's devices are never touched.
        other = self._account("demo.enrol2")
        self.assertEqual(self._enrol(username="demo.enrol2").status_code, 201)
        self.assertEqual(len([d for d in self._devices(other) if d.revoked_at is None]), 1)

    def test_unopened_demo_devices_do_not_consume_active_slots(self):
        bodies = [self._enrol().get_json() for _ in range(3)]
        self.assertEqual(self._enrol().status_code, 201)
        self.assertTrue(all(db.session.get(AuthDevice, body["device_id"]).revoked_at is None for body in bodies))
        self.assertEqual(len([d for d in self._devices() if d.revoked_at is None]), 4)

    def test_flag_off_is_404_and_enrols_nothing(self):
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=False):
            response = self._enrol()
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self._devices(), [])

    def test_main_database_guard_refuses_before_any_credential_work(self):
        with mock.patch.object(demo, "foreign_projects_exist", return_value=True):
            response = self._enrol()
        self.assertEqual((response.status_code, response.get_json()["code"]), (503, "wrong_database"))
        self.assertEqual(self._devices(), [])

    def test_rate_limited_per_client(self):
        statuses = [self._enrol(password="wrong-demo-password").status_code for _ in range(11)]
        self.assertEqual(statuses[:10], [401] * 10)
        self.assertEqual(statuses[10], 429)

    def test_purge_deletes_a_demo_device_that_never_signed_in(self):
        self.assertEqual(self._enrol().status_code, 201)
        then = datetime.now(UTC) - timedelta(days=31)
        self.user.last_signed_in_at = then
        self.user.user_created_at = then - timedelta(days=1)
        db.session.commit()
        user_id = self.user.user_id
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_PURGE_ENABLED=True):
            counts = purge.delete_account(user_id, 30)
        db.session.commit()
        self.assertEqual((counts["auth_devices"], counts["auth_device_enrolment_codes"], counts["va_users"]), (1, 1, 1))
        self.assertIsNone(db.session.get(VaUsers, user_id))
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(AuthDevice).where(
            AuthDevice.project_id == PROJECT)), 0)


class SignUpPageTests(PublicDemoBase):
    def test_sign_up_page_links_to_the_demo_dashboard(self):
        page = self.client.get("/vaauth/signup")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'href="/public-demo/dashboard"', page.data)


class DemoDeviceFlowTests(PublicDemoBase):
    """challenge -> demo-signup -> demo-enroll -> sessions -> a protected call."""

    def test_end_to_end(self):
        client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self.client = client
        signup = self._api_signup("demo.flow")
        self.assertEqual(signup.status_code, 201, signup.get_json())
        limiter.reset()
        enrolled = client.post(URL, json={"username": "demo.flow", "password": PASSWORD,
                                          "device_name": "Pixel", "platform": "android"})
        self.assertEqual(enrolled.status_code, 201, enrolled.get_json())
        device = enrolled.get_json()
        session = client.post("/api/v1/auth/sessions", json={
            "device_id": device["device_id"], "device_secret": device["device_secret"],
            "email": "demo.flow", "password": PASSWORD})
        self.assertEqual(session.status_code, 201, session.get_json())
        tokens = session.get_json()
        self.assertTrue(tokens["access"]["account"]["device_access"])
        access = client.get("/api/v1/me/access", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        self.assertEqual(access.status_code, 200, access.get_json())
        self.assertEqual([p["project_id"] for p in access.get_json()["projects"]], [PROJECT])
        self.assertEqual(
            sorted(g["role"] for g in access.get_json()["projects"][0]["grants"]),
            ["coder", "interviewer", "reviewer"])
        live = db.session.scalar(sa.select(sa.func.count()).select_from(AuthDeviceSession).where(
            AuthDeviceSession.device_id == device["device_id"]))
        self.assertEqual(live, 1)
