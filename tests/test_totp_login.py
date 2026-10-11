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



class RetiredSecondFactorFlowTests(TotpTestBase):
    def test_password_login_ignores_historical_totp_record(self):
        self._enroll_totp(self.user)
        response = self._login_via_form(self.user.email, PASSWORD)
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("second-factor", response.headers["Location"])
        with self.client.session_transaction() as sess:
            self.assertIn("_user_id", sess)
