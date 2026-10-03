"""Server-generated passwords for every account (digitva-kmoy).

Baseline: docs/policy/account-onboarding-and-passwords.md. Covers the
password email (password and login address only, sent synchronously, never
logged), email verification (emails a password once, never replaces a usable
one), the reset link (emails a new password, no password box), forgot
password by email or mobile, Profile "Generate a new password" for email
accounts, that every chosen-password path is gone (profile change, admin
edit, reset form fields, CLI options), admin "send a password reset link",
sign-in codes for email accounts, the CLI, the project user import with
mobile-only rows and mentoring-institute mobile-only staff.
"""

import logging
import re
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from unittest.mock import patch

import sqlalchemy as sa

from app import db, limiter
from app.models import (
    AuthSecurityEvent,
    MasMentorInstitute,
    VaProjectMaster,
    VaStatuses,
    VaUsers,
)
from app.services import mobile_sign_in_service as mobile
from app.services import project_user_import_service as user_import
from app.services.token_service import generate_token
from tests.authz.fixture import TA, AuthzFixtureMixin, P, R, U
from tests.test_mobile_sign_in import PASSWORD, PASSWORD_RE, MobileSignInTestBase, _number

PASSWORD_IN_TEXT = re.compile(r"\b[a-z]{4,7}-[a-z]{4,7}-[a-z]{4,7}-\d{4}\b")
PASSWORD_SUBJECT = "Your DigitVA password"
LOGIN_PATH = "/vaauth/valogin"
EMAILED = b"Your password has been emailed to you"


class _LogCapture(logging.Handler):
    """Every log line, formatted with any traceback, at any level."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(logging.Formatter().format(record))


@contextmanager
def _captured_logs():
    root = logging.getLogger()
    handler, level = _LogCapture(), root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield handler.lines
    finally:
        root.removeHandler(handler)
        root.setLevel(level)


@contextmanager
def _mailbox():
    """Synchronous sends land in the returned mock; queued (Celery) mails go
    to ``mailbox.queued`` instead of a broker."""
    with patch("app.services.email_service.is_mail_configured", return_value=True), \
            patch("app.services.email_service.mail.send") as send, \
            patch("app.services.email_service._dispatch_email") as dispatch:
        send.queued = dispatch.delay
        yield send


def _password_mails(send):
    return [call.args[0] for call in send.call_args_list
            if call.args[0].subject == PASSWORD_SUBJECT]


def _emailed_password(test, send, email):
    mails = _password_mails(send)
    test.assertEqual(len(mails), 1, [m.subject for m in mails])
    test.assertEqual(mails[0].recipients, [email])
    match = PASSWORD_IN_TEXT.search(mails[0].body)
    test.assertIsNotNone(match, mails[0].body)
    return match.group(0)


class OnboardingTestBase(MobileSignInTestBase):
    def _email_user(self, *, verified=True, onboarded=True, password=PASSWORD, phone=None):
        email = f"onboard.{uuid.uuid4().hex[:10]}@example.com"
        user = VaUsers(
            user_id=uuid.uuid4(), name="Email Person", email=email, phone=phone,
            mobile_login=phone, vacode_language=["English"], permission={},
            landing_page="coder", pw_reset_t_and_c=onboarded, email_verified=verified,
            user_status=VaStatuses.active,
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    def _events(self, user, event_type):
        return db.session.scalars(sa.select(AuthSecurityEvent).where(
            AuthSecurityEvent.user_id == user.user_id,
            AuthSecurityEvent.event_type == event_type,
        )).all()


class PasswordEmailTests(OnboardingTestBase):
    def test_carries_only_the_password_and_the_login_address(self):
        from app.services.email_service import login_page_url, send_password_email

        user = self._email_user()
        with _mailbox() as send:
            send_password_email(user, "river-mango-lamp-4821")
        message = send.call_args.args[0]
        self.assertEqual(message.subject, PASSWORD_SUBJECT)
        self.assertEqual(message.recipients, [user.email])
        login = login_page_url()
        self.assertTrue(login.endswith(LOGIN_PATH))
        for part in (message.body, message.html):
            self.assertIn("river-mango-lamp-4821", part)
            self.assertIn(login, part)
            self.assertEqual(set(re.findall(r"https?://[^\s\"'<>]+", part)), {login})
            self.assertNotIn(user.email, part)
            self.assertNotIn(user.name, part)

    def test_refuses_when_mail_is_not_configured(self):
        from app.services.email_service import send_password_email

        with patch("app.services.email_service.is_mail_configured", return_value=False), \
                patch("app.services.email_service.mail.send") as send, self.assertRaises(RuntimeError):
            send_password_email(self._email_user(), "river-mango-lamp-4821")
        send.assert_not_called()

    def test_is_never_queued(self):
        """The password must not sit in the Celery broker."""
        from app.services.email_service import send_password_email

        with _mailbox() as send:
            send_password_email(self._email_user(), "river-mango-lamp-4821")
        send.queued.assert_not_called()


class EmailVerificationTests(OnboardingTestBase):
    def _url(self, user):
        return f"/vaauth/verify-email/{generate_token(user.user_id, 'email_verify')}"

    def _confirm(self, url):
        return self.client.post(url, headers=self._csrf_headers(), follow_redirects=False)

    def test_opening_the_link_changes_nothing(self):
        user = self._email_user(verified=False, onboarded=False)
        with _mailbox() as send:
            page = self.client.get(self._url(user))
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"<form", page.data)
        self.assertNotIn(b'type="password"', page.data)
        send.assert_not_called()
        db.session.refresh(user)
        self.assertFalse(user.email_verified)
        self.assertTrue(user.check_password(PASSWORD))

    def test_new_account_gets_its_password_by_email_once(self):
        user = self._email_user(verified=False, onboarded=False)
        version = user.auth_session_version or 0
        url = self._url(user)
        with _captured_logs() as logs, _mailbox() as send:
            response = self._confirm(url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers["Location"].split("?")[0], LOGIN_PATH)
            page = self.client.get(response.headers["Location"])
            again = self._confirm(url)
        self.assertIn(EMAILED, page.data)
        password = _emailed_password(self, send, user.email)
        self.assertRegex(password, PASSWORD_RE)
        self.assertNotIn(password.encode(), page.data)
        self.assertEqual(again.status_code, 302)
        db.session.refresh(user)
        self.assertTrue(user.email_verified)
        self.assertTrue(user.check_password(password))
        self.assertFalse(user.check_password(PASSWORD))
        self.assertEqual(user.auth_session_version, version + 1)
        self.assertFalse(any(password in line for line in logs))
        [event] = self._events(user, "password_generated")
        self.assertEqual(event.detail, {"path": "email_verification"})
        self.assertNotIn(password, str(event.detail))
        self._fresh_client()
        self._login_via_form(user.email, password)
        self.assertTrue(self._signed_in())

    def test_existing_password_is_never_replaced(self):
        """Policy 5.3: an existing user verifying a changed email, or a
        mobile account that redeemed a code and then added an email."""
        changed = self._email_user(verified=False, onboarded=True)
        redeemed = self._email_user(verified=False, onboarded=False, phone=_number())
        redeemed.mobile_verified_at = datetime.now(UTC)
        db.session.commit()
        for user in (changed, redeemed):
            with self.subTest(user=user.email), _mailbox() as send:
                response = self._confirm(self._url(user))
                self.assertEqual(response.status_code, 302)
                self.assertEqual(_password_mails(send), [])
                db.session.refresh(user)
                self.assertTrue(user.email_verified)
                self.assertTrue(user.check_password(PASSWORD))
                self.assertNotIn(EMAILED, self.client.get(response.headers["Location"]).data)

    def test_breach_outage_and_mail_failure_change_nothing(self):
        user = self._email_user(verified=False, onboarded=False)
        url = self._url(user)
        with patch.object(mobile, "password_breach_error_message",
                          return_value=mobile.BREACH_CHECK_UNAVAILABLE_MESSAGE), _mailbox() as send:
            outage = self._confirm(url)
        self.assertEqual(outage.status_code, 302)
        self.assertIn(b"try again", self.client.get(outage.headers["Location"]).data.lower())
        self.assertEqual(_password_mails(send), [])
        with _mailbox() as send:
            send.side_effect = OSError("smtp down")
            self._confirm(url)
        for _ in range(2):
            db.session.refresh(user)
            self.assertFalse(user.email_verified)
            self.assertTrue(user.check_password(PASSWORD))
        # The link still works once the mail is back.
        with _mailbox() as send:
            self._confirm(url)
        _emailed_password(self, send, user.email)

    def test_invitation_sends_only_the_verification_link(self):
        from app.services.user_account_service import send_invitation

        user = self._email_user(verified=False, onboarded=False)
        with _mailbox() as send:
            send_invitation(user)
        self.assertEqual(send.queued.call_count, 1)
        kwargs = send.queued.call_args.kwargs
        self.assertEqual(kwargs["template_name"], "emails/verify_email")
        self.assertIn("/vaauth/verify-email/", kwargs["context"]["verify_url"])


class PasswordResetTests(OnboardingTestBase):
    def _url(self, user):
        return f"/vaauth/reset-password/{generate_token(user.user_id, 'password_reset')}"

    def test_reset_link_emails_a_new_password_and_works_once(self):
        user = self._email_user()
        version = user.auth_session_version or 0
        url = self._url(user)
        page = self.client.get(url)
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b'type="password"', page.data)
        db.session.refresh(user)
        self.assertTrue(user.check_password(PASSWORD))  # GET changes nothing
        with _captured_logs() as logs, _mailbox() as send:
            # A chosen password in the old form fields is ignored.
            response = self.client.post(url, data={
                "new_password": "Chosen1Password!x", "confirm_password": "Chosen1Password!x"},
                headers=self._csrf_headers())
            self.assertEqual(response.status_code, 302)
            self.assertIn(EMAILED, self.client.get(response.headers["Location"]).data)
            spent = self.client.post(url, headers=self._csrf_headers())
        password = _emailed_password(self, send, user.email)
        self.assertFalse(any(password in line for line in logs))
        self.assertIn(b"invalid or has expired", spent.data)
        db.session.refresh(user)
        self.assertTrue(user.check_password(password))
        self.assertFalse(user.check_password(PASSWORD))
        self.assertFalse(user.check_password("Chosen1Password!x"))
        self.assertEqual(user.auth_session_version, version + 1)
        self.assertFalse(user.pw_reset_t_and_c)
        [event] = self._events(user, "password_generated")
        self.assertEqual(event.detail, {"path": "password_reset"})

    def test_mobile_only_account_reset_link_changes_nothing(self):
        user = self._mobile_user()
        url = f"/vaauth/reset-password/{generate_token(user.user_id, 'password_reset')}"
        with _mailbox() as send:
            self.client.post(url, headers=self._csrf_headers())
        send.assert_not_called()
        db.session.refresh(user)
        self.assertTrue(user.check_password(PASSWORD))

    def _forgot(self, value):
        return self.client.post("/vaauth/forgot-password", data={"email": value},
                                headers=self._csrf_headers(), follow_redirects=True)

    def test_forgot_password_sends_a_link_only_to_a_verified_email(self):
        number = _number()
        verified = self._email_user(phone=number)
        unverified = self._email_user(verified=False)
        mobile_only = self._mobile_user()
        with _mailbox() as send:
            pages = {}
            for value in (verified.email, unverified.email, "nobody@example.com"):
                pages[value] = self._forgot(value).data
            self.assertEqual(send.queued.call_count, 1)
            self.assertEqual(send.queued.call_args.kwargs["to"], verified.email)
            self.assertEqual(len(set(pages.values())), 1)
            send.queued.reset_mock()
            limiter.reset()  # three tries an hour per IP
            mobile_pages = {self._forgot(v).data for v in
                            (f"+91 {number}", mobile_only.mobile_login, _number())}
            self.assertEqual(send.queued.call_count, 1)
            self.assertEqual(send.queued.call_args.kwargs["to"], verified.email)
            self.assertEqual(len(mobile_pages), 1)
            self.assertIn(b"ask your data manager", next(iter(mobile_pages)))
        send.assert_not_called()  # nothing synchronous: no password was sent
        for user in (verified, unverified, mobile_only):
            db.session.refresh(user)
            self.assertTrue(user.check_password(PASSWORD))


class ChosenPasswordPathsGoneTests(AuthzFixtureMixin, OnboardingTestBase):
    def test_profile_password_change_is_gone(self):
        user = self._email_user()
        self._login(user.get_id())
        response = self.client.patch("/api/v1/profile/password", json={
            "current_password": PASSWORD, "new_password": "Another1Pass!x",
            "confirm_password": "Another1Pass!x"}, headers=self._csrf_headers())
        self.assertGreaterEqual(response.status_code, 400)
        self.assertLess(response.status_code, 500)
        db.session.refresh(user)
        self.assertTrue(user.check_password(PASSWORD))

    def test_profile_page_has_no_new_password_box(self):
        user = self._email_user()
        self._login(user.get_id())
        page = self.client.get("/profile/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"genpw-btn", page.data)
        self.assertNotIn(b'autocomplete="new-password"', page.data)

    def test_admin_cannot_set_a_password(self):
        user = self._email_user()
        self._login(str(self.users["admin"].user_id))
        response = self.client.put(f"/admin/api/users/{user.user_id}",
                                   json={"password": "Chosen1Password!x"},
                                   headers=self._csrf_headers())
        self.assertEqual(response.status_code, 400)
        db.session.refresh(user)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertFalse(user.check_password("Chosen1Password!x"))

    def test_admin_user_form_has_no_password_box(self):
        from pathlib import Path

        root = Path(self.app.root_path)
        for name in ("templates/admin/panels/users.html", "static/js/admin/users_panel.js"):
            source = (root / name).read_text()
            self.assertIn("user-name-input", source)
            self.assertNotIn("user-password-input", source)

    def test_cli_password_options_are_gone(self):
        runner = self.app.test_cli_runner()
        user = self._email_user()
        reset = runner.invoke(args=["users", "reset-password", "--email", user.email,
                                    "--password", "Chosen1Password!x"])
        self.assertEqual(reset.exit_code, 2)
        create = runner.invoke(args=["users", "create", "--email", "x@example.com",
                                     "--name", "X", "--password", "Chosen1Password!x"])
        self.assertEqual(create.exit_code, 2)
        db.session.refresh(user)
        self.assertTrue(user.check_password(PASSWORD))


class ProfileGenerateTests(OnboardingTestBase):
    URL = "/api/v1/profile/password/generate"

    def test_email_account_gets_the_new_password_by_email(self):
        user = self._email_user()
        self._login(user.get_id())
        self.assertEqual(self.client.post(self.URL, headers=self._csrf_headers()).status_code, 401)
        with self.client.session_transaction() as sess:
            sess["auth_verified_at"] = datetime.now(UTC).isoformat()
        with _captured_logs() as logs, _mailbox() as send:
            response = self.client.post(self.URL, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertNotIn("password", response.get_json())
        password = _emailed_password(self, send, user.email)
        self.assertNotIn(password.encode(), response.data)
        self.assertFalse(any(password in line for line in logs))
        db.session.refresh(user)
        self.assertTrue(user.check_password(password))
        [event] = self._events(user, "password_generated")
        self.assertEqual(event.detail, {"path": "profile"})
        self._forget_cached_user()
        self.assertNotEqual(self.client.get("/profile/").status_code, 200)

    def test_mail_failure_keeps_the_old_password(self):
        user = self._email_user()
        self._login(user.get_id())
        with self.client.session_transaction() as sess:
            sess["auth_verified_at"] = datetime.now(UTC).isoformat()
        with _mailbox() as send:
            send.side_effect = OSError("smtp down")
            response = self.client.post(self.URL, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 503)
        db.session.refresh(user)
        self.assertTrue(user.check_password(PASSWORD))

    def test_unverified_email_sees_the_password_once_instead(self):
        """A mobile account with an email still awaiting verification is
        never mailed a password at that unproven address."""
        user = self._email_user(verified=False, phone=_number())
        user.mobile_verified_at = datetime.now(UTC)
        db.session.commit()
        self._login(user.get_id())
        with self.client.session_transaction() as sess:
            sess["auth_verified_at"] = datetime.now(UTC).isoformat()
        with _mailbox() as send:
            response = self.client.post(self.URL, headers=self._csrf_headers())
        self.assertEqual(response.status_code, 200)
        self.assertRegex(response.get_json()["password"], PASSWORD_RE)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        send.assert_not_called()


class AdminSendResetLinkTests(AuthzFixtureMixin, OnboardingTestBase):
    def _send(self, user):
        return self.client.post(f"/admin/api/users/{user.user_id}/send-password-reset",
                                headers=self._csrf_headers())

    def test_admin_sends_a_reset_link_never_a_password(self):
        user = self._email_user()
        self._login(str(self.users["admin"].user_id))
        with _mailbox() as send:
            response = self._send(user)
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(send.queued.call_args.kwargs["to"], user.email)
        self.assertIn("/vaauth/reset-password/", send.queued.call_args.kwargs["context"]["reset_url"])
        send.assert_not_called()
        db.session.refresh(user)
        self.assertTrue(user.check_password(PASSWORD))

    def test_refused_without_a_verified_email_or_for_non_admins(self):
        self._login(str(self.users["admin"].user_id))
        with _mailbox() as send:
            self.assertEqual(self._send(self._mobile_user()).status_code, 400)
            self.assertEqual(self._send(self._email_user(verified=False)).status_code, 400)
            self._login(str(self.users["dm_c1"].user_id))
            self.assertEqual(self._send(self._email_user()).status_code, 403)
        send.queued.assert_not_called()

    def test_undeliverable_link_is_reported_not_claimed(self):
        self._login(str(self.users["admin"].user_id))
        with _mailbox(), patch("app.services.email_service._email_delivery_enabled",
                               return_value=False):
            self.assertEqual(self._send(self._email_user()).status_code, 400)


class EmailAccountCodeTests(AuthzFixtureMixin, OnboardingTestBase):
    def _managed_email_user(self, *grants, verified=False):
        user = self._email_user(verified=verified, onboarded=False)
        db.session.add_all([self._grant_row(user, *g) for g in grants])
        db.session.commit()
        return user

    def test_dm_issues_a_code_for_a_managed_unverified_email_account_and_it_redeems_by_email(self):
        user = self._managed_email_user((R.reviewer, U, "P1"))
        self._login(str(self.users["dm_c1"].user_id))
        issued = self.client.post(f"/data-management/api/users/{user.user_id}/sign-in-code",
                                  headers=self._csrf_headers())
        self.assertEqual(issued.status_code, 200, issued.get_json())
        code = issued.get_json()["sign_in_code"]
        self._fresh_client()
        with _mailbox() as send:
            response = self._redeem(user.email.upper(), code)
        send.assert_not_called()  # nothing synchronous: no password is mailed
        # A notice goes to the address on file: no password, no code.
        send.queued.assert_called_once()
        notice = send.queued.call_args.kwargs
        self.assertEqual(notice["to"], user.email)
        self.assertEqual(notice["template_name"], "emails/code_redeemed")
        self.assertEqual(set(notice["context"]), {"name"})
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        password = self._password_from(response)
        from flask import render_template

        with self.app.test_request_context():
            rendered = render_template("emails/code_redeemed.txt", **notice["context"]) + \
                render_template("emails/code_redeemed.html", **notice["context"])
        self.assertIn("sign-in code", rendered)
        self.assertNotIn(password, rendered)
        self.assertNotIn(code, rendered)
        self._fresh_client()
        self._login_via_form(user.email, password)
        self.assertTrue(self._signed_in())
        [event] = self._events(user, "password_generated")
        self.assertEqual(event.detail, {"path": "sign_in_code"})

    def test_verified_email_accounts_get_codes_only_from_an_admin(self):
        """Security review: a DM must not take over a verified email account
        by redeeming a code they issued; it resets by email instead."""
        verified = self._managed_email_user((R.reviewer, U, "P1"), verified=True)
        unverified = self._managed_email_user((R.reviewer, U, "P1"))
        mobile_only = self._mobile_user()
        db.session.add(self._grant_row(mobile_only, R.reviewer, U, "P1"))
        db.session.commit()
        dm = self.users["dm_c1"]
        self.assertFalse(mobile.may_issue_code(dm, verified.user_id))
        self.assertTrue(mobile.may_issue_code(dm, unverified.user_id))
        self.assertTrue(mobile.may_issue_code(dm, mobile_only.user_id))
        self.assertTrue(mobile.may_issue_code(self.users["admin"], verified.user_id))
        self._login(str(dm.user_id))
        refused = self.client.post(f"/data-management/api/users/{verified.user_id}/sign-in-code",
                                   headers=self._csrf_headers())
        self.assertEqual(refused.status_code, 404)
        self._login(str(self.users["admin"].user_id))
        allowed = self.client.post(f"/admin/api/users/{verified.user_id}/sign-in-code",
                                   headers=self._csrf_headers())
        self.assertEqual(allowed.status_code, 200)

    def test_mobile_only_redeem_sends_no_notice(self):
        user = self._mobile_user()
        code = self._issue(user)
        with _mailbox() as send:
            self._password_from(self._redeem(user.mobile_login, code))
        send.queued.assert_not_called()
        send.assert_not_called()

    def test_privileged_or_partly_managed_email_accounts_are_refused(self):
        peer = self._managed_email_user((R.data_manager, U, "C1"))
        partial = self._managed_email_user((R.reviewer, U, "P1"), (R.reviewer, P, TA))
        for user in (peer, partial):
            self.assertFalse(mobile.may_issue_code(self.users["dm_c1"], user.user_id))
            self.assertTrue(mobile.may_issue_code(self.users["admin"], user.user_id))

    def test_unknown_email_and_wrong_code_get_the_same_answer(self):
        user = self._managed_email_user((R.reviewer, U, "P1"))
        code = self._issue(user)
        wrong = f"{(int(code) + 1) % 1_000_000:06d}"
        def alerts(response):
            return re.findall(rb'role="alert">\s*([^<]+?)\s*<', response.data)

        a = alerts(self._redeem(user.email, wrong))
        self._fresh_client()
        b = alerts(self._redeem("nobody@example.com", code))
        self.assertTrue(a and b"do not match" in a[0], a)
        self.assertEqual(a, b)
        self.assertIsNotNone(mobile.redeem_code(user.email, code))


class CliTests(OnboardingTestBase):
    def setUp(self):
        super().setUp()
        self.runner = self.app.test_cli_runner()

    def test_reset_password_prints_a_generated_password_once_and_ends_sessions(self):
        user = self._email_user()
        version = user.auth_session_version or 0
        with _captured_logs() as logs:
            result = self.runner.invoke(args=["users", "reset-password", "--email", user.email])
        self.assertEqual(result.exit_code, 0, result.output)
        printed = PASSWORD_IN_TEXT.findall(result.output)
        self.assertEqual(len(printed), 1, result.output)
        self.assertFalse(any(printed[0] in line for line in logs))
        db.session.refresh(user)
        self.assertTrue(user.check_password(printed[0]))
        self.assertEqual(user.auth_session_version, version + 1)

    def test_reset_password_by_mobile_and_breach_outage(self):
        user = self._mobile_user()
        with patch.object(mobile, "password_breach_error_message",
                          return_value=mobile.BREACH_CHECK_UNAVAILABLE_MESSAGE):
            down = self.runner.invoke(args=["users", "reset-password", "--mobile", user.mobile_login])
        self.assertNotEqual(down.exit_code, 0)
        db.session.refresh(user)
        self.assertTrue(user.check_password(PASSWORD))
        ok = self.runner.invoke(args=["users", "reset-password", "--mobile", f"+91{user.mobile_login}"])
        self.assertEqual(ok.exit_code, 0, ok.output)
        db.session.refresh(user)
        self.assertTrue(user.check_password(PASSWORD_IN_TEXT.search(ok.output).group(0)))

    def test_create_mobile_only_prints_once_and_signs_in(self):
        number = _number()
        result = self.runner.invoke(args=["users", "create", "--name", "Cli Mobile",
                                          "--phone", number])
        self.assertEqual(result.exit_code, 0, result.output)
        printed = PASSWORD_IN_TEXT.findall(result.output)
        self.assertEqual(len(printed), 1, result.output)
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.mobile_login == number))
        self.assertIsNone(user.email)
        self.assertIsNotNone(user.mobile_verified_at)
        self._login_via_form(number, printed[0])
        self.assertTrue(self._signed_in())

    def test_create_email_account_never_prints_a_password(self):
        tag = uuid.uuid4().hex[:8]
        with patch("app.services.user_account_service.send_invitation") as invite:
            pending = self.runner.invoke(args=["users", "create", "--email", f"cli.p.{tag}@example.com",
                                               "--name", "Pending"])
        self.assertEqual(pending.exit_code, 0, pending.output)
        invite.assert_called_once()
        self.assertIsNone(PASSWORD_IN_TEXT.search(pending.output))
        with _mailbox() as send:
            verified = self.runner.invoke(args=["users", "create", "--email", f"cli.v.{tag}@example.com",
                                                "--name", "Verified", "--email-verified"])
        self.assertEqual(verified.exit_code, 0, verified.output)
        self.assertIsNone(PASSWORD_IN_TEXT.search(verified.output))
        password = _emailed_password(self, send, f"cli.v.{tag}@example.com")
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == f"cli.v.{tag}@example.com"))
        self.assertTrue(user.check_password(password))

    def test_create_needs_an_email_or_a_mobile(self):
        result = self.runner.invoke(args=["users", "create", "--name", "Nobody"])
        self.assertNotEqual(result.exit_code, 0)


class ImportAndMentorTests(AuthzFixtureMixin, OnboardingTestBase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from app.models.mas_languages import MasLanguages

        if db.session.get(MasLanguages, "english") is None:
            db.session.add(MasLanguages(language_code="english", language_name="English",
                                        is_active=True))
        db.session.commit()

    def _row(self, n, email, phone, role="reviewer"):
        return {"_line_number": n, "email": email, "name": "Imported", "role": role,
                "org_unit_code": "P1", "cadre_code": "", "language_codes": "english",
                "phone": phone}

    def _organization(self):
        db.session.get(VaProjectMaster, TA).project_structure_mode = "organization"
        db.session.flush()

    def test_import_creates_mobile_only_accounts_with_a_code(self):
        self._organization()
        admin = self.users["admin"]
        fresh, held = _number(), _number()
        # Held only as another account's free-text phone: never a sign-in
        # number, so it names nobody and cannot be given to a new account.
        self._email_user().phone = f"0{held}"
        db.session.commit()
        for bad in ("", "12345", held):
            with self.subTest(phone=bad), self.assertRaises(user_import.ProjectUserImportError):
                user_import.prepare(TA, [self._row(2, "", bad)], actor=admin)
        plan = user_import.prepare(TA, [self._row(2, "", f"+91 {fresh}")], actor=admin)
        _invitations, _audit, codes = user_import.apply(TA, plan, actor_user_id=admin.user_id)
        db.session.flush()
        made = db.session.scalar(sa.select(VaUsers).where(VaUsers.mobile_login == fresh))
        self.assertIsNone(made.email)
        self.assertEqual(len(codes), 1)
        self.assertEqual(codes[0]["mobile"], "******" + fresh[-4:])
        self.assertIsNotNone(mobile.redeem_code(fresh, codes[0]["sign_in_code"]))

    def test_import_matches_an_existing_mobile_only_account(self):
        self._organization()
        existing = self._mobile_user()
        plan = user_import.prepare(TA, [self._row(2, "", existing.mobile_login)],
                                   actor=self.users["admin"])
        self.assertEqual(plan[0]["user"].user_id, existing.user_id)
        self.assertEqual(plan[0]["action"], "grant")

    def test_project_pi_cannot_create_a_mobile_only_account(self):
        self._organization()
        pi = self.users["pi_ta"]
        with self.assertRaises(user_import.ProjectUserImportError):
            user_import.prepare(TA, [self._row(2, "", _number())], actor=pi)

    def test_import_route_shows_codes_once_and_sends_verification_only(self):
        import io

        self._organization()
        tag = uuid.uuid4().hex[:8]
        fresh = _number()
        body = ("email,name,role,org_unit_code,cadre_code,language_codes,phone\n"
                f"imp.{tag}@example.com,Email Import,reviewer,P1,,english,\n"
                f",Mobile Import,reviewer,P1,,english,{fresh}\n")
        self._login(str(self.users["admin"].user_id))
        with _captured_logs() as logs, _mailbox() as send:
            response = self.client.post(
                f"/admin/api/organization/{TA}/project-users/import",
                data={"file": (io.BytesIO(body.encode()), "users.csv"), "dry_run": "0"},
                headers=self._csrf_headers(), content_type="multipart/form-data",
            )
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        data = response.get_json()
        self.assertEqual(data["created_users"], 2)
        [entry] = data["sign_in_codes"]
        self.assertRegex(entry["sign_in_code"], r"^\d{6}$")
        self.assertNotIn(fresh, response.get_data(as_text=True))
        self.assertFalse(any(entry["sign_in_code"] in line for line in logs))
        templates = [c.kwargs["template_name"] for c in send.queued.call_args_list]
        self.assertEqual(templates, ["emails/verify_email"])

    def test_mentor_institute_creates_mobile_only_staff_with_a_code(self):
        code = f"MI{uuid.uuid4().hex[:6].upper()}"
        db.session.add(MasMentorInstitute(institute_code=code, institute_name="Mentor Inst", is_active=True))
        db.session.commit()
        self._login(str(self.users["admin"].user_id))
        number = _number()
        with _mailbox() as send:
            response = self.client.post(
                f"/admin/api/mentor-institutes/{code}/staff",
                json={"name": "Mentor Mobile", "phone": number, "languages": ["english"]},
                headers=self._csrf_headers(),
            )
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertRegex(response.get_json()["sign_in_code"], r"^\d{6}$")
        send.queued.assert_not_called()
        user = db.session.scalar(sa.select(VaUsers).where(VaUsers.mobile_login == number))
        self.assertIsNone(user.email)


class VerificationLinkBindingTests(OnboardingTestBase):
    def test_link_stops_working_once_the_email_changes(self):
        from app.services.token_service import validate_token

        user = self._email_user(verified=False, onboarded=False)
        token = generate_token(user.user_id, "email_verify")
        self.assertEqual(validate_token(token, "email_verify"), str(user.user_id))
        user.email = f"changed.{uuid.uuid4().hex[:8]}@example.com"
        db.session.commit()
        self.assertIsNone(validate_token(token, "email_verify"))
        with _mailbox() as send:
            response = self.client.post(f"/vaauth/verify-email/{token}",
                                        headers=self._csrf_headers())
        self.assertEqual(response.status_code, 302)
        send.assert_not_called()
        db.session.refresh(user)
        self.assertFalse(user.email_verified)

    def test_inactive_account_link_gets_the_generic_refusal(self):
        user = self._email_user(verified=False, onboarded=False)
        user.user_status = VaStatuses.deactive
        db.session.commit()
        url = f"/vaauth/verify-email/{generate_token(user.user_id, 'email_verify')}"
        with _mailbox() as send:
            for method in ("get", "post"):
                response = getattr(self.client, method)(url, headers=self._csrf_headers())
                self.assertEqual(response.status_code, 302)
                page = self.client.get(response.headers["Location"]).data
                self.assertIn(b"invalid or has expired", page)
        send.assert_not_called()
        db.session.refresh(user)
        self.assertFalse(user.email_verified)
        self.assertTrue(user.check_password(PASSWORD))


class MentorMobileOnlyAdminOnlyTests(AuthzFixtureMixin, OnboardingTestBase):
    def test_institute_admin_must_give_an_email(self):
        from app.models import MapMentorInstituteUser
        from app.models.mas_languages import MasLanguages

        if db.session.get(MasLanguages, "english") is None:
            db.session.add(MasLanguages(language_code="english", language_name="English",
                                        is_active=True))
        code = f"MI{uuid.uuid4().hex[:6].upper()}"
        institute = MasMentorInstitute(institute_code=code, institute_name="Mentor Inst",
                                       is_active=True)
        db.session.add(institute)
        db.session.flush()
        head = self._email_user()
        db.session.add(MapMentorInstituteUser(institute_id=institute.institute_id,
                                              user_id=head.user_id, is_admin=True))
        db.session.commit()
        self._login(head.get_id())
        number = _number()
        response = self.client.post(
            f"/admin/api/mentor-institutes/{code}/staff",
            json={"name": "Mentor Mobile", "phone": number, "languages": ["english"]},
            headers=self._csrf_headers(),
        )
        self.assertEqual(response.status_code, 400, response.get_json())
        self.assertNotIn("sign_in_code", response.get_json())
        self.assertIsNone(db.session.scalar(sa.select(VaUsers).where(VaUsers.mobile_login == number)))
