"""Characterization of the four enrolment replies (bead digitva-r8nh.17, slice 2).

Written on the unchanged routes before ``enroll``, ``password-enroll``,
``sign-in-qr/redeem`` and ``demo-enroll`` shared one reply builder, and
before the two 401-only limiter predicates were merged. Old APKs read these
bodies, so this pins the wire: status, every value, raw key order, header
names, the audit rows each request writes, the ``signing_public_key``
variants (a bad key consumes nothing), and that only a 401 spends the
wrong-password budget of ``/password-enroll``. Policy:
docs/policy/mobile-sign-in.md, docs/policy/public-demo.md,
docs/current-state/api-v1.md. Borrows helpers of the existing suites
without inheriting their tests.
"""

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa

from app import db, limiter
from app.models import AuthDevice, AuthDeviceEnrolmentCode, AuthSecurityEvent, AuthSignInToken
from app.services import device_auth_service as devices
from app.services import device_signing_service as signing
from app.services import sign_in_qr_service
from tests.authz.fixture import AuthzFixtureMixin
from tests.base import BaseTestCase
from tests.routes import test_device_api as device_tests
from tests.routes import test_device_signing_keys as key_tests
from tests.routes import test_sign_in_qr as qr_tests
from tests.test_public_demo import PASSWORD as DEMO_PASSWORD
from tests.test_public_demo import PROJECT as DEMO_PROJECT
from tests.test_public_demo import PublicDemoBase

API = device_tests.API
PASSWORD = device_tests.PASSWORD
_DEV = device_tests.DeviceApiTests.__dict__
_QR = qr_tests.SignInQrTests.__dict__

#: Header names of a 201 enrolment reply and of an error reply (the app's
#: security and request-id headers included; no Cache-Control, no cookie).
REPLY_HEADERS = [
    "Content-Length", "Content-Security-Policy", "Content-Type", "Date", "Permissions-Policy",
    "Referrer-Policy", "Vary", "X-Content-Type-Options", "X-Frame-Options", "X-Request-ID",
    "X-XSS-Protection",
]
BAD_KEY = {
    "error": "signing_public_key must be a base64url Ed25519 public key (32 bytes).",
    "code": "invalid_request", "fields": ["signing_public_key"],
}
BAD_UUID = {"error": "client_device_uuid must be a UUID.", "code": "invalid_request"}
WRONG_PASSWORD = {"error": "Invalid email or password.", "code": "invalid_credentials"}


#: Timing headers ride on any response once g carries a request start time,
#: which a timed request earlier in the same app context can leave behind under
#: xdist; they are diagnostics, not part of the enrolment contract.
_TIMING_HEADERS = {"Server-Timing", "X-Response-Time"}


def _header_names(response) -> list:
    return sorted(k for k in response.headers.keys() if k not in _TIMING_HEADERS)


def _keys(response) -> list:
    """Top-level keys in the order they are on the wire."""
    return json.loads(response.get_data(), object_pairs_hook=lambda pairs: [k for k, _v in pairs])


class _WireAsserts:
    """Shared checks; a mixin so no test is collected twice."""

    def _event_ids(self):
        return set(db.session.scalars(sa.select(AuthSecurityEvent.id)))

    def _events_since(self, before, device_id=None):
        """(event_type, user_id, actor_user_id, detail) of rows added since
        *before*, oldest first, with *device_id* shown as ``<device>``."""
        rows = db.session.scalars(sa.select(AuthSecurityEvent).order_by(AuthSecurityEvent.occurred_at)).all()
        out = []
        for row in rows:
            if row.id in before:
                continue
            detail = {k: ("<device>" if v == device_id else v) for k, v in (row.detail or {}).items()}
            out.append((row.event_type, row.user_id, row.actor_user_id, detail))
        return sorted(out, key=lambda e: e[0])

    def _assert_enrolment_wire(self, response, keys, project, started):
        """A 201 enrolment reply: exact key order, headers, device row, secret, time."""
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(_keys(response), keys)
        self.assertEqual(response.headers["Content-Type"], "application/json")
        self.assertEqual(_header_names(response), REPLY_HEADERS)
        body = response.get_json()
        db.session.expire_all()
        row = db.session.get(AuthDevice, uuid.UUID(body["device_id"]))
        self.assertIsNotNone(row)
        self.assertEqual(body["device_id"], str(row.device_id))
        self.assertEqual(len(body["device_secret"]), 43)
        self.assertEqual(devices.hash_token(body["device_secret"]), row.secret_hash)
        self.assertEqual(body["project"], project)
        self.assertEqual(row.project_id, project["project_id"])
        self.assertTrue(body["server_time"].endswith("+00:00"), body["server_time"])
        server_time = datetime.fromisoformat(body["server_time"])
        self.assertTrue(started <= server_time <= datetime.now(UTC), body["server_time"])
        return body, row

    def _assert_error(self, response, status, body):
        self.assertEqual((response.status_code, response.get_json()), (status, body))
        self.assertEqual(_header_names(response), REPLY_HEADERS)
        self.assertEqual(response.headers["Content-Type"], "application/json")

    def _device_count(self):
        return db.session.scalar(sa.select(sa.func.count()).select_from(AuthDevice))


class EnrolAndPasswordEnrolReplyTests(_WireAsserts, BaseTestCase):
    PROJECT_ID = "ERC01"
    SITE_ID = "EC01"
    PROJECT = {"project_id": "ERC01", "name": "Device ERC01"}
    EMAIL = "reply.contract@test.local"
    _make_project = _DEV["_make_project"]
    _make_site = _DEV["_make_site"]
    _grant = _DEV["_grant"]
    _code = _DEV["_code"]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._make_project(cls.PROJECT_ID, cls.SITE_ID, datetime.now(UTC))
        cls.interviewer = cls._get_or_make_user(cls.EMAIL, PASSWORD)
        cls._grant(cls.interviewer, cls.PROJECT_ID)
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)

    def _post_enroll(self, code, **extra):
        return self.client.post(f"{API}/enroll", json={
            "code": code, "device_name": "Reply phone", "platform": "android", "app_version": "0.1.0", **extra})

    def _uses(self, code):
        return db.session.scalar(sa.select(AuthDeviceEnrolmentCode.use_count).where(
            AuthDeviceEnrolmentCode.code_hash == devices.hash_token(code)))

    # -- /enroll --------------------------------------------------------------

    def test_enroll_reply_without_signing_key(self):
        code = self._code()
        before, started = self._event_ids(), datetime.now(UTC)
        response = self._post_enroll(code, client_device_uuid=str(uuid.UUID(int=7)))
        body, row = self._assert_enrolment_wire(
            response, ["device_id", "device_secret", "project", "server_time"], self.PROJECT, started)
        self.assertEqual((row.name, row.platform, row.app_version, row.client_device_uuid, row.signing_key_id),
                         ("Reply phone", "android", "0.1.0", uuid.UUID(int=7), None))
        self.assertEqual(self._events_since(before, body["device_id"]), [
            ("device_enrolled", None, None, {"device_id": "<device>", "project_id": self.PROJECT_ID}),
        ])
        self.assertEqual(self._uses(code), 1)

    def test_enroll_reply_with_signing_key(self):
        _private, raw = key_tests._keypair()
        code = self._code()
        before, started = self._event_ids(), datetime.now(UTC)
        response = self._post_enroll(code, signing_public_key=key_tests._b64u(raw))
        body, row = self._assert_enrolment_wire(
            response, ["device_id", "device_secret", "project", "server_time", "signing_key_id"],
            self.PROJECT, started)
        key_id = signing.compute_signing_key_id(raw)
        self.assertEqual((body["signing_key_id"], row.signing_key_id, row.signing_public_key), (key_id, key_id, raw))
        self.assertEqual(self._events_since(before, body["device_id"]), [
            ("device_enrolled", None, None, {"device_id": "<device>", "project_id": self.PROJECT_ID}),
            ("device_signing_key_set", None, None,
             {"device_id": "<device>", "signing_key_id": key_id, "via": "enroll"}),
        ])

    def test_enroll_bad_key_or_uuid_consumes_nothing(self):
        code = self._code(max_uses=1)
        devices_before, before = self._device_count(), self._event_ids()
        self._assert_error(self._post_enroll(code, signing_public_key="not-a-key"), 400, BAD_KEY)
        self._assert_error(self._post_enroll(code, client_device_uuid="nope"), 400, BAD_UUID)
        self._assert_error(self._post_enroll(code, client_device_uuid=7), 400, BAD_UUID)
        self.assertEqual((self._uses(code), self._device_count(), self._events_since(before)),
                         (0, devices_before, []))
        # The single-use code still enrols.
        self.assertEqual(self._post_enroll(code).status_code, 201)
        self._assert_error(self._post_enroll(code), 404, {
            "error": "Enrolment code is invalid or expired.", "code": "enrolment_invalid"})

    def test_enroll_refusals(self):
        self._assert_error(self._post_enroll(None), 404, {
            "error": "Enrolment code is invalid or expired.", "code": "enrolment_invalid"})
        self._assert_error(self.client.post(f"{API}/enroll", json={
            "code": self._code(), "device_name": "p", "platform": "nokia"}), 400, {
            "error": "platform must be android, ios or desktop.", "code": "invalid_request"})

    # -- /password-enroll -------------------------------------------------------

    def _post_password(self, identifier=None, password=PASSWORD, ip="127.0.0.1", **extra):
        return self.client.post(f"{API}/password-enroll", json={
            "identifier": identifier or self.EMAIL, "password": password,
            "device_name": "Manual", "platform": "android", "app_version": "1", **extra,
        }, environ_overrides={"REMOTE_ADDR": ip})

    def test_password_enroll_reply(self):
        before, started = self._event_ids(), datetime.now(UTC)
        response = self._post_password(client_device_uuid=str(uuid.UUID(int=9)))
        body, row = self._assert_enrolment_wire(response, [
            "access", "access_expires_at", "access_token", "device_id", "device_secret", "project",
            "projects", "refresh_expires_at", "refresh_token", "server_time", "terms_required", "user",
        ], self.PROJECT, started)
        self.assertEqual(row.client_device_uuid, uuid.UUID(int=9))
        self.assertEqual(body["projects"], [self.PROJECT])
        self.assertEqual(body["user"], {"user_id": str(self.interviewer.user_id),
                                        "name": self.interviewer.name, "email": self.EMAIL})
        self.assertIs(body["terms_required"], False)
        uid = self.interviewer.user_id
        self.assertEqual(self._events_since(before, body["device_id"]), [
            ("device_enrolled", None, None, {"device_id": "<device>", "project_id": self.PROJECT_ID}),
            ("device_session_opened", uid, None, {"device_id": "<device>"}),
        ])

    def test_password_enroll_refusals(self):
        devices_before, before = self._device_count(), self._event_ids()
        self._assert_error(self._post_password(password="nope"), 401, WRONG_PASSWORD)
        self._assert_error(self._post_password(identifier="9" * 17), 400, {
            "error": "A mobile number has at most 16 characters.", "code": "invalid_request",
            "fields": ["identifier"]})
        self._assert_error(self._post_password(client_device_uuid="nope"), 400, BAD_UUID)
        self.assertEqual(self._device_count(), devices_before)
        self.assertEqual(self._events_since(before), [
            ("device_password_enrol_failed", self.interviewer.user_id, None, {"reason": "invalid_credentials"}),
        ])
        with patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=True):
            self.assertEqual(self._post_password().status_code, 404)

    def test_only_refused_passwords_spend_the_per_address_budget(self):
        """``60 per 10 minutes`` per address counts 401s only: a 400 and a
        201 in between spend nothing, and the 61st 401 is a 429."""
        ip = "10.81.0.1"
        statuses = [self._post_password(identifier=f"nobody{i}@test.local", password="x", ip=ip).status_code
                    for i in range(59)]
        statuses.append(self._post_password(identifier="9" * 17, ip=ip).status_code)
        statuses.append(self._post_password(ip=ip).status_code)
        statuses.append(self._post_password(identifier="nobody59@test.local", password="x", ip=ip).status_code)
        statuses.append(self._post_password(identifier="nobody60@test.local", password="x", ip=ip).status_code)
        self.assertEqual(statuses, [401] * 59 + [400, 201, 401, 429])
        # Another address is unaffected.
        self.assertEqual(self._post_password(identifier="nobody@test.local", password="x", ip="10.81.0.2")
                         .status_code, 401)


    def test_wrong_sign_in_code_reply(self):
        """The 401 that ``/sign-in-code/redeem``'s failure-only limits count."""
        response = self.client.post(f"{API}/sign-in-code/redeem", json={
            "identifier": "+919800000001", "code": "AAAA-AAAA", "accept_terms": True})
        self._assert_error(response, 401, {
            "error": "That email or mobile number and code do not match.", "code": "invalid_code"})


class SignInQrReplyTests(_WireAsserts, AuthzFixtureMixin, BaseTestCase):
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

    _issue = _QR["_issue"]
    _token = _QR["_token"]
    _redeem = _QR["_redeem"]

    def _expected_project(self, project_id):
        from app.models import VaProjectMaster
        return {"project_id": project_id, "name": db.session.get(VaProjectMaster, project_id).project_name}

    def test_redeem_reply_with_signing_key_and_bad_key_consumes_nothing(self):
        user = self.users["interviewer_p1"]
        token = self._token()
        devices_before, before = self._device_count(), self._event_ids()
        self._assert_error(self._redeem(token, signing_public_key="not-a-key"), 400, BAD_KEY)
        self._assert_error(self._redeem(token, client_device_uuid="nope"), 400, BAD_UUID)
        self.assertEqual((self._device_count(), self._events_since(before)), (devices_before, []))

        _private, raw = key_tests._keypair()
        started = datetime.now(UTC)
        with patch.dict(self.app.config, qr_tests.MAIL):
            response = self._redeem(token, signing_public_key=key_tests._b64u(raw),
                                    client_device_uuid=str(uuid.UUID(int=11)))
        db.session.expire_all()
        project_id = db.session.get(AuthDevice, uuid.UUID(response.get_json()["device_id"])).project_id
        project = self._expected_project(project_id)
        body, row = self._assert_enrolment_wire(response, [
            "access", "access_expires_at", "access_token", "device_id", "device_secret", "project",
            "projects", "refresh_expires_at", "refresh_token", "server_time", "signing_key_id",
            "terms_required", "user",
        ], project, started)
        key_id = signing.compute_signing_key_id(raw)
        self.assertEqual((body["signing_key_id"], row.signing_key_id, row.client_device_uuid),
                         (key_id, key_id, uuid.UUID(int=11)))
        # The QR suite's stubbed intake context leaves no eligible home list.
        self.assertEqual(body["projects"], devices.eligible_device_projects(user))
        self.assertEqual(body["projects"], [])
        self.assertEqual(body["user"]["user_id"], str(user.user_id))
        self.assertEqual(self._events_since(before, body["device_id"]), [
            ("device_enrolled", None, None, {"device_id": "<device>", "project_id": project_id}),
            ("device_session_opened", user.user_id, None, {"device_id": "<device>"}),
            ("device_signing_key_set", None, None,
             {"device_id": "<device>", "signing_key_id": key_id, "via": "enroll"}),
            ("sign_in_qr_redeemed", user.user_id, None, {"device_id": "<device>"}),
        ])
        self._assert_error(self._redeem(token), 404, {
            "error": "Sign-in QR is invalid or expired.", "code": "sign_in_qr_invalid"})

    def test_redeem_reply_without_signing_key(self):
        token = self._token()
        started = datetime.now(UTC)
        with patch.dict(self.app.config, qr_tests.MAIL):
            response = self._redeem(token)
        db.session.expire_all()
        project_id = db.session.get(AuthDevice, uuid.UUID(response.get_json()["device_id"])).project_id
        body, row = self._assert_enrolment_wire(response, [
            "access", "access_expires_at", "access_token", "device_id", "device_secret", "project",
            "projects", "refresh_expires_at", "refresh_token", "server_time", "terms_required", "user",
        ], self._expected_project(project_id), started)
        self.assertIsNone(row.signing_key_id)


class DemoEnrolReplyTests(_WireAsserts, PublicDemoBase):
    URL = "/api/v1/auth/demo-enroll"

    def setUp(self):
        super().setUp()
        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self.account = self._account("demo.reply")

    def _enrol(self, **fields):
        return self.client.post(self.URL, json={
            "username": "demo.reply", "password": DEMO_PASSWORD, "device_name": "Phone",
            "platform": "android", "app_version": "0.3.0", **fields})

    def test_demo_enroll_reply(self):
        from app.models import VaProjectMaster
        project = {"project_id": DEMO_PROJECT, "name": db.session.get(VaProjectMaster, DEMO_PROJECT).project_name}
        before, started = self._event_ids(), datetime.now(UTC)
        response = self._enrol(client_device_uuid=str(uuid.UUID(int=13)))
        body, row = self._assert_enrolment_wire(
            response, ["device_id", "device_secret", "project", "server_time"], project, started)
        self.assertEqual(row.client_device_uuid, uuid.UUID(int=13))
        self.assertEqual(self._events_since(before, body["device_id"]), [
            ("device_enrolled", None, None, {"device_id": "<device>", "project_id": DEMO_PROJECT}),
        ])

    def test_demo_enroll_refusals(self):
        devices_before, before = self._device_count(), self._event_ids()
        self._assert_error(self._enrol(password="wrong-demo-password"), 401, {
            "error": "Invalid username or password.", "code": "invalid_credentials"})
        self._assert_error(self._enrol(client_device_uuid="nope"), 400, BAD_UUID)
        self.assertEqual(self._device_count(), devices_before)
        self.assertEqual(self._events_since(before), [
            ("demo_device_enrol_failed", self.account.user_id, None, {"reason": "invalid_credentials"}),
        ])
        with patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=False):
            self.assertEqual(self._enrol().status_code, 404)
