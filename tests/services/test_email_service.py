from types import SimpleNamespace
from unittest.mock import patch
import smtplib

from tests.base import BaseTestCase


class TestEmailService(BaseTestCase):
    def test_actually_send_email_uses_current_app_context(self):
        user = SimpleNamespace(email="vivekguptarpc@gmail.com", name="Vivek")

        with self.app.app_context(), patch(
            "app.services.email_service.render_template",
            side_effect=lambda template, **context: f"{template}:{context['name']}",
        ) as render_template, patch(
            "app.services.email_service.mail.send"
        ) as mail_send:
            from app.services.email_service import _actually_send_email

            _actually_send_email(
                to=user.email,
                subject="Verify Your DigitVA Email",
                template_name="emails/verify_email",
                context={"name": user.name, "verify_url": "https://example.test"},
            )

        self.assertEqual(render_template.call_count, 2)
        mail_send.assert_called_once()
        msg = mail_send.call_args.args[0]
        self.assertEqual(msg.recipients, [user.email])
        self.assertEqual(msg.subject, "Verify Your DigitVA Email")

    def test_send_password_reset_email_uses_invite_copy_for_new_users(self):
        user = SimpleNamespace(email="new.user@example.com", name="New User")

        with self.app.app_context(), patch(
            "app.services.email_service._dispatch_email.delay"
        ) as dispatch_delay:
            from app.services.email_service import send_password_reset_email

            send_password_reset_email(user, "token-123", invite_mode=True)

        dispatch_delay.assert_called_once()
        kwargs = dispatch_delay.call_args.kwargs
        subject = kwargs["subject"]
        template_name = kwargs["template_name"]
        context = kwargs["context"]
        self.assertEqual(subject, "Set Your DigitVA Password")
        self.assertEqual(template_name, "emails/reset_password")
        self.assertTrue(context["invite_mode"])
        self.assertTrue(context["reset_url"].endswith("/vaauth/reset-password/token-123"))
        self.assertTrue(context["reset_url"].startswith("http"))

    def test_send_password_reset_email_keeps_reset_copy_for_existing_users(self):
        user = SimpleNamespace(email="existing.user@example.com", name="Existing User")

        with self.app.app_context(), patch(
            "app.services.email_service._dispatch_email.delay"
        ) as dispatch_delay:
            from app.services.email_service import send_password_reset_email

            send_password_reset_email(user, "token-456")

        dispatch_delay.assert_called_once()
        kwargs = dispatch_delay.call_args.kwargs
        subject = kwargs["subject"]
        template_name = kwargs["template_name"]
        context = kwargs["context"]
        self.assertEqual(subject, "Reset Your DigitVA Password")
        self.assertEqual(template_name, "emails/reset_password")
        self.assertFalse(context["invite_mode"])

    def test_dispatch_email_does_not_retry_for_permanent_recipient_failure(self):
        recipient_error = smtplib.SMTPRecipientsRefused(
            {"blocked@example.com": (550, b"blacklisted")}
        )
        with self.app.app_context(), patch(
            "app.services.email_service._actually_send_email",
            side_effect=recipient_error,
        ), patch("app.services.email_service._dispatch_email.retry") as retry_mock:
            from app.services.email_service import _dispatch_email

            _dispatch_email(
                to="blocked@example.com",
                subject="Verify",
                template_name="emails/verify_email",
                context={"name": "Blocked", "verify_url": "https://example.test"},
            )

        retry_mock.assert_not_called()

    def test_dispatch_email_retries_for_transient_failure(self):
        with self.app.app_context(), patch(
            "app.services.email_service._actually_send_email",
            side_effect=smtplib.SMTPServerDisconnected("disconnected"),
        ), patch(
            "app.services.email_service._dispatch_email.retry",
            side_effect=RuntimeError("retry-called"),
        ) as retry_mock:
            from app.services.email_service import _dispatch_email

            with self.assertRaises(RuntimeError):
                _dispatch_email(
                    to="user@example.com",
                    subject="Verify",
                    template_name="emails/verify_email",
                    context={"name": "User", "verify_url": "https://example.test"},
                )

        retry_mock.assert_called_once()
