"""Sign-in by mobile number with server-generated passwords (digitva-l7c2).

Baseline: docs/policy/mobile-sign-in.md; docs/policy/authentication-factors.md
governs the rest of the login. Covers canonicalisation, uniqueness on every
create path, login by mobile (password and passkey), indistinguishable
unknown/shared/invalid numbers, sign-in code issue gating, expiry, voiding,
the five-failure rule, rate limits, redemption, regeneration, and that a
mobile-only account is never emailed and never chooses a password.
"""

import random
import re
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from app import db, limiter
from app.models import AuthMobileCode, AuthSecurityEvent, VaProjectMaster, VaStatuses, VaUsers
from app.models.mas_languages import MasLanguages
from app.services import mobile_sign_in_service as mobile
from app.services import project_user_import_service as user_import
from app.services.user_account_service import canonical_mobile, mask_mobile
from tests.authz.fixture import TA, AuthzFixtureMixin, P, R, U
from tests.base import BaseTestCase
from tests.test_passkey_login import PasskeyTestBase

PASSWORD = "MobileSignIn123!"
INVALID_LOGIN = b"Invalid email or password"
REDEEM = "/vaauth/valogin/code"
PASSWORD_RE = re.compile(r"^[a-z]{4,7}-[a-z]{4,7}-[a-z]{4,7}-\d{4}$")


def _number():
    """A random canonical mobile number, unique enough per test."""
    return "9" + "".join(random.choice("0123456789") for _ in range(9))


class CanonicalMobileAndPasswordTests(unittest.TestCase):
    def test_canonical_mobile(self):
        cases = {
            "9876543210": "9876543210",
            "98765 43210": "9876543210",
            "+91 98765-43210": "9876543210",
            "(0) 98765 43210": "9876543210",
            "919876543210": "9876543210",
            "987654321": None,          # nine digits
            "19876543210": None,        # 11 digits, no trunk 0
            "929876543210": None,       # 12 digits, not 91
            "": None,
            None: None,
            "abc": None,
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(canonical_mobile(raw), expected)

    def test_mask_never_shows_the_whole_number(self):
        self.assertEqual(mask_mobile("9876543210"), "******3210")
        self.assertIsNone(mask_mobile(None))

    def test_wordlist_is_plain_unique_and_large_enough(self):
        words = mobile._words()
        self.assertGreaterEqual(len(words), 1000)
        self.assertEqual(len(words), len(set(words)))
        for word in words:
            self.assertRegex(word, r"^[a-z]{4,7}$")

    def test_generated_password_shape(self):
        for _ in range(50):
            password = mobile.generate_password()
            self.assertRegex(password, PASSWORD_RE)
            self.assertGreaterEqual(len(password), 16)

    def test_breached_password_is_redrawn_and_outage_raises(self):
        breached = "Password has been found in known breach data. Choose a different password."
        with patch.object(mobile, "password_breach_error_message", side_effect=[breached, None]):
            self.assertRegex(mobile.generate_password(), PASSWORD_RE)
        with patch.object(mobile, "password_breach_error_message",
                          return_value=mobile.BREACH_CHECK_UNAVAILABLE_MESSAGE):
            with self.assertRaises(mobile.PasswordGenerationUnavailable):
                mobile.generate_password()


class MobileSignInTestBase(BaseTestCase):
    def setUp(self):
        super().setUp()
        limiter.reset()

    def _mobile_user(self, number=None, *, redeemed=True, password=PASSWORD):
        number = number or _number()
        user = VaUsers(
            user_id=uuid.uuid4(), name="Mobile Worker", email=None, phone=number,
            mobile_login=number, vacode_language=["English"], permission={},
            landing_page="coder", pw_reset_t_and_c=True, email_verified=False,
            mobile_verified_at=datetime.now(UTC) if redeemed else None,
            user_status=VaStatuses.active,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    def _captcha(self):
        from app.services.pow_captcha_service import issue_challenge

        challenge = issue_challenge()
        return {
            "captcha_salt": challenge["salt"],
            "captcha_difficulty": challenge["difficulty"],
            "captcha_expires": challenge["expires"],
            "captcha_signature": challenge["signature"],
            "captcha_solution": self._solve_pow_captcha(challenge["salt"], challenge["difficulty"]),
        }

    def _redeem(self, number, code, ip="127.0.0.1"):
        return self.client.post(
            REDEEM, data={"mobile": number, "code": code, **self._captcha()},
            headers=self._csrf_headers(), environ_overrides={"REMOTE_ADDR": ip},
        )

    def _issue(self, user, actor=None):
        code = mobile.issue_code(user, actor_user_id=actor)
        db.session.commit()
        return code

    @staticmethod
    def _forget_cached_user():
        """Flask-Login caches the user on the session-long g; drop it so the
        next request reloads (and re-checks the session version)."""
        from flask import g

        if hasattr(g, "_login_user"):
            del g._login_user

    def _fresh_client(self):
        """A new browser with empty rate-limit buckets."""
        self._forget_cached_user()
        self.client = self.app.test_client()
        limiter.reset()

    def _signed_in(self):
        with self.client.session_transaction() as sess:
            return "_user_id" in sess

    def _password_from(self, response):
        match = re.search(rb'id="generated-password"[^>]*>([^<]+)<', response.data)
        self.assertIsNotNone(match, response.data[:500])
        return match.group(1).decode()


class SchemaTests(MobileSignInTestBase):
    def test_an_account_needs_an_email_or_a_mobile(self):
        user = VaUsers(name="Nobody", email=None, mobile_login=None, vacode_language=["English"],
                       permission={}, landing_page="coder", user_status=VaStatuses.active)
        user.set_password(PASSWORD)
        db.session.add(user)
        with self.assertRaises(IntegrityError):
            db.session.flush()
        db.session.rollback()

    def test_sign_in_number_is_unique(self):
        number = _number()
        self._mobile_user(number)
        with self.assertRaises(IntegrityError):
            self._mobile_user(number)
        db.session.rollback()


class MobileLoginTests(MobileSignInTestBase):
    def test_mobile_password_sign_in_in_any_typed_format(self):
        number = _number()
        self._mobile_user(number)
        for typed in (number, f"+91 {number[:5]} {number[5:]}", "0" + number):
            with self.subTest(typed=typed):
                self._fresh_client()
                response = self._login_via_form(typed, PASSWORD)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(self._signed_in())

    def test_email_account_with_a_unique_number_signs_in_both_ways(self):
        number = _number()
        user = self._make_user(f"both.{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
        user.phone = number
        user.mobile_login = number
        db.session.commit()
        self._login_via_form(user.email, PASSWORD)
        self.assertTrue(self._signed_in())
        self._fresh_client()
        self._login_via_form(number, PASSWORD)
        self.assertTrue(self._signed_in())

    def _assert_generic_failure(self, typed, password=PASSWORD):
        self._fresh_client()
        response = self._login_via_form(typed, password)
        self.assertEqual(response.status_code, 302)
        page = self.client.get(response.headers["Location"], follow_redirects=True)
        self.assertIn(INVALID_LOGIN, page.data)
        self.assertFalse(self._signed_in())
        return page

    def test_unknown_shared_and_invalid_numbers_are_indistinguishable(self):
        # Two email accounts sharing one number (legacy data): the number is
        # in phone only, never in mobile_login, so it signs nobody in.
        shared = _number()
        for i in range(2):
            u = self._make_user(f"shared{i}.{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
            u.phone = shared
        db.session.commit()
        pages = [self._assert_generic_failure(value) for value in (_number(), shared, "98765")]
        # The email step answers every value, real number included, the same.
        statuses = set()
        for value in (_number(), shared, "98765", self._mobile_user().mobile_login):
            self._fresh_client()
            statuses.add(self._step1_status(value))
        self.assertEqual(statuses, {302})
        self.assertEqual(len(pages), 3)

    def _step1_status(self, value):
        response = self.client.post(
            "/vaauth/valogin", data={"email": value, **self._captcha()},
            headers=self._csrf_headers(),
        )
        self.assertIn("/valogin/password", response.headers.get("Location", ""))
        return response.status_code

    def test_mobile_step_does_not_query_va_users(self):
        data = {"email": _number(), **self._captcha()}
        headers = self._csrf_headers()
        statements = []

        def _capture(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", _capture)
        try:
            response = self.client.post("/vaauth/valogin", data=data, headers=headers)
        finally:
            event.remove(db.engine, "before_cursor_execute", _capture)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(any("va_users" in s.lower() for s in statements))

    def test_wrong_password_for_a_mobile_account_is_generic(self):
        number = self._mobile_user().mobile_login
        self._assert_generic_failure(number, "not-the-password")

    def test_unredeemed_mobile_account_cannot_sign_in(self):
        user = self._mobile_user(redeemed=False)
        self._assert_generic_failure(user.mobile_login)

    def test_forgot_password_with_a_number_points_to_the_data_manager(self):
        with patch("app.services.email_service._dispatch_email") as dispatch:
            for value in (self._mobile_user().mobile_login, _number()):
                response = self.client.post(
                    "/vaauth/forgot-password", data={"email": value},
                    headers=self._csrf_headers(), follow_redirects=True,
                )
                self.assertIn(b"ask your data manager", response.data)
        dispatch.delay.assert_not_called()


class MobilePasskeyTests(PasskeyTestBase):
    def test_passkey_sign_in_after_a_mobile_step(self):
        number = _number()
        self.user.email = None
        self.user.phone = number
        self.user.mobile_login = number
        self.user.mobile_verified_at = datetime.now(UTC)
        db.session.commit()
        cred, priv = self._add_credential(self.user)
        response = self._sign_in_with_credential(
            f"+91 {number}", cred.credential_id, priv, sign_count=1
        )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertIn("redirect", response.get_json())

    def test_passkey_of_another_account_refused_for_a_mobile_step(self):
        cred, priv = self._add_credential(self.user)
        response = self._sign_in_with_credential(_number(), cred.credential_id, priv, sign_count=1)
        self.assertEqual(response.status_code, 400)


class RedeemCodeTests(MobileSignInTestBase):
    def test_redeem_shows_a_generated_password_once_and_it_signs_in(self):
        user = self._mobile_user(redeemed=False)
        code = self._issue(user)
        self.assertRegex(code, r"^\d{6}$")
        response = self._redeem(f"+91 {user.mobile_login}", code)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Write this down. It will not be shown again.", response.data)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        password = self._password_from(response)
        self.assertRegex(password, PASSWORD_RE)
        db.session.refresh(user)
        self.assertIsNotNone(user.mobile_verified_at)
        self.assertNotIn(code, str(user.password))
        # The old password stops working, the new one signs in.
        self._fresh_client()
        page = self._login_via_form(user.mobile_login, PASSWORD)
        self.assertIn(INVALID_LOGIN, self.client.get(page.headers["Location"]).data)
        self.assertFalse(self._signed_in())
        self._fresh_client()
        self._login_via_form(user.mobile_login, password)
        self.assertTrue(self._signed_in())
        # The code works once.
        self._fresh_client()
        self.assertNotIn(b"generated-password", self._redeem(user.mobile_login, code).data)
        events = set(db.session.scalars(sa.select(AuthSecurityEvent.event_type).where(
            AuthSecurityEvent.user_id == user.user_id)))
        self.assertTrue({"mobile_code_issued", "mobile_code_redeemed"} <= events)

    def test_redeem_ends_existing_sessions(self):
        user = self._mobile_user()
        self._login(user.get_id())
        self.assertEqual(self.client.get("/profile/").status_code, 200)
        code = self._issue(user)
        self.assertIsNotNone(mobile.redeem_code(user.mobile_login, code))
        db.session.commit()
        self._forget_cached_user()
        self.assertEqual(self.client.get("/profile/").status_code, 302)

    def test_wrong_number_and_wrong_code_get_the_same_answer(self):
        user = self._mobile_user()
        code = self._issue(user)
        wrong = f"{(int(code) + 1) % 1_000_000:06d}"
        a = self._redeem(user.mobile_login, wrong)
        b = self._redeem(_number(), code)
        c = self._redeem("123", code)
        self.assertEqual({a.status_code, b.status_code, c.status_code}, {200})
        for response in (a, b, c):
            self.assertIn(b"That email or mobile number and code do not match", response.data)
            self.assertNotIn(b"generated-password", response.data)

    def test_expired_code_fails(self):
        user = self._mobile_user()
        code = self._issue(user)
        db.session.execute(sa.update(AuthMobileCode).where(AuthMobileCode.user_id == user.user_id)
                           .values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
        db.session.commit()
        self.assertIsNone(mobile.redeem_code(user.mobile_login, code))

    def test_code_lasts_72_hours(self):
        user = self._mobile_user()
        self._issue(user)
        row = db.session.scalar(sa.select(AuthMobileCode).where(AuthMobileCode.user_id == user.user_id))
        self.assertEqual(row.expires_at - row.issued_at, timedelta(hours=72))

    def test_a_new_code_voids_the_old(self):
        user = self._mobile_user()
        first = self._issue(user)
        second = self._issue(user)
        if first == second:  # 1 in a million: draw again
            second = self._issue(user)
        self.assertIsNone(mobile.redeem_code(user.mobile_login, first))
        db.session.commit()
        self.assertIsNotNone(mobile.redeem_code(user.mobile_login, second))

    def test_five_wrong_codes_void_the_code(self):
        user = self._mobile_user()
        code = self._issue(user)
        wrong = f"{(int(code) + 1) % 1_000_000:06d}"
        for _ in range(mobile.MAX_CODE_FAILURES):
            self.assertIsNone(mobile.redeem_code(user.mobile_login, wrong))
            db.session.commit()
        self.assertIsNone(mobile.redeem_code(user.mobile_login, code))
        row = db.session.scalar(sa.select(AuthMobileCode).where(AuthMobileCode.user_id == user.user_id))
        self.assertIsNotNone(row.voided_at)
        self.assertEqual(row.failed_attempts, mobile.MAX_CODE_FAILURES)
        self.assertTrue(db.session.scalar(sa.select(sa.exists().where(
            AuthSecurityEvent.user_id == user.user_id,
            AuthSecurityEvent.event_type == "mobile_code_voided"))))

    def test_breach_outage_changes_nothing_and_counts_nothing(self):
        user = self._mobile_user()
        code = self._issue(user)
        with patch.object(mobile, "password_breach_error_message",
                          return_value=mobile.BREACH_CHECK_UNAVAILABLE_MESSAGE):
            response = self._redeem(user.mobile_login, code)
        self.assertIn(b"temporarily unavailable", response.data)
        row = db.session.scalar(sa.select(AuthMobileCode).where(AuthMobileCode.user_id == user.user_id))
        self.assertIsNone(row.redeemed_at)
        self.assertEqual(row.failed_attempts, 0)

    def test_attempts_are_rate_limited_per_number(self):
        number = self._mobile_user().mobile_login
        statuses = [self._redeem(number, "000000", ip=f"10.9.0.{i}").status_code for i in range(11)]
        self.assertEqual(statuses[:10], [200] * 10)
        self._assert_rate_limited(statuses[10])

    def test_attempts_are_rate_limited_per_ip(self):
        statuses = [self._redeem(_number(), "000000", ip="10.9.1.1").status_code for _ in range(11)]
        self.assertEqual(statuses[:10], [200] * 10)
        self._assert_rate_limited(statuses[10])

    def _assert_rate_limited(self, status):
        # Browser paths flash and redirect on a rate limit (app/routes/va_errors.py).
        self.assertEqual(status, 302)
        with self.client.session_transaction() as sess:
            flashed = [m for _c, m in sess.get("_flashes", [])]
        self.assertTrue(any("Too many requests" in m for m in flashed), flashed)

    def test_at_most_five_comparisons_per_code(self):
        user = self._mobile_user()
        code = self._issue(user)
        # A row at the cap but not (yet) voided is never compared again.
        db.session.execute(sa.update(AuthMobileCode).where(AuthMobileCode.user_id == user.user_id)
                           .values(failed_attempts=mobile.MAX_CODE_FAILURES))
        db.session.commit()
        self.assertIsNone(mobile.redeem_code(user.mobile_login, code))

    def test_one_live_code_per_user_is_enforced_by_the_database(self):
        user = self._mobile_user()
        self._issue(user)
        now = datetime.now(UTC)
        db.session.add(AuthMobileCode(user_id=user.user_id, code_hash="x" * 64,
                                      issued_at=now, expires_at=now + timedelta(hours=1)))
        with self.assertRaises(IntegrityError):
            db.session.flush()
        db.session.rollback()

    def _statements(self, fn):
        statements = []

        def _capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith(("SAVEPOINT", "RELEASE", "ROLLBACK")):
                return  # the test harness's own transaction bookkeeping
            statements.append(statement.lstrip().split()[0].upper()
                              + (" FOR UPDATE" if "FOR UPDATE" in statement.upper() else ""))

        event.listen(db.engine, "before_cursor_execute", _capture)
        try:
            fn()
        finally:
            event.remove(db.engine, "before_cursor_execute", _capture)
        return statements

    def test_issue_and_redeem_lock_their_rows(self):
        user = self._mobile_user()
        issued = self._statements(lambda: mobile.issue_code(user, actor_user_id=None))
        self.assertIn("SELECT FOR UPDATE", issued)
        db.session.commit()
        redeemed = self._statements(lambda: mobile.redeem_code(user.mobile_login, "000000"))
        self.assertIn("SELECT FOR UPDATE", redeemed)
        db.session.rollback()

    def test_wrong_code_and_no_code_do_the_same_database_work(self):
        with_code = self._mobile_user()
        code = self._issue(with_code)
        wrong = f"{(int(code) + 1) % 1_000_000:06d}"
        without_code = self._mobile_user()
        # Read the numbers first: touching an expired instance inside the
        # capture would add its own refresh SELECT.
        live_number, idle_number = with_code.mobile_login, without_code.mobile_login
        a = self._statements(lambda: mobile.redeem_code(live_number, wrong))
        db.session.rollback()
        b = self._statements(lambda: mobile.redeem_code(idle_number, wrong))
        db.session.rollback()
        c = self._statements(lambda: mobile.redeem_code(_number(), wrong))
        db.session.rollback()
        self.assertEqual(a, b)
        self.assertEqual(a, c)

    def test_codes_also_work_for_email_accounts(self):
        """digitva-kmoy: any managed account may get a code, redeemed with
        its email (account-onboarding-and-passwords.md section 6)."""
        user = self._make_user(f"emailonly.{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
        db.session.commit()
        code = self._issue(user)
        redeemed, password = mobile.redeem_code(user.email, code)
        self.assertEqual(redeemed.user_id, user.user_id)
        self.assertRegex(password, PASSWORD_RE)


class MobileAccountPasswordTests(MobileSignInTestBase):
    def test_chosen_password_change_is_refused(self):
        user = self._mobile_user()
        self._login(user.get_id())
        response = self.client.patch("/api/v1/profile/password", json={
            "current_password": PASSWORD, "new_password": "Another1Pass!x",
            "confirm_password": "Another1Pass!x"}, headers=self._csrf_headers())
        # The endpoint is gone for everyone (digitva-kmoy).
        self.assertIn(response.status_code, (404, 405))
        db.session.refresh(user)
        self.assertTrue(user.check_password(PASSWORD))

    def test_reset_link_is_refused_for_a_mobile_only_account(self):
        from app.services.token_service import generate_token

        user = self._mobile_user()
        token = generate_token(user.user_id, "password_reset")
        self.client.post(f"/vaauth/reset-password/{token}", data={
            "new_password": "Another1Pass!x", "confirm_password": "Another1Pass!x"},
            headers=self._csrf_headers())
        db.session.refresh(user)
        self.assertTrue(user.check_password(PASSWORD))

    def test_regenerate_needs_reauth_then_ends_the_session(self):
        user = self._mobile_user()
        self._login(user.get_id())
        url = "/api/v1/profile/password/generate"
        self.assertEqual(self.client.post(url, headers=self._csrf_headers()).status_code, 401)
        with self.client.session_transaction() as sess:
            sess["auth_verified_at"] = datetime.now(UTC).isoformat()
        response = self.client.post(url, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        password = response.get_json()["password"]
        self.assertRegex(password, PASSWORD_RE)
        db.session.refresh(user)
        self.assertFalse(user.check_password(PASSWORD))
        self.assertTrue(user.check_password(password))
        self._forget_cached_user()
        self.assertNotEqual(self.client.get("/profile/").status_code, 200)

    def test_regenerate_for_email_accounts_is_emailed_not_shown(self):
        """digitva-kmoy: tests/test_account_onboarding.py covers the email."""
        user = self._make_user(f"regen.{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
        db.session.commit()
        self._login(user.get_id())
        with self.client.session_transaction() as sess:
            sess["auth_verified_at"] = datetime.now(UTC).isoformat()
        with patch("app.services.user_account_service.email_new_password") as emailed:
            response = self.client.post("/api/v1/profile/password/generate",
                                        headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("password", response.get_json())
        emailed.assert_called_once()

    def test_no_email_is_sent_to_a_mobile_only_account(self):
        from app.services.email_service import send_password_reset_email, send_verification_email
        from app.services.user_account_service import send_invitation

        user = self._mobile_user()
        with patch("app.services.email_service._dispatch_email") as dispatch:
            send_invitation(user)
            self.assertFalse(send_verification_email(user, "token"))
            self.assertFalse(send_password_reset_email(user, "token"))
        dispatch.delay.assert_not_called()


class MobileCreatePathTests(AuthzFixtureMixin, MobileSignInTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if db.session.get(MasLanguages, "english") is None:
            db.session.add(MasLanguages(language_code="english", language_name="English",
                                        is_active=True))
        db.session.commit()

    def _as(self, key):
        self._login(str(self.users[key].user_id))

    def _dm_payload(self, **extra):
        return {
            "name": "Field Worker", "languages": ["english"], "initial_project_id": TA,
            "initial_role": "reviewer", "initial_scope_type": "org_unit",
            "initial_org_unit_id": str(self.units["P1"].org_unit_id), **extra,
        }

    def _post(self, url, body):
        return self.client.post(url, json=body, headers=self._csrf_headers())

    def test_dm_creates_a_mobile_only_account_and_gets_a_code_once(self):
        number = _number()
        self._as("dm_c1")
        with patch("app.services.email_service._dispatch_email") as dispatch:
            made = self._post("/data-management/api/users", self._dm_payload(phone=f"+91 {number}"))
        self.assertEqual(made.status_code, 201, made.get_json())
        body = made.get_json()
        self.assertRegex(body["sign_in_code"], r"^\d{6}$")
        self.assertTrue(body["user"]["mobile_only"])
        self.assertNotIn("sign_in_code", body["user"])
        dispatch.delay.assert_not_called()
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.mobile_login == number))
        self.assertIsNone(user.email)
        self.assertIsNotNone(mobile.redeem_code(number, body["sign_in_code"]))

    def test_dm_create_refuses_a_held_number_and_a_missing_identity(self):
        held = self._mobile_user().mobile_login
        legacy = _number()
        other = self._make_user(f"legacy.{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
        other.phone = f"0{legacy}"  # only in phone, as shared legacy numbers are
        db.session.commit()
        self._as("dm_c1")
        for phone in (held, legacy):
            with self.subTest(phone=phone):
                response = self._post("/data-management/api/users", self._dm_payload(phone=phone))
                self.assertEqual(response.status_code, 400)
                self.assertIn("already used by another account", response.get_json()["error"])
        for phone in ("", "98765"):
            with self.subTest(phone=phone):
                response = self._post("/data-management/api/users", self._dm_payload(phone=phone))
                self.assertEqual(response.status_code, 400)

    def test_email_account_create_keeps_the_invitation(self):
        number = _number()
        email = f"invite.{uuid.uuid4().hex[:8]}@example.com"
        self._as("admin")
        with patch("app.services.user_account_service.send_invitation") as invite:
            made = self._post("/admin/api/users", {"email": email, "email_confirm": email,
                                                   "name": "Email Person", "phone": number,
                                                   "languages": ["english"]})
        self.assertEqual(made.status_code, 201, made.get_json())
        self.assertNotIn("sign_in_code", made.get_json())
        invite.assert_called_once()
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email))
        self.assertEqual(user.mobile_login, number)

    def test_admin_create_update_and_password_rules(self):
        number = _number()
        self._as("admin")
        made = self._post("/admin/api/users", {"name": "Admin Made", "phone": number,
                                               "languages": ["english"]})
        self.assertEqual(made.status_code, 201, made.get_json())
        self.assertRegex(made.get_json()["sign_in_code"], r"^\d{6}$")
        user_id = made.get_json()["user"]["user_id"]
        url = f"/admin/api/users/{user_id}"
        held = self._mobile_user().mobile_login
        self.assertEqual(self.client.put(url, json={"phone": held},
                                         headers=self._csrf_headers()).status_code, 400)
        self.assertEqual(self.client.put(url, json={"phone": ""},
                                         headers=self._csrf_headers()).status_code, 400)
        self.assertEqual(self.client.put(url, json={"password": "Chosen1Password!"},
                                         headers=self._csrf_headers()).status_code, 400)
        new_number = _number()
        ok = self.client.put(url, json={"phone": new_number}, headers=self._csrf_headers())
        self.assertEqual(ok.status_code, 200, ok.get_json())
        self.assertEqual(db.session.get(VaUsers, uuid.UUID(user_id)).mobile_login, new_number)

    def test_mentor_institute_style_callers_still_need_an_email(self):
        from app.services import user_account_service as accounts

        with self.assertRaises(accounts.UserAccountError):
            accounts.validate_new_user_payload({"name": "X", "phone": _number(),
                                                "languages": ["english"]})

    def test_issue_code_gating(self):
        inside = self._mobile_user()
        outside = self._mobile_user()
        db.session.add_all([
            self._grant_row(inside, R.reviewer,
                            U, "P1"),
            self._grant_row(outside, R.reviewer,
                            P, TA),
        ])
        db.session.commit()

        def issue(target):
            return self.client.post(f"/data-management/api/users/{target.user_id}/sign-in-code",
                                    headers=self._csrf_headers())

        self._as("dm_c1")
        allowed = issue(inside)
        self.assertEqual(allowed.status_code, 200, allowed.get_json())
        self.assertRegex(allowed.get_json()["sign_in_code"], r"^\d{6}$")
        self.assertEqual(issue(outside).status_code, 404)
        self._as("admin")
        self.assertEqual(issue(outside).status_code, 200)
        admin_route = self.client.post(f"/admin/api/users/{outside.user_id}/sign-in-code",
                                       headers=self._csrf_headers())
        self.assertEqual(admin_route.status_code, 200)
        no_csrf = self.client.post(f"/data-management/api/users/{outside.user_id}/sign-in-code")
        self.assertEqual(no_csrf.status_code, 400)
        # Security review (digitva-kmoy): a verified email account resets by
        # email; only an admin issues it a code.
        self._as("dm_c1")
        self.assertEqual(issue(self.users["reviewer_p1"]).status_code, 404)
        self.assertEqual(issue(self.users["reviewer_ta"]).status_code, 404)

    def test_issue_code_refused_unless_every_grant_is_managed_and_unprivileged(self):
        """Security review 2026-10-03: managing one grant of a person is not
        enough to take over their account by code."""
        def target(*grants):
            user = self._mobile_user()
            db.session.add_all([self._grant_row(user, *g) for g in grants])
            db.session.commit()
            return user

        refused = {
            "extra grant outside scope": target((R.reviewer, U, "P1"), (R.reviewer, P, TA)),
            "peer data manager": target((R.data_manager, U, "C1")),
            "data manager below": target((R.data_manager, U, "P1")),
            "project PI elsewhere": target((R.reviewer, U, "P1"), (R.project_pi, P, TA)),
            "no grants": target(),
        }
        inside = target((R.reviewer, U, "P1"), (R.interviewer, U, "SC1"))
        for name, user in refused.items():
            with self.subTest(name=name):
                self.assertFalse(mobile.may_issue_code(self.users["dm_c1"], user.user_id))
        self.assertTrue(mobile.may_issue_code(self.users["dm_c1"], inside.user_id))
        self._as("dm_c1")
        response = self.client.post(
            f"/data-management/api/users/{refused['peer data manager'].user_id}/sign-in-code",
            headers=self._csrf_headers())
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"], "User not found.")
        for user in refused.values():
            self.assertTrue(mobile.may_issue_code(self.users["admin"], user.user_id))

    def _created_by(self, user, actor_key):
        user.other = {"created_by_user_id": str(self.users[actor_key].user_id)}
        db.session.add(self._grant_row(user, R.reviewer, U, "P1"))
        db.session.commit()

    def _edit_email(self, user, email):
        return self.client.put(f"/data-management/api/users/{user.user_id}",
                               json={"email": email, "email_confirm": email},
                               headers=self._csrf_headers())

    def test_dm_may_set_an_email_only_before_first_sign_in(self):
        never = self._mobile_user(redeemed=False)
        redeemed = self._mobile_user(redeemed=True)
        verified = self._make_user(f"verified.{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
        for user in (never, redeemed, verified):
            self._created_by(user, "dm_c1")
        self._as("dm_c1")
        for user in (redeemed, verified):
            with self.subTest(user=user.user_id):
                self.assertEqual(
                    self._edit_email(user, f"dm.box.{uuid.uuid4().hex[:8]}@example.com").status_code,
                    403)
        version = never.auth_session_version
        new_email = f"first.{uuid.uuid4().hex[:8]}@example.com"
        with patch("app.services.email_service._dispatch_email") as dispatch:
            ok = self._edit_email(never, new_email)
        self.assertEqual(ok.status_code, 200, ok.get_json())
        db.session.refresh(never)
        self.assertEqual(never.email, new_email)
        self.assertFalse(never.email_verified)
        self.assertEqual(never.auth_session_version, version + 1)
        self.assertEqual(dispatch.delay.call_args.kwargs["to"], new_email)

    def test_admin_email_change_clears_verification_and_ends_sessions(self):
        user = self._make_user(f"adm.{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
        db.session.commit()
        version = user.auth_session_version
        self._as("admin")
        new_email = f"adm.new.{uuid.uuid4().hex[:8]}@example.com"
        with patch("app.services.email_service._dispatch_email"):
            response = self.client.put(f"/admin/api/users/{user.user_id}",
                                       json={"email": new_email, "email_confirm": new_email},
                                       headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        db.session.refresh(user)
        self.assertFalse(user.email_verified)
        self.assertEqual(user.auth_session_version, version + 1)

    def test_import_refuses_held_and_repeated_numbers(self):
        held = self._mobile_user().mobile_login
        fresh = _number()

        def row(n, email, phone):
            return {"_line_number": n, "email": email, "name": "Imported", "role": "reviewer",
                    "org_unit_code": "P1", "cadre_code": "", "language_codes": "english",
                    "phone": phone}

        tag = uuid.uuid4().hex[:8]
        admin = self.users["admin"]
        db.session.get(VaProjectMaster, TA).project_structure_mode = "organization"
        db.session.flush()
        with self.assertRaises(user_import.ProjectUserImportError) as held_error:
            user_import.prepare(TA, [row(2, f"a.{tag}@example.com", held)], actor=admin)
        self.assertIn("already used", str(held_error.exception))
        with self.assertRaises(user_import.ProjectUserImportError):
            user_import.prepare(TA, [row(2, f"b.{tag}@example.com", fresh),
                                     row(3, f"c.{tag}@example.com", f"+91{fresh}")], actor=admin)
        plan = user_import.prepare(TA, [row(2, f"d.{tag}@example.com", fresh)], actor=admin)
        user_import.apply(TA, plan, actor_user_id=admin.user_id)
        db.session.flush()
        made = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == f"d.{tag}@example.com"))
        self.assertEqual(made.mobile_login, fresh)

    def test_cli_create_sets_and_refuses_numbers(self):
        runner = self.app.test_cli_runner()
        held = self._mobile_user().mobile_login
        fresh = _number()
        tag = uuid.uuid4().hex[:8]
        refused = runner.invoke(args=["users", "create", "--email", f"cli1.{tag}@example.com",
                                      "--name", "Cli", "--phone", held])
        self.assertNotEqual(refused.exit_code, 0)
        self.assertIn("already used", refused.output)
        with patch("app.services.user_account_service.send_invitation"):
            made = runner.invoke(args=["users", "create", "--email", f"cli2.{tag}@example.com",
                                       "--name", "Cli", "--phone", fresh])
        self.assertEqual(made.exit_code, 0, made.output)
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == f"cli2.{tag}@example.com"))
        self.assertEqual(user.mobile_login, fresh)

    def test_unit_writer_search_survives_mobile_only_accounts(self):
        user = self._mobile_user()
        db.session.add(self._grant_row(
            user, R.reviewer,
            U, "P1"))
        db.session.commit()
        self._as("dm_c1")
        response = self.client.get("/data-management/api/users", query_string={"query": ""})
        self.assertEqual(response.status_code, 200)
        ids = {u["user_id"] for u in response.get_json()["users"]}
        self.assertIn(str(user.user_id), ids)
