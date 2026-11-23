import smtplib
from types import SimpleNamespace
from unittest.mock import patch

from tests.base import BaseTestCase


class TestEmailService(BaseTestCase):
    def test_masked_recipients_hide_the_local_part(self):
        from app.services.email_service import _masked_recipients

        self.assertEqual(_masked_recipients("victim@example.org"), "v***@example.org")
        self.assertEqual(_masked_recipients(["ab@x.in", "bad"]), "a***@x.in, ***")

    def test_test_config_suppresses_mail_send(self):
        self.assertTrue(self.app.config["MAIL_SUPPRESS_SEND"])

    def test_actually_send_email_uses_current_app_context(self):
        user = SimpleNamespace(email="vivekguptarpc@gmail.com", name="Vivek")

        # This test exercises the configured-SMTP path.  TestConfig leaves
        # MAIL_SERVER at "localhost", which is_mail_configured() treats as
        # unconfigured (email_service.py), so the send is skipped without it.
        with self.app.app_context(), patch.dict(
            self.app.config, {"MAIL_SERVER": "smtp.test.invalid"}
        ), patch(
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

    def test_send_password_reset_email_queues_the_link_only(self):
        """digitva-kmoy: no invite variant; the link carries no password."""
        user = SimpleNamespace(email="existing.user@example.com", name="Existing User")

        with self.app.app_context(), patch(
            "app.services.email_service._dispatch_email.delay"
        ) as dispatch_delay:
            from app.services.email_service import send_password_reset_email

            send_password_reset_email(user, "token-456")

        dispatch_delay.assert_called_once()
        kwargs = dispatch_delay.call_args.kwargs
        self.assertEqual(kwargs["subject"], "Reset Your DigitVA Password")
        self.assertEqual(kwargs["template_name"], "emails/reset_password")
        self.assertNotIn("invite_mode", kwargs["context"])
        self.assertNotIn("password", kwargs["context"])
        self.assertTrue(kwargs["context"]["reset_url"].endswith("/vaauth/reset-password/token-456"))

    def test_dispatch_email_does_not_retry_for_permanent_recipient_failure(self):
        recipient_error = smtplib.SMTPRecipientsRefused(
            {"blocked@example.com": (550, b"blacklisted")}
        )
        with self.app.app_context(), patch(
            "app.services.email_service._actually_send_email",
            side_effect=recipient_error,
        ), patch(
            "app.services.email_service._mark_suppressed_email"
        ) as mark_suppressed, patch(
            "app.services.email_service._is_suppressed_recipient",
            return_value=False,
        ), patch("app.services.email_service._dispatch_email.retry") as retry_mock:
            from app.services.email_service import _dispatch_email

            _dispatch_email(
                to="blocked@example.com",
                subject="Verify",
                template_name="emails/verify_email",
                context={"name": "Blocked", "verify_url": "https://example.test"},
            )

        mark_suppressed.assert_called_once()
        retry_mock.assert_not_called()

    def test_dispatch_email_retries_for_transient_failure(self):
        with self.app.app_context(), patch(
            "app.services.email_service._actually_send_email",
            side_effect=smtplib.SMTPServerDisconnected("disconnected"),
        ), patch(
            "app.services.email_service._is_suppressed_recipient",
            return_value=False,
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

    def _refused_dispatch(self, retries):
        """Run _dispatch_email against a refused SMTP connection; return the retry mock."""
        from app.services.email_service import _dispatch_email

        with self.app.app_context(), patch(
            "app.services.email_service._actually_send_email",
            side_effect=ConnectionRefusedError(111, "Connection refused"),
        ), patch(
            "app.services.email_service._is_suppressed_recipient", return_value=False
        ), patch(
            "app.services.email_service._dispatch_email.retry",
            side_effect=RuntimeError("retry-called"),
        ) as retry_mock, patch.object(
            type(_dispatch_email.request),
            "retries",
            retries,
            create=True,
        ):
            with self.assertRaises(RuntimeError):
                _dispatch_email(
                    to="user@example.com",
                    subject="Verify",
                    template_name="emails/verify_email",
                    context={"name": "User", "verify_url": "https://example.test"},
                )
        return retry_mock

    def test_connection_refused_retries_with_jittered_capped_backoff(self):
        first = self._refused_dispatch(0).call_args.kwargs["countdown"]
        late = self._refused_dispatch(5).call_args.kwargs["countdown"]
        self.assertTrue(0 <= first <= 30)
        self.assertTrue(0 <= late <= 600)

    def test_each_failed_attempt_logs_one_masked_line(self):
        with self.assertLogs("app.services.email_service", level="WARNING") as logs:
            self._refused_dispatch(0)
        line = "\n".join(logs.output)
        self.assertIn("attempt 1 of 7", line)
        self.assertIn("ConnectionRefusedError(111)", line)
        self.assertIn("u***@example.com", line)
        self.assertNotIn("user@example.com", line)
        self.assertNotIn("Traceback", line)

    def test_last_attempt_logs_give_up_and_does_not_retry(self):
        from app.services.email_service import _dispatch_email

        with self.app.app_context(), patch(
            "app.services.email_service._actually_send_email",
            side_effect=ConnectionRefusedError(111, "Connection refused"),
        ), patch(
            "app.services.email_service._is_suppressed_recipient", return_value=False
        ), patch(
            "app.services.email_service._dispatch_email.retry"
        ) as retry_mock, patch.object(
            type(_dispatch_email.request), "retries", 6, create=True
        ), self.assertLogs("app.services.email_service", level="ERROR") as logs:
            with self.assertRaises(ConnectionRefusedError):
                _dispatch_email(
                    to="user@example.com",
                    subject="Verify",
                    template_name="emails/verify_email",
                    context={"name": "User", "verify_url": "https://example.test"},
                )
        retry_mock.assert_not_called()
        self.assertIn("gave up for u***@example.com after 7 attempts", "\n".join(logs.output))

    def test_dispatch_email_allows_six_retries(self):
        from app.services.email_service import _dispatch_email

        self.assertEqual(_dispatch_email.max_retries, 6)

    def test_send_verification_email_paces_with_countdown(self):
        user = SimpleNamespace(user_id=1, email="paced@example.com", name="Paced")
        from app.services.email_service import send_verification_email

        with self.app.app_context(), patch(
            "app.services.email_service._dispatch_email.apply_async"
        ) as apply_async, patch(
            "app.services.email_service._dispatch_email.delay"
        ) as delay, patch(
            "app.services.email_service._is_suppressed_recipient", return_value=False
        ), patch("app.services.security_event_service.record_security_event"):
            self.assertTrue(send_verification_email(user, "t", commit=False, countdown=7))
            apply_async.assert_called_once()
            self.assertEqual(apply_async.call_args.kwargs["countdown"], 7)
            self.assertEqual(apply_async.call_args.kwargs["kwargs"]["to"], "paced@example.com")
            delay.assert_not_called()
            apply_async.reset_mock()
            self.assertTrue(send_verification_email(user, "t", commit=False))
            apply_async.assert_not_called()
            delay.assert_called_once()

    def test_password_reset_email_is_not_paced(self):
        user = SimpleNamespace(email="reset@example.com", name="Reset")
        from app.services.email_service import send_password_reset_email

        with self.app.app_context(), patch(
            "app.services.email_service._dispatch_email.apply_async"
        ) as apply_async, patch(
            "app.services.email_service._dispatch_email.delay"
        ) as delay, patch(
            "app.services.email_service._is_suppressed_recipient", return_value=False
        ):
            send_password_reset_email(user, "tok")
        delay.assert_called_once()
        apply_async.assert_not_called()

    def test_send_verification_email_skips_suppressed_recipient(self):
        user = SimpleNamespace(email="suppressed@example.com", name="Suppressed User")
        with self.app.app_context(), patch(
            "app.services.email_service._dispatch_email.delay"
        ) as dispatch_delay, patch(
            "app.services.email_service._is_suppressed_recipient",
            return_value=True,
        ):
            from app.services.email_service import send_verification_email

            send_verification_email(user, "token-789")

        dispatch_delay.assert_not_called()

    def test_send_verification_email_skips_when_delivery_disabled(self):
        user = SimpleNamespace(email="disabled@example.com", name="Disabled User")
        old_enabled = self.app.config.get("EMAIL_DELIVERY_ENABLED", True)
        with self.app.app_context(), patch(
            "app.services.email_service._dispatch_email.delay"
        ) as dispatch_delay, patch(
            "app.services.email_service._is_suppressed_recipient",
            return_value=False,
        ):
            self.app.config["EMAIL_DELIVERY_ENABLED"] = False
            from app.services.email_service import send_verification_email

            send_verification_email(user, "token-999")

        self.app.config["EMAIL_DELIVERY_ENABLED"] = old_enabled
        dispatch_delay.assert_not_called()
