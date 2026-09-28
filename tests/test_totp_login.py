"""TOTP enrolment/verification, recovery codes, and the second-factor login
step -- digitva-sn1.1.5. Baseline: docs/policy/authentication-factors.md
sections 3, 4, 6, 7, 9.
"""

import base64
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import pyotp
import sqlalchemy as sa

from app import db, limiter
from app.models import (
    AuthRecoveryCode,
    AuthSecurityEvent,
    AuthTotp,
    AuthWebauthnCredential,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services import totp_service
from tests.base import BaseTestCase

PASSWORD = "TotpLogin123!"


class TotpTestBase(BaseTestCase):
    def setUp(self):
        super().setUp()
        limiter.reset()
        self.user = self._make_user(f"totp.{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
        db.session.commit()

    def _grant_admin(self, user):
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=VaAccessRoles.admin,
            scope_type=VaAccessScopeTypes.global_scope,
            notes="test admin grant",
            grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def _grant_data_manager(self, user):
        db.session.add(VaUserAccessGrants(
            user_id=user.user_id,
            role=VaAccessRoles.data_manager,
            scope_type=VaAccessScopeTypes.project,
            project_id=self.BASE_PROJECT_ID,
            notes="test data manager grant",
            grant_status=VaStatuses.active,
        ))
        db.session.commit()

    def _enroll_totp(self, user):
        """Enrol and confirm TOTP for ``user`` directly through the service
        (not the API), returning the raw secret. Resets the replay-protection
        step afterwards so tests can drive verify()/login independently of
        the exact time step confirm_enrolment happened to consume."""
        result = totp_service.begin_enrolment(user)
        code = pyotp.TOTP(result["secret"]).now()
        self.assertTrue(totp_service.confirm_enrolment(user, code))
        db.session.execute(
            sa.update(AuthTotp).where(AuthTotp.user_id == user.user_id).values(last_used_step=None)
        )
        db.session.commit()
        return result["secret"]

    def _set_auth_verified_recently(self, *, minutes_ago=0):
        with self.client.session_transaction() as sess:
            sess["auth_verified_at"] = (
                datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
            ).isoformat()

    def _add_credential(self, user):
        cred = AuthWebauthnCredential(
            user_id=user.user_id,
            credential_id=uuid.uuid4().bytes,
            public_key=b"fake-public-key",
            sign_count=0,
            name="Test key",
        )
        db.session.add(cred)
        db.session.commit()
        return cred


# ---------------------------------------------------------------------------
# Service: enrolment, verification, replay protection, encryption
# ---------------------------------------------------------------------------

class TotpServiceTests(TotpTestBase):
    def test_enrol_and_confirm_with_valid_code(self):
        result = totp_service.begin_enrolment(self.user)
        self.assertIn("secret", result)
        self.assertIn("provisioning_uri", result)
        code = pyotp.TOTP(result["secret"]).now()
        self.assertTrue(totp_service.confirm_enrolment(self.user, code))
        db.session.commit()
        self.assertTrue(totp_service.has_confirmed_totp(self.user.user_id))

    def test_wrong_code_rejected(self):
        totp_service.begin_enrolment(self.user)
        self.assertFalse(totp_service.confirm_enrolment(self.user, "000000"))

    def test_secret_stored_encrypted(self):
        result = totp_service.begin_enrolment(self.user)
        row = db.session.get(AuthTotp, self.user.user_id)
        self.assertNotEqual(row.secret_encrypted, result["secret"])
        decrypted = totp_service._decrypt(row.secret_encrypted, self.user.user_id)
        self.assertEqual(decrypted, result["secret"])

    def test_secret_stored_as_v2_aes_gcm(self):
        result = totp_service.begin_enrolment(self.user)
        row = db.session.get(AuthTotp, self.user.user_id)
        self.assertTrue(row.secret_encrypted.startswith("v2:"))
        self.assertNotIn(result["secret"], row.secret_encrypted)

    def test_encrypt_decrypt_round_trip(self):
        secret = pyotp.random_base32()
        encrypted = totp_service._encrypt(secret, self.user.user_id)
        self.assertEqual(totp_service._decrypt(encrypted, self.user.user_id), secret)

    def test_two_encryptions_of_same_secret_differ(self):
        secret = pyotp.random_base32()
        first = totp_service._encrypt(secret, self.user.user_id)
        second = totp_service._encrypt(secret, self.user.user_id)
        self.assertNotEqual(first, second)

    def test_decrypt_fails_for_a_different_user(self):
        secret = pyotp.random_base32()
        encrypted = totp_service._encrypt(secret, self.user.user_id)
        other_user = self._make_user(f"totp.other.{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
        db.session.commit()
        with self.assertRaises(ValueError):
            totp_service._decrypt(encrypted, other_user.user_id)

    def test_decrypt_fails_for_tampered_ciphertext(self):
        secret = pyotp.random_base32()
        encrypted = totp_service._encrypt(secret, self.user.user_id)
        raw = bytearray(base64.urlsafe_b64decode(encrypted[len("v2:"):]))
        raw[-1] ^= 0xFF  # flip a bit inside the GCM tag
        tampered = "v2:" + base64.urlsafe_b64encode(bytes(raw)).decode("ascii")
        with self.assertRaises(ValueError):
            totp_service._decrypt(tampered, self.user.user_id)

    def test_legacy_fernet_secret_decrypts_and_upgrades_on_success(self):
        secret = pyotp.random_base32()
        legacy = totp_service._fernet().encrypt(secret.encode("utf-8")).decode("utf-8")
        self.assertFalse(legacy.startswith("v2:"))
        db.session.add(AuthTotp(user_id=self.user.user_id, secret_encrypted=legacy))
        db.session.commit()

        self.assertEqual(totp_service._decrypt(legacy, self.user.user_id), secret)

        code = pyotp.TOTP(secret).now()
        self.assertTrue(totp_service.confirm_enrolment(self.user, code))
        db.session.commit()
        row = db.session.get(AuthTotp, self.user.user_id)
        self.assertTrue(row.secret_encrypted.startswith("v2:"))
        self.assertEqual(totp_service._decrypt(row.secret_encrypted, self.user.user_id), secret)

    def test_legacy_fernet_secret_not_upgraded_on_failed_code(self):
        secret = pyotp.random_base32()
        legacy = totp_service._fernet().encrypt(secret.encode("utf-8")).decode("utf-8")
        db.session.add(AuthTotp(user_id=self.user.user_id, secret_encrypted=legacy))
        db.session.commit()

        self.assertFalse(totp_service.confirm_enrolment(self.user, "000000"))
        row = db.session.get(AuthTotp, self.user.user_id)
        self.assertEqual(row.secret_encrypted, legacy)

    def _add_legacy_confirmed_totp(self, secret):
        legacy = totp_service._fernet().encrypt(secret.encode("utf-8")).decode("utf-8")
        db.session.add(AuthTotp(
            user_id=self.user.user_id,
            secret_encrypted=legacy,
            confirmed_at=datetime.now(timezone.utc),
        ))
        db.session.commit()
        return legacy

    def test_legacy_fernet_secret_upgraded_on_successful_verify(self):
        secret = pyotp.random_base32()
        self._add_legacy_confirmed_totp(secret)
        now = time.time()
        code = pyotp.TOTP(secret).at(now)

        self.assertTrue(totp_service.verify(self.user, code, for_time=now))
        db.session.commit()
        row = db.session.get(AuthTotp, self.user.user_id)
        self.assertTrue(row.secret_encrypted.startswith("v2:"))
        self.assertEqual(totp_service._decrypt(row.secret_encrypted, self.user.user_id), secret)

        # The rewritten value still verifies through the live path.
        next_code = pyotp.TOTP(secret).at(now + 30)
        self.assertTrue(totp_service.verify(self.user, next_code, for_time=now + 30))
        db.session.commit()

    def test_legacy_fernet_secret_not_upgraded_on_failed_verify(self):
        secret = pyotp.random_base32()
        legacy = self._add_legacy_confirmed_totp(secret)

        self.assertFalse(totp_service.verify(self.user, "000000", for_time=time.time()))
        row = db.session.get(AuthTotp, self.user.user_id)
        self.assertEqual(row.secret_encrypted, legacy)

    def test_replay_of_same_code_rejected(self):
        secret = self._enroll_totp(self.user)
        now = time.time()
        code = pyotp.TOTP(secret).at(now)
        self.assertTrue(totp_service.verify(self.user, code, for_time=now))
        db.session.commit()
        # Same code, same step: refused even though it is still time-valid.
        self.assertFalse(totp_service.verify(self.user, code, for_time=now))

    def test_drift_within_one_step_accepted(self):
        secret = self._enroll_totp(self.user)
        now = time.time()
        earlier_code = pyotp.TOTP(secret).at(now - 30)
        self.assertTrue(totp_service.verify(self.user, earlier_code, for_time=now))
        db.session.commit()

    def test_drift_beyond_one_step_rejected(self):
        secret = self._enroll_totp(self.user)
        now = time.time()
        too_old_code = pyotp.TOTP(secret).at(now - 60)
        self.assertFalse(totp_service.verify(self.user, too_old_code, for_time=now))

    def test_recovery_code_single_use(self):
        codes = totp_service.generate_recovery_codes(self.user)
        db.session.commit()
        code = codes[0]
        self.assertTrue(totp_service.verify_recovery_code(self.user, code))
        db.session.commit()
        self.assertFalse(totp_service.verify_recovery_code(self.user, code))

    def test_recovery_code_normalises_case_and_separators(self):
        codes = totp_service.generate_recovery_codes(self.user)
        db.session.commit()
        mangled = codes[0].lower().replace("-", " ")
        self.assertTrue(totp_service.verify_recovery_code(self.user, mangled))

    def test_regenerate_voids_old_codes(self):
        old_codes = totp_service.generate_recovery_codes(self.user)
        db.session.commit()
        new_codes = totp_service.generate_recovery_codes(self.user)
        db.session.commit()
        self.assertFalse(totp_service.verify_recovery_code(self.user, old_codes[0]))
        self.assertTrue(totp_service.verify_recovery_code(self.user, new_codes[0]))


# ---------------------------------------------------------------------------
# Who needs a second factor (policy section 3)
# ---------------------------------------------------------------------------

class NeedsSecondFactorTests(TotpTestBase):
    def test_coder_without_totp_does_not_need_second_factor(self):
        self.assertFalse(totp_service.needs_second_factor(self.user))

    def test_coder_with_totp_needs_second_factor(self):
        self._enroll_totp(self.user)
        self.assertTrue(totp_service.needs_second_factor(self.user))

    def test_admin_without_any_factor_does_not_need_second_factor(self):
        self._grant_admin(self.user)
        self.assertFalse(totp_service.needs_second_factor(self.user))

    def test_admin_with_passkey_needs_second_factor(self):
        self._grant_admin(self.user)
        self._add_credential(self.user)
        self.assertTrue(totp_service.needs_second_factor(self.user))

    def test_data_manager_with_totp_needs_second_factor(self):
        self._grant_data_manager(self.user)
        self._enroll_totp(self.user)
        self.assertTrue(totp_service.needs_second_factor(self.user))


# ---------------------------------------------------------------------------
# Login: the second-factor step
# ---------------------------------------------------------------------------

class SecondFactorLoginTests(TotpTestBase):
    def test_coder_without_totp_signs_in_with_password_alone(self):
        resp = self._login_via_form(self.user.email, PASSWORD)
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("/second-factor", resp.headers["Location"])
        with self.client.session_transaction() as sess:
            self.assertIn("_user_id", sess)

    def test_coder_with_totp_is_sent_to_second_factor_page(self):
        secret = self._enroll_totp(self.user)
        resp = self._login_via_form(self.user.email, PASSWORD)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/second-factor", resp.headers["Location"])
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)

        code = pyotp.TOTP(secret).now()
        resp = self.client.post(
            resp.headers["Location"],
            data={"code": code},
            headers=self._csrf_headers(),
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302, resp.data)
        with self.client.session_transaction() as sess:
            self.assertIn("_user_id", sess)

    def test_admin_without_any_factor_signs_in_with_password_alone(self):
        self._grant_admin(self.user)
        resp = self._login_via_form(self.user.email, PASSWORD)
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("/second-factor", resp.headers["Location"])

    def test_admin_with_passkey_only_uses_recovery_code(self):
        self._grant_admin(self.user)
        self._add_credential(self.user)
        codes = totp_service.generate_recovery_codes(self.user)
        db.session.commit()

        resp = self._login_via_form(self.user.email, PASSWORD)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/second-factor", resp.headers["Location"])

        second_factor_url = resp.headers["Location"]
        page = self.client.get(second_factor_url)
        self.assertIn(b"Enter one of your unused recovery codes.", page.data)

        resp = self.client.post(
            second_factor_url,
            data={"code": codes[0]},
            headers=self._csrf_headers(),
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302, resp.data)
        with self.client.session_transaction() as sess:
            self.assertIn("_user_id", sess)
        # Single use.
        self.assertFalse(totp_service.verify_recovery_code(self.user, codes[0]))

    def test_wrong_second_factor_code_rejected(self):
        self._enroll_totp(self.user)
        resp = self._login_via_form(self.user.email, PASSWORD)
        resp = self.client.post(
            resp.headers["Location"],
            data={"code": "000000"},
            headers=self._csrf_headers(),
            follow_redirects=True,
        )
        self.assertIn(b"Invalid code", resp.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)

    def test_five_failures_lockout_sends_to_email_step(self):
        self._enroll_totp(self.user)
        resp = self._login_via_form(self.user.email, PASSWORD)
        second_factor_url = resp.headers["Location"]

        for _ in range(4):
            resp = self.client.post(
                second_factor_url,
                data={"code": "000000"},
                headers=self._csrf_headers(),
                follow_redirects=False,
            )
            self.assertEqual(resp.status_code, 302)
            self.assertIn("/second-factor", resp.headers["Location"])

        # Fifth failure: locked out, back to the email step.
        resp = self.client.post(
            second_factor_url,
            data={"code": "000000"},
            headers=self._csrf_headers(),
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302)
        self.assertNotIn("/second-factor", resp.headers["Location"])
        self.assertIn("/valogin", resp.headers["Location"])

        event = db.session.scalar(
            sa.select(AuthSecurityEvent).where(
                AuthSecurityEvent.event_type == "second_factor_lockout",
                AuthSecurityEvent.user_id == self.user.user_id,
            )
        )
        self.assertIsNotNone(event)

        # Pre-auth state is gone: the second-factor page redirects to the
        # email step again.
        resp = self.client.get(second_factor_url, follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/valogin", resp.headers["Location"])
        self.assertNotIn("/second-factor", resp.headers["Location"])

    def test_second_factor_page_unreachable_without_verified_password(self):
        self._enroll_totp(self.user)
        resp = self.client.get("/vaauth/valogin/second-factor", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/vaauth/valogin", resp.headers["Location"])
        self.assertNotIn("/second-factor", resp.headers["Location"])

    def test_second_factor_page_unreachable_after_only_email_step(self):
        self._enroll_totp(self.user)
        self._solve_email_step_only()
        resp = self.client.get("/vaauth/valogin/second-factor", follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/vaauth/valogin", resp.headers["Location"])
        self.assertNotIn("/second-factor", resp.headers["Location"])

    def _solve_email_step_only(self):
        from app.services.pow_captcha_service import issue_challenge

        with self.app.app_context():
            challenge = issue_challenge()
        solution = self._solve_pow_captcha(challenge["salt"], challenge["difficulty"])
        self.client.post(
            "/vaauth/valogin",
            data={
                "email": self.user.email,
                "captcha_salt": challenge["salt"],
                "captcha_difficulty": challenge["difficulty"],
                "captcha_expires": challenge["expires"],
                "captcha_signature": challenge["signature"],
                "captcha_solution": solution,
            },
            headers=self._csrf_headers(),
            follow_redirects=False,
        )

    def test_unknown_email_at_password_step_unchanged(self):
        unknown_email = f"nobody.{uuid.uuid4().hex[:8]}@example.com"
        resp = self._login_via_form(unknown_email, "whatever-password")
        self.assertEqual(resp.status_code, 302)
        resp = self.client.get(resp.headers["Location"], follow_redirects=True)
        self.assertIn(b"Invalid email or password", resp.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)


# ---------------------------------------------------------------------------
# Profile API: TOTP and recovery codes
# ---------------------------------------------------------------------------

class TotpProfileApiTests(TotpTestBase):
    def setUp(self):
        super().setUp()
        self._login(str(self.user.user_id))
        self._set_auth_verified_recently()

    def _enroll_via_api(self):
        resp = self.client.post("/api/v1/profile/totp/enroll", headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 200, resp.data)
        return resp.get_json()

    def _confirm_via_api(self, code):
        return self.client.post(
            "/api/v1/profile/totp/confirm",
            data=json.dumps({"code": code}),
            content_type="application/json",
            headers=self._csrf_headers(),
        )

    def test_enroll_returns_secret_and_qr(self):
        data = self._enroll_via_api()
        self.assertIn("secret", data)
        self.assertIn("qr_svg", data)
        self.assertIn("<svg", data["qr_svg"])

    def test_confirm_with_valid_code_enables_totp(self):
        data = self._enroll_via_api()
        code = pyotp.TOTP(data["secret"]).now()
        resp = self._confirm_via_api(code)
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertTrue(totp_service.has_confirmed_totp(self.user.user_id))
        event = db.session.scalar(
            sa.select(AuthSecurityEvent).where(
                AuthSecurityEvent.event_type == "totp_enrolled",
                AuthSecurityEvent.user_id == self.user.user_id,
            )
        )
        self.assertIsNotNone(event)

    def test_confirm_with_wrong_code_rejected(self):
        self._enroll_via_api()
        resp = self._confirm_via_api("000000")
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(totp_service.has_confirmed_totp(self.user.user_id))

    def test_recovery_codes_issued_once_totp_first_no_passkey(self):
        data = self._enroll_via_api()
        code = pyotp.TOTP(data["secret"]).now()
        resp = self._confirm_via_api(code)
        body = resp.get_json()
        self.assertEqual(len(body["recovery_codes"]), 10)

        # Removing and re-enrolling does not reissue -- codes exist already.
        remove_resp = self.client.delete("/api/v1/profile/totp", headers=self._csrf_headers())
        self.assertEqual(remove_resp.status_code, 200, remove_resp.data)
        data2 = self._enroll_via_api()
        code2 = pyotp.TOTP(data2["secret"]).now()
        resp2 = self._confirm_via_api(code2)
        self.assertNotIn("recovery_codes", resp2.get_json())

    def test_recovery_codes_issued_once_passkey_first_no_totp(self):
        from tests.webauthn_test_utils import build_registration_credential, new_keypair, b64url_decode

        priv = new_keypair()
        options_resp = self.client.post(
            "/api/v1/profile/passkeys/options", headers=self._csrf_headers()
        )
        options = options_resp.get_json()
        challenge = b64url_decode(options["challenge"])
        credential_id = uuid.uuid4().bytes
        credential = build_registration_credential(
            rp_id=self.app.config["WEBAUTHN_RP_ID"],
            origin=self.app.config["WEBAUTHN_ORIGIN"],
            challenge=challenge,
            credential_id=credential_id,
            priv=priv,
        )
        resp = self.client.post(
            "/api/v1/profile/passkeys",
            data=json.dumps({"credential": credential, "name": "First key"}),
            content_type="application/json",
            headers=self._csrf_headers(),
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json()
        self.assertEqual(len(body["recovery_codes"]), 10)

    def test_reauth_required_for_enroll(self):
        self._set_auth_verified_recently(minutes_ago=11)
        resp = self.client.post("/api/v1/profile/totp/enroll", headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 401)

    def test_reauth_required_for_remove(self):
        self._enroll_totp(self.user)
        self._set_auth_verified_recently(minutes_ago=11)
        resp = self.client.delete("/api/v1/profile/totp", headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 401)

    def test_reauth_required_for_recovery_regenerate(self):
        self._set_auth_verified_recently(minutes_ago=11)
        resp = self.client.post(
            "/api/v1/profile/recovery-codes/regenerate", headers=self._csrf_headers()
        )
        self.assertEqual(resp.status_code, 401)

    def test_csrf_missing_rejected(self):
        resp = self.client.post("/api/v1/profile/totp/enroll")
        self.assertEqual(resp.status_code, 400)

    def test_remove_totp(self):
        self._enroll_totp(self.user)
        resp = self.client.delete("/api/v1/profile/totp", headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertFalse(totp_service.has_confirmed_totp(self.user.user_id))
        event = db.session.scalar(
            sa.select(AuthSecurityEvent).where(
                AuthSecurityEvent.event_type == "totp_removed",
                AuthSecurityEvent.user_id == self.user.user_id,
            )
        )
        self.assertIsNotNone(event)

    def test_regenerate_recovery_codes(self):
        old_codes = totp_service.generate_recovery_codes(self.user)
        db.session.commit()
        resp = self.client.post(
            "/api/v1/profile/recovery-codes/regenerate", headers=self._csrf_headers()
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        new_codes = resp.get_json()["recovery_codes"]
        self.assertEqual(len(new_codes), 10)
        self.assertFalse(totp_service.verify_recovery_code(self.user, old_codes[0]))


# ---------------------------------------------------------------------------
# Last-factor removal guard (enforcement window, section 7)
# ---------------------------------------------------------------------------

class LastFactorRemovalGuardTests(TotpTestBase):
    def setUp(self):
        super().setUp()
        self._grant_admin(self.user)
        self._login(str(self.user.user_id))
        self._set_auth_verified_recently()

    def _with_enforcement_in_past(self):
        self.app.config["AUTH_FACTOR_ENFORCE_FROM"] = "2020-01-01"
        self.addCleanup(lambda: self.app.config.__setitem__("AUTH_FACTOR_ENFORCE_FROM", ""))

    def test_guard_off_without_enforce_from(self):
        self._enroll_totp(self.user)
        resp = self.client.delete("/api/v1/profile/totp", headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_guard_blocks_removing_last_factor_once_enforced(self):
        self._with_enforcement_in_past()
        self._enroll_totp(self.user)
        resp = self.client.delete("/api/v1/profile/totp", headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertTrue(totp_service.has_confirmed_totp(self.user.user_id))

    def test_guard_allows_removal_when_another_factor_remains(self):
        self._with_enforcement_in_past()
        self._enroll_totp(self.user)
        self._add_credential(self.user)
        resp = self.client.delete("/api/v1/profile/totp", headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_guard_blocks_revoking_last_passkey_once_enforced(self):
        self._with_enforcement_in_past()
        cred = self._add_credential(self.user)
        resp = self.client.delete(
            f"/api/v1/profile/passkeys/{cred.id}", headers=self._csrf_headers()
        )
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertIsNotNone(db.session.get(AuthWebauthnCredential, cred.id))
