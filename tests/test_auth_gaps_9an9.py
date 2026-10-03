"""Authentication gaps closed by digitva-9an9.

Baselines: docs/policy/account-onboarding-and-passwords.md (5.2, 5.4, 6, 9),
docs/policy/authentication-factors.md section 7, and
docs/current-state/authentication-and-onboarding.md section 11.
"""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models import AuthSecurityEvent, MasLanguages, VaUsers
from app.services import device_auth_service as devices
from tests.authz.fixture import AuthzFixtureMixin, R, U
from tests.routes import test_device_api as device_tests
from tests.test_account_onboarding import OnboardingTestBase, _mailbox
from tests.test_mobile_sign_in import PASSWORD, PASSWORD_RE, REDEEM, _number
from tests.test_passkey_login import PasskeyTestBase
from tests.webauthn_test_utils import b64url_decode, build_authentication_credential

PROFILE = "/api/v1/profile"


def _events(user_id, event_type):
    return db.session.scalars(sa.select(AuthSecurityEvent).where(
        AuthSecurityEvent.user_id == user_id,
        AuthSecurityEvent.event_type == event_type,
    ).order_by(AuthSecurityEvent.occurred_at)).all()


# ── Item 1a: terms on the code page ──────────────────────────────────────


class CodeRedeemTermsTests(OnboardingTestBase):
    def _new_mobile_user(self):
        user = self._mobile_user(redeemed=False)
        user.pw_reset_t_and_c = False
        db.session.commit()
        return user

    def test_redeeming_with_the_box_ticked_records_acceptance(self):
        user = self._new_mobile_user()
        code = self._issue(user)
        response = self._redeem(user.mobile_login, code)
        self.assertEqual(response.status_code, 200)
        self.assertRegex(self._password_from(response), PASSWORD_RE)
        db.session.refresh(user)
        self.assertTrue(user.pw_reset_t_and_c)
        [event] = _events(user.user_id, "terms_accepted")
        self.assertEqual(event.detail, {"via": "sign_in_code"})

    def test_redeeming_without_the_box_is_refused_and_changes_nothing(self):
        user = self._new_mobile_user()
        code = self._issue(user)
        response = self.client.post(
            REDEEM, data={"mobile": user.mobile_login, "code": code, **self._captcha()},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Please accept the terms of use.", response.data)
        self.assertNotIn(b'id="generated-password"', response.data)
        db.session.refresh(user)
        self.assertFalse(user.pw_reset_t_and_c)
        self.assertIsNone(user.mobile_verified_at)
        # The code is still live: the same code with the box ticked works.
        self.assertEqual(self._redeem(user.mobile_login, code).status_code, 200)
        db.session.refresh(user)
        self.assertTrue(user.pw_reset_t_and_c)


# ── Item 1b/1c: JSON accept-terms and JSON terms gate (browser session) ───


class BrowserTermsTests(OnboardingTestBase):
    def setUp(self):
        super().setUp()
        self.user = self._email_user(onboarded=False)
        self._login(self.user.get_id())

    def test_json_calls_get_terms_required_and_pages_still_redirect(self):
        page = self.client.get("/profile/")
        self.assertEqual(page.status_code, 302)
        self.assertIn("/profile/force-password-change", page.headers["Location"])
        response = self.client.get(f"{PROFILE}/")
        self.assertEqual(response.status_code, 403)
        body = response.get_json()
        self.assertEqual((body["code"], body["error"]), ("terms_required", "terms_required"))
        self.assertTrue(body["redirect_url"].startswith("/profile/"))
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        # Other JSON prefixes too, never a redirect.
        self.assertEqual(self.client.get("/admin/api/users").get_json()["code"], "terms_required")

    def test_accept_terms_endpoint_records_acceptance(self):
        self.assertEqual(self.client.post(f"{PROFILE}/terms", json={"accept_terms": True}).status_code, 400)
        self.assertEqual(self.client.post(f"{PROFILE}/terms", json={},
                                          headers=self._csrf_headers()).status_code, 400)
        self.assertEqual(self.client.post(f"{PROFILE}/terms", json={"accept_terms": "yes"},
                                          headers=self._csrf_headers()).status_code, 400)
        db.session.refresh(self.user)
        self.assertFalse(self.user.pw_reset_t_and_c)
        response = self.client.post(f"{PROFILE}/terms", json={"accept_terms": True},
                                    headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()["terms_accepted"])
        db.session.refresh(self.user)
        self.assertTrue(self.user.pw_reset_t_and_c)
        [event] = _events(self.user.user_id, "terms_accepted")
        self.assertEqual(event.detail, {"via": "api"})
        self._forget_cached_user()
        self.assertEqual(self.client.get(f"{PROFILE}/").status_code, 200)
        # Accepting again is harmless and records nothing new.
        again = self.client.post(f"{PROFILE}/terms", json={"accept_terms": True},
                                 headers=self._csrf_headers())
        self.assertEqual(again.status_code, 200)
        self.assertEqual(len(_events(self.user.user_id, "terms_accepted")), 1)

    def test_web_terms_page_records_the_same_event(self):
        response = self.client.post("/profile/force-password-change", data={"accept_terms": "y"},
                                    headers=self._csrf_headers())
        self.assertEqual(response.status_code, 302)
        [event] = _events(self.user.user_id, "terms_accepted")
        self.assertEqual(event.detail, {"via": "web"})


# ── Item 1b: device token with pending terms ─────────────────────────────


class DeviceTermsTests(OnboardingTestBase):
    PROJECT_ID = "TRM01"
    SITE_ID = "TM01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        device_tests.DeviceApiTests._make_project(cls.PROJECT_ID, cls.SITE_ID, datetime.now(UTC))
        cls.person = cls._get_or_make_user(f"terms.{uuid.uuid4().hex[:8]}@test.local", PASSWORD)
        device_tests.DeviceApiTests._grant(cls.person, cls.PROJECT_ID)
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)
        self.person.pw_reset_t_and_c = False
        db.session.commit()

    def _sign_in(self):
        _row, code = devices.create_enrolment_code(self.PROJECT_ID, actor=self.base_admin_user)
        db.session.commit()
        device = self.client.post("/api/v1/device/enroll", json={
            "code": code, "device_name": "Terms phone", "platform": "android",
        }).get_json()
        return self.client.post("/api/v1/device/sessions", json={
            "device_id": device["device_id"], "device_secret": device["device_secret"],
            "email": self.person.email, "password": PASSWORD,
        })

    def test_sign_in_succeeds_and_only_terms_and_sign_out_are_open(self):
        response = self._sign_in()
        self.assertEqual(response.status_code, 201, response.get_json())
        tokens = response.get_json()
        self.assertIs(tokens["terms_required"], True)
        bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
        refused = self.client.get("/api/v1/device/bootstrap", headers=bearer)
        self.assertEqual((refused.status_code, refused.get_json()["code"]), (403, "terms_required"))
        bad = self.client.post("/api/v1/device/terms", json={}, headers=bearer)
        self.assertEqual((bad.status_code, bad.get_json()["code"]), (400, "invalid_request"))
        accepted = self.client.post("/api/v1/device/terms", json={"accept_terms": True}, headers=bearer)
        self.assertEqual(accepted.status_code, 200, accepted.get_json())
        db.session.refresh(self.person)
        self.assertTrue(self.person.pw_reset_t_and_c)
        [event] = _events(self.person.user_id, "terms_accepted")
        self.assertEqual(event.detail, {"via": "device"})
        self.assertEqual(self.client.get("/api/v1/device/bootstrap", headers=bearer).status_code, 200)
        self.assertIs(self._sign_in().get_json()["terms_required"], False)

    def test_sign_out_stays_open_while_terms_are_pending(self):
        tokens = self._sign_in().get_json()
        self.assertIs(tokens["terms_required"], True)
        bearer = {"Authorization": f"Bearer {tokens['access_token']}"}
        self.assertEqual(self.client.delete("/api/v1/device/sessions/current", headers=bearer).status_code, 204)

    def test_device_terms_needs_a_bearer_token(self):
        response = self.client.post("/api/v1/device/terms", json={"accept_terms": True})
        self.assertEqual((response.status_code, response.get_json()["code"]), (401, "unauthorized"))
        db.session.refresh(self.person)
        self.assertFalse(self.person.pw_reset_t_and_c)


# ── Item 2: passkey reauthentication ─────────────────────────────────────


class PasskeyReauthTests(PasskeyTestBase):
    def _assertion(self, credential_id, priv, *, sign_count=1):
        options = self.client.post(f"{PROFILE}/reauth/passkey/options", headers=self._csrf_headers())
        self.assertEqual(options.status_code, 200, options.get_json())
        return build_authentication_credential(
            rp_id=self._rp_id(), origin=self._origin(),
            challenge=b64url_decode(options.get_json()["challenge"]),
            credential_id=credential_id, priv=priv, sign_count=sign_count,
        )

    def _reauth(self, credential):
        return self.client.post(f"{PROFILE}/reauth/passkey", data=json.dumps({"credential": credential}),
                                content_type="application/json", headers=self._csrf_headers())

    def _window_open(self):
        response = self.client.post(f"{PROFILE}/passkeys/options", headers=self._csrf_headers())
        return response.status_code == 200

    def test_own_passkey_opens_the_reauth_window(self):
        cred, priv = self._add_credential(self.user)
        self._login(self.user.get_id())
        self.assertFalse(self._window_open())
        response = self._reauth(self._assertion(cred.credential_id, priv))
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json(), {"message": "Reauthenticated."})
        self.assertTrue(self._window_open())
        db.session.refresh(cred)
        self.assertEqual(cred.sign_count, 1)

    def test_another_accounts_passkey_is_refused(self):
        other = self._make_user(f"passkey.other.{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
        db.session.commit()
        own, own_priv = self._add_credential(self.user)
        theirs, their_priv = self._add_credential(other)
        self._login(self.user.get_id())
        refused = self._reauth(self._assertion(theirs.credential_id, their_priv))
        self.assertEqual(refused.status_code, 403)
        self.assertFalse(self._window_open())
        # Positive control: the user's own passkey works in the same session.
        self.assertEqual(self._reauth(self._assertion(own.credential_id, own_priv)).status_code, 200)

    def test_counter_regression_is_refused_and_audited(self):
        cred, priv = self._add_credential(self.user, sign_count=5)
        self._login(self.user.get_id())
        self.assertEqual(self._reauth(self._assertion(cred.credential_id, priv, sign_count=5)).status_code, 403)
        self.assertFalse(self._window_open())
        self.assertEqual(len(_events(self.user.user_id, "counter_regression")), 1)
        self.assertEqual(self._reauth(self._assertion(cred.credential_id, priv, sign_count=6)).status_code, 200)

    def test_malformed_body_is_refused(self):
        self._login(self.user.get_id())
        for body in ("[]", json.dumps({"credential": "x"})):
            response = self.client.post(f"{PROFILE}/reauth/passkey", data=body,
                                        content_type="application/json", headers=self._csrf_headers())
            self.assertEqual(response.status_code, 403)


# ── Item 4: profile generate for an unverified email ─────────────────────


class ProfileGenerateUnverifiedTests(OnboardingTestBase):
    URL = f"{PROFILE}/password/generate"

    def _post_with_reauth(self, user):
        self._login(user.get_id())
        with self.client.session_transaction() as sess:
            sess["auth_verified_at"] = datetime.now(UTC).isoformat()
        with _mailbox() as send:
            response = self.client.post(self.URL, headers=self._csrf_headers())
        return response, send

    def test_mobile_only_account_still_sees_it_on_screen(self):
        response, send = self._post_with_reauth(self._mobile_user())
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.get_json()["password"], PASSWORD_RE)
        send.assert_not_called()

    def test_unverified_email_is_refused_neither_shown_nor_mailed(self):
        user = self._email_user(verified=False, phone=_number())
        user.mobile_verified_at = datetime.now(UTC)
        db.session.commit()
        response, send = self._post_with_reauth(user)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "email_unverified")
        self.assertNotIn("password", response.get_json())
        send.assert_not_called()
        send.queued.assert_not_called()
        db.session.refresh(user)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(_events(user.user_id, "password_generated"), [])


# ── Item 5: account creation, verification sent, web sign-in ──────────────


class AuditEventTests(AuthzFixtureMixin, OnboardingTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if db.session.get(MasLanguages, "english") is None:
            db.session.add(MasLanguages(language_code="english", language_name="English",
                                        is_active=True))
        db.session.commit()

    def test_admin_creation_audits_account_created_and_verification_sent(self):
        email = f"audit.{uuid.uuid4().hex[:8]}@example.com"
        admin = self.users["admin"]
        self._login(str(admin.user_id))
        with _mailbox() as send:
            made = self.client.post("/admin/api/users", json={
                "email": email, "email_confirm": email, "name": "Audit Person",
                "languages": ["english"],
            }, headers=self._csrf_headers())
        self.assertEqual(made.status_code, 201, made.get_json())
        send.queued.assert_called_once()
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email))
        [created] = _events(user.user_id, "account_created")
        self.assertEqual(created.actor_user_id, admin.user_id)
        self.assertEqual(created.detail, {"via": "admin", "mobile_only": False})
        [sent] = _events(user.user_id, "verification_email_sent")
        self.assertEqual(sent.actor_user_id, admin.user_id)
        self.assertIsNone(sent.detail)

    def test_mobile_only_creation_is_audited_without_the_number(self):
        number = _number()
        self._login(str(self.users["admin"].user_id))
        made = self.client.post("/admin/api/users", json={
            "name": "Audit Mobile", "phone": number, "languages": ["english"],
        }, headers=self._csrf_headers())
        self.assertEqual(made.status_code, 201, made.get_json())
        [created] = _events(uuid.UUID(made.get_json()["user"]["user_id"]), "account_created")
        self.assertEqual(created.detail, {"via": "admin", "mobile_only": True})
        self.assertNotIn(number, json.dumps(created.detail))

    def test_web_sign_in_success_and_failure_are_audited_without_secrets(self):
        user = self._email_user()
        self._login_via_form(user.email, "wrong-password-1")
        [failed] = _events(user.user_id, "web_sign_in_failed")
        self.assertEqual(failed.detail, {"reason": "invalid_credentials"})
        self.assertEqual(_events(user.user_id, "web_sign_in"), [])
        self._fresh_client()
        self._login_via_form(user.email, PASSWORD)
        self.assertTrue(self._signed_in())
        [signed_in] = _events(user.user_id, "web_sign_in")
        self.assertEqual(signed_in.detail, {"method": "password"})
        for event in (failed, signed_in):
            text = json.dumps(event.detail)
            self.assertNotIn(PASSWORD, text)
            self.assertNotIn(user.email, text)

    def test_unknown_identifier_failure_is_audited_with_no_account(self):
        before = db.session.scalar(sa.select(sa.func.count()).select_from(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "web_sign_in_failed", AuthSecurityEvent.user_id.is_(None)))
        email = f"nobody.{uuid.uuid4().hex[:8]}@example.com"
        self._login_via_form(email, PASSWORD)
        events = db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.event_type == "web_sign_in_failed", AuthSecurityEvent.user_id.is_(None))).all()
        self.assertEqual(len(events), before + 1)
        self.assertNotIn(email, json.dumps([e.detail for e in events]))

    def test_unverified_email_sign_in_failure_reason(self):
        user = self._email_user(verified=False)
        self._login_via_form(user.email, PASSWORD)
        self.assertFalse(self._signed_in())
        [failed] = _events(user.user_id, "web_sign_in_failed")
        self.assertEqual(failed.detail, {"reason": "email_unverified"})


# ── Item 6: resend verification guards and honest results ─────────────────


class ResendVerificationTests(AuthzFixtureMixin, OnboardingTestBase):
    def _admin_resend(self, user):
        self._login(str(self.users["admin"].user_id))
        return self.client.post(f"/admin/api/users/{user.user_id}/resend-verification",
                                headers=self._csrf_headers())

    def _dm_resend(self, user):
        self._login(str(self.users["dm_c1"].user_id))
        return self.client.post(f"/data-management/api/users/{user.user_id}/resend-verification",
                                headers=self._csrf_headers())

    def _managed_unverified(self):
        user = self._email_user(verified=False, onboarded=False)
        db.session.add(self._grant_row(user, R.reviewer, U, "P1"))
        db.session.commit()
        return user

    def test_admin_resend_sends_and_audits(self):
        user = self._email_user(verified=False)
        with _mailbox() as send:
            response = self._admin_resend(user)
        self.assertEqual(response.status_code, 200, response.get_json())
        send.queued.assert_called_once()
        [event] = _events(user.user_id, "verification_email_sent")
        self.assertEqual(event.actor_user_id, self.users["admin"].user_id)

    def test_admin_resend_refuses_a_mobile_only_account(self):
        with _mailbox() as send:
            response = self._admin_resend(self._mobile_user())
        self.assertEqual(response.status_code, 400)
        self.assertIn("no email", response.get_json()["error"])
        send.queued.assert_not_called()

    def test_both_resends_report_an_undelivered_email_honestly(self):
        admin_target = self._email_user(verified=False)
        dm_target = self._managed_unverified()
        # Positive control: the DM may resend for this account when delivery works.
        with _mailbox() as send:
            self.assertEqual(self._dm_resend(dm_target).status_code, 200)
        send.queued.assert_called_once()
        with _mailbox() as send, patch("app.services.email_service._email_delivery_enabled",
                                       return_value=False):
            for response in (self._admin_resend(admin_target), self._dm_resend(dm_target)):
                self.assertEqual(response.status_code, 400)
                self.assertIn("no verification email was sent", response.get_json()["error"])
        send.queued.assert_not_called()
        self.assertEqual(_events(admin_target.user_id, "verification_email_sent"), [])


# ── Item 8: signed-out JSON gets 401, pages still redirect ────────────────


class SignedOutJsonTests(OnboardingTestBase):
    def test_profile_api_answers_json_401_and_pages_redirect(self):
        page = self.client.get("/profile/")
        self.assertEqual(page.status_code, 302)
        self.assertIn("/vaauth/valogin", page.headers["Location"])
        self.assertIn("next=", page.headers["Location"])
        for path in (f"{PROFILE}/", f"{PROFILE}/passkeys"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, path)
            self.assertEqual(response.get_json(), {"error": "Authentication required."})
        posted = self.client.post(f"{PROFILE}/terms", json={"accept_terms": True},
                                  headers=self._csrf_headers())
        self.assertEqual(posted.status_code, 401)

