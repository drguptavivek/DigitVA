"""Passkey (WebAuthn) sign-in and Profile passkey management --
digitva-sn1.1.4. Baseline: docs/policy/authentication-factors.md sections
1, 2, 7, 9.

Registration and assertion payloads are built for real in
tests/webauthn_test_utils.py (EC P-256, "none" attestation) so
app/services/webauthn_service.py's calls into py_webauthn's own
verify_registration_response/verify_authentication_response run their
actual cryptographic checks -- nothing about verification is mocked here.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app import db, limiter
from app.models import AuthSecurityEvent, AuthWebauthnCredential
from tests.base import BaseTestCase
from tests.webauthn_test_utils import (
    b64url_decode,
    build_authentication_credential,
    build_registration_credential,
    cose_public_key,
    new_keypair,
)

PASSWORD = "PasskeyLogin123!"


class PasskeyTestBase(BaseTestCase):
    def setUp(self):
        super().setUp()
        limiter.reset()
        self.user = self._make_user(
            f"passkey.{uuid.uuid4().hex[:8]}@example.com", PASSWORD
        )
        db.session.commit()

    # -- shared helpers ---------------------------------------------------

    def _rp_id(self):
        return self.app.config["WEBAUTHN_RP_ID"]

    def _origin(self):
        return self.app.config["WEBAUTHN_ORIGIN"]

    def _add_credential(self, user, *, priv=None, sign_count=0, name="Test key"):
        priv = priv or new_keypair()
        credential_id = uuid.uuid4().bytes
        cred = AuthWebauthnCredential(
            user_id=user.user_id,
            credential_id=credential_id,
            public_key=cose_public_key(priv),
            sign_count=sign_count,
            name=name,
        )
        db.session.add(cred)
        db.session.commit()
        return cred, priv

    def _start_preauth(self, email):
        """Drive the CAPTCHA-gated email step only, leaving the pre-auth
        session state set but not signed in -- mirrors
        tests.base.BaseTestCase._login_via_form's first half."""
        from app.services.pow_captcha_service import issue_challenge

        with self.app.app_context():
            challenge = issue_challenge()
        solution = self._solve_pow_captcha(challenge["salt"], challenge["difficulty"])
        resp = self.client.post(
            "/vaauth/valogin",
            data={
                "email": email,
                "captcha_salt": challenge["salt"],
                "captcha_difficulty": challenge["difficulty"],
                "captcha_expires": challenge["expires"],
                "captcha_signature": challenge["signature"],
                "captcha_solution": solution,
            },
            headers=self._csrf_headers(),
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 302, resp.data)
        return resp

    def _passkey_options(self):
        resp = self.client.post(
            "/vaauth/valogin/passkey/options", headers=self._csrf_headers()
        )
        return resp

    def _passkey_verify(self, credential):
        return self.client.post(
            "/vaauth/valogin/passkey/verify",
            data=json.dumps({"credential": credential}),
            content_type="application/json",
            headers=self._csrf_headers(),
        )

    def _sign_in_with_credential(self, email, credential_id, priv, *, sign_count, uv=True):
        self._start_preauth(email)
        options = self._passkey_options().get_json()
        challenge = b64url_decode(options["challenge"])
        credential = build_authentication_credential(
            rp_id=self._rp_id(),
            origin=self._origin(),
            challenge=challenge,
            credential_id=credential_id,
            priv=priv,
            sign_count=sign_count,
            uv=uv,
        )
        return self._passkey_verify(credential)

    def _set_auth_verified_recently(self, *, minutes_ago=0):
        with self.client.session_transaction() as sess:
            sess["auth_verified_at"] = (
                datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
            ).isoformat()


# ---------------------------------------------------------------------------
# Sign-in
# ---------------------------------------------------------------------------

class PasskeySignInTests(PasskeyTestBase):
    def test_options_identical_for_known_and_unknown_email(self):
        self._start_preauth(self.user.email)
        known = self._passkey_options().get_json()
        limiter.reset()
        self._start_preauth(f"nobody.{uuid.uuid4().hex[:8]}@example.com")
        unknown = self._passkey_options().get_json()

        known.pop("challenge")
        unknown.pop("challenge")
        self.assertEqual(known, unknown)
        self.assertEqual(known.get("allowCredentials"), [])

    def test_sign_in_success_sets_session_and_rotates_session_id(self):
        cred, priv = self._add_credential(self.user)
        cookie_before = self.client.get_cookie(
            self.app.config.get("SESSION_COOKIE_NAME", "session")
        )
        resp = self._sign_in_with_credential(
            self.user.email, cred.credential_id, priv, sign_count=1
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        body = resp.get_json()
        self.assertIn("redirect", body)
        with self.client.session_transaction() as sess:
            # auth_session_version is 0 for a fresh user -- VaUsers.get_id()
            # then returns the bare user_id (see app/models/va_users.py).
            self.assertEqual(sess.get("_user_id"), self.user.get_id())
            self.assertIn("auth_verified_at", sess)
        cookie_after = self.client.get_cookie(
            self.app.config.get("SESSION_COOKIE_NAME", "session")
        )
        if cookie_before is not None and cookie_after is not None:
            self.assertNotEqual(cookie_before.value, cookie_after.value)

    def test_uv_flag_missing_rejected(self):
        cred, priv = self._add_credential(self.user)
        resp = self._sign_in_with_credential(
            self.user.email, cred.credential_id, priv, sign_count=1, uv=False
        )
        self.assertEqual(resp.status_code, 400)
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)

    def test_wrong_origin_rejected(self):
        cred, priv = self._add_credential(self.user)
        self._start_preauth(self.user.email)
        options = self._passkey_options().get_json()
        challenge = b64url_decode(options["challenge"])
        credential = build_authentication_credential(
            rp_id=self._rp_id(),
            origin="https://attacker.example",
            challenge=challenge,
            credential_id=cred.credential_id,
            priv=priv,
            sign_count=1,
        )
        resp = self._passkey_verify(credential)
        self.assertEqual(resp.status_code, 400)

    def test_wrong_rp_id_hash_rejected(self):
        cred, priv = self._add_credential(self.user)
        self._start_preauth(self.user.email)
        options = self._passkey_options().get_json()
        challenge = b64url_decode(options["challenge"])
        credential = build_authentication_credential(
            rp_id="not-" + self._rp_id(),
            origin=self._origin(),
            challenge=challenge,
            credential_id=cred.credential_id,
            priv=priv,
            sign_count=1,
        )
        resp = self._passkey_verify(credential)
        self.assertEqual(resp.status_code, 400)

    def test_challenge_replay_rejected(self):
        cred, priv = self._add_credential(self.user)
        self._start_preauth(self.user.email)
        options = self._passkey_options().get_json()
        challenge = b64url_decode(options["challenge"])
        credential = build_authentication_credential(
            rp_id=self._rp_id(),
            origin=self._origin(),
            challenge=challenge,
            credential_id=cred.credential_id,
            priv=priv,
            sign_count=1,
        )
        first = self._passkey_verify(credential)
        self.assertEqual(first.status_code, 200, first.data)

        # Re-establish a signed-out session at the same email, but do NOT
        # fetch new options -- there is no outstanding challenge left, so
        # replaying the same signed assertion must fail.
        self.client.post("/vaauth/valogout", headers=self._csrf_headers())
        self._start_preauth(self.user.email)
        second = self._passkey_verify(credential)
        self.assertEqual(second.status_code, 400)

    def test_expired_challenge_rejected(self):
        cred, priv = self._add_credential(self.user)
        self._start_preauth(self.user.email)
        options = self._passkey_options().get_json()
        challenge = b64url_decode(options["challenge"])
        with self.client.session_transaction() as sess:
            state = dict(sess["webauthn_authentication"])
            state["issued_at"] = (
                datetime.now(timezone.utc) - timedelta(minutes=6)
            ).isoformat()
            sess["webauthn_authentication"] = state
        credential = build_authentication_credential(
            rp_id=self._rp_id(),
            origin=self._origin(),
            challenge=challenge,
            credential_id=cred.credential_id,
            priv=priv,
            sign_count=1,
        )
        resp = self._passkey_verify(credential)
        self.assertEqual(resp.status_code, 400)

    def test_credential_of_another_user_rejected(self):
        other = self._make_user(f"other.{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
        db.session.commit()
        cred, priv = self._add_credential(other)
        resp = self._sign_in_with_credential(
            self.user.email, cred.credential_id, priv, sign_count=1
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn(b"Invalid email or password", resp.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)

    def test_unknown_email_preauth_with_valid_credential_of_someone_else_rejected(self):
        cred, priv = self._add_credential(self.user)
        unknown_email = f"nobody.{uuid.uuid4().hex[:8]}@example.com"
        resp = self._sign_in_with_credential(
            unknown_email, cred.credential_id, priv, sign_count=1
        )
        self.assertEqual(resp.status_code, 400)
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)

    def test_counter_zero_zero_accepted(self):
        cred, priv = self._add_credential(self.user, sign_count=0)
        resp = self._sign_in_with_credential(
            self.user.email, cred.credential_id, priv, sign_count=0
        )
        self.assertEqual(resp.status_code, 200, resp.data)

    def test_counter_zero_assertion_replay_rejected_after_challenge_copy(self):
        """A copied request-local session cannot replay a zero-counter assertion."""
        cred, priv = self._add_credential(self.user, sign_count=0)
        self._start_preauth(self.user.email)
        options = self._passkey_options().get_json()
        challenge = b64url_decode(options["challenge"])
        with self.client.session_transaction() as sess:
            original_state = dict(sess["webauthn_authentication"])
        credential = build_authentication_credential(
            rp_id=self._rp_id(),
            origin=self._origin(),
            challenge=challenge,
            credential_id=cred.credential_id,
            priv=priv,
            sign_count=0,
        )

        first = self._passkey_verify(credential)
        self.assertEqual(first.status_code, 200, first.data)

        # Restore the exact challenge as a second worker would receive from a
        # concurrent request's already-decoded session copy.
        self.client.post("/vaauth/valogout", headers=self._csrf_headers())
        self._start_preauth(self.user.email)
        with self.client.session_transaction() as sess:
            sess["webauthn_authentication"] = original_state
        second = self._passkey_verify(credential)
        self.assertEqual(second.status_code, 400, second.data)

    def test_counter_zero_concurrent_assertions_only_one_claims_challenge(self):
        """Two workers sharing a session snapshot cannot both verify once."""
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier

        from flask import session

        from app.services import webauthn_service

        with self.app.test_request_context("/"):
            options = webauthn_service.build_authentication_options()
            original_state = dict(session["webauthn_authentication"])
        challenge = b64url_decode(options["challenge"])
        credential_id = uuid.uuid4().bytes
        priv = new_keypair()
        credential = build_authentication_credential(
            rp_id=self._rp_id(),
            origin=self._origin(),
            challenge=challenge,
            credential_id=credential_id,
            priv=priv,
            sign_count=0,
        )
        barrier = Barrier(2)

        def verify_from_copied_session():
            with self.app.test_request_context("/"):
                session["webauthn_authentication"] = dict(original_state)
                barrier.wait(timeout=5)
                try:
                    webauthn_service.verify_authentication(
                        credential,
                        credential_public_key=cose_public_key(priv),
                    )
                except webauthn_service.PasskeyVerificationError:
                    return "rejected"
                return "accepted"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = sorted(pool.map(lambda _: verify_from_copied_session(), (0, 1)))
        self.assertEqual(outcomes, ["accepted", "rejected"])

    def test_challenge_claim_fails_closed_when_cache_unavailable(self):
        from unittest.mock import patch

        from flask import session

        from app import cache
        from app.services import webauthn_service

        with self.app.test_request_context("/"):
            webauthn_service.build_authentication_options()
            with patch.object(cache, "add", side_effect=RuntimeError("redis down")):
                self.assertIsNone(
                    webauthn_service._consume_challenge(
                        webauthn_service.AUTHENTICATION_SESSION_KEY
                    )
                )
            self.assertIn("webauthn_authentication", session)

    def test_counter_regression_rejected_and_audited(self):
        cred, priv = self._add_credential(self.user, sign_count=5)
        events_before = db.session.scalar(
            sa.select(sa.func.count()).select_from(AuthSecurityEvent).where(
                AuthSecurityEvent.event_type == "counter_regression"
            )
        )
        resp = self._sign_in_with_credential(
            self.user.email, cred.credential_id, priv, sign_count=5
        )
        self.assertEqual(resp.status_code, 400)
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)
        events_after = db.session.scalar(
            sa.select(sa.func.count()).select_from(AuthSecurityEvent).where(
                AuthSecurityEvent.event_type == "counter_regression"
            )
        )
        self.assertEqual(events_after, events_before + 1)

    def test_inactive_user_rejected(self):
        from app.models import VaStatuses

        cred, priv = self._add_credential(self.user)
        self.user.user_status = VaStatuses.deactive
        db.session.commit()
        resp = self._sign_in_with_credential(
            self.user.email, cred.credential_id, priv, sign_count=1
        )
        self.assertEqual(resp.status_code, 400)

    def test_unverified_user_rejected(self):
        cred, priv = self._add_credential(self.user)
        self.user.email_verified = False
        db.session.commit()
        resp = self._sign_in_with_credential(
            self.user.email, cred.credential_id, priv, sign_count=1
        )
        self.assertEqual(resp.status_code, 400)

    def test_csrf_missing_rejected(self):
        cred, priv = self._add_credential(self.user)
        self._start_preauth(self.user.email)
        options_resp = self.client.post(
            "/vaauth/valogin/passkey/options", headers=self._csrf_headers()
        )
        options = options_resp.get_json()
        challenge = b64url_decode(options["challenge"])
        credential = build_authentication_credential(
            rp_id=self._rp_id(),
            origin=self._origin(),
            challenge=challenge,
            credential_id=cred.credential_id,
            priv=priv,
            sign_count=1,
        )
        resp = self.client.post(
            "/vaauth/valogin/passkey/verify",
            data=json.dumps({"credential": credential}),
            content_type="application/json",
            # No X-CSRFToken header.
        )
        self.assertEqual(resp.status_code, 400)
        with self.client.session_transaction() as sess:
            self.assertNotIn("_user_id", sess)


# ---------------------------------------------------------------------------
# Registration, rename, revoke (Profile)
# ---------------------------------------------------------------------------

class PasskeyProfileTests(PasskeyTestBase):
    def setUp(self):
        super().setUp()
        self._login(str(self.user.user_id))
        self._set_auth_verified_recently()

    def _register(self, *, name="My laptop", priv=None):
        priv = priv or new_keypair()
        options_resp = self.client.post(
            "/api/v1/profile/passkeys/options", headers=self._csrf_headers()
        )
        self.assertEqual(options_resp.status_code, 200, options_resp.data)
        options = options_resp.get_json()
        challenge = b64url_decode(options["challenge"])
        credential_id = uuid.uuid4().bytes
        credential = build_registration_credential(
            rp_id=self._rp_id(),
            origin=self._origin(),
            challenge=challenge,
            credential_id=credential_id,
            priv=priv,
        )
        resp = self.client.post(
            "/api/v1/profile/passkeys",
            data=json.dumps({"credential": credential, "name": name}),
            content_type="application/json",
            headers=self._csrf_headers(),
        )
        return resp, priv, credential_id

    def test_registration_success(self):
        resp, _, credential_id = self._register()
        self.assertEqual(resp.status_code, 200, resp.data)
        stored = db.session.scalar(
            sa.select(AuthWebauthnCredential).where(
                AuthWebauthnCredential.credential_id == credential_id
            )
        )
        self.assertIsNotNone(stored)
        self.assertEqual(stored.user_id, self.user.user_id)
        self.assertEqual(stored.name, "My laptop")

    def test_registration_clears_the_passkey_nudge(self):
        with self.client.session_transaction() as sess:
            sess["passkey_nudge"] = True
        resp, _, _ = self._register()
        self.assertEqual(resp.status_code, 200, resp.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("passkey_nudge", sess)

    def test_registration_records_security_event(self):
        self._register()
        event = db.session.scalar(
            sa.select(AuthSecurityEvent).where(
                AuthSecurityEvent.event_type == "passkey_registered",
                AuthSecurityEvent.user_id == self.user.user_id,
            )
        )
        self.assertIsNotNone(event)
        self.assertNotIn("credential_id", json.dumps(event.detail))

    def test_reauth_required_for_registration_after_ten_minutes(self):
        self._set_auth_verified_recently(minutes_ago=11)
        resp = self.client.post(
            "/api/v1/profile/passkeys/options", headers=self._csrf_headers()
        )
        self.assertEqual(resp.status_code, 401)

    def test_reauth_endpoint_refreshes_window(self):
        self._set_auth_verified_recently(minutes_ago=11)
        resp = self.client.post(
            "/api/v1/profile/reauth",
            data=json.dumps({"password": PASSWORD}),
            content_type="application/json",
            headers=self._csrf_headers(),
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        options_resp = self.client.post(
            "/api/v1/profile/passkeys/options", headers=self._csrf_headers()
        )
        self.assertEqual(options_resp.status_code, 200)

    def test_rename_passkey(self):
        resp, _, credential_id = self._register(name="Old name")
        self.assertEqual(resp.status_code, 200, resp.data)
        cred = db.session.scalar(
            sa.select(AuthWebauthnCredential).where(
                AuthWebauthnCredential.credential_id == credential_id
            )
        )
        resp = self.client.patch(
            f"/api/v1/profile/passkeys/{cred.id}",
            data=json.dumps({"name": "New name"}),
            content_type="application/json",
            headers=self._csrf_headers(),
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        db.session.refresh(cred)
        self.assertEqual(cred.name, "New name")

    def test_revoke_passkey(self):
        resp, _, credential_id = self._register()
        cred = db.session.scalar(
            sa.select(AuthWebauthnCredential).where(
                AuthWebauthnCredential.credential_id == credential_id
            )
        )
        resp = self.client.delete(
            f"/api/v1/profile/passkeys/{cred.id}", headers=self._csrf_headers()
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        self.assertIsNone(db.session.get(AuthWebauthnCredential, cred.id))

    def test_revoke_of_another_users_passkey_forbidden(self):
        other = self._make_user(f"other.{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
        db.session.commit()
        other_cred, _ = self._add_credential(other)
        resp = self.client.delete(
            f"/api/v1/profile/passkeys/{other_cred.id}", headers=self._csrf_headers()
        )
        self.assertEqual(resp.status_code, 404)
        self.assertIsNotNone(db.session.get(AuthWebauthnCredential, other_cred.id))


# ---------------------------------------------------------------------------
# Post-login nudge
# ---------------------------------------------------------------------------

class PasskeyNudgeTests(PasskeyTestBase):
    def test_nudge_after_password_login_without_passkey(self):
        resp = self._login_via_form(self.user.email, PASSWORD)
        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertTrue(sess.get("passkey_nudge"))

    def test_no_nudge_after_password_login_with_passkey(self):
        self._add_credential(self.user)
        resp = self._login_via_form(self.user.email, PASSWORD)
        self.assertEqual(resp.status_code, 302)
        with self.client.session_transaction() as sess:
            self.assertNotIn("passkey_nudge", sess)

    def test_no_nudge_after_passkey_login(self):
        cred, priv = self._add_credential(self.user)
        resp = self._sign_in_with_credential(
            self.user.email, cred.credential_id, priv, sign_count=1
        )
        self.assertEqual(resp.status_code, 200, resp.data)
        with self.client.session_transaction() as sess:
            self.assertNotIn("passkey_nudge", sess)
