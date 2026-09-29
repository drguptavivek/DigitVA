"""Device API for the Android collection app (Path B, bead digitva-kmk.1).

Contract: .tasks/2026-09-30-android-collection-app.md ("API contract").
Covers enrolment, sign-in (password, second factor, grant, revoked device,
rate limit), refresh rotation and reuse, grant withdrawal, bearer scoping
(never outside /api/v1/device, never a cookie inside it), bootstrap scope,
idempotent upload, scope refusals, superseded copies, the outstanding-work
report, the admin endpoints (admin only, CSRF) and that no credential
reaches the logs.
"""
import hashlib
import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta

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
        return device, response.get_json()

    @staticmethod
    def _bearer(tokens):
        return {"Authorization": f"Bearer {tokens['access_token']}"}

    def _refresh(self, refresh_token, **extra):
        return self.client.post(f"{API}/sessions/refresh", json={"refresh_token": refresh_token, **extra})

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

    def test_reusing_a_rotated_refresh_token_revokes_the_session(self):
        _device, tokens = self._session()
        new = self._refresh(tokens["refresh_token"]).get_json()
        reused = self._refresh(tokens["refresh_token"])
        self.assertEqual((reused.status_code, reused.get_json()["code"]), (401, "session_revoked"))
        # The whole session is gone: the attacker's or the owner's newer tokens too.
        self.assertEqual(self._refresh(new["refresh_token"]).get_json()["code"], "session_revoked")
        self.assertEqual(self.client.get(f"{API}/bootstrap", headers=self._bearer(new)).status_code, 401)

    def test_an_unknown_refresh_token_revokes_nothing(self):
        response = self._refresh("never-issued")
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

    def test_a_password_or_factor_reset_ends_device_sessions(self):
        _device, tokens = self._session(email="device.teammate@test.local")
        self.teammate.bump_session_version()
        db.session.commit()
        self.assertEqual(self.client.get(f"{API}/bootstrap", headers=self._bearer(tokens)).status_code, 401)
        response = self._refresh(tokens["refresh_token"])
        self.assertEqual(response.get_json()["code"], "session_revoked")
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
