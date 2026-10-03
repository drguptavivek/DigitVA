"""Device API for the Android collection app (Path B, bead digitva-kmk.1).

Contract: .tasks/2026-09-30-android-collection-app.md ("API contract").
Covers enrolment, sign-in (password, second factor, grant, revoked device,
rate limit), refresh rotation and reuse, grant withdrawal, bearer scoping
(never outside /api/v1/device, never a cookie inside it), bootstrap scope,
idempotent upload, scope refusals, superseded copies, the outstanding-work
report, the admin endpoints (admin only, CSRF) and that no credential
reaches the logs. Hardening (bead digitva-kmk.6): body caps and answer
bounds, the absolute session cap, device-bound refresh, retired-token reuse
(``refresh_reused``, never ``session_revoked``) and the lost-response grace
window, the second-factor lockout and refusal audit, device units and
translations, outstanding draft ids, and the enrolment QR URL check.
Offline cases (bead digitva-kmk.4): the case download (scope, states,
masking, prefill, paging), idempotent offline registration, attempts and
visits, registration before upload, and outstanding registration ids.
"""
import hashlib
import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest import mock

import pyotp
import sqlalchemy as sa
from flask import g
from flask.testing import FlaskClient

from app import db, limiter
from app.models import (
    AuthDevice,
    AuthDeviceEnrolmentCode,
    AuthDeviceSession,
    AuthSecurityEvent,
    AuthTotp,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaUserAccessGrants,
    VaWebIntakeDraft,
)
from app.models.va_submission_payload_versions import VaSubmissionPayloadVersion
from app.services import device_auth_service as devices
from app.services import totp_service
from app.services import web_intake_service as intake_svc
from app.services.runtime_form_sync_service import _ensure_legacy_project_site_rows
from tests.base import BaseTestCase

PASSWORD = "DeviceApi123!"
API = "/api/v1/device"


def _complete_answers():
    return {
        "Id10013": "yes",
        "Id10017": "Bina",
        "Id10018": "Sahu",
        "Id10019": "female",
        "Id10023": (date.today() - timedelta(days=5)).isoformat(),
        "finalAgeInYears": "71",
        "narr_language": "english",
    }


class _FreshGClient(FlaskClient):
    """The suite keeps one app context for the whole session, so ``g`` (and
    Flask-Login's cached user on it) outlives a request. Production pushes a
    fresh ``g`` per request; so does this client, or a bearer request would
    reuse the previous request's user and ``g.device_session``."""

    def open(self, *args, **kwargs):
        g.pop("_login_user", None)
        g.pop("device_session", None)
        return super().open(*args, **kwargs)


class DeviceApiTests(BaseTestCase):
    PROJECT_ID = "DEV01"
    SITE_ID = "DV01"
    OTHER_PROJECT_ID = "DEV02"
    OTHER_SITE_ID = "DV02"

    @classmethod
    def _make_project(cls, project_id, site_id, now):
        db.session.add(VaProjectMaster(
            project_id=project_id, project_code=project_id, project_name=f"Device {project_id}",
            project_nickname=project_id, project_status=VaStatuses.active,
            project_registered_at=now, project_updated_at=now, web_intake_mode="both",
        ))
        db.session.add(VaSiteMaster(
            site_id=site_id, site_name=f"Site {site_id}", site_abbr=site_id,
            site_status=VaStatuses.active, site_registered_at=now, site_updated_at=now,
        ))
        db.session.flush()
        db.session.add(VaProjectSites(
            project_id=project_id, site_id=site_id, project_site_status=VaStatuses.active,
            project_site_registered_at=now, project_site_updated_at=now,
        ))
        db.session.flush()
        _ensure_legacy_project_site_rows(project_id, site_id)
        db.session.add(VaForms(
            form_id=f"{project_id}{site_id}01"[:12], project_id=project_id, site_id=site_id,
            odk_form_id=f"ODK_{project_id}", odk_project_id="7", form_type="WHO VA 2022",
            form_source="odk", form_status=VaStatuses.active, form_registered_at=now,
            form_updated_at=now,
        ))
        db.session.flush()

    @classmethod
    def _grant(cls, user, project_id):
        grant = VaUserAccessGrants(
            user_id=user.user_id, role=VaAccessRoles.interviewer,
            scope_type=VaAccessScopeTypes.project, project_id=project_id,
            notes="device api test grant", grant_status=VaStatuses.active,
        )
        db.session.add(grant)
        db.session.flush()
        return grant

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(UTC)
        cls._make_project(cls.PROJECT_ID, cls.SITE_ID, now)
        cls._make_project(cls.OTHER_PROJECT_ID, cls.OTHER_SITE_ID, now)
        cls.interviewer = cls._get_or_make_user("device.interviewer@test.local", PASSWORD)
        cls.teammate = cls._get_or_make_user("device.teammate@test.local", PASSWORD)
        cls.outsider = cls._get_or_make_user("device.outsider@test.local", PASSWORD)
        cls.grant = cls._grant(cls.interviewer, cls.PROJECT_ID)
        cls._grant(cls.interviewer, cls.OTHER_PROJECT_ID)
        cls._grant(cls.teammate, cls.PROJECT_ID)
        db.session.commit()

    def setUp(self):
        super().setUp()
        limiter.reset()
        self.client = _FreshGClient(self.app, self.app.response_class, use_cookies=True)
        # refresh token -> the device it was issued to, so _refresh can
        # present the device credentials a refresh now requires.
        self._device_for = {}

    # ── helpers ────────────────────────────────────────────────────────────

    def _code(self, project_id=None, **kwargs):
        _row, code = devices.create_enrolment_code(
            project_id or self.PROJECT_ID, actor=self.base_admin_user, **kwargs
        )
        db.session.commit()
        return code

    def _enrol(self, code=None):
        response = self.client.post(f"{API}/enroll", json={
            "code": code or self._code(), "device_name": "Field phone 1",
            "platform": "android", "app_version": "0.1.0",
        })
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def _sign_in(self, device, email="device.interviewer@test.local", password=PASSWORD, **extra):
        return self.client.post(f"{API}/sessions", json={
            "device_id": device["device_id"], "device_secret": device["device_secret"],
            "email": email, "password": password, **extra,
        })

    def _session(self, device=None, **kwargs):
        device = device or self._enrol()
        response = self._sign_in(device, **kwargs)
        self.assertEqual(response.status_code, 201, response.get_json())
        tokens = response.get_json()
        self._device_for[tokens["refresh_token"]] = device
        return device, tokens

    @staticmethod
    def _bearer(tokens):
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    def _refresh(self, refresh_token, device=None, **extra):
        device = device or self._device_for.get(refresh_token) or {}
        response = self.client.post(f"{API}/sessions/refresh", json={
            "refresh_token": refresh_token, "device_id": device.get("device_id"),
            "device_secret": device.get("device_secret"), **extra,
        })
        if response.status_code == 200:
            self._device_for[response.get_json()["refresh_token"]] = device
        return response

    def _upload(self, tokens, client_draft_id=None, **body):
        payload = {
            "client_draft_id": str(client_draft_id or uuid.uuid4()),
            "site_id": self.SITE_ID,
            "draft": {"schemaVersion": 1, "formVersion": "2022", "id": "local-1",
                      "instrumentId": "va_who_2022", "instrumentVersion": "2023072701",
                      "currentSection": "consented", "createdAt": "2026-09-30T08:00:00+00:00",
                      "updatedAt": "2026-09-30T09:00:00+00:00", "data": _complete_answers()},
            "completion": {"valid": True, "issues": []},
        }
        payload.update(body)
        return self.client.post(f"{API}/submissions", json=payload, headers=self._bearer(tokens))

    # ── enrolment ──────────────────────────────────────────────────────────

    def test_enrol_returns_a_device_secret_stored_only_hashed(self):
        body = self._enrol()
        self.assertEqual(body["project"], {"project_id": self.PROJECT_ID, "name": f"Device {self.PROJECT_ID}"})
        self.assertTrue(body["server_time"])
        device = db.session.get(AuthDevice, uuid.UUID(body["device_id"]))
        self.assertEqual(device.secret_hash, hashlib.sha256(body["device_secret"].encode()).hexdigest())
        self.assertNotEqual(device.secret_hash, body["device_secret"])

    def test_enrol_refuses_unknown_expired_used_and_revoked_codes_alike(self):
        def enrol(code):
            return self.client.post(f"{API}/enroll", json={
                "code": code, "device_name": "p", "platform": "android", "app_version": "1"})

        self.assertEqual(enrol("not-a-real-code").get_json()["code"], "enrolment_invalid")

        used = self._code()
        self._enrol(used)
        response = enrol(used)
        self.assertEqual((response.status_code, response.get_json()["code"]), (404, "enrolment_invalid"))

        expired = self._code()
        db.session.execute(sa.update(AuthDeviceEnrolmentCode).where(
            AuthDeviceEnrolmentCode.code_hash == devices.hash_token(expired)
        ).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.session.commit()
        self.assertEqual(enrol(expired).status_code, 404)

        revoked = self._code()
        db.session.execute(sa.update(AuthDeviceEnrolmentCode).where(
            AuthDeviceEnrolmentCode.code_hash == devices.hash_token(revoked)
        ).values(revoked_at=datetime.now(UTC)))
        db.session.commit()
        self.assertEqual(enrol(revoked).status_code, 404)

    def test_enrol_code_with_max_uses_enrols_that_many_devices(self):
        code = self._code(max_uses=2)
        first, second = self._enrol(code), self._enrol(code)
        self.assertNotEqual(first["device_id"], second["device_id"])
        response = self.client.post(f"{API}/enroll", json={
            "code": code, "device_name": "p3", "platform": "android", "app_version": "1"})
        self.assertEqual(response.status_code, 404)

    # ── sessions ───────────────────────────────────────────────────────────

    def test_sign_in_returns_the_contract_token_shape(self):
        _device, tokens = self._session()
        self.assertEqual(
            set(tokens), {"access_token", "access_expires_at", "refresh_token", "refresh_expires_at", "user"}
        )
        self.assertEqual(tokens["user"]["user_id"], str(self.interviewer.user_id))
        self.assertEqual(tokens["user"]["email"], "device.interviewer@test.local")
        row = db.session.scalar(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.user_id == self.interviewer.user_id))
        self.assertEqual(row.access_hash, devices.hash_token(tokens["access_token"]))
        self.assertEqual(row.refresh_hash, devices.hash_token(tokens["refresh_token"]))

    def test_sign_in_refuses_a_wrong_device_secret(self):
        device = self._enrol()
        response = self._sign_in({**device, "device_secret": "wrong"})
        self.assertEqual((response.status_code, response.get_json()["code"]), (401, "device_invalid"))

    def test_sign_in_refuses_a_wrong_password_and_audits_it(self):
        device = self._enrol()
        response = self._sign_in(device, password="wrong-password")
        self.assertEqual((response.status_code, response.get_json()["code"]), (401, "invalid_credentials"))
        event = db.session.scalar(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "device_session_failed",
            AuthSecurityEvent.user_id == self.interviewer.user_id,
        ))
        self.assertIsNotNone(event)
        self.assertEqual(event.detail, {"device_id": device["device_id"], "reason": "invalid_credentials"})

    def _enrol_totp(self, user):
        secret = totp_service.begin_enrolment(user)["secret"]
        self.assertTrue(totp_service.confirm_enrolment(user, pyotp.TOTP(secret).now()))
        db.session.execute(sa.update(AuthTotp).where(AuthTotp.user_id == user.user_id).values(last_used_step=None))
        db.session.commit()
        return secret

    def test_second_factor_required_then_accepted_by_totp_or_recovery_code(self):
        secret = self._enrol_totp(self.interviewer)
        codes = totp_service.generate_recovery_codes(self.interviewer)
        db.session.commit()
        device = self._enrol()

        missing = self._sign_in(device)
        self.assertEqual((missing.status_code, missing.get_json()["code"]), (401, "second_factor_required"))
        wrong = self._sign_in(device, otp="000000")
        self.assertEqual((wrong.status_code, wrong.get_json()["code"]), (401, "second_factor_required"))

        self.assertEqual(self._sign_in(device, otp=pyotp.TOTP(secret).now()).status_code, 201)
        self.assertEqual(self._sign_in(device, otp=codes[0]).status_code, 201)
        # A recovery code works once.
        self.assertEqual(self._sign_in(device, otp=codes[0]).status_code, 401)

    def test_five_wrong_second_factor_codes_lock_the_account_on_devices(self):
        secret = self._enrol_totp(self.interviewer)
        device = self._enrol()
        statuses = [self._sign_in(device, otp="000000").get_json()["code"] for _ in range(5)]
        self.assertEqual(statuses, ["second_factor_required"] * 5)
        lockouts = db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.user_id == self.interviewer.user_id,
            AuthSecurityEvent.event_type == "second_factor_lockout")).all()
        self.assertEqual(len(lockouts), 1)
        self.assertEqual(lockouts[0].detail, {"device_id": device["device_id"], "channel": "device"})
        # Even the right code is refused now, without being checked.
        locked = self._sign_in(device, otp=pyotp.TOTP(secret).now())
        self.assertEqual((locked.status_code, locked.get_json()["code"]), (429, "second_factor_locked"))
        # The window passes: the right code works again.
        db.session.execute(sa.update(AuthSecurityEvent).where(
            AuthSecurityEvent.user_id == self.interviewer.user_id
        ).values(occurred_at=datetime.now(UTC) - devices.SECOND_FACTOR_WINDOW - timedelta(seconds=1)))
        db.session.commit()
        self.assertEqual(self._sign_in(device, otp=pyotp.TOTP(secret).now()).status_code, 201)

    def test_a_successful_sign_in_resets_the_second_factor_count(self):
        secret = self._enrol_totp(self.interviewer)
        codes = totp_service.generate_recovery_codes(self.interviewer)
        db.session.commit()
        device = self._enrol()
        for _ in range(4):
            self._sign_in(device, otp="000000")
        self.assertEqual(self._sign_in(device, otp=codes[0]).status_code, 201)
        self._sign_in(device, otp="000000")
        self.assertEqual(self._sign_in(device, otp=pyotp.TOTP(secret).now()).status_code, 201)

    def test_post_password_refusals_are_audited_without_secrets(self):
        device = self._enrol()
        user = self.teammate
        cases = [
            ("email_verified", False, "email_unverified"),
            ("pw_reset_t_and_c", False, "password_change_required"),
        ]
        for attribute, value, code in cases:
            original = getattr(user, attribute)
            setattr(user, attribute, value)
            db.session.commit()
            try:
                response = self._sign_in(device, email="device.teammate@test.local")
                self.assertEqual(response.get_json()["code"], code)
            finally:
                setattr(user, attribute, original)
                db.session.commit()
        with mock.patch.object(devices, "should_block_non_admin_after_cutoff", return_value=True):
            self.assertEqual(self._sign_in(device, email="device.teammate@test.local").get_json()["code"], "maintenance")
        self._enrol_totp(user)
        self.assertEqual(
            self._sign_in(device, email="device.teammate@test.local").get_json()["code"], "second_factor_required")
        events = db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.user_id == user.user_id,
            AuthSecurityEvent.event_type == "device_session_failed",
        ).order_by(AuthSecurityEvent.occurred_at)).all()
        self.assertEqual(
            [e.detail["reason"] for e in events],
            ["email_unverified", "password_change_required", "maintenance", "second_factor_required"],
        )
        for event in events:
            self.assertEqual(set(event.detail), {"device_id", "reason"})

    def test_sign_in_needs_an_interviewer_grant_in_the_device_project(self):
        device = self._enrol()
        response = self._sign_in(device, email="device.outsider@test.local")
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "no_interviewer_grant"))

    def test_sign_in_refused_on_a_revoked_device(self):
        device = self._enrol()
        devices.revoke_device(db.session.get(AuthDevice, uuid.UUID(device["device_id"])), actor=self.base_admin_user)
        db.session.commit()
        response = self._sign_in(device)
        self.assertEqual((response.status_code, response.get_json()["code"]), (403, "device_revoked"))

    def _sign_in_from(self, ip, device, **kwargs):
        self.client.environ_base["REMOTE_ADDR"] = ip
        try:
            return self._sign_in(device, **kwargs).status_code
        finally:
            self.client.environ_base.pop("REMOTE_ADDR", None)

    def test_sign_in_is_rate_limited_per_device_not_only_per_ip(self):
        device_a, device_b = self._enrol(), self._enrol()
        statuses = [self._sign_in_from("10.0.0.1", device_a, password="wrong") for _ in range(10)]
        self.assertEqual(statuses, [401] * 10)
        # A fresh IP: device A is still limited, device B is not.
        self.assertEqual(self._sign_in_from("10.0.0.2", device_a, password="wrong"), 429)
        self.assertEqual(self._sign_in_from("10.0.0.2", device_b, password="wrong"), 401)

    def test_sign_in_is_rate_limited_per_account(self):
        attempts = []
        for n in range(21):
            # Through the service: /enroll's own per-IP limit is not under test.
            row, secret = devices.enrol_device(self._code(), device_name=f"p{n}", platform="android", app_version="1")
            db.session.commit()
            device = {"device_id": str(row.device_id), "device_secret": secret}
            attempts.append(self._sign_in_from(f"10.0.1.{n}", device, password="wrong"))
        self.assertEqual(attempts[:20], [401] * 20)
        self.assertEqual(attempts[20], 429)

    # ── sign-in by mobile number (digitva-kmoy) ───────────────────────────

    @staticmethod
    def _new_number():
        return "9" + uuid.uuid4().int.__str__()[:9]

    def _mobile_interviewer(self, *, redeemed=True):
        from app.models import VaUsers

        number = self._new_number()
        user = VaUsers(
            user_id=uuid.uuid4(), name="Mobile Interviewer", email=None, phone=number,
            mobile_login=number, vacode_language=["English"], permission={},
            landing_page="coder", pw_reset_t_and_c=True, email_verified=False,
            mobile_verified_at=datetime.now(UTC) if redeemed else None,
            user_status=VaStatuses.active,
        )
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.flush()
        self._grant(user, self.PROJECT_ID)
        db.session.commit()
        return user

    def test_sign_in_by_mobile_number_in_any_typed_format(self):
        user = self._mobile_interviewer()
        device = self._enrol()
        for typed in (user.mobile_login, f"+91 {user.mobile_login[:5]} {user.mobile_login[5:]}"):
            with self.subTest(typed=typed):
                response = self._sign_in(device, email=typed)
                self.assertEqual(response.status_code, 201, response.get_json())
                self.assertEqual(response.get_json()["user"]["user_id"], str(user.user_id))

    def test_email_account_with_a_unique_number_signs_in_by_either(self):
        number = self._new_number()
        self.teammate.phone = number
        self.teammate.mobile_login = number
        db.session.commit()
        try:
            device = self._enrol()
            self.assertEqual(self._sign_in(device, email=f"0{number}").status_code, 201)
            self.assertEqual(self._sign_in(device, email="device.teammate@test.local").status_code, 201)
        finally:
            self.teammate.phone = None
            self.teammate.mobile_login = None
            db.session.commit()

    def test_unknown_shared_invalid_and_unredeemed_numbers_are_indistinguishable(self):
        shared = self._new_number()
        self.outsider.phone = f"+91{shared}"  # held only as free text, never a sign-in number
        db.session.commit()
        unredeemed = self._mobile_interviewer(redeemed=False)
        device = self._enrol()
        answers = set()
        for typed in (self._new_number(), shared, "12345", "not a number", unredeemed.mobile_login):
            with self.subTest(typed=typed):
                response = self._sign_in(device, email=typed)
                answers.add((response.status_code, json.dumps(response.get_json(), sort_keys=True)))
        self.assertEqual(len(answers), 1, answers)
        status, body = answers.pop()
        self.assertEqual(status, 401)
        self.assertEqual(json.loads(body)["code"], "invalid_credentials")
        self.outsider.phone = None
        db.session.commit()

    def test_mobile_sign_in_is_rate_limited_on_the_canonical_number(self):
        user = self._mobile_interviewer()
        attempts = []
        for n in range(21):
            row, secret = devices.enrol_device(self._code(), device_name=f"m{n}", platform="android", app_version="1")
            db.session.commit()
            device = {"device_id": str(row.device_id), "device_secret": secret}
            typed = user.mobile_login if n % 2 else f"+91 {user.mobile_login}"
            attempts.append(self._sign_in_from(f"10.0.2.{n}", device, email=typed, password="wrong"))
        self.assertEqual(attempts[:20], [401] * 20)
        self.assertEqual(attempts[20], 429)

    # ── refresh ────────────────────────────────────────────────────────────

    def test_refresh_rotates_and_the_old_token_is_dead(self):
        _device, tokens = self._session()
        rotated = self._refresh(tokens["refresh_token"])
        self.assertEqual(rotated.status_code, 200, rotated.get_json())
        new = rotated.get_json()
        self.assertNotEqual(new["refresh_token"], tokens["refresh_token"])
        self.assertNotEqual(new["access_token"], tokens["access_token"])
        # The new access token works, the old one does not.
        self.assertEqual(self.client.get(f"{API}/bootstrap", headers=self._bearer(new)).status_code, 200)
        self.assertEqual(self.client.get(f"{API}/bootstrap", headers=self._bearer(tokens)).status_code, 401)

    def _age_rotation(self, user, seconds=120):
        """Move the session's last rotation out of the grace window."""
        db.session.execute(sa.update(AuthDeviceSession).where(
            AuthDeviceSession.user_id == user.user_id
        ).values(refreshed_at=datetime.now(UTC) - timedelta(seconds=seconds)))
        db.session.commit()

    def test_reusing_a_rotated_refresh_token_revokes_the_session_as_reuse_not_revocation(self):
        device, tokens = self._session()
        new = self._refresh(tokens["refresh_token"]).get_json()
        self._age_rotation(self.interviewer)
        reused = self._refresh(tokens["refresh_token"], device)
        self.assertEqual((reused.status_code, reused.get_json()["code"]), (401, "refresh_reused"))
        # The whole session is gone: the attacker's or the owner's newer tokens
        # too, and they keep answering refresh_reused, never session_revoked
        # (the only code on which the app wipes the interviewer's store).
        again = self._refresh(new["refresh_token"])
        self.assertEqual((again.status_code, again.get_json()["code"]), (401, "refresh_reused"))
        self.assertEqual(self.client.get(f"{API}/bootstrap", headers=self._bearer(new)).status_code, 401)
        row = db.session.scalar(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.user_id == self.interviewer.user_id))
        self.assertEqual(row.revoked_reason, "refresh_reuse")

    def test_any_of_the_last_retired_refresh_tokens_is_reuse(self):
        device, tokens = self._session()
        chain = [tokens["refresh_token"]]
        for _ in range(4):
            chain.append(self._refresh(chain[-1]).get_json()["refresh_token"])
        row = db.session.scalar(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.user_id == self.interviewer.user_id))
        self.assertEqual(len(row.retired_refresh_hashes), 4)
        self.assertEqual(row.retired_refresh_hashes[0], devices.hash_token(chain[-2]))
        # The oldest one, three rotations back from the previous one.
        reused = self._refresh(chain[0], device)
        self.assertEqual((reused.status_code, reused.get_json()["code"]), (401, "refresh_reused"))
        db.session.refresh(row)
        self.assertIsNotNone(row.revoked_at)

    def test_retired_hash_history_is_bounded(self):
        _device, tokens = self._session()
        token = tokens["refresh_token"]
        for _ in range(devices.RETIRED_REFRESH_KEEP + 3):
            token = self._refresh(token).get_json()["refresh_token"]
        row = db.session.scalar(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.user_id == self.interviewer.user_id))
        self.assertEqual(len(row.retired_refresh_hashes), devices.RETIRED_REFRESH_KEEP)

    def test_a_retry_within_the_grace_window_is_a_race_and_keeps_the_app_data(self):
        device, tokens = self._session()
        new = self._refresh(tokens["refresh_token"]).get_json()
        # The response was lost; the app retries with the token it still has.
        retry = self._refresh(tokens["refresh_token"], device)
        self.assertEqual((retry.status_code, retry.get_json()["code"]), (409, "refresh_retry_race"))
        # Revoked (the app never held the new pair), but not as session_revoked.
        again = self._refresh(new["refresh_token"])
        self.assertEqual((again.status_code, again.get_json()["code"]), (409, "refresh_retry_race"))
        row = db.session.scalar(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.user_id == self.interviewer.user_id))
        self.assertEqual(row.revoked_reason, "refresh_retry_race")

    def test_refresh_needs_the_session_device_credentials(self):
        device, tokens = self._session()
        other = self._enrol()
        for creds in ({}, {"device_id": device["device_id"]},
                      {"device_id": device["device_id"], "device_secret": "wrong"},
                      other):
            response = self._refresh(tokens["refresh_token"], creds or {"device_id": None})
            self.assertEqual((response.status_code, response.get_json()["code"]), (401, "device_invalid"), creds)
        # Nothing was revoked or rotated: the right device still refreshes.
        self.assertEqual(self._refresh(tokens["refresh_token"], device).status_code, 200)

    def test_a_retired_token_without_the_device_secret_revokes_nothing(self):
        device, tokens = self._session()
        new = self._refresh(tokens["refresh_token"]).get_json()
        self._age_rotation(self.interviewer)
        leaked = self._refresh(tokens["refresh_token"], {"device_id": device["device_id"], "device_secret": "x"})
        self.assertEqual(leaked.get_json()["code"], "device_invalid")
        self.assertEqual(self._refresh(new["refresh_token"]).status_code, 200)

    def test_session_past_the_absolute_cap_expires_without_revocation(self):
        _device, tokens = self._session()
        row = db.session.scalar(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.user_id == self.interviewer.user_id))
        self.assertLessEqual(row.refresh_expires_at, row.created_at + timedelta(days=90))
        db.session.execute(sa.update(AuthDeviceSession).where(
            AuthDeviceSession.session_id == row.session_id
        ).values(created_at=datetime.now(UTC) - timedelta(days=91)))
        db.session.commit()
        response = self._refresh(tokens["refresh_token"])
        self.assertEqual((response.status_code, response.get_json()["code"]), (401, "session_expired"))
        db.session.refresh(row)
        self.assertIsNone(row.revoked_at)

    def test_sliding_refresh_expiry_is_clamped_to_the_cap(self):
        _device, tokens = self._session()
        row = db.session.scalar(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.user_id == self.interviewer.user_id))
        created = datetime.now(UTC) - timedelta(days=80)
        db.session.execute(sa.update(AuthDeviceSession).where(
            AuthDeviceSession.session_id == row.session_id).values(created_at=created))
        db.session.commit()
        body = self._refresh(tokens["refresh_token"]).get_json()
        self.assertEqual(datetime.fromisoformat(body["refresh_expires_at"]), created + timedelta(days=90))

    def test_an_unknown_refresh_token_revokes_nothing(self):
        response = self._refresh("never-issued", self._enrol())
        self.assertEqual((response.status_code, response.get_json()["code"]), (401, "refresh_invalid"))

    def test_withdrawn_grant_revokes_the_session_at_refresh(self):
        _device, tokens = self._session(email="device.teammate@test.local")
        db.session.execute(sa.update(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == self.teammate.user_id
        ).values(grant_status=VaStatuses.deactive))
        db.session.commit()
        response = self._refresh(tokens["refresh_token"])
        self.assertEqual((response.status_code, response.get_json()["code"]), (401, "session_revoked"))
        row = db.session.scalar(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.user_id == self.teammate.user_id))
        self.assertEqual(row.revoked_reason, "grant_withdrawn")

    def test_a_password_or_factor_reset_ends_device_sessions_without_a_wipe(self):
        _device, tokens = self._session(email="device.teammate@test.local")
        self.teammate.bump_session_version()
        db.session.commit()
        self.assertEqual(self.client.get(f"{API}/bootstrap", headers=self._bearer(tokens)).status_code, 401)
        response = self._refresh(tokens["refresh_token"])
        # session_ended, not session_revoked: a forgotten-password reset must
        # not make the phone destroy that interviewer's unsent interviews.
        self.assertEqual((response.status_code, response.get_json()["code"]), (401, "session_ended"))
        self.assertEqual(self._refresh(tokens["refresh_token"]).get_json()["code"], "session_ended")
        row = db.session.scalar(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.user_id == self.teammate.user_id))
        self.assertEqual(row.revoked_reason, "account_changed")

    def test_sign_out_ends_the_session(self):
        _device, tokens = self._session()
        self.assertEqual(self.client.delete(f"{API}/sessions/current", headers=self._bearer(tokens)).status_code, 204)
        self.assertEqual(self.client.get(f"{API}/bootstrap", headers=self._bearer(tokens)).status_code, 401)
        self.assertEqual(self._refresh(tokens["refresh_token"]).get_json()["code"], "session_revoked")

    # ── bearer scope ───────────────────────────────────────────────────────

    def test_bearer_token_is_not_accepted_outside_the_device_api(self):
        _device, tokens = self._session()
        # Present first: the token does open the device API.
        self.assertEqual(self.client.get(f"{API}/bootstrap", headers=self._bearer(tokens)).status_code, 200)
        self.assertEqual(self.client.get("/intake/api/bootstrap", headers=self._bearer(tokens)).status_code, 401)
        self.assertEqual(self.client.get("/intake/", headers=self._bearer(tokens)).status_code, 302)

    def test_a_cookie_session_is_not_accepted_inside_the_device_api(self):
        self._login(str(self.interviewer.user_id))
        self.assertEqual(self.client.get("/intake/api/bootstrap").status_code, 200)
        response = self.client.get(f"{API}/bootstrap")
        self.assertEqual((response.status_code, response.get_json()["code"]), (401, "unauthorized"))
        self.assertEqual(self._upload({"access_token": ""}).status_code, 401)

    def test_device_responses_set_no_cookie(self):
        device, tokens = self._session()
        responses = [
            self.client.get(f"{API}/bootstrap", headers=self._bearer(tokens)),
            self._refresh(tokens["refresh_token"]),
            self._sign_in(device),
        ]
        responses.append(self._upload(responses[1].get_json()))
        for response in responses:
            self.assertIn(response.status_code, (200, 201))
            self.assertNotIn("Set-Cookie", response.headers)

    # ── bootstrap ──────────────────────────────────────────────────────────

    def test_bootstrap_is_scoped_to_the_device_project(self):
        _device, tokens = self._session()
        # The interviewer's web bootstrap reaches both projects...
        self._login(str(self.interviewer.user_id))
        web = self.client.get("/intake/api/bootstrap").get_json()
        self.assertEqual({c["project_id"] for c in web["context"]}, {self.PROJECT_ID, self.OTHER_PROJECT_ID})
        # ...the device's only its own.
        self.client.delete_cookie("session")
        body = self.client.get(f"{API}/bootstrap", headers=self._bearer(tokens)).get_json()
        self.assertEqual([c["project_id"] for c in body["context"]], [self.PROJECT_ID])
        self.assertEqual(body["user"]["user_id"], str(self.interviewer.user_id))
        self.assertEqual(body["form_options"]["project_id"], self.PROJECT_ID)
        self.assertIn("instrument_version", body)
        self.assertNotIn("csrf_token", body)

    # ── submissions ────────────────────────────────────────────────────────

    def test_upload_is_idempotent_on_client_draft_id(self):
        _device, tokens = self._session()
        client_draft_id = uuid.uuid4()
        first = self._upload(tokens, client_draft_id)
        self.assertEqual(first.status_code, 201, first.get_json())
        body = first.get_json()
        self.assertTrue(body["va_sid"])
        self.assertEqual(body["outcome"], "completed")
        self.assertEqual(body["case"]["status"], "submitted")
        self.assertFalse(body["superseded"])

        again = self._upload(tokens, client_draft_id)
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.get_json(), body)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeDraft).where(
            VaWebIntakeDraft.client_draft_id == client_draft_id)), 1)
        version = db.session.scalar(sa.select(VaSubmissionPayloadVersion).where(
            VaSubmissionPayloadVersion.va_sid == body["va_sid"]))
        self.assertEqual(version.payload_data["intake_source"], "device")

    def test_upload_without_a_valid_completion_needs_an_incomplete_outcome(self):
        _device, tokens = self._session()
        response = self._upload(tokens, completion={"valid": False, "issues": []})
        self.assertEqual((response.status_code, response.get_json()["code"]), (422, "invalid_interview"))

    def test_another_interviewers_client_draft_id_is_not_theirs_to_read(self):
        _device, tokens = self._session()
        client_draft_id = uuid.uuid4()
        self.assertEqual(self._upload(tokens, client_draft_id).status_code, 201)
        _device2, teammate_tokens = self._session(email="device.teammate@test.local")
        response = self._upload(teammate_tokens, client_draft_id)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn("va_sid", response.get_json())

    def test_upload_outside_scope_is_refused(self):
        _device, tokens = self._session()
        # A site of another project: the device's project has no such site.
        other_site = self._upload(tokens, site_id=self.OTHER_SITE_ID)
        self.assertEqual(other_site.status_code, 403)
        unknown_case = self._upload(tokens, death_id=str(uuid.uuid4()))
        self.assertEqual(unknown_case.status_code, 404)
        # A case in another project the interviewer can reach on the web.
        other = intake_svc.register_death(
            self.interviewer, project_id=self.OTHER_PROJECT_ID, site_id=self.OTHER_SITE_ID,
            deceased_name="Other Case", deceased_sex="female",
            date_of_death=(date.today() - timedelta(days=3)).isoformat(), age_years=60,
        )
        db.session.commit()
        cross = self._upload(tokens, death_id=str(other.death_id), site_id=self.OTHER_SITE_ID)
        self.assertEqual(cross.status_code, 404)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeDraft).where(
            VaWebIntakeDraft.user_id == self.interviewer.user_id)), 0)

    def test_upload_for_a_case_a_teammate_submitted_is_kept_as_a_superseded_copy(self):
        _device, teammate_tokens = self._session(email="device.teammate@test.local")
        won = self._upload(teammate_tokens).get_json()
        death_id = won["case"]["death_id"]
        submissions_before = db.session.scalar(sa.select(sa.func.count()).select_from(VaSubmissions))

        _device2, tokens = self._session()
        answers = {**_complete_answers(), "Id10017": "Different"}
        late = self._upload(tokens, death_id=death_id, draft={"data": answers})
        self.assertEqual(late.status_code, 201, late.get_json())
        body = late.get_json()
        self.assertTrue(body["superseded"])
        self.assertIsNone(body["va_sid"])
        self.assertEqual(body["case"], {"death_id": death_id, "unique_id": won["case"]["unique_id"], "status": "submitted"})
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaSubmissions)), submissions_before)
        copy = db.session.scalar(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.user_id == self.interviewer.user_id, VaWebIntakeDraft.death_id == uuid.UUID(death_id)))
        self.assertEqual(copy.status, "superseded")
        self.assertEqual(copy.sections[0].data["Id10017"], "Different")
        # The winning case's identity is untouched by the copy.
        self.assertEqual(db.session.get(VaDeathRegister, uuid.UUID(death_id)).deceased_name, "Bina Sahu")

    # ── offline cases (digitva-kmk.4) ───────────────────────────────────────

    def _web_case(self, user=None, project_id=None, site_id=None, **fields):
        death = intake_svc.register_death(
            user or self.interviewer, project_id=project_id or self.PROJECT_ID, site_id=site_id or self.SITE_ID,
            deceased_name=fields.pop("deceased_name", "Kamla Devi"), deceased_sex="female",
            date_of_death=(date.today() - timedelta(days=4)).isoformat(), age_years=64, **fields,
        )
        db.session.commit()
        return death

    def _register(self, tokens, client_death_id=None, **fields):
        body = {
            "client_death_id": str(client_death_id or uuid.uuid4()), "site_id": self.SITE_ID,
            "deceased_name": "Ram Lal Verma", "deceased_sex": "male",
            "date_of_death": (date.today() - timedelta(days=2)).isoformat(), "age_years": "58",
            "informant_name": "Sita Verma", "informant_phone": "+91 98765-43210",
            **fields,
        }
        return self.client.post(f"{API}/deaths", json=body, headers=self._bearer(tokens))

    def _cases(self, tokens, **params):
        response = self.client.get(f"{API}/cases", query_string=params, headers=self._bearer(tokens))
        self.assertEqual(response.status_code, 200, response.get_json())
        return response

    def _attempt(self, tokens, death_id, client_attempt_id=None, **body):
        return self.client.post(f"{API}/cases/{death_id}/attempts", json={
            "client_attempt_id": str(client_attempt_id or uuid.uuid4()), "outcome": "no_answer", **body,
        }, headers=self._bearer(tokens))

    def test_cases_lists_waiting_and_own_in_progress_cases_of_the_device_project_only(self):
        _device, tokens = self._session()
        waiting = self._web_case(informant_phone="9876543210", informant_name="Mohan Das")
        refused = self._web_case(deceased_name="Refused Case")
        intake_svc.log_contact_attempt(self.interviewer, refused.death_id, outcome="refused")
        mine = self._web_case(deceased_name="Mine Started")
        intake_svc.start_draft(self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_id=mine.death_id)
        theirs = self._web_case(user=self.teammate, deceased_name="Teammate Started")
        intake_svc.start_draft(self.teammate, project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_id=theirs.death_id)
        other_project = self._web_case(project_id=self.OTHER_PROJECT_ID, site_id=self.OTHER_SITE_ID)
        db.session.commit()

        response = self._cases(tokens)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        rows = {row["death_id"]: row for row in response.get_json()["cases"]}
        self.assertIn(str(waiting.death_id), rows)
        self.assertIn(str(refused.death_id), rows)
        self.assertIn(str(mine.death_id), rows)
        self.assertNotIn(str(theirs.death_id), rows)
        self.assertNotIn(str(other_project.death_id), rows)

        row = rows[str(waiting.death_id)]
        self.assertEqual(row["state"], "registered")
        self.assertEqual(row["informant_phone_masked"], "******3210")
        self.assertNotIn("9876543210", response.get_data(as_text=True))
        prefill = row["prefill"]
        self.assertEqual(set(prefill), {"interviewer", "deceased", "answers", "lockedQuestionNames"})
        self.assertEqual(prefill["deceased"]["givenNames"], "Kamla")
        self.assertEqual(prefill["deceased"]["surname"], "Devi")
        self.assertEqual(prefill["answers"]["Id10007"], "Mohan Das")
        self.assertEqual(prefill["interviewer"]["id"], str(self.interviewer.user_id))
        # The same prefill the web form gets for this case.
        self.assertEqual(prefill, intake_svc._prefill_from_death(waiting, self.interviewer, waiting.org_unit_id))

    def test_cases_page_with_a_cursor_and_refuse_a_bad_limit(self):
        _device, tokens = self._session()
        first, second = self._web_case(deceased_name="Page One"), self._web_case(deceased_name="Page Two")
        seen, cursor = [], None
        while True:
            body = self._cases(tokens, limit=1, **({"cursor": cursor} if cursor else {})).get_json()
            self.assertLessEqual(len(body["cases"]), 1)
            seen += [row["death_id"] for row in body["cases"]]
            cursor = body["next_cursor"]
            if not cursor:
                break
        self.assertIn(str(first.death_id), seen)
        self.assertIn(str(second.death_id), seen)
        self.assertEqual(len(seen), len(set(seen)))
        bad = self.client.get(f"{API}/cases?limit=x", headers=self._bearer(tokens))
        self.assertEqual((bad.status_code, bad.get_json()["code"]), (400, "invalid_request"))
        self.assertEqual(self.client.get(f"{API}/cases").status_code, 401)

    def test_offline_registration_is_idempotent_on_client_death_id(self):
        _device, tokens = self._session()
        client_death_id = uuid.uuid4()
        created = self._register(tokens, client_death_id)
        self.assertEqual(created.status_code, 201, created.get_json())
        case = created.get_json()["case"]
        self.assertEqual(case["state"], "registered")
        self.assertEqual(case["informant_phone_masked"], "******3210")
        self.assertNotIn("9876543210", created.get_data(as_text=True))
        self.assertEqual(case["prefill"]["deceased"]["givenNames"], "Ram")
        death = db.session.get(VaDeathRegister, uuid.UUID(case["death_id"]))
        self.assertEqual((death.client_death_id, death.informant_phone), (client_death_id, "9876543210"))

        again = self._register(tokens, client_death_id, deceased_name="Changed On Resend")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.get_json()["case"]["death_id"], case["death_id"])
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister).where(
            VaDeathRegister.client_death_id == client_death_id)), 1)
        self.assertEqual(db.session.get(VaDeathRegister, uuid.UUID(case["death_id"])).deceased_name, "Ram Lal Verma")

        _device2, teammate_tokens = self._session(email="device.teammate@test.local")
        taken = self._register(teammate_tokens, client_death_id)
        self.assertEqual((taken.status_code, taken.get_json()["code"]), (409, "conflict"))
        self.assertNotIn("case", taken.get_json())

    def test_offline_registration_refusals(self):
        _device, tokens = self._session()
        before = db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister))
        for fields, expected in (
            ({"informant_phone": "12345"}, (422, "invalid_registration")),
            ({"deceased_name": ""}, (422, "invalid_registration")),
            ({"date_of_death": "2999-01-01"}, (422, "invalid_registration")),
            ({"deceased_name": ["x"]}, (422, "invalid_registration")),
            ({"client_death_id": "not-a-uuid"}, (400, "invalid_request")),
            ({"site_id": ""}, (400, "invalid_request")),
            ({"site_id": self.OTHER_SITE_ID}, (403, "forbidden")),
        ):
            response = self._register(tokens, **fields)
            self.assertEqual((response.status_code, response.get_json()["code"]), expected, fields)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaDeathRegister)), before)

    def test_a_death_registered_offline_then_interviewed_offline_uploads_in_order(self):
        _device, tokens = self._session()
        client_death_id = uuid.uuid4()
        case = self._register(tokens, client_death_id).get_json()["case"]
        uploaded = self._upload(tokens, death_id=case["death_id"])
        self.assertEqual(uploaded.status_code, 201, uploaded.get_json())
        body = uploaded.get_json()
        self.assertEqual(body["case"]["death_id"], case["death_id"])
        self.assertEqual(body["case"]["status"], "submitted")
        self.assertIsNotNone(body["va_sid"])
        # A late resend of the registration still answers with the same case.
        again = self._register(tokens, client_death_id)
        self.assertEqual((again.status_code, again.get_json()["case"]["state"]), (200, "submitted"))
        # And the case leaves the download.
        self.assertNotIn(case["death_id"], [row["death_id"] for row in self._cases(tokens).get_json()["cases"]])

    def test_offline_attempt_is_idempotent_on_client_attempt_id(self):
        from app.models import MapCaseContactAttempt

        _device, tokens = self._session()
        death = self._web_case()
        client_attempt_id = uuid.uuid4()
        logged = self._attempt(tokens, death.death_id, client_attempt_id)
        self.assertEqual(logged.status_code, 201, logged.get_json())
        self.assertEqual(logged.get_json()["case"]["status"], "not_reachable")
        resent = self._attempt(tokens, death.death_id, client_attempt_id)
        self.assertEqual(resent.status_code, 200)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(MapCaseContactAttempt).where(
            MapCaseContactAttempt.client_attempt_id == client_attempt_id)), 1)
        # The case has since moved on: a resend still acknowledges, logs nothing.
        intake_svc.start_draft(self.interviewer, project_id=self.PROJECT_ID, site_id=self.SITE_ID, death_id=death.death_id)
        db.session.commit()
        self.assertEqual(self._attempt(tokens, death.death_id, client_attempt_id).status_code, 200)
        self.assertEqual(self._attempt(tokens, death.death_id).status_code, 409)
        # The same id on another case, or by another interviewer, is a conflict.
        other = self._web_case(deceased_name="Other Case")
        self.assertEqual(self._attempt(tokens, other.death_id, client_attempt_id).status_code, 409)
        _device2, teammate_tokens = self._session(email="device.teammate@test.local")
        self.assertEqual(self._attempt(teammate_tokens, death.death_id, client_attempt_id).status_code, 409)

    def test_offline_attempt_and_visit_refusals(self):
        _device, tokens = self._session()
        death = self._web_case()
        other_project = self._web_case(project_id=self.OTHER_PROJECT_ID, site_id=self.OTHER_SITE_ID)
        for death_id in (other_project.death_id, uuid.uuid4(), "not-a-uuid"):
            self.assertEqual(self._attempt(tokens, death_id).status_code, 404, death_id)
            visit = self.client.post(f"{API}/cases/{death_id}/visit", json={"next_visit_at": None},
                                     headers=self._bearer(tokens))
            self.assertEqual(visit.status_code, 404, death_id)
        bad = self._attempt(tokens, death.death_id, outcome="gossip")
        self.assertEqual((bad.status_code, bad.get_json()["code"]), (422, "invalid_attempt"))
        self.assertEqual(self._attempt(tokens, death.death_id, client_attempt_id="x").status_code, 400)
        late = self.client.post(f"{API}/cases/{death.death_id}/visit", json={"next_visit_at": "2020-01-01T09:00:00+00:00"},
                                headers=self._bearer(tokens))
        self.assertEqual((late.status_code, late.get_json()["code"]), (422, "invalid_visit"))

    def test_offline_visit_schedules_the_case_and_a_resend_sets_the_same_date(self):
        _device, tokens = self._session()
        death = self._web_case()
        when = (datetime.now(UTC) + timedelta(days=2)).replace(microsecond=0).isoformat()
        for _ in range(2):
            response = self.client.post(f"{API}/cases/{death.death_id}/visit", json={"next_visit_at": when},
                                        headers=self._bearer(tokens))
            self.assertEqual(response.status_code, 200, response.get_json())
            self.assertEqual(response.get_json()["case"]["status"], "scheduled")
            self.assertEqual(response.get_json()["case"]["next_visit_at"], when)

    def test_outstanding_report_records_pending_registrations(self):
        _device, tokens = self._session()
        pending = str(uuid.uuid4())
        response = self.client.post(f"{API}/outstanding", json={
            "count": 0, "unique_ids": [], "client_draft_ids": [], "client_death_ids": [pending.upper()],
        }, headers=self._bearer(tokens))
        self.assertEqual(response.status_code, 204)
        row = db.session.scalar(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.user_id == self.interviewer.user_id))
        self.assertEqual(row.outstanding_client_death_ids, [pending])
        bad = self.client.post(f"{API}/outstanding", json={"count": 0, "client_death_ids": ["x"]},
                               headers=self._bearer(tokens))
        self.assertEqual(bad.status_code, 400)

    # ── size limits ────────────────────────────────────────────────────────

    def test_oversized_bodies_are_refused_with_413(self):
        device, tokens = self._session()
        big = "x" * (17 * 1024)
        report = "x" * (257 * 1024)
        for response in (
            self._sign_in(device, password=big),
            self.client.post(f"{API}/enroll", json={"code": big}),
            self._refresh(tokens["refresh_token"], note=report),
            self.client.post(f"{API}/outstanding", json={"count": 0, "note": report}, headers=self._bearer(tokens)),
        ):
            self.assertEqual((response.status_code, response.get_json()["code"]), (413, "payload_too_large"))
        # The upload gets 2 MB: 17 KB is fine there, 2 MB + 1 is not.
        ok = self._upload(tokens, draft={"data": {**_complete_answers(), "Id10476": big}})
        self.assertEqual(ok.status_code, 201, ok.get_json())
        huge = self._upload(tokens, draft={"data": {"Id10476": "x" * (2 * 1024 * 1024)}})
        self.assertEqual((huge.status_code, huge.get_json()["code"]), (413, "payload_too_large"))

    def test_deeply_nested_or_huge_answers_are_refused_before_storing(self):
        _device, tokens = self._session()
        nested = "leaf"
        for _ in range(intake_svc.DEVICE_ANSWERS_MAX_DEPTH):
            nested = {"n": nested}
        deep = self._upload(tokens, draft={"data": {**_complete_answers(), "Id10476": nested}})
        self.assertEqual((deep.status_code, deep.get_json()["code"]), (422, "invalid_interview"))
        with mock.patch.object(intake_svc, "DEVICE_ANSWERS_MAX_BYTES", 200):
            large = self._upload(tokens, draft={"data": {**_complete_answers(), "Id10476": "x" * 300}})
        self.assertEqual((large.status_code, large.get_json()["code"]), (422, "invalid_interview"))
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeDraft).where(
            VaWebIntakeDraft.user_id == self.interviewer.user_id)), 0)

    def test_superseded_path_is_bounded_too(self):
        _device, teammate_tokens = self._session(email="device.teammate@test.local")
        death_id = self._upload(teammate_tokens).get_json()["case"]["death_id"]
        _device2, tokens = self._session()
        nested = "leaf"
        for _ in range(intake_svc.DEVICE_ANSWERS_MAX_DEPTH):
            nested = [nested]
        late = self._upload(tokens, death_id=death_id, draft={"data": {**_complete_answers(), "Id10476": nested}})
        self.assertEqual(late.status_code, 422)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(VaWebIntakeDraft).where(
            VaWebIntakeDraft.user_id == self.interviewer.user_id)), 0)

    # ── locked prefill and partial birth dates (digitva-p6fs.9, tld2) ──────

    _TAMPERED = {
        "Id10010": "Someone Else", "Id10010a": 25, "Id10010b": "male",
        "Id10010c": "00000000-0000-0000-0000-000000000000", "Id10002": "veryl",
        "abha_number": "99999999999999",
    }

    def _locked_case(self):
        """A case at a unit with an HIV preset and ABHA, interviewed by a
        profile that locks name, age and sex; returns (case, authoritative)."""
        from app.services import organization_service as org

        self.interviewer.name = "Device Worker"
        self.interviewer.sex = "male"
        self.interviewer.year_of_birth = date.today().year - 35
        d1, _p1, _d2 = self._tree()
        org.set_unit_va_presets(self.PROJECT_ID, d1.org_unit_id, hiv_mortality="high", malaria_mortality=None)
        death = self._web_case(org_unit_id=str(d1.org_unit_id), abha_number="12345678901234")
        return death, {
            "Id10010": "Device Worker", "Id10010a": 35, "Id10010b": "male",
            "Id10010c": str(self.interviewer.user_id), "Id10002": "high", "abha_number": "12345678901234",
        }

    def test_upload_overwrites_tampered_locked_answers(self):
        death, authoritative = self._locked_case()
        _device, tokens = self._session()
        response = self._upload(tokens, death_id=str(death.death_id),
                                draft={"data": {**_complete_answers(), **self._TAMPERED}})
        self.assertEqual(response.status_code, 201, response.get_json())
        payload = db.session.scalar(sa.select(VaSubmissionPayloadVersion.payload_data).where(
            VaSubmissionPayloadVersion.va_sid == response.get_json()["va_sid"]))
        draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.death_id == death.death_id, VaWebIntakeDraft.user_id == self.interviewer.user_id))
        for name, value in authoritative.items():
            with self.subTest(name=name):
                self.assertEqual(payload[name], value)
                self.assertEqual(draft.sections[0].data[name], value)
        self.assertEqual(payload["Id10017"], "Bina")

    def test_untampered_upload_is_unaffected(self):
        death, authoritative = self._locked_case()
        _device, tokens = self._session()
        response = self._upload(tokens, death_id=str(death.death_id),
                                draft={"data": {**_complete_answers(), **authoritative}})
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["outcome"], "completed")
        draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.death_id == death.death_id, VaWebIntakeDraft.user_id == self.interviewer.user_id))
        self.assertEqual(draft.sections[0].data, {**_complete_answers(), **authoritative})

    def test_superseded_copy_overwrites_tampered_locked_answers(self):
        death, authoritative = self._locked_case()
        _device, teammate_tokens = self._session(email="device.teammate@test.local")
        self.assertEqual(self._upload(teammate_tokens, death_id=str(death.death_id)).status_code, 201)
        _device2, tokens = self._session()
        late = self._upload(tokens, death_id=str(death.death_id),
                            draft={"data": {**_complete_answers(), **self._TAMPERED}})
        self.assertTrue(late.get_json()["superseded"])
        copy = db.session.scalar(sa.select(VaWebIntakeDraft).where(
            VaWebIntakeDraft.user_id == self.interviewer.user_id, VaWebIntakeDraft.death_id == death.death_id))
        for name, value in authoritative.items():
            with self.subTest(name=name):
                self.assertEqual(copy.sections[0].data[name], value)

    def test_offline_registration_takes_a_partial_birth_date(self):
        _device, tokens = self._session()
        created = self._register(tokens, date_of_birth_partial="1966-04")
        self.assertEqual(created.status_code, 201, created.get_json())
        case = created.get_json()["case"]
        self.assertEqual(db.session.get(VaDeathRegister, uuid.UUID(case["death_id"])).date_of_birth_partial, "1966-04")
        answers = case["prefill"]["answers"]
        self.assertEqual((answers["Id10020"], answers["dob_precision"], answers["dob_month_year"]),
                         ("no", "month_year", "1966-04-01"))
        for fields in ({"date_of_birth_partial": "1966-13"},
                       {"date_of_birth_partial": "1966", "date_of_birth": "1966-04-02"}):
            refused = self._register(tokens, **fields)
            self.assertEqual((refused.status_code, refused.get_json()["code"]), (422, "invalid_registration"), fields)

    # ── units and translations ─────────────────────────────────────────────

    def _tree(self):
        """District D1 with PHC P1 below it, and district D2, in the device project."""
        from app.models.mas_organization import MasOrgLevel, MasOrgUnit

        district = MasOrgLevel(project_id=self.PROJECT_ID, level_code="district", level_name="District", depth=1)
        phc = MasOrgLevel(project_id=self.PROJECT_ID, level_code="phc", level_name="PHC", depth=2)
        db.session.add_all([district, phc])
        db.session.flush()

        def unit(code, level, path, parent=None):
            row = MasOrgUnit(org_unit_id=uuid.uuid4(), project_id=self.PROJECT_ID, org_level_id=level.org_level_id,
                             parent_org_unit_id=parent.org_unit_id if parent else None,
                             unit_code=code, unit_name=f"Unit {code}", path=path, is_active=True)
            db.session.add(row)
            db.session.flush()
            return row

        d1 = unit("D1", district, "D1")
        p1 = unit("P1", phc, "D1.P1", d1)
        d2 = unit("D2", district, "D2")
        db.session.commit()
        return d1, p1, d2

    def test_units_are_the_interviewers_reachable_units(self):
        d1, p1, d2 = self._tree()
        unit_user = self._get_or_make_user("device.unit@test.local", PASSWORD)
        db.session.add(VaUserAccessGrants(
            user_id=unit_user.user_id, role=VaAccessRoles.interviewer, scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=d1.org_unit_id, notes="device unit grant", grant_status=VaStatuses.active,
        ))
        # A coder grant elsewhere must not widen the interviewer picker.
        db.session.add(VaUserAccessGrants(
            user_id=unit_user.user_id, role=VaAccessRoles.coder, scope_type=VaAccessScopeTypes.org_unit,
            org_unit_id=d2.org_unit_id, notes="device unit coder grant", grant_status=VaStatuses.active,
        ))
        db.session.commit()

        _device, tokens = self._session(email="device.unit@test.local")
        body = self.client.get(f"{API}/units", headers=self._bearer(tokens)).get_json()
        self.assertTrue(body["scoped"])
        self.assertEqual(body["project_id"], self.PROJECT_ID)
        self.assertEqual({u["unit_code"] for u in body["units"]}, {"D1", "P1"})
        self.assertEqual({lvl["level_code"] for lvl in body["levels"]}, {"district", "phc"})

        _device2, project_tokens = self._session()
        whole = self.client.get(f"{API}/units", headers=self._bearer(project_tokens)).get_json()
        self.assertFalse(whole["scoped"])
        self.assertEqual({u["unit_code"] for u in whole["units"]}, {"D1", "P1", "D2"})
        self.assertTrue(all(u["selectable"] for u in whole["units"]))

    def test_units_need_a_bearer_token(self):
        self._login(str(self.interviewer.user_id))
        self.assertEqual(self.client.get(f"{API}/units").status_code, 401)

    def test_translations_only_for_the_projects_instrument_and_locales(self):
        from app.models.mas_instrument_locales import LIFECYCLE_APPROVED, MasInstrumentLocales
        from app.routes.api.organization import served_instrument_locales

        project = db.session.get(VaProjectMaster, self.PROJECT_ID)
        code, _ = served_instrument_locales(project)
        for locale, name in (("hi", "Hindi"), ("ta", "Tamil")):
            if db.session.get(MasInstrumentLocales, (code, locale)) is None:
                db.session.add(MasInstrumentLocales(
                    instrument_code=code, locale_code=locale, language_name=name, version=3, is_active=True,
                    updated_at=datetime.now(UTC), lifecycle_state=LIFECYCLE_APPROVED))
        project.web_intake_available_locales = None
        db.session.commit()
        _device, tokens = self._session()

        def get(locale, instrument=code):
            return self.client.get(f"{API}/instruments/{instrument}/translations/{locale}", headers=self._bearer(tokens))

        # Every instrument locale is served while the project names none...
        self.assertEqual(get("ta").status_code, 200)
        hi = get("hi")
        self.assertEqual(hi.status_code, 200)
        self.assertEqual(hi.get_json()["version"], 3)
        self.assertTrue(hi.headers["ETag"])
        self.assertEqual(get("en").status_code, 200)
        # ...then only the ones it names.
        project.web_intake_available_locales = ["hi"]
        db.session.commit()
        self.assertEqual(get("hi").status_code, 200)
        refused = get("ta")
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (404, "not_found"))
        self.assertEqual(get("hi", instrument="PHMRC_ADULT").status_code, 404)
        self.assertEqual(get("xx").status_code, 404)

    # ── outstanding ────────────────────────────────────────────────────────

    def test_outstanding_report_is_stored_on_the_session(self):
        _device, tokens = self._session()
        response = self.client.post(f"{API}/outstanding", json={"count": 2, "unique_ids": ["DV01-2", "DV01-1"]},
                                    headers=self._bearer(tokens))
        self.assertEqual(response.status_code, 204)
        row = db.session.scalar(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.user_id == self.interviewer.user_id))
        self.assertEqual((row.outstanding_count, row.outstanding_unique_ids), (2, ["DV01-1", "DV01-2"]))

        rotated = self._refresh(tokens["refresh_token"], count=0, unique_ids=[])
        self.assertEqual(rotated.status_code, 200)
        db.session.refresh(row)
        self.assertEqual((row.outstanding_count, row.outstanding_unique_ids), (0, []))

        bad = self.client.post(f"{API}/outstanding", json={"count": -1}, headers=self._bearer(rotated.get_json()))
        self.assertEqual(bad.status_code, 400)

    def test_outstanding_report_stores_client_draft_ids(self):
        _device, tokens = self._session()
        a, b = uuid.uuid4(), uuid.uuid4()
        response = self.client.post(f"{API}/outstanding", json={
            "count": 2, "unique_ids": [], "client_draft_ids": [str(b).upper(), str(a)],
        }, headers=self._bearer(tokens))
        self.assertEqual(response.status_code, 204)
        row = db.session.scalar(sa.select(AuthDeviceSession).where(
            AuthDeviceSession.user_id == self.interviewer.user_id))
        self.assertEqual(row.outstanding_client_draft_ids, sorted([str(a), str(b)]))
        self.assertEqual(row.outstanding_unique_ids, [])

        rotated = self._refresh(tokens["refresh_token"], count=1, client_draft_ids=[str(a)])
        self.assertEqual(rotated.status_code, 200)
        db.session.refresh(row)
        self.assertEqual(row.outstanding_client_draft_ids, [str(a)])

        for bad_ids in (["not-a-uuid"], [1], "x", [str(uuid.uuid4()) for _ in range(devices.OUTSTANDING_MAX_IDS + 1)]):
            bad = self.client.post(f"{API}/outstanding", json={"count": 0, "client_draft_ids": bad_ids},
                                   headers=self._bearer(rotated.get_json()))
            self.assertEqual(bad.status_code, 400, bad_ids)

        self._login(str(self.base_admin_id))
        listed = self.client.get(f"/admin/api/projects/{self.PROJECT_ID}/devices").get_json()["devices"]
        self.assertEqual(listed[0]["sessions"][0]["outstanding_client_draft_ids"], [str(a)])

    # ── admin ──────────────────────────────────────────────────────────────

    def test_admin_endpoints_are_admin_only_and_csrf_checked(self):
        url = f"/admin/api/projects/{self.PROJECT_ID}/device-enrolments"
        self._login(str(self.interviewer.user_id))
        self.assertEqual(self.client.post(url, json={}, headers=self._csrf_headers()).status_code, 403)
        self.assertEqual(self.client.get(f"/admin/api/projects/{self.PROJECT_ID}/devices").status_code, 403)
        self._login(str(self.base_project_pi_id))
        self.assertEqual(self.client.post(url, json={}, headers=self._csrf_headers()).status_code, 403)

        self._login(str(self.base_admin_id))
        self.assertEqual(self.client.post(url, json={}).status_code, 400)  # no CSRF token
        created = self.client.post(url, json={"expires_in_minutes": 30, "max_uses": 3}, headers=self._csrf_headers())
        self.assertEqual(created.status_code, 201, created.get_json())
        body = created.get_json()
        self.assertEqual(created.headers["Cache-Control"], "no-store")
        qr = json.loads(body["qr_payload"])
        self.assertEqual(qr, {"v": 1, "server": self.app.config["DEVICE_PUBLIC_URL"],
                              "enroll": body["code"], "project": self.PROJECT_ID})
        self.assertTrue(body["qr_svg"].startswith("<svg"))
        self.assertEqual(body["max_uses"], 3)
        self.assertIsNone(db.session.scalar(sa.select(AuthDeviceEnrolmentCode).where(
            AuthDeviceEnrolmentCode.code_hash == body["code"])))

        bad = self.client.post(url, json={"max_uses": 0}, headers=self._csrf_headers())
        self.assertEqual(bad.status_code, 400)

    def test_device_public_url_rules(self):
        problem = devices.device_public_url_problem
        self.assertIsNone(problem("https://digitva.example.org", allow_insecure=False))
        self.assertIsNone(problem("http://10.0.2.2:8051", allow_insecure=False))
        self.assertIsNone(problem("http://localhost:8051", allow_insecure=False))
        self.assertIsNotNone(problem("http://digitva.example.org", allow_insecure=False))
        self.assertIsNone(problem("http://digitva.example.org", allow_insecure=True))
        self.assertIsNotNone(problem("", allow_insecure=True))
        self.assertIsNotNone(problem("ftp://x", allow_insecure=True))

    def test_an_http_device_url_refuses_enrolment_codes_outside_development(self):
        url = f"/admin/api/projects/{self.PROJECT_ID}/device-enrolments"
        self._login(str(self.base_admin_id))
        with mock.patch.dict(self.app.config, {"DEVICE_PUBLIC_URL": "http://digitva.example.org"}), \
                mock.patch.object(devices, "_insecure_device_url_allowed", return_value=False):
            refused = self.client.post(url, json={}, headers=self._csrf_headers())
        self.assertEqual(refused.status_code, 503)
        self.assertNotIn("code", refused.get_json())
        with mock.patch.dict(self.app.config, {"DEVICE_PUBLIC_URL": "https://digitva.example.org"}), \
                mock.patch.object(devices, "_insecure_device_url_allowed", return_value=False):
            self.assertEqual(self.client.post(url, json={}, headers=self._csrf_headers()).status_code, 201)

    def test_admin_revoke_kills_every_session_on_the_device(self):
        device, tokens = self._session()
        self.assertEqual(self.client.get(f"{API}/bootstrap", headers=self._bearer(tokens)).status_code, 200)
        self._login(str(self.base_admin_id))
        listed = self.client.get(f"/admin/api/projects/{self.PROJECT_ID}/devices").get_json()["devices"]
        self.assertEqual(listed[0]["device_id"], device["device_id"])
        self.assertEqual(listed[0]["sessions"][0]["user_name"], self.interviewer.name)
        self.assertNotIn("secret_hash", json.dumps(listed))

        self.assertEqual(self.client.post(f"/admin/api/devices/{device['device_id']}/revoke").status_code, 400)
        revoked = self.client.post(f"/admin/api/devices/{device['device_id']}/revoke", headers=self._csrf_headers())
        self.assertEqual(revoked.get_json()["sessions_ended"], 1)
        self.client.delete_cookie("session")
        self.assertEqual(self.client.get(f"{API}/bootstrap", headers=self._bearer(tokens)).status_code, 401)
        self.assertEqual(self._refresh(tokens["refresh_token"]).get_json()["code"], "session_revoked")

    # ── logs ───────────────────────────────────────────────────────────────

    def test_no_credential_reaches_the_logs(self):
        with self.assertLogs(level=logging.DEBUG) as captured:
            logging.getLogger("app").info("device test marker")
            code = self._code()
            device = self._enrol(code)
            _device, tokens = self._session(device)
            refreshed = self._refresh(tokens["refresh_token"]).get_json()
            self._sign_in(device, password="wrong-password")
            self._upload(refreshed)
        text = "\n".join(captured.output)
        self.assertIn("device test marker", text)
        self.assertIn(device["device_id"], text)
        for secret in (code, device["device_secret"], tokens["access_token"], tokens["refresh_token"],
                       refreshed["access_token"], refreshed["refresh_token"], PASSWORD, "wrong-password",
                       "device.interviewer@test.local", "Bina"):
            self.assertNotIn(secret, text)
