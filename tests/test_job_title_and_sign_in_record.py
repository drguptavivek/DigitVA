"""Job title (digitva-04u4) and the web sign-in record (digitva-ci8).

Baselines: docs/policy/people-and-roles-page.md ("Job title", Gaps) and
docs/policy/authentication-factors.md section 9.
"""

import uuid
from datetime import UTC, datetime

import pyotp
import sqlalchemy as sa

from app import db
from app.models import AuthSecurityEvent, MasLanguages, VaUsers
from app.services import device_auth_service as devices
from app.services.token_service import generate_token
from app.services.user_account_service import UserAccountError, clean_job_title
from tests.authz.fixture import AuthzFixtureMixin
from tests.routes import test_device_api as device_tests
from tests.test_account_onboarding import OnboardingTestBase, _mailbox
from tests.test_factor_reset import FactorResetTestBase
from tests.test_mobile_sign_in import PASSWORD
from tests.test_passkey_login import PasskeyTestBase
from tests.test_totp_login import PASSWORD as TOTP_PASSWORD
from tests.test_totp_login import TotpTestBase

TITLE = "Chief Medical Officer, Faridabad"


def _events(user_id, event_type):
    return db.session.scalars(sa.select(AuthSecurityEvent).where(
        AuthSecurityEvent.user_id == user_id,
        AuthSecurityEvent.event_type == event_type,
    ).order_by(AuthSecurityEvent.occurred_at)).all()


def _refresh(user):
    db.session.expire_all()
    return db.session.get(VaUsers, user.user_id)


# -- job title: the validator ---------------------------------------------


class CleanJobTitleTests(OnboardingTestBase):
    def test_trims_and_clears(self):
        self.assertEqual(clean_job_title("  ANM, Sub-centre Rampur \n"), "ANM, Sub-centre Rampur")
        self.assertIsNone(clean_job_title(None))
        self.assertIsNone(clean_job_title("   "))

    def test_length_boundary(self):
        self.assertEqual(clean_job_title("x" * 120), "x" * 120)
        with self.assertRaises(UserAccountError):
            clean_job_title("x" * 121)

    def test_rejects_control_characters_and_non_text(self):
        # Cc, then Cf (bidi override, zero-width), Zl and Zp, then non-text.
        for bad in ("a\x00b", "a\nb", "a\tb", "a\x7fb", "a\u202eb", "a\u200bb",
                    "a\u2028b", "a\u2029b", 5, ["x"]):
            with self.assertRaises(UserAccountError, msg=repr(bad)):
                clean_job_title(bad)


# -- job title: every write path and the places it shows ------------------


class JobTitleWritePathTests(AuthzFixtureMixin, OnboardingTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if db.session.get(MasLanguages, "english") is None:
            db.session.add(MasLanguages(language_code="english", language_name="English",
                                        is_active=True))
        db.session.commit()

    def _create(self, payload_extra):
        email = f"jt.{uuid.uuid4().hex[:8]}@example.com"
        return email, {"email": email, "email_confirm": email, "name": "Title Person",
                       "languages": ["english"], **payload_extra}

    def test_admin_create_edit_and_clear(self):
        self._login(str(self.users["admin"].user_id))
        email, payload = self._create({"job_title": f"  {TITLE} "})
        made = self.client.post("/admin/api/users", json=payload, headers=self._csrf_headers())
        self.assertEqual(made.status_code, 201, made.get_json())
        self.assertEqual(made.get_json()["user"]["job_title"], TITLE)
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email))
        self.assertEqual(user.job_title, TITLE)

        url = f"/admin/api/users/{user.user_id}"
        edited = self.client.put(url, json={"job_title": "District Programme Officer"},
                                 headers=self._csrf_headers())
        self.assertEqual(edited.status_code, 200, edited.get_json())
        self.assertEqual(_refresh(user).job_title, "District Programme Officer")
        # An edit that omits the key keeps it.
        self.client.put(url, json={"name": "Renamed"}, headers=self._csrf_headers())
        self.assertEqual(_refresh(user).job_title, "District Programme Officer")
        cleared = self.client.put(url, json={"job_title": ""}, headers=self._csrf_headers())
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(_refresh(user).job_title)

    def test_admin_refuses_a_bad_title_on_create_and_edit(self):
        self._login(str(self.users["admin"].user_id))
        email, payload = self._create({"job_title": "x" * 121})
        refused = self.client.post("/admin/api/users", json=payload, headers=self._csrf_headers())
        self.assertEqual(refused.status_code, 400)
        self.assertIsNone(db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email)))
        target = self._email_user()
        for bad in ("a\nb", "x" * 121):
            response = self.client.put(f"/admin/api/users/{target.user_id}", json={"job_title": bad},
                                       headers=self._csrf_headers())
            self.assertEqual(response.status_code, 400)
        self.assertIsNone(_refresh(target).job_title)

    def test_admin_user_list_shows_it(self):
        target = self._email_user()
        target.job_title = TITLE
        db.session.commit()
        self._login(str(self.users["admin"].user_id))
        found = self.client.get(f"/admin/api/users?master=1&query={target.email}").get_json()["users"]
        self.assertEqual([u["job_title"] for u in found], [TITLE])

    def test_data_manager_create_edit_detail_lookup_and_grant_list(self):
        dm = self.users["dm_ta"]
        self._login(str(dm.user_id))
        email, payload = self._create({
            "job_title": TITLE, "initial_role": "coder", "initial_scope_type": "project",
            "initial_project_id": "AZTA01",
        })
        with _mailbox():
            made = self.client.post("/data-management/api/users", json=payload,
                                    headers=self._csrf_headers())
        self.assertEqual(made.status_code, 201, made.get_json())
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email))
        self.assertEqual(user.job_title, TITLE)

        edited = self.client.put(f"/data-management/api/users/{user.user_id}",
                                 json={"job_title": "Block Medical Officer"},
                                 headers=self._csrf_headers())
        self.assertEqual(edited.status_code, 200, edited.get_json())
        self.assertEqual(edited.get_json()["user"]["job_title"], "Block Medical Officer")
        bad = self.client.put(f"/data-management/api/users/{user.user_id}",
                              json={"job_title": "a\x00b"}, headers=self._csrf_headers())
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(_refresh(user).job_title, "Block Medical Officer")

        detail = self.client.get(f"/data-management/api/users/{user.user_id}").get_json()
        self.assertEqual(detail["user"]["job_title"], "Block Medical Officer")
        grants = self.client.get("/data-management/api/access-grants").get_json()["grants"]
        mine = [g for g in grants if g["user_id"] == str(user.user_id)]
        self.assertTrue(mine)
        self.assertEqual({g["user_job_title"] for g in mine}, {"Block Medical Officer"})

    def test_unit_writer_lookup_shows_it_without_phone(self):
        target = self._email_user()
        target.job_title = TITLE
        db.session.commit()
        self._login(str(self.users["dm_c1"].user_id))
        found = self.client.get(f"/data-management/api/users/lookup?value={target.email}")
        self.assertEqual(found.status_code, 200, found.get_json())
        [row] = found.get_json()["users"]
        self.assertEqual(row["job_title"], TITLE)
        self.assertNotIn("phone", row)

    def test_person_edits_their_own_in_profile(self):
        user = self._email_user()
        self._login(str(user.user_id))
        self.assertIsNone(self.client.get("/api/v1/profile/").get_json()["job_title"])
        saved = self.client.patch("/api/v1/profile/job-title", json={"job_title": f" {TITLE} "},
                                  headers=self._csrf_headers())
        self.assertEqual(saved.status_code, 200, saved.get_json())
        self.assertEqual(saved.get_json()["job_title"], TITLE)
        self.assertEqual(self.client.get("/api/v1/profile/").get_json()["job_title"], TITLE)
        bad = self.client.patch("/api/v1/profile/job-title", json={"job_title": "x" * 121},
                                headers=self._csrf_headers())
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(_refresh(user).job_title, TITLE)
        cleared = self.client.patch("/api/v1/profile/job-title", json={"job_title": None},
                                    headers=self._csrf_headers())
        self.assertEqual(cleared.status_code, 200)
        self.assertIsNone(_refresh(user).job_title)

    def test_profile_job_title_needs_the_key_and_an_object_body(self):
        user = self._email_user()
        self._login(str(user.user_id))
        saved = self.client.patch("/api/v1/profile/job-title", json={"job_title": TITLE},
                                  headers=self._csrf_headers())
        self.assertEqual(saved.status_code, 200)
        for body in ([TITLE], {}, {"title": "x"}):
            response = self.client.patch("/api/v1/profile/job-title", json=body,
                                         headers=self._csrf_headers())
            self.assertEqual(
                (response.status_code, response.get_json()["code"]), (400, "invalid_request"), body)
        self.assertEqual(_refresh(user).job_title, TITLE)
        bad = self.client.patch("/api/v1/profile/job-title", json={"job_title": "a\u202eb"},
                                headers=self._csrf_headers())
        self.assertEqual(bad.status_code, 400)

    def test_profile_edit_needs_csrf_and_a_session(self):
        user = self._email_user()
        self._login(str(user.user_id))
        self.assertEqual(self.client.patch("/api/v1/profile/job-title",
                                           json={"job_title": TITLE}).status_code, 400)
        self.assertIsNone(_refresh(user).job_title)

    def test_job_title_grants_nothing(self):
        user = self._email_user()
        user.job_title = "Administrator"
        db.session.commit()
        self._login(str(user.user_id))
        self.assertEqual(self.client.get("/admin/api/users").status_code, 403)


# -- sign-in record -------------------------------------------------------


class WebSignInRecordMixin:
    def _assert_one_sign_in(self, user, method, ip="127.0.0.1"):
        [event] = _events(user.user_id, "web_sign_in")
        self.assertEqual(event.detail, {"method": method} if ip is None else {"method": method, "ip": ip})
        stamped = _refresh(user).last_signed_in_at
        self.assertIsNotNone(stamped)
        self.assertIsNotNone(stamped.tzinfo)
        self.assertLessEqual((datetime.now(UTC) - stamped).total_seconds(), 60)


class PasswordSignInRecordTests(WebSignInRecordMixin, OnboardingTestBase):
    def test_password_sign_in_records_method_and_ip(self):
        user = self._email_user()
        self.assertIsNone(user.last_signed_in_at)
        self._login_via_form(user.email, PASSWORD)
        self.assertTrue(self._signed_in())
        self._assert_one_sign_in(user, "password")

    def test_ip_is_the_trusted_proxy_hop_not_a_client_supplied_value(self):
        user = self._email_user()
        # One trusted hop (ProxyFix x_for=1): the last address is the one the
        # ingress saw; anything the client put in front of it is ignored.
        self.client.environ_base["HTTP_X_FORWARDED_FOR"] = "198.51.100.7, 203.0.113.9"
        self._login_via_form(user.email, PASSWORD)
        self._assert_one_sign_in(user, "password", ip="203.0.113.9")

    def test_a_forwarded_value_that_is_not_an_address_is_not_stored(self):
        user = self._email_user()
        self.client.environ_base["HTTP_X_FORWARDED_FOR"] = "<script>alert(1)</script>"
        self._login_via_form(user.email, PASSWORD)
        self.assertTrue(self._signed_in())
        self._assert_one_sign_in(user, "password", ip=None)

    def test_failed_sign_in_writes_nothing(self):
        user = self._email_user()
        self._login_via_form(user.email, "wrong-password-1")
        self.assertFalse(self._signed_in())
        self.assertEqual(_events(user.user_id, "web_sign_in"), [])
        self.assertIsNone(_refresh(user).last_signed_in_at)

    def test_ip_never_reaches_the_application_log(self):
        user = self._email_user()
        self.client.environ_base["HTTP_X_FORWARDED_FOR"] = "203.0.113.77"
        with self.assertLogs(level="DEBUG") as logs:
            import logging
            logging.getLogger("app").debug("probe")  # assertLogs needs one record
            self._login_via_form(user.email, PASSWORD)
        self.assertFalse(any("203.0.113.77" in line for line in logs.output))


class SecondFactorSignInRecordTests(WebSignInRecordMixin, TotpTestBase):
    def test_nothing_is_written_until_the_second_factor_completes(self):
        secret = self._enroll_totp(self.user)
        step = self._login_via_form(self.user.email, TOTP_PASSWORD)
        self.assertIn("/second-factor", step.headers["Location"])
        self.assertEqual(_events(self.user.user_id, "web_sign_in"), [])
        self.assertIsNone(_refresh(self.user).last_signed_in_at)
        wrong = self.client.post(step.headers["Location"], data={"code": "000000"},
                                 headers=self._csrf_headers())
        self.assertEqual(wrong.status_code, 302)
        self.assertEqual(_events(self.user.user_id, "web_sign_in"), [])
        done = self.client.post(step.headers["Location"], data={"code": pyotp.TOTP(secret).now()},
                                headers=self._csrf_headers())
        self.assertEqual(done.status_code, 302)
        self._assert_one_sign_in(self.user, "second_factor")


class PasskeySignInRecordTests(WebSignInRecordMixin, PasskeyTestBase):
    def test_passkey_sign_in_records_method_and_ip(self):
        cred, priv = self._add_credential(self.user)
        resp = self._sign_in_with_credential(self.user.email, cred.credential_id, priv, sign_count=1)
        self.assertEqual(resp.status_code, 200, resp.data)
        self._assert_one_sign_in(self.user, "passkey")

    def test_refused_passkey_writes_nothing(self):
        cred, priv = self._add_credential(self.user)
        resp = self._sign_in_with_credential(self.user.email, cred.credential_id, priv,
                                             sign_count=1, uv=False)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(_events(self.user.user_id, "web_sign_in"), [])
        self.assertIsNone(_refresh(self.user).last_signed_in_at)


class FactorResetSignInRecordTests(WebSignInRecordMixin, FactorResetTestBase):
    def test_factor_reset_link_records_method_and_ip(self):
        token = generate_token(self.target.user_id, "factor_reset")
        resp = self.client.post(f"/vaauth/factor-reset/{token}", headers=self._csrf_headers())
        self.assertEqual(resp.status_code, 302)
        self._assert_one_sign_in(self.target, "factor_reset")


class DeviceSignInRecordTests(OnboardingTestBase):
    PROJECT_ID = "SIR01"
    SITE_ID = "SR01"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        device_tests.DeviceApiTests._make_project(cls.PROJECT_ID, cls.SITE_ID, datetime.now(UTC))
        cls.person = cls._get_or_make_user(f"signin.{uuid.uuid4().hex[:8]}@test.local", PASSWORD)
        device_tests.DeviceApiTests._grant(cls.person, cls.PROJECT_ID)
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.client = device_tests._FreshGClient(self.app, self.app.response_class, use_cookies=True)

    def _sign_in(self, password):
        _row, code = devices.create_enrolment_code(self.PROJECT_ID, actor=self.base_admin_user)
        db.session.commit()
        device = self.client.post("/api/v1/auth/enroll", json={
            "code": code, "device_name": "Record phone", "platform": "android",
        }).get_json()
        return self.client.post("/api/v1/auth/sessions", json={
            "device_id": device["device_id"], "device_secret": device["device_secret"],
            "email": self.person.email, "password": password,
        })

    def test_device_session_open_stamps_last_signed_in_and_a_refusal_does_not(self):
        self.person.last_signed_in_at = None
        db.session.commit()
        refused = self._sign_in("not-the-password")
        self.assertGreaterEqual(refused.status_code, 400)
        self.assertIsNone(_refresh(self.person).last_signed_in_at)
        opened = self._sign_in(PASSWORD)
        self.assertEqual(opened.status_code, 201, opened.get_json())
        stamped = _refresh(self.person).last_signed_in_at
        self.assertIsNotNone(stamped)
        self.assertLessEqual((datetime.now(UTC) - stamped).total_seconds(), 60)
        self.assertTrue(_events(self.person.user_id, "device_session_opened"))
        self.assertEqual(_events(self.person.user_id, "web_sign_in"), [])
