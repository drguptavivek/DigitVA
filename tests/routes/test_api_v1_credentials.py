"""/api/v1/ accepts a session cookie or a device bearer token (bead digitva-uzhq).

A bearer request is authenticated by the token alone (a cookie beside it is
ignored, a bad token is a 401), is exempt from CSRF, never sets a cookie, and
meets the same terms and maintenance gates; a cookie request is unchanged.
Outside /api/v1/ a bearer opens nothing. Device enrolment helpers are reused
from tests/routes/test_device_api.py.
"""
import uuid
from datetime import UTC, datetime
from unittest import mock

from app import db, limiter
from app.models import AuthDevice, VaUsers
from app.services import device_auth_service as devices
from tests.base import BaseTestCase
from tests.routes import test_device_api as device_tests

PASSWORD = device_tests.PASSWORD
_FreshGClient = device_tests._FreshGClient
_DEV = device_tests.DeviceApiTests.__dict__
PROFILE = "/api/v1/profile/"
TIMEZONE = "/api/v1/profile/timezone"


class ApiV1CredentialTests(BaseTestCase):
    PROJECT_ID = device_tests.DeviceApiTests.PROJECT_ID
    SITE_ID = device_tests.DeviceApiTests.SITE_ID
    UNITS = f"/api/v1/organization/{PROJECT_ID}/units?role=interviewer"

    # Reuse the device suite's fixtures and enrolment helpers verbatim.
    _make_project = _DEV["_make_project"]
    _make_site = _DEV["_make_site"]
    _grant = _DEV["_grant"]
    _code = _DEV["_code"]
    _enrol = _DEV["_enrol"]
    _sign_in = _DEV["_sign_in"]
    _session = _DEV["_session"]
    _bearer = _DEV["_bearer"]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._make_project(cls.PROJECT_ID, cls.SITE_ID, datetime.now(UTC))
        cls.interviewer = cls._get_or_make_user("cred.interviewer@test.local", PASSWORD)
        cls.teammate = cls._get_or_make_user("cred.teammate@test.local", PASSWORD)
        cls._grant(cls.interviewer, cls.PROJECT_ID)
        cls._grant(cls.teammate, cls.PROJECT_ID)
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.client = _FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self._device_for = {}

    def _bearer_only_client(self):
        return _FreshGClient(self.app, self.app.response_class, use_cookies=True)

    def _tokens(self):
        return self._session(email="cred.interviewer@test.local")[1]

    # ── bearer reaches non-device routes ───────────────────────────────────

    def test_bearer_gets_the_cookie_users_body_on_a_non_device_route(self):
        tokens = self._tokens()
        self._login(str(self.interviewer.user_id))
        for path in (PROFILE, self.UNITS):
            cookie = self.client.get(path)
            self.assertEqual(cookie.status_code, 200, path)
            bearer = self._bearer_only_client().get(path, headers=self._bearer(tokens))
            self.assertEqual(bearer.status_code, 200, path)
            self.assertEqual(bearer.get_json(), cookie.get_json(), path)
        self.assertEqual(bearer.get_json()["units"] is not None, True)

    def test_bearer_beats_a_cookie_of_another_user(self):
        tokens = self._tokens()
        self._login(str(self.teammate.user_id))
        self.assertEqual(self.client.get(PROFILE).get_json()["email"], "cred.teammate@test.local")
        response = self.client.get(PROFILE, headers=self._bearer(tokens))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["email"], "cred.interviewer@test.local")

    def test_a_bad_bearer_is_refused_even_beside_a_valid_cookie(self):
        self._login(str(self.interviewer.user_id))
        self.assertEqual(self.client.get(PROFILE).status_code, 200)
        for header in ("Bearer not-a-token", "Bearer "):
            response = self.client.get(PROFILE, headers={"Authorization": header})
            self.assertEqual(response.status_code, 401, header)
            self.assertEqual(
                response.get_json(), {"error": "Authentication required.", "code": "unauthorized"})

    def test_unauthenticated_calls_keep_the_json_401(self):
        response = self.client.get(PROFILE)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.get_json(), {"error": "Authentication required."})

    # ── CSRF ───────────────────────────────────────────────────────────────

    def test_bearer_state_change_needs_no_csrf_token_but_a_cookie_one_does(self):
        tokens = self._tokens()
        # Present first: a cookie request with a token goes through.
        self._login(str(self.interviewer.user_id))
        ok = self.client.patch(TIMEZONE, json={"timezone": "UTC"}, headers=self._csrf_headers())
        self.assertEqual(ok.status_code, 200, ok.get_data(as_text=True))
        refused = self.client.patch(TIMEZONE, json={"timezone": "Asia/Kolkata"})
        self.assertEqual(refused.status_code, 400)

        response = self._bearer_only_client().patch(
            TIMEZONE, json={"timezone": "Asia/Kolkata"}, headers=self._bearer(tokens))
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        self.assertEqual(response.get_json()["timezone"], "Asia/Kolkata")

    def test_bearer_and_cookie_together_skip_csrf_only_for_the_bearer_user(self):
        tokens = self._tokens()
        self._login(str(self.teammate.user_id))
        response = self.client.patch(
            TIMEZONE, json={"timezone": "America/New_York"}, headers=self._bearer(tokens))
        self.assertEqual(response.status_code, 200)
        db.session.expire_all()
        self.assertEqual(db.session.get(VaUsers, self.interviewer.user_id).timezone, "America/New_York")
        self.assertNotEqual(db.session.get(VaUsers, self.teammate.user_id).timezone, "America/New_York")

    # ── revocation ─────────────────────────────────────────────────────────

    def test_revoked_device_and_revoked_session_are_401(self):
        device, tokens = self._session(email="cred.interviewer@test.local")
        self.assertEqual(self.client.get(PROFILE, headers=self._bearer(tokens)).status_code, 200)
        devices.revoke_device(db.session.get(AuthDevice, uuid.UUID(device["device_id"])), actor=self.base_admin_user)
        db.session.commit()
        self.assertEqual(self.client.get(PROFILE, headers=self._bearer(tokens)).status_code, 401)

        _device, tokens = self._session(email="cred.interviewer@test.local")
        self.assertEqual(self.client.get(PROFILE, headers=self._bearer(tokens)).status_code, 200)
        self.assertEqual(
            self.client.delete("/api/v1/device/sessions/current", headers=self._bearer(tokens)).status_code, 204)
        self.assertEqual(self.client.get(PROFILE, headers=self._bearer(tokens)).status_code, 401)

    # ── no cookie ──────────────────────────────────────────────────────────

    def test_bearer_responses_set_no_cookie(self):
        tokens = self._tokens()
        self._login(str(self.interviewer.user_id))  # a cookie in the jar must not be refreshed either
        calls = [
            self.client.get(PROFILE, headers=self._bearer(tokens)),
            self.client.patch(TIMEZONE, json={"timezone": "UTC"}, headers=self._bearer(tokens)),
            self.client.get("/api/v1/client/bootstrap", headers=self._bearer(tokens)),  # writes the session
        ]
        for response in calls:
            self.assertIn(response.status_code, (200, 401, 403))
            self.assertNotIn("Set-Cookie", response.headers)
        self.assertEqual(calls[0].status_code, 200)
        self.assertEqual(calls[1].status_code, 200)

    # ── scope ──────────────────────────────────────────────────────────────

    def test_bearer_opens_nothing_outside_api_v1(self):
        tokens = self._tokens()
        self.assertEqual(self.client.get(PROFILE, headers=self._bearer(tokens)).status_code, 200)
        headers = self._bearer(tokens)
        self.assertEqual(
            self.client.get(f"/admin/api/projects/{self.PROJECT_ID}/devices", headers=headers).status_code, 401)
        self.assertEqual(self.client.get("/intake/api/bootstrap", headers=headers).status_code, 401)
        self.assertEqual(self.client.get("/intake/", headers=headers).status_code, 302)
        self.assertEqual(self.client.get("/profile/", headers=headers).status_code, 302)

    # ── gates ──────────────────────────────────────────────────────────────

    def test_terms_gate_holds_for_bearer_on_a_non_device_route(self):
        tokens = self._tokens()
        self.assertEqual(self.client.get(PROFILE, headers=self._bearer(tokens)).status_code, 200)
        db.session.get(VaUsers, self.interviewer.user_id).pw_reset_t_and_c = False
        db.session.commit()
        response = self.client.get(PROFILE, headers=self._bearer(tokens))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json(), {
            "error": "Accept the terms of use to continue.", "code": "terms_required"})
        # The exempt calls still work, then the gate opens.
        accepted = self.client.post("/api/v1/profile/terms", json={"accept_terms": True}, headers=self._bearer(tokens))
        self.assertEqual(accepted.status_code, 200, accepted.get_data(as_text=True))
        self.assertEqual(self.client.get(PROFILE, headers=self._bearer(tokens)).status_code, 200)

    def test_maintenance_cutoff_holds_for_bearer_on_a_non_device_route(self):
        tokens = self._tokens()
        self.assertEqual(self.client.get(PROFILE, headers=self._bearer(tokens)).status_code, 200)
        with mock.patch(
            "app.services.site_maintenance_service.should_block_non_admin_after_cutoff", return_value=True
        ):
            response = self.client.get(PROFILE, headers=self._bearer(tokens))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.get_json()["code"], "maintenance")

    def test_factor_setup_holds_a_privileged_bearer_with_no_factor(self):
        tokens = self._tokens()
        self.assertEqual(self.client.get(PROFILE, headers=self._bearer(tokens)).status_code, 200)
        with mock.patch.object(VaUsers, "is_data_manager", return_value=True), \
                mock.patch("app.services.totp_service.enforcement_active", return_value=True), \
                mock.patch("app.services.totp_service.has_any_factor", return_value=False):
            response = self.client.get(PROFILE, headers=self._bearer(tokens))
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.get_json()["code"], "factor_setup_required")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertNotIn("Set-Cookie", response.headers)
            # Signing out stays reachable.
            self.assertNotEqual(
                self.client.delete("/api/v1/device/sessions/current", headers=self._bearer(tokens)).status_code, 403)
        # A factor-holder, or enforcement off, is not held.
        with mock.patch.object(VaUsers, "is_data_manager", return_value=True), \
                mock.patch("app.services.totp_service.enforcement_active", return_value=False):
            fresh = self._tokens()
            self.assertEqual(self.client.get(PROFILE, headers=self._bearer(fresh)).status_code, 200)

    def test_account_security_routes_refuse_a_bearer(self):
        tokens = self._tokens()
        self.assertEqual(self.client.get(PROFILE, headers=self._bearer(tokens)).status_code, 200)
        for method, path in (
            ("post", "/api/v1/profile/reauth"),
            ("post", "/api/v1/profile/password/generate"),
            ("get", "/api/v1/profile/passkeys"),
            ("post", "/api/v1/profile/passkeys/options"),
            ("get", "/api/v1/profile/totp"),
            ("post", "/api/v1/profile/totp/enroll"),
            ("post", "/api/v1/profile/recovery-codes/regenerate"),
        ):
            response = getattr(self.client, method)(path, json={}, headers=self._bearer(tokens))
            self.assertEqual(response.status_code, 403, path)
            self.assertEqual(response.get_json()["code"], "cookie_session_required", path)
        # The cookie user still reaches them (reauth answers, not 403).
        self._login(str(self.interviewer.user_id))
        self.assertNotEqual(self.client.get("/api/v1/profile/totp").status_code, 403)
