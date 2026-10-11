"""Admin factor reset and the break-glass CLI -- digitva-sn1.1.6. Baseline:
docs/policy/authentication-factors.md section 8.
"""

import uuid
from unittest.mock import patch

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
from app.services.token_service import generate_token
from tests.base import BaseTestCase

PASSWORD = "FactorReset123!"


class FactorResetTestBase(BaseTestCase):
    def setUp(self):
        super().setUp()
        limiter.reset()
        self.target = self._make_user(f"reset.target.{uuid.uuid4().hex[:8]}@example.com", PASSWORD)
        db.session.commit()

    def _add_passkey(self, user):
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

    def _enroll_totp(self, user):
        result = totp_service.begin_enrolment(user)
        code = pyotp.TOTP(result["secret"]).now()
        self.assertTrue(totp_service.confirm_enrolment(user, code))
        totp_service.generate_recovery_codes(user)
        db.session.commit()


# ---------------------------------------------------------------------------
# Admin reset (POST /admin/api/users/<id>/reset-factors)
# ---------------------------------------------------------------------------

class AdminFactorResetTests(FactorResetTestBase):
    def _reset(self, user_id, reason="lost device", headers=None):
        return self.client.post(
            f"/admin/api/users/{user_id}/reset-factors",
            json={"reason": reason} if reason is not None else {},
            headers=headers if headers is not None else self._csrf_headers(),
        )

    def test_clears_all_factor_kinds(self):
        self._add_passkey(self.target)
        self._enroll_totp(self.target)
        self.assertTrue(
            db.session.scalar(sa.select(sa.exists().where(AuthRecoveryCode.user_id == self.target.user_id)))
        )

        self._login(str(self.base_admin_id))
        resp = self._reset(self.target.user_id)

        self.assertEqual(resp.status_code, 200, resp.get_json())
        self.assertFalse(db.session.scalar(
            sa.select(sa.exists().where(AuthWebauthnCredential.user_id == self.target.user_id))
        ))
        self.assertIsNone(db.session.get(AuthTotp, self.target.user_id))
        self.assertFalse(db.session.scalar(
            sa.select(sa.exists().where(AuthRecoveryCode.user_id == self.target.user_id))
        ))

    def test_bumps_version_old_session_no_longer_loads(self):
        self._login(str(self.target.user_id))
        # An unversioned "<uuid>" session is what load_user sees as version 0.
        self.client.get("/profile/")

        self._login(str(self.base_admin_id))
        resp = self._reset(self.target.user_id)
        self.assertEqual(resp.status_code, 200)

        # Restore the stale, pre-reset session and confirm it no longer works.
        # Flask-Login caches the loaded user on `g`, and this test environment
        # keeps one app context for the whole session (see tests/base.py
        # _login), so that cache has to be dropped by hand here too.
        from flask import g

        if hasattr(g, "_login_user"):
            del g._login_user
        with self.client.session_transaction() as sess:
            sess["_user_id"] = str(self.target.user_id)
            sess["_fresh"] = True
        stale = self.client.get("/profile/")
        self.assertEqual(stale.status_code, 302)
        self.assertIn("valogin", stale.headers.get("Location", ""))

    def test_records_event_with_actor_and_reason(self):
        self._login(str(self.base_admin_id))
        resp = self._reset(self.target.user_id, reason="user reported lost phone")
        self.assertEqual(resp.status_code, 200)

        event = db.session.scalar(
            sa.select(AuthSecurityEvent)
            .where(
                AuthSecurityEvent.user_id == self.target.user_id,
                AuthSecurityEvent.event_type == "factor_reset",
            )
            .order_by(AuthSecurityEvent.occurred_at.desc())
        )
        self.assertIsNotNone(event)
        self.assertEqual(str(event.actor_user_id), self.base_admin_id)
        self.assertEqual(event.detail["reason"], "user reported lost phone")
        self.assertEqual(event.detail["via"], "admin")

    def test_email_sent(self):
        self._login(str(self.base_admin_id))
        with patch(
            "app.services.email_service.send_factor_reset_email", return_value=True
        ) as mailer:
            resp = self._reset(self.target.user_id)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["email_sent"])
        mailer.assert_called_once()
        self.assertEqual(mailer.call_args[0][0].user_id, self.target.user_id)

    def test_email_send_failure_does_not_fail_the_reset(self):
        """The reset itself already committed; a broker/SMTP failure sending
        the notice must not turn the response into a 500 -- see
        admin_create_user's own try/except for the same reasoning."""
        self._add_passkey(self.target)
        self._login(str(self.base_admin_id))
        with patch(
            "app.services.email_service.send_factor_reset_email",
            side_effect=RuntimeError("broker down"),
        ):
            resp = self._reset(self.target.user_id)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.get_json()["email_sent"])
        self.assertFalse(db.session.scalar(
            sa.select(sa.exists().where(AuthWebauthnCredential.user_id == self.target.user_id))
        ))

    def test_self_reset_refused(self):
        self._login(str(self.base_admin_id))
        resp = self._reset(self.base_admin_id)
        self.assertEqual(resp.status_code, 400)

    def test_non_admin_refused(self):
        self._login(str(self.base_coder_id))
        resp = self._reset(self.target.user_id)
        self.assertEqual(resp.status_code, 403)

    def test_empty_reason_refused(self):
        self._login(str(self.base_admin_id))
        resp = self._reset(self.target.user_id, reason="")
        self.assertEqual(resp.status_code, 400)

    def test_csrf_missing_rejected(self):
        self._login(str(self.base_admin_id))
        resp = self.client.post(
            f"/admin/api/users/{self.target.user_id}/reset-factors",
            json={"reason": "lost device"},
        )
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# Break-glass CLI
# ---------------------------------------------------------------------------

class FactorResetCliTests(FactorResetTestBase):
    def setUp(self):
        super().setUp()
        self.runner = self.app.test_cli_runner()

    def test_resets_and_sends_email_with_working_link(self):
        self._add_passkey(self.target)
        captured = {}

        def _fake_send(user, token):
            captured["token"] = token

        with patch("app.commands.auth.send_factor_reset_link_email", side_effect=_fake_send) as mailer:
            result = self.runner.invoke(
                args=["auth", "reset-factors", self.target.email, "--reason", "lost device"]
            )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("reset for", result.output)
        self.assertIn("emailed", result.output)
        mailer.assert_called_once()
        self.assertFalse(db.session.scalar(
            sa.select(sa.exists().where(AuthWebauthnCredential.user_id == self.target.user_id))
        ))

        token = captured["token"]
        resp = self.client.get(f"/vaauth/factor-reset/{token}")
        self.assertEqual(resp.status_code, 200)

    def test_link_works_once(self):
        with patch("app.commands.auth.send_factor_reset_link_email"):
            self.runner.invoke(
                args=["auth", "reset-factors", self.target.email, "--reason", "lost device"]
            )
        token = generate_token(self.target.user_id, "factor_reset")

        first = self.client.post(f"/vaauth/factor-reset/{token}", headers=self._csrf_headers())
        self.assertEqual(first.status_code, 302)

        # The first use signed the client in; log back out so the second
        # request actually re-checks the (now-spent) token instead of just
        # bouncing an authenticated session to its landing page. g caches the
        # loaded user for this whole test session (see tests/base.py _login).
        from flask import g

        if hasattr(g, "_login_user"):
            del g._login_user
        with self.client.session_transaction() as sess:
            sess.clear()
        second = self.client.get(f"/vaauth/factor-reset/{token}")
        self.assertIn(b"invalid or has expired", second.data)

    def test_link_rejected_after_later_reset_or_password_change(self):
        token = generate_token(self.target.user_id, "factor_reset")
        # A second reset bumps auth_session_version again, invalidating the
        # first token before it was ever used.
        totp_service.reset_factors(self.target, actor_user_id=None, reason="again", via="cli")
        db.session.commit()

        resp = self.client.get(f"/vaauth/factor-reset/{token}")
        self.assertIn(b"invalid or has expired", resp.data)

    def test_unknown_email_exits_nonzero(self):
        result = self.runner.invoke(
            args=["auth", "reset-factors", "nobody@example.com", "--reason", "x"]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("not found", result.output)

    def test_reason_required(self):
        result = self.runner.invoke(args=["auth", "reset-factors", self.target.email])
        self.assertNotEqual(result.exit_code, 0)

    def test_link_email_renders_real_template(self):
        """Exercise send_factor_reset_link_email itself (not a mock of the
        whole function), so a template bug (e.g. TemplateNotFound) fails
        here instead of being silently reported as "could not send"."""
        from app.services.email_service import send_factor_reset_link_email

        with patch("app.services.email_service.is_mail_configured", return_value=True), patch(
            "app.services.email_service.mail.send"
        ) as mail_send:
            send_factor_reset_link_email(self.target, "dummy-token-123")

        mail_send.assert_called_once()
        sent_message = mail_send.call_args[0][0]
        self.assertEqual(sent_message.recipients, [self.target.email])
        self.assertIn("dummy-token-123", sent_message.html)
        self.assertIn("dummy-token-123", sent_message.body)

    def test_link_printed_only_when_mail_send_raises(self):
        with patch(
            "app.commands.auth.send_factor_reset_link_email",
            side_effect=RuntimeError("smtp down"),
        ):
            result = self.runner.invoke(
                args=["auth", "reset-factors", self.target.email, "--reason", "lost device"]
            )
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("/vaauth/factor-reset/", result.output)
        self.assertIn("Could not send", result.output)


# ---------------------------------------------------------------------------
# Magic-link flow (GET/POST /vaauth/factor-reset/<token>)
# ---------------------------------------------------------------------------

class FactorResetLinkRouteTests(FactorResetTestBase):
    def _post(self, token):
        return self.client.post(
            f"/vaauth/factor-reset/{token}",
            headers=self._csrf_headers(),
        )

    def test_link_changes_no_password_and_get_changes_nothing(self):
        """digitva-kmoy: nobody chooses a password, so the link only signs
        the person in; the existing password keeps working."""
        token = generate_token(self.target.user_id, "factor_reset")
        page = self.client.get(f"/vaauth/factor-reset/{token}")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b'type="password"', page.data)
        version = self.target.auth_session_version
        db.session.refresh(self.target)
        self.assertEqual(self.target.auth_session_version, version)  # GET changed nothing
        posted = self.client.post(
            f"/vaauth/factor-reset/{token}",
            data={"new_password": "BrandNewSecret789!", "confirm_password": "BrandNewSecret789!"},
            headers=self._csrf_headers(),
        )
        self.assertEqual(posted.status_code, 302)
        db.session.refresh(self.target)
        self.assertTrue(self.target.check_password(PASSWORD))
        self.assertFalse(self.target.check_password("BrandNewSecret789!"))

    def test_sets_email_verified(self):
        self.target.email_verified = False
        db.session.commit()
        token = generate_token(self.target.user_id, "factor_reset")

        resp = self._post(token)
        self.assertEqual(resp.status_code, 302)
        db.session.refresh(self.target)
        self.assertTrue(self.target.email_verified)

    def test_logs_in_and_lands_on_factor_setup(self):
        token = generate_token(self.target.user_id, "factor_reset")
        resp = self._post(token)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/profile/", resp.headers["Location"])
        self.assertIn("passkeys-card", resp.headers["Location"])
        with self.client.session_transaction() as sess:
            self.assertIn("_user_id", sess)

    def test_recovery_link_does_not_force_factor_setup(self):
        db.session.add(VaUserAccessGrants(
            user_id=self.target.user_id,
            role=VaAccessRoles.admin,
            scope_type=VaAccessScopeTypes.global_scope,
            notes="test admin grant",
            grant_status=VaStatuses.active,
        ))
        db.session.commit()

        token = generate_token(self.target.user_id, "factor_reset")
        self._post(token)

        resp = self.client.get("/coding/dashboard")
        self.assertNotEqual(resp.status_code, 302)
