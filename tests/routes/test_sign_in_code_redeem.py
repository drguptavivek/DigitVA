"""App sign-in code redemption, POST /api/v1/auth/sign-in-code/redeem (digitva-42y3).

Baseline: docs/policy/mobile-sign-in.md section 3. The web page's redemption
(shared service) as JSON: one 401 for every mismatch, counted attempts, the
terms record, no-store, loose per-IP limits for a training room.
"""

import logging
import uuid
from datetime import UTC, datetime
from unittest import mock

import sqlalchemy as sa

from app import db
from app.models import AuthMobileCode, AuthSecurityEvent
from app.services import device_auth_service as devices
from app.services import mobile_sign_in_service as mobile
from app.services.authz.consulted import PUBLIC_ENDPOINTS
from tests.routes import test_device_api as device_tests
from tests.test_mobile_sign_in import PASSWORD_RE, MobileSignInTestBase, _number

URL = "/api/v1/auth/sign-in-code/redeem"
ENROL = "/api/v1/auth/password-enroll"
ENDPOINT = "api_v1.auth_api.redeem_sign_in_code"
_DEV = device_tests.DeviceApiTests.__dict__


class SignInCodeRedeemTests(MobileSignInTestBase):
    PROJECT_ID = "SCR01"
    _make_project = _DEV["_make_project"]
    _make_site = _DEV["_make_site"]
    _grant = _DEV["_grant"]

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._make_project(cls.PROJECT_ID, "SC01", datetime.now(UTC))
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)

    def _post(self, identifier, code, ip="127.0.0.1", **fields):
        body = {"identifier": identifier, "code": code, "accept_terms": True, **fields}
        return self.client.post(URL, json=body, environ_overrides={"REMOTE_ADDR": ip})

    def _new_user(self, **kwargs):
        """A mobile-only account that has never redeemed a code (no usable password)."""
        return self._mobile_user(redeemed=False, password=uuid.uuid4().hex, **kwargs)

    def _row(self, user):
        return db.session.scalar(sa.select(AuthMobileCode).where(AuthMobileCode.user_id == user.user_id))

    def test_success_returns_the_password_once_and_it_enrols_the_phone(self):
        user = self._new_user()
        self._grant(user, self.PROJECT_ID)
        db.session.commit()
        code = self._issue(user)
        response = self._post(f"+91 {user.mobile_login}", code)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["Pragma"], "no-cache")
        password = response.get_json()["password"]
        self.assertEqual(set(response.get_json()), {"password"})
        self.assertRegex(password, PASSWORD_RE)
        enrolled = self.client.post(ENROL, json={
            "identifier": user.mobile_login, "password": password,
            "device_name": "Phone", "platform": "android",
        })
        self.assertEqual(enrolled.status_code, 201, enrolled.get_json())
        self.assertEqual(enrolled.get_json()["user"]["user_id"], str(user.user_id))
        # The code works once.
        again = self._post(user.mobile_login, code)
        self.assertEqual((again.status_code, again.get_json()["code"]), (401, "invalid_code"))

    def test_wrong_code_counts_and_the_fifth_voids(self):
        user = self._new_user()
        code = self._issue(user)
        wrong = ("B" if code[0] == "A" else "A") + code[1:]
        for attempt in range(1, mobile.MAX_CODE_FAILURES + 1):
            response = self._post(user.mobile_login, wrong)
            self.assertEqual((response.status_code, response.get_json()["code"]), (401, "invalid_code"))
            db.session.expire_all()
            self.assertEqual(self._row(user).failed_attempts, attempt)
        self.assertIsNotNone(self._row(user).voided_at)
        self.assertEqual(self._post(user.mobile_login, code).status_code, 401)

    def test_unknown_number_wrong_and_expired_code_share_one_answer(self):
        user = self._new_user()
        code = self._issue(user)
        wrong = ("B" if code[0] == "A" else "A") + code[1:]
        answers = [self._post(user.mobile_login, wrong), self._post(_number(), code),
                   self._post("nobody@example.invalid", code)]
        expired = self._new_user()
        expired_code = self._issue(expired)
        db.session.execute(sa.update(AuthMobileCode).where(AuthMobileCode.user_id == expired.user_id)
                           .values(issued_at=datetime(2026, 1, 1, tzinfo=UTC),
                                   expires_at=datetime(2026, 1, 1, 1, tzinfo=UTC)))
        db.session.commit()
        answers.append(self._post(expired.mobile_login, expired_code))
        self.assertEqual({(r.status_code, r.get_data(as_text=True)) for r in answers},
                         {(401, answers[0].get_data(as_text=True))})
        self.assertEqual(answers[0].get_json()["code"], "invalid_code")

    def test_lowercase_dashless_and_legacy_six_digit_codes_redeem(self):
        user = self._new_user()
        code = self._issue(user)
        self.assertEqual(self._post(user.mobile_login, code.replace("-", "").lower()).status_code, 200)
        legacy = self._new_user()
        self._issue(legacy)
        db.session.execute(sa.update(AuthMobileCode).where(AuthMobileCode.user_id == legacy.user_id)
                           .values(code_hash=mobile._code_hash(legacy.user_id, "123456")))
        db.session.commit()
        self.assertEqual(self._post(legacy.mobile_login, "123456").status_code, 200)

    def test_terms_are_required_before_anything_is_counted_and_recorded_on_success(self):
        user = self._new_user()
        user.pw_reset_t_and_c = False
        db.session.commit()
        code = self._issue(user)
        for terms in (False, None, "true", 1):
            response = self._post(user.mobile_login, code, accept_terms=terms)
            self.assertEqual(response.status_code, 400, terms)
            self.assertEqual(response.get_json()["code"], "invalid_request")
            self.assertEqual(response.get_json()["fields"], ["accept_terms"])
        missing = self.client.post(URL, json={"identifier": user.mobile_login, "code": code})
        self.assertEqual(missing.status_code, 400)
        for bad in ({"identifier": None}, {"code": ""}, {"code": "X" * 33}, {"identifier": 98765}):
            fields = {"identifier": user.mobile_login, "code": code, **bad}
            self.assertEqual(self._post(**fields).status_code, 400, bad)
        db.session.expire_all()
        self.assertEqual(self._row(user).failed_attempts, 0)
        self.assertIsNone(self._row(user).redeemed_at)
        self.assertEqual(self._post(user.mobile_login, code).status_code, 200)
        db.session.refresh(user)
        self.assertTrue(user.pw_reset_t_and_c)
        self.assertTrue(db.session.scalar(sa.select(sa.exists().where(
            AuthSecurityEvent.user_id == user.user_id,
            AuthSecurityEvent.event_type == "terms_accepted"))))

    def test_email_on_file_gets_the_notice(self):
        user = self._new_user()
        user.email = f"code.{uuid.uuid4().hex[:8]}@test.local"
        db.session.commit()
        code = self._issue(user)
        with mock.patch("app.services.email_service.send_code_redeemed_notice") as notice:
            response = self._post(user.email, code)
        self.assertEqual(response.status_code, 200, response.get_json())
        notice.assert_called_once()
        self.assertEqual(notice.call_args.args[0].user_id, user.user_id)

    def test_breach_outage_is_retryable_and_counts_nothing(self):
        user = self._new_user()
        code = self._issue(user)
        with mock.patch.object(mobile, "password_breach_error_message",
                               return_value=mobile.BREACH_CHECK_UNAVAILABLE_MESSAGE):
            response = self._post(user.mobile_login, code)
        self.assertEqual((response.status_code, response.get_json()["code"]), (503, "breach_check_unavailable"))
        row = self._row(user)
        self.assertEqual((row.failed_attempts, row.redeemed_at), (0, None))

    def test_a_training_room_on_one_address_is_not_throttled(self):
        """About 30 phones on one Wi-Fi address (field sign-in 2026-11-16),
        each with three typos before the right code: nobody is refused."""
        people = [(user, self._issue(user)) for user in (self._new_user() for _ in range(30))]
        statuses = []
        for user, code in people:
            wrong = ("B" if code[0] == "A" else "A") + code[1:]
            statuses += [self._post(user.mobile_login, wrong, ip="10.77.0.1").status_code for _ in range(3)]
            statuses.append(self._post(user.mobile_login, code, ip="10.77.0.1").status_code)
        self.assertEqual(statuses.count(429), 0)
        self.assertEqual(statuses.count(200), 30)

    def test_rate_limited_per_identifier_across_addresses_and_per_address(self):
        number = self._new_user().mobile_login
        statuses = [self._post(number if i % 2 else f"+91 {number}", "AAAA-AAAA", ip=f"10.78.0.{i + 1}").status_code
                    for i in range(11)]
        self.assertEqual(statuses, [401] * 10 + [429])
        # Wrong codes from one address: their own budget of 100 per 10 minutes.
        statuses = [self._post(_number(), "AAAA-AAAA", ip="10.79.0.1").status_code for _ in range(101)]
        self.assertEqual(statuses, [401] * 100 + [429])

    def test_requests_that_are_not_wrong_codes_do_not_lock_a_person_out(self):
        user = self._new_user()
        code = self._issue(user)
        # A stranger's malformed requests (400) for this number are not counted.
        for _ in range(12):
            self.assertEqual(self.client.post(URL, json={"identifier": user.mobile_login, "code": code}).status_code, 400)
        self.assertEqual(self._post(user.mobile_login, code).status_code, 200)

    def test_registered_as_unauthenticated_and_public(self):
        self.assertIn(ENDPOINT, devices.UNAUTHENTICATED_ENDPOINTS)
        self.assertIn(ENDPOINT, PUBLIC_ENDPOINTS)
        user = self._new_user()
        code = self._issue(user)
        # A stale bearer and CSRF on: the app's call still answers.
        with mock.patch.dict(self.app.config, WTF_CSRF_ENABLED=True):
            response = self.client.post(URL, json={
                "identifier": user.mobile_login, "code": code, "accept_terms": True,
            }, headers={"Authorization": "Bearer stale-access-token"})
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_public_demo_deployment_has_no_code_redemption(self):
        user = self._new_user()
        code = self._issue(user)
        with mock.patch.dict(self.app.config, PUBLIC_DEMO_ENABLED=True):
            self.assertEqual(self._post(user.mobile_login, code).status_code, 404)
        self.assertIsNone(self._row(user).redeemed_at)

    def test_code_and_password_are_absent_from_logs(self):
        user = self._new_user()
        code = self._issue(user)
        with self.assertLogs("app", level="INFO") as captured:
            logging.getLogger("app").info("sign-in code test marker")
            self._post(user.mobile_login, "AAAA-AAAA")
            password = self._post(user.mobile_login, code).get_json()["password"]
        text = "\n".join(captured.output)
        self.assertIn("sign-in code test marker", text)
        for secret in (code, code.replace("-", ""), password, user.mobile_login):
            self.assertNotIn(secret, text)
