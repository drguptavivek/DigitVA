"""Daily wipe of the client IP on web_sign_in events (digitva-ci8)."""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from app import db
from app.models import AuthSecurityEvent
from app.tasks import security_event_tasks as tasks
from tests.base import BaseTestCase

IP = "203.0.113.9"


def _event(event_type, age_days, detail):
    row = AuthSecurityEvent(
        event_type=event_type, detail=detail,
        occurred_at=datetime.now(UTC) - timedelta(days=age_days))
    db.session.add(row)
    db.session.commit()
    return row.id


def _detail(event_id):
    db.session.expire_all()
    return db.session.get(AuthSecurityEvent, event_id).detail


class SignInIpWipeTests(BaseTestCase):
    def test_retention_is_210_days(self):
        self.assertEqual(tasks.SIGN_IN_IP_RETENTION_DAYS, 210)

    def test_old_sign_in_loses_ip_and_keeps_the_rest(self):
        old = _event("web_sign_in", 211, {"method": "password", "ip": IP})
        recent = _event("web_sign_in", 209, {"method": "passkey", "ip": IP})
        failed = _event("web_sign_in_failed", 400, {"reason": "invalid_credentials", "ip": IP})
        self.assertEqual(_detail(old)["ip"], IP)
        self.assertEqual(_detail(recent)["ip"], IP)
        self.assertEqual(_detail(failed)["ip"], IP)

        self.assertEqual(tasks.wipe_sign_in_ips(), 1)

        self.assertEqual(_detail(old), {"method": "password"})
        self.assertEqual(_detail(recent), {"method": "passkey", "ip": IP})
        self.assertEqual(_detail(failed), {"reason": "invalid_credentials", "ip": IP})
        self.assertIsNotNone(db.session.get(AuthSecurityEvent, old))  # event kept

    def test_rerun_changes_nothing_and_ipless_rows_are_skipped(self):
        old = _event("web_sign_in", 300, {"method": "password", "ip": IP})
        ipless = _event("web_sign_in", 300, {"method": "password"})
        self.assertEqual(tasks.wipe_sign_in_ips(), 1)
        self.assertEqual(tasks.wipe_sign_in_ips(), 0)
        self.assertEqual(_detail(old), {"method": "password"})
        self.assertEqual(_detail(ipless), {"method": "password"})

    def test_task_reports_the_count_only(self):
        _event("web_sign_in", 211, {"method": "password", "ip": IP})
        with self.assertLogs(tasks.log, level="INFO") as logs:
            result = tasks.wipe_sign_in_ips_task.run()
        self.assertEqual(result, {"wiped": 1, "status": "ok"})
        self.assertNotIn(IP, "\n".join(logs.output))

    def test_the_update_is_one_statement(self):
        from tests.authz.test_grants import count_queries

        for _ in range(3):
            _event("web_sign_in", 300, {"method": "password", "ip": IP})
        with count_queries() as statements:
            tasks.wipe_sign_in_ips()
        self.assertEqual(len([s for s in statements if s.startswith("UPDATE")]), 1)


class SignInIpWipeBeatTests(BaseTestCase):
    def test_beat_seeding_is_idempotent(self):
        """The beat tables only exist in the migrated dev database, so the
        seeding runs against a stand-in connection that remembers its inserts."""
        inserted = []

        class Conn:
            def execute(self, statement, params=None):
                sql = str(statement)
                if "INSERT INTO public.celery_periodictask\n" in sql:
                    inserted.append(params)
                result = mock.Mock()
                if "SELECT id FROM public.celery_intervalschedule" in sql:
                    result.scalar.return_value = 7
                elif "SELECT id FROM public.celery_periodictask" in sql:
                    result.scalar.return_value = 1 if inserted else None
                return result

        @contextmanager
        def begin():
            yield Conn()

        with mock.patch("app.db", mock.Mock(engine=mock.Mock(begin=begin))):
            tasks.ensure_sign_in_ip_wipe_scheduled()
            tasks.ensure_sign_in_ip_wipe_scheduled()
        self.assertEqual(len(inserted), 1)
        self.assertEqual(inserted[0]["name"], tasks.SIGN_IN_IP_WIPE_SCHEDULE_NAME)
        self.assertEqual(inserted[0]["task"], "app.tasks.security_event_tasks.wipe_sign_in_ips_task")
        self.assertEqual(inserted[0]["schedule_id"], 7)

    def test_worker_startup_registers_and_seeds_it(self):
        source = (Path(__file__).resolve().parents[1] / "make_celery.py").read_text()
        self.assertIn("import app.tasks.security_event_tasks", source)
        self.assertIn("ensure_sign_in_ip_wipe_scheduled()", source)
