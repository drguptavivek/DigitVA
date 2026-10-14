"""The daily TLS check: mails admins only while a certificate needs attention."""

from unittest import mock

from app.tasks import tls_health_tasks as task
from tests.base import BaseTestCase


def _row(status):
    return {
        "key": "app_https",
        "label": "App HTTPS certificate",
        "source": "/x.crt",
        "subject_cn": "app.test.invalid",
        "sans": [],
        "not_after": None,
        "days_left": 3,
        "status": status,
        "detail": "",
    }


class TlsHealthTaskTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.admin = mock.Mock(email="base.admin@test.local")
        self.admins_patch = mock.patch.object(task, "_active_admins", return_value=[self.admin])
        self.admins_patch.start()
        self.addCleanup(self.admins_patch.stop)
        store = mock.patch("app.services.tls_health_service.store_report")
        self.store_report = store.start()
        self.addCleanup(store.stop)

    def test_mails_every_admin_while_a_certificate_is_urgent(self):
        rows = [_row("urgent")]
        with (
            mock.patch("app.services.tls_health_service.certificate_report", return_value=rows),
            mock.patch(
                "app.services.email_service.send_tls_expiry_notice", return_value=True
            ) as send,
        ):
            result = task.run_tls_health_check()

        send.assert_called_once_with(self.admin, rows)
        self.assertEqual(result, {"status_counts": {"urgent": 1}, "notified": 1})
        self.store_report.assert_called_once_with(rows)

    def test_sends_nothing_when_every_certificate_is_ok(self):
        with (
            mock.patch(
                "app.services.tls_health_service.certificate_report", return_value=[_row("ok")]
            ),
            mock.patch("app.services.email_service.send_tls_expiry_notice") as send,
        ):
            result = task.run_tls_health_check()

        send.assert_not_called()
        self.assertEqual(result["notified"], 0)
        self.store_report.assert_called_once()

    def test_not_configured_rows_do_not_trigger_mail(self):
        rows = [_row("not_configured"), _row("unreachable")]
        with (
            mock.patch("app.services.tls_health_service.certificate_report", return_value=rows),
            mock.patch("app.services.email_service.send_tls_expiry_notice") as send,
        ):
            task.run_tls_health_check()

        send.assert_not_called()

    def test_active_admin_query_returns_the_base_admin(self):
        self.admins_patch.stop()

        emails = [u.email for u in task._active_admins()]

        self.assertIn("base.admin@test.local", emails)
        self.assertNotIn("base.coder@test.local", emails)

    def test_mails_admins_when_the_s3_store_credentials_are_rejected(self):
        s3_row = {
            **_row("error"),
            "key": "s3_access",
            "label": "S3 bucket access",
            "source": "s3://example-bucket/staging/",
            "days_left": None,
            "detail": "credentials rejected",
        }
        rows = [s3_row]
        with (
            mock.patch("app.services.tls_health_service.certificate_report", return_value=rows),
            mock.patch(
                "app.services.email_service.send_tls_expiry_notice", return_value=True
            ) as send,
        ):
            result = task.run_tls_health_check()

        send.assert_called_once_with(self.admin, rows)
        self.assertEqual(result, {"status_counts": {"error": 1}, "notified": 1})


class TlsExpiryNoticeTests(BaseTestCase):
    def test_notice_carries_only_attention_rows_and_renders(self):
        from datetime import UTC, datetime, timedelta

        from flask import render_template

        expires = datetime.now(UTC) + timedelta(days=5)
        due = {
            **_row("urgent"),
            "label": "Public HTTPS certificate",
            "not_after": expires,
            "days_left": 5,
            "detail": "",
        }
        fine = {**_row("ok"), "label": "App HTTPS certificate"}
        user = mock.Mock(email="base.admin@test.local", name="Base Admin")

        from app.services import email_service

        with (
            mock.patch.object(email_service, "_dispatch_email") as dispatch,
            mock.patch.object(email_service, "_should_attempt_email_delivery", return_value=True),
        ):
            self.assertTrue(email_service.send_tls_expiry_notice(user, [due, fine]))

        context = dispatch.delay.call_args.kwargs["context"]
        self.assertEqual(
            [c["label"] for c in context["certificates"]], ["Public HTTPS certificate"]
        )
        with self.app.test_request_context():
            body = render_template("emails/tls_expiry_notice.txt", **context)
        self.assertIn("Public HTTPS certificate: urgent", body)
        self.assertIn("5 days left", body)
        self.assertNotIn("App HTTPS certificate", body)

    def test_s3_row_renders_its_detail_without_an_expiry(self):
        from flask import render_template

        s3_row = {
            "label": "S3 bucket access",
            "not_after": None,
            "days_left": None,
            "status": "error",
            "detail": "bucket not found",
        }
        from app.services import email_service

        with (
            mock.patch.object(email_service, "_dispatch_email") as dispatch,
            mock.patch.object(email_service, "_should_attempt_email_delivery", return_value=True),
        ):
            email_service.send_tls_expiry_notice(mock.Mock(email="base.admin@test.local"), [s3_row])

        context = dispatch.delay.call_args.kwargs["context"]
        self.assertEqual(
            dispatch.delay.call_args.kwargs["subject"], "DigitVA: system health needs attention"
        )
        with self.app.test_request_context():
            body = render_template("emails/tls_expiry_notice.txt", **context)
            html = render_template("emails/tls_expiry_notice.html", **context)
        self.assertIn("S3 bucket access: error - bucket not found", body)
        self.assertIn("S3 bucket access: <strong>error</strong>", html)
        for text in (body, html):
            self.assertIn("bucket not found", text)
            self.assertNotIn("expires", text)
            self.assertNotIn("days left", text)


class TlsHealthScheduleTests(BaseTestCase):
    """The beat row itself is written by seed_daily_crontab_task, which needs the
    celery beat tables; this test pins what the TLS seeder hands it. The test
    database has no beat tables, so the SQL is not exercised here."""

    def test_hands_the_configured_time_to_the_shared_seeder(self):
        with (
            mock.patch.dict(self.app.config, {"TLS_HEALTH_DAILY_TIME": "07:15"}),
            mock.patch("app.tasks.backup_tasks.seed_daily_crontab_task") as seed,
        ):
            task.ensure_tls_health_scheduled()

        seed.assert_called_once_with(
            task.TLS_HEALTH_SCHEDULE_NAME,
            task.TLS_HEALTH_TASK_NAME,
            7,
            15,
            label="TLS health check",
        )

    def test_unparseable_time_falls_back_to_the_tls_default_not_the_backup_one(self):
        with (
            mock.patch.dict(self.app.config, {"TLS_HEALTH_DAILY_TIME": "nonsense"}),
            mock.patch("app.tasks.backup_tasks.seed_daily_crontab_task") as seed,
        ):
            task.ensure_tls_health_scheduled()

        self.assertEqual(seed.call_args.args[2:4], (6, 30))
