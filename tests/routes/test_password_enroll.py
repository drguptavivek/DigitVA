"""Atomic manual native enrolment (digitva-hs7e.6.2).

Uses the existing device API project and HTTP helpers without inheriting its
tests. All writes belong to the normal isolated BaseTestCase transaction.
"""

import logging
import uuid
from datetime import UTC, datetime
from unittest import mock

import sqlalchemy as sa

from app import db, limiter
from app.models import (
    AuthDevice,
    AuthDeviceSession,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import device_auth_service as devices
from app.services import organization_service as org
from app.services.authz import invalidate
from app.services.authz.consulted import PUBLIC_ENDPOINTS
from tests.base import BaseTestCase
from tests.routes import test_device_api as device_tests

URL = "/api/v1/auth/password-enroll"
PASSWORD = device_tests.PASSWORD
_DEV = device_tests.DeviceApiTests.__dict__


class PasswordEnrolTests(BaseTestCase):
    PROJECT_ID = "PWE01"
    OTHER_PROJECT_ID = "PWE02"
    _make_project = _DEV["_make_project"]
    _make_site = _DEV["_make_site"]
    _grant = _DEV["_grant"]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls._make_project(cls.PROJECT_ID, "PW01", now)
        cls._make_project(cls.OTHER_PROJECT_ID, "PW02", now)
        cls.user = cls._get_or_make_user("password.enrol@test.local", PASSWORD)
        cls._grant(cls.user, cls.OTHER_PROJECT_ID)
        cls._grant(cls.user, cls.PROJECT_ID)
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)

    def _enrol(self, **fields):
        """Post one valid enrolment, overriding only the fields under test."""
        return self.client.post(URL, json={
            "identifier": self.user.email, "password": PASSWORD,
            "device_name": "Manual phone", "platform": "android", "app_version": "0.3.12",
            **fields,
        })

    @staticmethod
    def _counts():
        """Device/session counts before and after a refused atomic request."""
        return tuple(db.session.scalar(sa.select(sa.func.count()).select_from(model))
                     for model in (AuthDevice, AuthDeviceSession))

    def _worker(self, role, project_ids):
        """Make a verified worker with only the explicit project grants named."""
        user = self._get_or_make_user(f"password.{role.value}@test.local", PASSWORD)
        db.session.add_all([
            VaUserAccessGrants(
                user_id=user.user_id, role=role, scope_type=VaAccessScopeTypes.project,
                project_id=project_id, notes="manual enrolment test", grant_status=VaStatuses.active,
            ) for project_id in project_ids
        ])
        db.session.commit()
        return user

    def test_success_combines_enrolment_and_session_and_stores_install_uuid(self):
        client_uuid = uuid.uuid4()
        response = self._enrol(client_device_uuid=str(client_uuid).upper())
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        self.assertEqual(set(body), {
            "device_id", "device_secret", "project", "server_time", "access_token", "access_expires_at",
            "refresh_token", "refresh_expires_at", "user", "terms_required", "access",
        })
        self.assertEqual(body["project"], {"project_id": self.PROJECT_ID, "name": "Device PWE01"})
        self.assertTrue(body["server_time"])
        device = db.session.get(AuthDevice, uuid.UUID(body["device_id"]))
        self.assertEqual(device.client_device_uuid, client_uuid)
        self.assertEqual(device.secret_hash, devices.hash_token(body["device_secret"]))
        self.assertEqual((device.platform, device.app_version), ("android", "0.3.12"))
        self.assertIsNone(device.enrolled_via)
        session = db.session.scalar(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.device_id == device.device_id))
        self.assertIsNotNone(session)
        self.assertEqual(session.user_id, self.user.user_id)
        self.assertEqual(session.refresh_hash, devices.hash_token(body["refresh_token"]))
        self.assertEqual(session.access_hash, devices.hash_token(body["access_token"]))
        self.assertFalse(body["terms_required"])
        access = self.client.get("/api/v1/me/access", headers={
            "Authorization": f"Bearer {body['access_token']}",
        })
        self.assertEqual(access.status_code, 200, access.get_json())
        self.assertEqual(access.get_json(), body["access"])
        self.assertEqual({p["project_id"] for p in body["access"]["projects"]},
                         {self.PROJECT_ID, self.OTHER_PROJECT_ID})
        refreshed = self.client.post("/api/v1/auth/sessions/refresh", json={
            "device_id": body["device_id"], "device_secret": body["device_secret"],
            "refresh_token": body["refresh_token"],
        })
        self.assertEqual(refreshed.status_code, 200, refreshed.get_json())

    def test_wrong_unknown_inactive_and_empty_credentials_share_one_401_without_rows(self):
        before = self._counts()
        uniform = {"error": "Invalid email or password.", "code": "invalid_credentials"}
        cases = (
            {"password": "wrong"}, {"identifier": "missing@test.local"},
            {"identifier": ""}, {"identifier": None}, {"password": None}, {"password": {}},
        )
        for fields in cases:
            with self.subTest(fields=fields):
                response = self._enrol(**fields)
                self.assertEqual((response.status_code, response.get_json()), (401, uniform))
                self.assertEqual(self._counts(), before)
        self.user.user_status = VaStatuses.deactive
        db.session.commit()
        response = self._enrol()
        self.assertEqual((response.status_code, response.get_json()), (401, uniform))
        self.assertEqual(self._counts(), before)

    def test_no_native_access_creates_neither_device_nor_session(self):
        outsider = self._get_or_make_user("password.outsider@test.local", PASSWORD)
        db.session.commit()
        before = self._counts()
        response = self._enrol(identifier=outsider.email)
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "no_interviewer_grant"))
        self.assertEqual(self._counts(), before)

    def test_invalid_device_fields_and_uuid_leave_no_rows(self):
        before = self._counts()
        for fields in (
            {"device_name": ""}, {"device_name": "x" * 65}, {"platform": "symbian"},
            {"platform": []}, {"app_version": "x" * 33}, {"client_device_uuid": "invalid"},
            {"client_device_uuid": 7},
        ):
            with self.subTest(fields=fields):
                response = self._enrol(**fields)
                self.assertEqual((response.status_code, response.get_json()["code"]), (400, "invalid_request"))
                self.assertEqual(self._counts(), before)

    def test_fourth_phone_is_refused_without_any_eviction(self):
        bodies = []
        for _ in range(3):
            response = self._enrol()
            self.assertEqual(response.status_code, 201, response.get_json())
            bodies.append(response.get_json())
        before = self._counts()
        response = self._enrol()
        self.assertEqual((response.status_code, response.get_json()["code"]), (409, "device_limit"))
        self.assertEqual(self._counts(), before)
        for body in bodies:
            device = db.session.get(AuthDevice, uuid.UUID(body["device_id"]))
            self.assertIsNotNone(device)
            self.assertIsNone(device.revoked_at)
            self.assertIsNotNone(devices.resolve_access_token(body["access_token"]))

    def test_session_failure_rolls_back_both_flushed_rows(self):
        create_session = devices._create_session
        before = self._counts()

        def fail_after_issue(device, user):
            create_session(device, user)
            raise devices.DeviceAuthError("Could not open session.", "unavailable", 503)

        with mock.patch.object(devices, "_create_session", side_effect=fail_after_issue):
            response = self._enrol()
        self.assertEqual((response.status_code, response.get_json()["code"]), (503, "unavailable"))
        self.assertEqual(self._counts(), before)

    def test_pending_terms_enrols_but_data_calls_use_the_normal_terms_gate(self):
        self.user.pw_reset_t_and_c = False
        db.session.commit()
        response = self._enrol()
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        self.assertTrue(body["terms_required"])
        headers = {"Authorization": f"Bearer {body['access_token']}"}
        refused = self.client.get("/api/v1/me/access", headers=headers)
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (403, "terms_required"))
        accepted = self.client.post("/api/v1/me/terms", json={"accept_terms": True}, headers=headers)
        self.assertEqual(accepted.status_code, 200, accepted.get_json())
        self.assertEqual(self.client.get("/api/v1/me/access", headers=headers).status_code, 200)

    def test_coder_coding_tester_and_reviewer_only_use_first_native_project(self):
        for role in (VaAccessRoles.coder, VaAccessRoles.coding_tester, VaAccessRoles.reviewer):
            with self.subTest(role=role):
                user = self._worker(role, [self.OTHER_PROJECT_ID, self.PROJECT_ID])
                response = self._enrol(identifier=user.email)
                self.assertEqual(response.status_code, 201, response.get_json())
                body = response.get_json()
                self.assertEqual(body["project"]["project_id"], self.PROJECT_ID)
                self.assertEqual(body["access"]["roles"], [role.value])

    def test_collection_home_wins_over_a_lower_coding_project(self):
        user = self._worker(VaAccessRoles.coder, [self.PROJECT_ID])
        self._grant(user, self.OTHER_PROJECT_ID)
        db.session.commit()
        response = self._enrol(identifier=user.email)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["project"]["project_id"], self.OTHER_PROJECT_ID)

    def test_death_reporter_only_uses_first_registration_project(self):
        user = self._get_or_make_user("password.death_reporter@test.local", PASSWORD)
        for project_id in (self.OTHER_PROJECT_ID, self.PROJECT_ID):
            level = org.create_level(project_id, level_code="district", level_name="District", depth=1)
            unit = org.create_unit(
                project_id, org_level_id=level.org_level_id,
                unit_code="D1", unit_name="District 1",
            )
            db.session.add(VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.death_reporter,
                scope_type=VaAccessScopeTypes.org_unit, org_unit_id=unit.org_unit_id,
                notes="manual enrolment test", grant_status=VaStatuses.active,
            ))
        db.session.commit()
        response = self._enrol(identifier=user.email)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["project"]["project_id"], self.PROJECT_ID)
        self.assertEqual(response.get_json()["access"]["roles"], ["death_reporter"])

    def test_mixed_admin_coder_keeps_native_projection_and_native_home(self):
        user = self._worker(VaAccessRoles.coder, [self.OTHER_PROJECT_ID])
        db.session.add_all([
            VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.admin,
                scope_type=VaAccessScopeTypes.global_scope, grant_status=VaStatuses.active,
            ),
            VaUserAccessGrants(
                user_id=user.user_id, role=VaAccessRoles.data_manager,
                scope_type=VaAccessScopeTypes.project, project_id=self.PROJECT_ID,
                grant_status=VaStatuses.active,
            ),
        ])
        db.session.commit()
        response = self._enrol(identifier=user.email)
        self.assertEqual(response.status_code, 201, response.get_json())
        body = response.get_json()
        self.assertEqual(body["project"]["project_id"], self.OTHER_PROJECT_ID)
        self.assertEqual(body["access"]["roles"], ["coder"])
        self.assertFalse(body["access"]["is_admin"])

    def test_closed_native_gate_never_becomes_home(self):
        user = self._worker(VaAccessRoles.reviewer, [self.PROJECT_ID, self.OTHER_PROJECT_ID])
        db.session.execute(sa.update(VaForms).where(VaForms.project_id == self.PROJECT_ID)
                           .values(form_status=VaStatuses.deactive))
        db.session.commit()
        invalidate(user.user_id)
        response = self._enrol(identifier=user.email)
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["project"]["project_id"], self.OTHER_PROJECT_ID)

    def test_inactive_project_never_becomes_home(self):
        db.session.get(VaProjectMaster, self.PROJECT_ID).project_status = VaStatuses.deactive
        db.session.commit()
        response = self._enrol()
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["project"]["project_id"], self.OTHER_PROJECT_ID)

    def test_email_verification_and_maintenance_refuse_before_creation(self):
        self.user.email_verified = False
        db.session.commit()
        before = self._counts()
        response = self._enrol()
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "email_unverified"))
        self.assertEqual(self._counts(), before)
        self.user.email_verified = True
        db.session.commit()
        with mock.patch.object(devices, "should_block_non_admin_after_cutoff", return_value=True):
            response = self._enrol()
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "maintenance"))
        self.assertEqual(self._counts(), before)

    def test_mobile_identifier_uses_the_existing_resolver(self):
        self.user.mobile_login = "9876543210"
        db.session.commit()
        response = self._enrol(identifier="+91 98765 43210")
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["user"]["user_id"], str(self.user.user_id))

    def test_rate_limited_per_ip(self):
        statuses = [self._enrol(password="wrong").status_code for _ in range(11)]
        self.assertEqual(statuses, [401] * 10 + [429])

    def test_rate_limited_on_canonical_identifier_across_ips(self):
        self.user.mobile_login = "9876543210"
        db.session.commit()
        statuses = []
        for index in range(21):
            response = self.client.post(URL, json={
                "identifier": "9876543210" if index % 2 else "+91 98765 43210",
                "password": "wrong", "device_name": "Phone", "platform": "android",
            }, environ_overrides={"REMOTE_ADDR": f"10.42.0.{index + 1}"})
            statuses.append(response.status_code)
        self.assertEqual(statuses, [401] * 20 + [429])

    def test_registered_native_endpoint_accepts_stale_bearer_without_using_cookie_authority(self):
        endpoint = "api_v1.auth_api.password_enroll"
        self.assertIn(endpoint, devices.UNAUTHENTICATED_ENDPOINTS)
        self.assertIn(endpoint, PUBLIC_ENDPOINTS)
        self._login(str(self.base_admin_user.user_id))
        with mock.patch.dict(self.app.config, WTF_CSRF_ENABLED=True):
            response = self.client.post(URL, json={
                "identifier": self.user.email, "password": PASSWORD,
                "device_name": "Phone", "platform": "android",
            }, headers={"Authorization": "Bearer stale-access-token"})
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["user"]["user_id"], str(self.user.user_id))
        before = self._counts()
        refused = self._enrol(identifier=None, password=None)
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (401, "invalid_credentials"))
        self.assertEqual(self._counts(), before)
        with mock.patch.dict(self.app.config, WTF_CSRF_ENABLED=True):
            mutation = self.client.post("/api/v1/me/terms", json={"accept_terms": True})
        self.assertEqual(mutation.status_code, 400)

    def test_public_demo_deployment_does_not_offer_active_password_enrolment(self):
        before = self._counts()
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=True):
            with mock.patch.object(devices, "enrol_with_password") as enrol:
                response = self._enrol()
        self.assertEqual(response.status_code, 404)
        enrol.assert_not_called()
        self.assertEqual(self._counts(), before)

    def test_public_demo_account_cannot_use_active_enrolment(self):
        self.user.is_public_demo = True
        db.session.commit()
        before = self._counts()
        response = self._enrol()
        self.assertEqual((response.status_code, response.get_json()["code"]), (401, "invalid_credentials"))
        self.assertEqual(self._counts(), before)

    def test_credentials_and_tokens_are_absent_from_logs(self):
        with self.assertLogs("app", level="INFO") as captured:
            logging.getLogger("app").info("password enrolment test marker")
            response = self._enrol()
            self.assertEqual(response.status_code, 201, response.get_json())
            body = response.get_json()
            self._enrol(password="wrong-enrolment-password")
        text = "\n".join(captured.output)
        self.assertIn("password enrolment test marker", text)
        for secret in (self.user.email, PASSWORD, "wrong-enrolment-password", body["device_secret"],
                       body["access_token"], body["refresh_token"]):
            self.assertNotIn(secret, text)
