"""Characterization of the device sign-in contract (bead digitva-r8nh.17).

Written on the unchanged ``device_auth_service`` before it was split into
``app/services/device/``, so the split can be shown to change nothing old
APKs depend on: the exact reply keys, statuses and error bodies of enroll,
password-enroll, sign-in-QR redeem, demo-enroll, sign-in, refresh and
sign-out; bearer refusals; which credential paths audit a revoked device;
``UNAUTHENTICATED_ENDPOINTS``; the logger name; and every name the module
exposes. Policy: docs/policy/mobile-sign-in.md, docs/current-state/api-v1.md,
docs/current-state/device-collection-api.md. Borrows the helpers of the
existing suites without inheriting their tests.
"""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa

from app import db, limiter
from app.models import AuthDevice, AuthSecurityEvent, AuthSignInToken
from app.services import device_auth_service as devices
from app.services import sign_in_qr_service
from tests.authz.fixture import AuthzFixtureMixin
from tests.base import BaseTestCase
from tests.routes import test_device_api as device_tests
from tests.routes import test_sign_in_qr as qr_tests
from tests.test_public_demo import PASSWORD as DEMO_PASSWORD
from tests.test_public_demo import PROJECT as DEMO_PROJECT
from tests.test_public_demo import PublicDemoBase

API = device_tests.API
PASSWORD = device_tests.PASSWORD
_DEV = device_tests.DeviceApiTests.__dict__

ENROL_KEYS = {"device_id", "device_secret", "project", "server_time"}
SESSION_KEYS = {
    "access_token", "access_expires_at", "refresh_token", "refresh_expires_at", "user",
    "terms_required", "access",
}
UNAUTHORIZED = {"error": "Authentication required.", "code": "unauthorized"}

#: Every top-level name the module defined on the unchanged code (ast), plus
#: the imported names callers or tests reach through it.
FACADE_NAMES = {
    "ACCESS_TTL", "API_V1_PREFIX", "DEFAULT_REFRESH_TTL_DAYS", "DEFAULT_SESSION_MAX_DAYS",
    "DEVICE_LIMIT_MESSAGE", "DeviceAuthError", "ENROLMENT_DEFAULT_MINUTES", "ENROLMENT_MAX_MINUTES",
    "ENROLMENT_MAX_USES", "IssuedTokens", "LAST_SEEN_INTERVAL", "MAX_ACTIVE_USER_DEVICES",
    "OUTSTANDING_MAX_IDS", "REFRESH_RETRY_GRACE", "RETIRED_REFRESH_KEEP", "UNAUTHENTICATED_ENDPOINTS",
    "_APP_VERSION_MAX", "_DEVICE_CODING_ROLES", "_DEVICE_NAME_MAX", "_DUMMY_PASSWORD_HASH",
    "_KEEP_DATA_REASONS", "_PLAIN_HTTP_HOSTS", "_PLATFORMS", "_REUSE_REASONS", "_add_device",
    "_authenticate_device", "_bounded_int", "_check_credentials", "_check_demo_device_cap",
    "_clean_text", "_create_session", "_default_home_project", "_demo_code_hash", "_device_by_secret",
    "_device_fields", "_eligible_projects", "_end_existing_pair_sessions", "_get_device",
    "_insecure_device_url_allowed", "_issue", "_live_session", "_native_grant_projects",
    "_native_grants", "_new_secret", "_no_access_error", "_now", "_open_authorized_session",
    "_project_active", "_refresh_ttl", "_refuse", "_revoke", "_revoked_error", "_session_max_age",
    "_session_still_allowed", "_sign_in_failed", "_sign_in_user", "_station_state", "_uuid_list",
    "check_device_slot", "create_enrolment_code", "decommission_account_device",
    "device_for_client_uuid", "device_public_url_problem", "eligible_device_projects", "end_session",
    "enrol_demo_device", "enrol_device", "enrol_with_password", "enrolment_qr_payload",
    "has_device_access", "hash_token", "list_account_devices", "list_project_devices",
    "live_session_clauses", "log", "open_session", "parse_client_device_uuid", "record_app_version",
    "record_outstanding", "record_profile_deletion", "refresh_session", "request_bearer_token",
    "resolve_access_token", "revoke_device", "serialize_tokens", "set_device_project",
    "should_block_non_admin_after_cutoff",
}


class DeviceAuthModuleContractTests(BaseTestCase):
    """What importers and tests reach on the module object."""

    def test_every_name_is_still_exposed(self):
        missing = sorted(name for name in FACADE_NAMES if not hasattr(devices, name))
        self.assertEqual(missing, [])

    def test_unauthenticated_endpoints(self):
        self.assertEqual(devices.UNAUTHENTICATED_ENDPOINTS, frozenset({
            "api_v1.auth_api.enroll", "api_v1.auth_api.open_session", "api_v1.auth_api.refresh_session",
            "api_v1.auth_api.demo_enroll", "api_v1.auth_api.redeem_sign_in_qr",
            "api_v1.auth_api.password_enroll", "api_v1.auth_api.redeem_sign_in_code",
            "api_v1.auth_api.forgot_password",
        }))

    def test_logger_name_and_token_primitives(self):
        self.assertEqual(devices.log.name, "app.services.device_auth_service")
        self.assertEqual(devices.hash_token("abc"),
                         "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")
        self.assertEqual(len(devices._new_secret()), 43)
        self.assertEqual(devices.ACCESS_TTL.total_seconds(), 900)
        self.assertEqual((devices.MAX_ACTIVE_USER_DEVICES, devices.RETIRED_REFRESH_KEEP,
                          devices.OUTSTANDING_MAX_IDS, devices.ENROLMENT_MAX_USES), (3, 5, 1000, 200))

    def test_request_bearer_token(self):
        def req(path, header=None):
            return SimpleNamespace(path=path, headers={"Authorization": header} if header else {})

        self.assertEqual(devices.request_bearer_token(req("/api/v1/me", "Bearer  tok ")), "tok")
        self.assertEqual(devices.request_bearer_token(req("/api/v1/me", "bearer tok")), "tok")
        self.assertEqual(devices.request_bearer_token(req("/api/v1/me", "Bearer")), "")
        self.assertIsNone(devices.request_bearer_token(req("/api/v1/me", "Basic tok")))
        self.assertIsNone(devices.request_bearer_token(req("/api/v1/me")))
        self.assertIsNone(devices.request_bearer_token(req("/admin/api/x", "Bearer tok")))


class DeviceAuthRouteContractTests(BaseTestCase):
    PROJECT_ID = "DCH01"
    SITE_ID = "DC01"
    _make_project = _DEV["_make_project"]
    _make_site = _DEV["_make_site"]
    _grant = _DEV["_grant"]
    _code = _DEV["_code"]
    _enrol = _DEV["_enrol"]
    _sign_in = _DEV["_sign_in"]
    _session = _DEV["_session"]
    _bearer = _DEV["_bearer"]
    _refresh = _DEV["_refresh"]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._make_project(cls.PROJECT_ID, cls.SITE_ID, datetime.now(UTC))
        cls.interviewer = cls._get_or_make_user("contract.interviewer@test.local", PASSWORD)
        cls._grant(cls.interviewer, cls.PROJECT_ID)
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self._device_for = {}

    def _sign_in(self, device, email="contract.interviewer@test.local", password=PASSWORD, **extra):
        return _DEV["_sign_in"](self, device, email=email, password=password, **extra)

    def _session(self, device=None, **kwargs):
        kwargs.setdefault("email", "contract.interviewer@test.local")
        return _DEV["_session"](self, device, **kwargs)

    def _failed(self, device):
        """``device_session_failed`` audit rows for *device*: (user_id, reason)."""
        rows = db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "device_session_failed",
            AuthSecurityEvent.detail["device_id"].astext == device["device_id"],
        ).order_by(AuthSecurityEvent.occurred_at)).all()
        return [(row.user_id, row.detail["reason"]) for row in rows]

    def _revoke_device(self, device):
        row = db.session.get(AuthDevice, uuid.UUID(device["device_id"]))
        devices.revoke_device(row, actor=self.base_admin_user)
        db.session.commit()

    # -- enroll ---------------------------------------------------------------

    def test_enroll_reply_and_refusal(self):
        body = self._enrol()
        self.assertEqual(set(body), ENROL_KEYS)
        self.assertEqual(body["project"], {"project_id": self.PROJECT_ID, "name": f"Device {self.PROJECT_ID}"})
        refused = self.client.post(f"{API}/enroll", json={
            "code": "not-a-code", "device_name": "p", "platform": "android"})
        self.assertEqual((refused.status_code, refused.get_json()),
                         (404, {"error": "Enrolment code is invalid or expired.", "code": "enrolment_invalid"}))
        bad = self.client.post(f"{API}/enroll", json={"code": self._code(), "device_name": "p", "platform": "nokia"})
        self.assertEqual((bad.status_code, bad.get_json()), (400, {
            "error": "platform must be android, ios or desktop.", "code": "invalid_request"}))

    # -- password-enroll --------------------------------------------------------

    def test_password_enroll_reply_and_refusal(self):
        url = f"{API}/password-enroll"
        fields = {"device_name": "Manual", "platform": "android", "app_version": "1"}
        ok = self.client.post(url, json={"identifier": self.interviewer.email, "password": PASSWORD, **fields})
        self.assertEqual(ok.status_code, 201, ok.get_json())
        self.assertEqual(set(ok.get_json()), ENROL_KEYS | SESSION_KEYS | {"projects"})
        self.assertEqual(set(ok.get_json()["user"]), {"user_id", "name", "email"})
        wrong = self.client.post(url, json={"identifier": self.interviewer.email, "password": "nope", **fields})
        self.assertEqual((wrong.status_code, wrong.get_json()),
                         (401, {"error": "Invalid email or password.", "code": "invalid_credentials"}))
        failed = db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "device_password_enrol_failed")).all()
        self.assertEqual([(r.user_id, r.detail) for r in failed],
                         [(self.interviewer.user_id, {"reason": "invalid_credentials"})])

    # -- sign-in ----------------------------------------------------------------

    def test_sign_in_reply_and_refusals(self):
        device = self._enrol()
        ok = self._sign_in(device)
        self.assertEqual(ok.status_code, 201, ok.get_json())
        body = ok.get_json()
        self.assertEqual(set(body), SESSION_KEYS)
        self.assertEqual(body["user"], {"user_id": str(self.interviewer.user_id),
                                        "name": self.interviewer.name, "email": self.interviewer.email})
        self.assertIs(body["terms_required"], False)

        wrong = self._sign_in(device, password="nope")
        self.assertEqual((wrong.status_code, wrong.get_json()),
                         (401, {"error": "Invalid email or password.", "code": "invalid_credentials"}))
        bad_secret = self._sign_in({**device, "device_secret": "x"})
        self.assertEqual((bad_secret.status_code, bad_secret.get_json()),
                         (401, {"error": "Device is not recognised.", "code": "device_invalid"}))
        self.assertEqual(self._failed(device), [(self.interviewer.user_id, "invalid_credentials")])

    def test_sign_in_with_a_stale_bearer_still_signs_in(self):
        device = self._enrol()
        response = self.client.post(f"{API}/sessions", headers={"Authorization": "Bearer stale"}, json={
            "device_id": device["device_id"], "device_secret": device["device_secret"],
            "email": self.interviewer.email, "password": PASSWORD})
        self.assertEqual(response.status_code, 201, response.get_json())

    def test_device_limit_reply_and_audit(self):
        for _ in range(3):
            self._session()
        device = self._enrol()
        refused = self._sign_in(device)
        self.assertEqual(refused.status_code, 409)
        body = refused.get_json()
        self.assertEqual(set(body), {"error", "code", "devices"})
        self.assertEqual((body["code"], body["error"]), ("device_limit", devices.DEVICE_LIMIT_MESSAGE))
        self.assertEqual(len(body["devices"]), 3)
        for entry in body["devices"]:
            self.assertEqual(set(entry), {"device_id", "label", "last_seen_at", "unsent_count"})
        self.assertEqual(self._failed(device), [(self.interviewer.user_id, "device_limit")])

    # -- revoked device: which credential paths audit it ------------------------

    def test_revoked_device_is_audited_at_sign_in_only(self):
        device, tokens = self._session()
        self._revoke_device(device)
        self.assertEqual(self._failed(device), [])

        signed_in = self._sign_in(device)
        self.assertEqual((signed_in.status_code, signed_in.get_json()),
                         (403, {"error": "This device has been revoked.", "code": "device_revoked"}))
        self.assertEqual(self._failed(device), [(None, "device_revoked")])

        refreshed = self._refresh(tokens["refresh_token"], device)
        self.assertEqual((refreshed.status_code, refreshed.get_json()),
                         (401, {"error": "This session has been revoked.", "code": "session_revoked"}))
        deleted = self.client.post(f"{API}/profile-deletions", json={
            "device_id": device["device_id"], "device_secret": device["device_secret"],
            "user_id": str(self.interviewer.user_id), "unsent_count": 0, "loss_confirmed": False})
        self.assertEqual((deleted.status_code, deleted.get_json()), (201, {"recorded": True}))
        bearer = self.client.get("/api/v1/me/access", headers=self._bearer(tokens))
        self.assertEqual((bearer.status_code, bearer.get_json()), (401, UNAUTHORIZED))
        # Refresh, profile deletion and bearer requests add no sign-in audit row.
        self.assertEqual(self._failed(device), [(None, "device_revoked")])

    # -- refresh ----------------------------------------------------------------

    def test_refresh_reply_and_refusals(self):
        device, tokens = self._session()
        ok = self._refresh(tokens["refresh_token"])
        self.assertEqual(ok.status_code, 200, ok.get_json())
        self.assertEqual(set(ok.get_json()), SESSION_KEYS)

        missing = self._refresh("", device)
        self.assertEqual((missing.status_code, missing.get_json()),
                         (400, {"error": "refresh_token is required.", "code": "invalid_request"}))
        unknown = self._refresh("no-such-token", device)
        self.assertEqual((unknown.status_code, unknown.get_json()),
                         (401, {"error": "Refresh token is not valid.", "code": "refresh_invalid"}))
        other_device = self._refresh(ok.get_json()["refresh_token"], {**device, "device_secret": "x"})
        self.assertEqual((other_device.status_code, other_device.get_json()),
                         (401, {"error": "Device is not recognised.", "code": "device_invalid"}))
        # The rotated-away token, retried at once: a lost response.
        race = self._refresh(tokens["refresh_token"], device)
        self.assertEqual((race.status_code, race.get_json()),
                         (409, {"error": "Sign in again.", "code": "refresh_retry_race"}))
        again = self._refresh(ok.get_json()["refresh_token"], device)
        self.assertEqual((again.status_code, again.get_json()["code"]), (409, "refresh_retry_race"))
        revoked = db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "device_session_revoked",
            AuthSecurityEvent.detail["device_id"].astext == device["device_id"],
        )).all()
        self.assertEqual([r.detail["reason"] for r in revoked], ["refresh_retry_race"])

    # -- sign-out and bearer refusals --------------------------------------------

    def test_sign_out_and_bearer_refusals(self):
        device, tokens = self._session()
        self.assertEqual(self.client.get("/api/v1/me/access", headers=self._bearer(tokens)).status_code, 200)
        out = self.client.delete(f"{API}/sessions/current", headers=self._bearer(tokens))
        self.assertEqual((out.status_code, out.get_data()), (204, b""))
        after = self.client.get("/api/v1/me/access", headers=self._bearer(tokens))
        self.assertEqual((after.status_code, after.get_json()), (401, UNAUTHORIZED))
        refreshed = self._refresh(tokens["refresh_token"], device)
        self.assertEqual((refreshed.status_code, refreshed.get_json()["code"]), (401, "session_revoked"))
        for header in ("Bearer garbage", "Bearer "):
            response = self.client.get("/api/v1/me/access", headers={"Authorization": header})
            self.assertEqual((response.status_code, response.get_json()), (401, UNAUTHORIZED), header)
        cookie_less = self.client.delete(f"{API}/sessions/current")
        self.assertEqual(cookie_less.status_code, 401)


class SignInQrContractTests(AuthzFixtureMixin, BaseTestCase):
    """``POST /auth/sign-in-qr/redeem`` with the QR suite's patches."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.users["interviewer_p1"].email_verified = True
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        patcher = patch.object(devices, "has_device_access", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        stub = SimpleNamespace(interviewer_context=qr_tests._fake_context,
                               register_death_context=lambda *a, **k: [])
        p = patch.object(sign_in_qr_service, "web_intake_service", stub)
        p.start()
        self.addCleanup(p.stop)
        for token in db.session.scalars(sa.select(AuthSignInToken)):
            db.session.delete(token)
        db.session.commit()

    _issue = qr_tests.SignInQrTests.__dict__["_issue"]
    _token = qr_tests.SignInQrTests.__dict__["_token"]
    _redeem = qr_tests.SignInQrTests.__dict__["_redeem"]

    def test_redeem_reply_device_limit_and_refusal(self):
        user = self.users["interviewer_p1"]
        for index in range(3):
            device, _secret = devices._add_device("AZTA01", f"Existing {index}", "android", "1.2.3", None)
            devices._open_authorized_session(device, user)
        db.session.commit()
        token = self._token()
        limited = self._redeem(token)
        self.assertEqual(limited.status_code, 409)
        self.assertEqual(set(limited.get_json()), {"error", "code", "devices"})
        self.assertEqual(limited.get_json()["code"], "device_limit")
        replace = limited.get_json()["devices"][0]["device_id"]

        with patch.dict(self.app.config, qr_tests.MAIL):
            ok = self._redeem(token, replace_device_id=replace)
        self.assertEqual(ok.status_code, 201, ok.get_json())
        self.assertEqual(set(ok.get_json()), ENROL_KEYS | SESSION_KEYS | {"projects"})

        unknown = self._redeem("not-a-token")
        self.assertEqual((unknown.status_code, unknown.get_json()["code"]), (404, "sign_in_qr_invalid"))


class DemoEnrolContractTests(PublicDemoBase):
    URL = "/api/v1/auth/demo-enroll"

    def setUp(self):
        super().setUp()
        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self._account("demo.contract")

    def _enrol(self, **fields):
        return self.client.post(self.URL, json={
            "username": "demo.contract", "password": DEMO_PASSWORD, "device_name": "Phone",
            "platform": "android", "app_version": "0.3.0", **fields})

    def test_demo_enroll_reply_and_refusal(self):
        ok = self._enrol()
        self.assertEqual(ok.status_code, 201, ok.get_json())
        self.assertEqual(set(ok.get_json()), ENROL_KEYS)
        self.assertEqual(ok.get_json()["project"]["project_id"], DEMO_PROJECT)
        wrong = self._enrol(password="wrong-demo-password")
        self.assertEqual((wrong.status_code, wrong.get_json()),
                         (401, {"error": "Invalid username or password.", "code": "invalid_credentials"}))
        failed = db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "demo_device_enrol_failed")).all()
        self.assertEqual([r.detail for r in failed], [{"reason": "invalid_credentials"}])
        # Password enrolment is not served on the public-demo deployment.
        self.assertEqual(self.client.post(f"{API}/password-enroll", json={}).status_code, 404)
