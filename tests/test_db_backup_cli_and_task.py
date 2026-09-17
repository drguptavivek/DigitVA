"""The `flask backups` commands and the scheduled `run_db_backup` task.

Both are thin wrappers, so what is asserted here is wrapper behaviour: exit
codes, what is printed, and the one rule that matters for a scheduled job — the
task never raises, whatever the service does.

Everything runs on the local store against the test database; no S3 client is
built and no AWS endpoint is contacted.
"""

import io
import os
from unittest import mock

from app.models import VaDbBackup
from app.services import db_backup_service as svc
from app.tasks import backup_tasks
from tests.base import BaseTestCase
from tests.services.test_db_backup_service import DbBackupBase


class DbBackupCliTests(DbBackupBase):
    """`flask backups db-dump` / `db-prune` / `db-list` / `db-download`."""

    def setUp(self):
        super().setUp()
        self.runner = self.app.test_cli_runner()
        self._override("DB_BACKUP_KEEP_DAILY", 2)

    def _dumps(self):
        return sorted(os.listdir(self.local_dir.name))

    def test_db_dump_makes_a_dump_and_prunes(self):
        for stamp in ("20260101T010000Z", "20260102T010000Z", "20260103T010000Z"):
            with open(
                os.path.join(self.local_dir.name, f"pg_dump_minerva_{stamp}.dump"), "wb"
            ) as handle:
                handle.write(b"x")

        result = self.runner.invoke(args=["backups", "db-dump"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("status=success", result.output)
        self.assertIn("sha256:", result.output)
        # The new dump plus DB_BACKUP_KEEP_DAILY-1 of the old ones.
        self.assertEqual(len(self._dumps()), 2)

    def test_db_dump_no_prune_keeps_every_existing_dump(self):
        for stamp in ("20260101T010000Z", "20260102T010000Z"):
            with open(
                os.path.join(self.local_dir.name, f"pg_dump_minerva_{stamp}.dump"), "wb"
            ) as handle:
                handle.write(b"x")

        result = self.runner.invoke(args=["backups", "db-dump", "--no-prune"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertNotIn("prune:", result.output)
        self.assertEqual(len(self._dumps()), 3)

    def test_db_dump_exits_non_zero_when_the_dump_fails(self):
        with mock.patch.object(svc.subprocess, "Popen", side_effect=FileNotFoundError):
            result = self.runner.invoke(args=["backups", "db-dump"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn(svc.ERROR_PG_DUMP_MISSING, result.output)
        self.assertEqual(self._dumps(), [])

    def test_db_prune_dry_run_deletes_nothing(self):
        for stamp in ("20260101T010000Z", "20260102T010000Z", "20260103T010000Z"):
            with open(
                os.path.join(self.local_dir.name, f"pg_dump_minerva_{stamp}.dump"), "wb"
            ) as handle:
                handle.write(b"x")

        result = self.runner.invoke(args=["backups", "db-prune", "--dry-run"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("dry run", result.output)
        self.assertEqual(len(self._dumps()), 3)

    def test_db_prune_applies_retention(self):
        for stamp in ("20260101T010000Z", "20260102T010000Z", "20260103T010000Z"):
            with open(
                os.path.join(self.local_dir.name, f"pg_dump_minerva_{stamp}.dump"), "wb"
            ) as handle:
                handle.write(b"x")

        result = self.runner.invoke(args=["backups", "db-prune"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("pruned=1", result.output)
        self.assertEqual(len(self._dumps()), 2)

    def test_db_list_prints_the_recent_backups_and_never_a_connection_string(self):
        outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_CLI)

        result = self.runner.invoke(args=["backups", "db-list", "--limit", "5"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn(outcome.object_key, result.output)
        self.assertIn("Backup store: local", result.output)
        # The listing names dumps, never how to reach the database. (The test
        # password is a substring of the database name, so the URI as a whole is
        # what can be asserted on here.)
        self.assertNotIn("postgresql://", result.output)
        self.assertNotIn(self.app.config["SQLALCHEMY_DATABASE_URI"], result.output)

    def test_db_download_writes_a_verified_copy(self):
        outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_CLI)
        dest = os.path.join(self.tmp_dir.name, "copy.dump")

        result = self.runner.invoke(
            args=["backups", "db-download", outcome.object_key, dest]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("sha256 verified", result.output)
        self.assertEqual(os.path.getsize(dest), outcome.size_bytes)

    def test_db_download_refuses_an_unknown_key(self):
        result = self.runner.invoke(
            args=[
                "backups",
                "db-download",
                "pg_dump_minerva_20200101T000000Z.dump",
                os.path.join(self.tmp_dir.name, "nope.dump"),
            ]
        )

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("No recorded checksum", result.output)


class _FakeProcess:
    """A pg_dump that wrote ``payload`` to stdout and exited ``returncode``."""

    def __init__(self, payload=b"PGDMP-fake-dump-bytes", returncode=0):
        self.stdout = io.BytesIO(payload)
        self._returncode = returncode

    def wait(self, timeout=None):
        return self._returncode

    def kill(self):
        return None


class RunDbBackupTaskTests(DbBackupBase):
    """The scheduled task records everything and raises nothing.

    The dump is stubbed here on purpose: what is under test is the wrapper —
    what it returns, what it skips, what it swallows — not pg_dump, which the
    service tests exercise for real against the test database.

    The task body is invoked through ``.run()`` rather than by calling the task,
    because ``FlaskTask.__call__`` pushes the app context of whichever Celery app
    is current — and the suite's other modules make that unpredictable. ``.run()``
    executes the same function in this test's own app context.
    """

    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(
            svc.subprocess, "Popen", side_effect=lambda *a, **kw: _FakeProcess()
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_successful_run_reports_the_dump_and_the_prune(self):
        result = backup_tasks.run_db_backup.run(triggered_by=VaDbBackup.TRIGGER_SCHEDULED)

        self.assertEqual(result["status"], VaDbBackup.STATUS_SUCCESS, result)
        self.assertEqual(result["store"], "local")
        self.assertGreater(result["size_bytes"], 0)
        self.assertEqual(result["pruned"], 0)

    def test_a_failed_dump_is_recorded_and_the_prune_is_skipped(self):
        with mock.patch.object(svc.subprocess, "Popen", side_effect=FileNotFoundError):
            with mock.patch.object(svc, "prune_db_backups") as pruner:
                result = backup_tasks.run_db_backup.run()

        self.assertEqual(result["status"], VaDbBackup.STATUS_FAILED)
        self.assertEqual(result["error_code"], svc.ERROR_PG_DUMP_MISSING)
        pruner.assert_not_called()

    def test_the_task_never_raises_even_when_the_service_explodes(self):
        with mock.patch.object(
            svc, "create_db_backup", side_effect=RuntimeError("boom")
        ):
            result = backup_tasks.run_db_backup.run()

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "unexpected")

    def test_a_failed_prune_does_not_fail_a_good_backup(self):
        with mock.patch.object(
            svc, "prune_db_backups", side_effect=RuntimeError("boom")
        ):
            result = backup_tasks.run_db_backup.run()

        self.assertEqual(result["status"], VaDbBackup.STATUS_SUCCESS, result)
        self.assertEqual(result["prune_skipped"], "unexpected")


class DailyTimeParsingTests(BaseTestCase):
    """DB_BACKUP_DAILY_TIME decides the crontab row the beat entry points at."""

    def test_a_valid_time_is_parsed(self):
        self.assertEqual(backup_tasks.parse_daily_time("03:05"), (3, 5))

    def test_an_empty_or_invalid_value_falls_back_to_the_default(self):
        default = tuple(int(part) for part in backup_tasks.DEFAULT_DAILY_TIME.split(":"))
        for value in (None, "", "nonsense", "25:00", "01:75", "1"):
            self.assertEqual(backup_tasks.parse_daily_time(value), default, value)

