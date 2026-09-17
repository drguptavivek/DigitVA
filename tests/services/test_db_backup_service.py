"""Database dumps to the DigitVA object store.

Everything S3 here runs inside moto: no AWS credentials exist in this project
and no test may reach a real bucket. ``TestConfig`` keeps the suite on the local
store, so the classes that need the bucket flip ``ATTACHMENT_STORE`` themselves
exactly as the S3 attachment and SmartVA archive tests do.

``pg_dump`` is real: the container ships PostgreSQL 17 client binaries, and the
happy paths below dump the **test** database. Nothing here ever touches the
development database. The failure paths patch ``subprocess.Popen`` because a
genuinely failing pg_dump is not something a test can arrange safely.

Runbook baseline: docs/current-state/backup.md.
"""

import hashlib
import io
import os
import subprocess
import tempfile
import uuid
from unittest import mock

import sqlalchemy as sa
from moto import mock_aws

from app import db
from app.models import VaDbBackup
from app.services import attachment_store as store_mod
from app.services import db_backup_service as svc
from tests.base import BaseTestCase


class _FakeProcess:
    """A pg_dump that wrote ``payload`` to stdout and exited ``returncode``."""

    def __init__(self, payload=b"", returncode=0):
        self.stdout = io.BytesIO(payload)
        self._returncode = returncode

    def wait(self, timeout=None):
        return self._returncode

    def kill(self):
        return None


class DbBackupBase(BaseTestCase):
    """Isolated temp and local-backup directories, pinned to the local store.

    Shared with the CLI, task and admin-panel backup tests, which import this
    class rather than repeating the fixture.
    """

    def setUp(self):
        super().setUp()
        self._pin_local_store()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.local_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.addCleanup(self.local_dir.cleanup)
        self._override("DB_BACKUP_TMP_DIR", self.tmp_dir.name)
        self._override("DB_BACKUP_LOCAL_DIR", self.local_dir.name)
        self._override("DB_BACKUP_KEEP_DAILY", 3)

    def _pin_local_store(self):
        """Run against the local store whatever an earlier module left behind.

        ``ATTACHMENT_STORE`` lives on the session-wide app, and several modules
        flip it; a backup test must not inherit whichever value happened to
        survive. Production has one store per deployment, and these classes want
        the local one.
        """
        old_store = self.app.config.get("ATTACHMENT_STORE")
        self.app.config["ATTACHMENT_STORE"] = "local"
        self.app.extensions.pop("attachment_store", None)

        def restore():
            self.app.config["ATTACHMENT_STORE"] = old_store
            self.app.extensions.pop("attachment_store", None)

        self.addCleanup(restore)

    def _override(self, key, value):
        old = self.app.config.get(key)
        self.app.config[key] = value
        self.addCleanup(lambda: self.app.config.__setitem__(key, old))

    def _rows(self):
        return list(
            db.session.scalars(
                sa.select(VaDbBackup).order_by(VaDbBackup.started_at)
            ).all()
        )

    def _temp_files(self):
        return [name for name in os.listdir(self.tmp_dir.name) if "db_backup" in name]

    def _patch_dump(self, payload=b"PGDMP-fake-dump-bytes", returncode=0):
        """Replace pg_dump with a process that emits exactly ``payload``."""
        patcher = mock.patch.object(
            svc.subprocess,
            "Popen",
            return_value=_FakeProcess(payload, returncode),
        )
        self.addCleanup(patcher.stop)
        return patcher.start()


class PgDumpCommandTests(DbBackupBase):
    """The password must reach pg_dump through the environment, never argv."""

    def test_password_is_in_the_environment_and_not_in_the_argument_vector(self):
        self._override(
            "SQLALCHEMY_DATABASE_URI",
            "postgresql://dumpuser:sup3r-s3cret@db.example:5433/minerva_test_a",
        )

        argv, env = svc._pg_dump_command()

        self.assertNotIn("sup3r-s3cret", " ".join(argv))
        self.assertEqual(env["PGPASSWORD"], "sup3r-s3cret")
        self.assertEqual(argv[0], "pg_dump")
        self.assertIn("--format=custom", argv)
        self.assertIn("dumpuser", argv)
        self.assertIn("5433", argv)
        # No --file: the archive goes to stdout so it can be hashed in one pass.
        self.assertNotIn("--file", argv)

    def test_a_url_without_a_password_clears_any_inherited_one(self):
        self._override(
            "SQLALCHEMY_DATABASE_URI", "postgresql://dumpuser@db.example/minerva_test_a"
        )
        with mock.patch.dict(os.environ, {"PGPASSWORD": "inherited"}, clear=False):
            _argv, env = svc._pg_dump_command()
        self.assertNotIn("PGPASSWORD", env)


class LocalStoreBackupTests(DbBackupBase):
    """With ATTACHMENT_STORE=local the dump lands in DB_BACKUP_LOCAL_DIR."""

    def test_a_real_pg_dump_of_the_test_database_is_written_and_recorded(self):
        outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_CLI)

        self.assertEqual(outcome.status, VaDbBackup.STATUS_SUCCESS, outcome.error_code)
        self.assertEqual(outcome.store, "local")
        self.assertGreater(outcome.size_bytes, 0)
        path = os.path.join(self.local_dir.name, outcome.object_key)
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.getsize(path), outcome.size_bytes)
        with open(path, "rb") as handle:
            self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), outcome.sha256)
        self.assertEqual(self._temp_files(), [])

        row = db.session.get(VaDbBackup, uuid.UUID(outcome.backup_id))
        self.assertEqual(row.status, VaDbBackup.STATUS_SUCCESS)
        self.assertEqual(row.store, "local")
        self.assertEqual(row.triggered_by, VaDbBackup.TRIGGER_CLI)
        self.assertIsNotNone(row.completed_at)
        self.assertIsNone(row.error_code)

    def test_prune_keeps_the_newest_n_dumps_in_the_directory(self):
        names = [
            f"pg_dump_minerva_2026090{day}T010000Z.dump" for day in range(1, 7)
        ]
        for name in names:
            with open(os.path.join(self.local_dir.name, name), "wb") as handle:
                handle.write(b"x")

        outcome = svc.prune_db_backups(keep_daily=3)

        self.assertEqual(outcome.pruned, 3)
        self.assertEqual(outcome.kept, 3)
        self.assertEqual(
            sorted(os.listdir(self.local_dir.name)), sorted(names[3:])
        )

    def test_prune_never_removes_the_only_dump_even_at_keep_zero(self):
        name = "pg_dump_minerva_20260901T010000Z.dump"
        with open(os.path.join(self.local_dir.name, name), "wb") as handle:
            handle.write(b"x")

        outcome = svc.prune_db_backups(keep_daily=0)

        self.assertEqual(outcome.pruned, 0)
        self.assertEqual(os.listdir(self.local_dir.name), [name])

    def test_download_verifies_the_recorded_sha256(self):
        outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_CLI)
        dest = os.path.join(self.tmp_dir.name, "restored.dump")

        result = svc.download_db_backup(outcome.object_key, dest)

        self.assertEqual(result["sha256"], outcome.sha256)
        self.assertEqual(result["size_bytes"], outcome.size_bytes)
        self.assertTrue(os.path.isfile(dest))

    def test_download_rejects_a_dump_whose_bytes_changed(self):
        outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_CLI)
        with open(os.path.join(self.local_dir.name, outcome.object_key), "ab") as handle:
            handle.write(b"tampered")
        dest = os.path.join(self.tmp_dir.name, "restored.dump")

        with self.assertRaises(svc.DbBackupError) as caught:
            svc.download_db_backup(outcome.object_key, dest)

        self.assertIn("Checksum mismatch", str(caught.exception))
        self.assertFalse(os.path.exists(dest))

    def test_download_refuses_a_key_with_no_recorded_checksum(self):
        with self.assertRaises(svc.DbBackupError):
            svc.download_db_backup(
                "pg_dump_minerva_20260101T000000Z.dump",
                os.path.join(self.tmp_dir.name, "nope.dump"),
            )

    def test_overview_reports_retention_and_the_last_success(self):
        outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_CLI)

        report = svc.db_backup_overview()

        self.assertEqual(report["store"], "local")
        self.assertEqual(report["keep_daily"], 3)
        self.assertEqual(report["daily_time"], self.app.config["DB_BACKUP_DAILY_TIME"])
        self.assertEqual(report["last_success"]["object_key"], outcome.object_key)
        self.assertIsNone(report["last_failure"])
        self.assertGreaterEqual(report["successful_backups"], 1)
        self.assertLessEqual(len(report["recent"]), svc.OVERVIEW_LIMIT)


class PgDumpFailureTests(DbBackupBase):
    """A failed dump is a `failed` row, no file, and no temp left behind."""

    def test_a_nonzero_pg_dump_records_failed_and_writes_nothing(self):
        self._patch_dump(payload=b"partial", returncode=1)

        outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_SCHEDULED)

        self.assertEqual(outcome.status, VaDbBackup.STATUS_FAILED)
        self.assertEqual(outcome.error_code, svc.ERROR_PG_DUMP_FAILED)
        self.assertIsNone(outcome.object_key)
        self.assertEqual(os.listdir(self.local_dir.name), [])
        self.assertEqual(self._temp_files(), [])

    def test_an_empty_dump_is_a_failure_not_a_zero_byte_backup(self):
        self._patch_dump(payload=b"", returncode=0)

        outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_SCHEDULED)

        self.assertEqual(outcome.error_code, svc.ERROR_DUMP_EMPTY)
        self.assertEqual(os.listdir(self.local_dir.name), [])

    def test_a_missing_pg_dump_binary_is_reported_as_such(self):
        with mock.patch.object(svc.subprocess, "Popen", side_effect=FileNotFoundError):
            outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_SCHEDULED)

        self.assertEqual(outcome.error_code, svc.ERROR_PG_DUMP_MISSING)

    def test_a_dump_over_the_single_request_limit_is_aborted(self):
        self._override("DB_BACKUP_TMP_DIR", self.tmp_dir.name)
        self._patch_dump(payload=b"z" * 64)
        with mock.patch.object(svc, "PUT_OBJECT_MAX_BYTES", 16):
            outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_SCHEDULED)

        self.assertEqual(outcome.error_code, svc.ERROR_DUMP_TOO_LARGE)
        self.assertEqual(os.listdir(self.local_dir.name), [])
        self.assertEqual(self._temp_files(), [])

    def test_a_pg_dump_that_never_finishes_times_out(self):
        process = _FakeProcess(b"bytes", 0)
        process.wait = mock.Mock(
            side_effect=subprocess.TimeoutExpired(cmd="pg_dump", timeout=1)
        )
        with mock.patch.object(svc.subprocess, "Popen", return_value=process):
            outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_SCHEDULED)

        self.assertEqual(outcome.error_code, svc.ERROR_PG_DUMP_TIMEOUT)


class S3BackupBase(DbBackupBase):
    """DbBackupBase with ATTACHMENT_STORE=s3 and a moto bucket."""

    def setUp(self):
        super().setUp()
        self.mock = mock_aws()
        self.mock.start()
        self.addCleanup(self.mock.stop)
        self.addCleanup(store_mod.reset_s3_clients)
        store_mod.reset_s3_clients()
        self._old_store_name = self.app.config.get("ATTACHMENT_STORE")
        self.app.config["ATTACHMENT_STORE"] = "s3"
        self.app.extensions.pop("attachment_store", None)
        self.addCleanup(self._restore_store)
        self.store = store_mod.get_attachment_store()
        self.store.client.create_bucket(
            Bucket=self.store.bucket,
            CreateBucketConfiguration={
                "LocationConstraint": self.app.config["S3_REGION"]
            },
        )

    def _restore_store(self):
        self.app.config["ATTACHMENT_STORE"] = self._old_store_name
        self.app.extensions.pop("attachment_store", None)

    def _keys(self):
        return {
            key for key, _size, _etag in self.store.iter_keys(svc.BACKUP_KEY_ROOT)
        }


class S3BackupTests(S3BackupBase):
    """The real contract: dump, upload, verify, and leave nothing on the VM."""

    def test_a_real_dump_reaches_the_bucket_verified_and_leaves_no_temp_file(self):
        outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_SCHEDULED)

        self.assertEqual(outcome.status, VaDbBackup.STATUS_SUCCESS, outcome.error_code)
        self.assertEqual(outcome.store, "s3")
        self.assertTrue(outcome.object_key.startswith(svc.dump_key_prefix()))
        self.assertEqual(self._keys(), {outcome.object_key})

        head = self.store.head_key(outcome.object_key)
        self.assertEqual(int(head["ContentLength"]), outcome.size_bytes)
        self.assertEqual(head["ContentType"], "application/octet-stream")
        self.assertEqual(head["CacheControl"], store_mod.STORE_CACHE_CONTROL)
        self.assertEqual(head["ServerSideEncryption"], "AES256")

        self.assertEqual(self._temp_files(), [])
        self.assertEqual(os.listdir(self.local_dir.name), [])

        row = db.session.get(VaDbBackup, uuid.UUID(outcome.backup_id))
        self.assertEqual(row.status, VaDbBackup.STATUS_SUCCESS)
        self.assertEqual(row.sha256, outcome.sha256)
        self.assertEqual(row.size_bytes, outcome.size_bytes)

    def test_an_upload_failure_records_failed_and_leaves_no_object(self):
        self._patch_dump()
        original = type(self.store).put_key

        def boom(self, key, source, *, content_type=None):
            raise store_mod.AttachmentStoreError("nope")

        type(self.store).put_key = boom
        self.addCleanup(lambda: setattr(type(self.store), "put_key", original))

        outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_SCHEDULED)

        self.assertEqual(outcome.status, VaDbBackup.STATUS_FAILED)
        self.assertEqual(outcome.error_code, svc.ERROR_UPLOAD_FAILED)
        self.assertEqual(self._keys(), set())
        self.assertEqual(self._temp_files(), [])

    def test_a_short_object_fails_verification_and_is_deleted(self):
        self._patch_dump(payload=b"the full dump body")
        original = type(self.store).put_key

        def truncate(store_self, key, source, *, content_type=None):
            return original(store_self, key, io.BytesIO(b"short"),
                            content_type=content_type)

        type(self.store).put_key = truncate
        self.addCleanup(lambda: setattr(type(self.store), "put_key", original))

        outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_SCHEDULED)

        self.assertEqual(outcome.error_code, svc.ERROR_VERIFY_MISMATCH)
        self.assertEqual(self._keys(), set())

    def test_prune_keeps_the_newest_n_objects_and_marks_their_rows(self):
        prefix = svc.dump_key_prefix()
        keys = [
            f"{prefix}pg_dump_minerva_2026090{day}T010000Z.dump"
            for day in range(1, 7)
        ]
        for key in keys:
            self.store.put_key(key, io.BytesIO(b"x"), content_type=None)
            db.session.add(VaDbBackup(
                triggered_by=VaDbBackup.TRIGGER_SCHEDULED,
                status=VaDbBackup.STATUS_SUCCESS,
                store="s3",
                object_key=key,
                size_bytes=1,
                sha256="0" * 64,
            ))
        db.session.commit()

        outcome = svc.prune_db_backups(keep_daily=3)

        self.assertEqual(outcome.pruned, 3)
        self.assertEqual(outcome.kept, 3)
        self.assertEqual(self._keys(), set(keys[3:]))
        pruned_rows = db.session.scalars(
            sa.select(VaDbBackup).where(VaDbBackup.status == VaDbBackup.STATUS_PRUNED)
        ).all()
        self.assertEqual({row.object_key for row in pruned_rows}, set(keys[:3]))
        self.assertTrue(all(row.pruned_at is not None for row in pruned_rows))

    def test_prune_deletes_nothing_when_the_listing_fails(self):
        self.store.put_key(
            f"{svc.dump_key_prefix()}pg_dump_minerva_20260901T010000Z.dump",
            io.BytesIO(b"x"),
            content_type=None,
        )
        with mock.patch.object(
            svc, "_list_dump_names", side_effect=store_mod.AttachmentStoreError("x")
        ):
            outcome = svc.prune_db_backups(keep_daily=0)

        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.skipped_reason, "listing_failed")
        self.assertEqual(outcome.pruned, 0)
        self.assertEqual(len(self._keys()), 1)

    def test_download_from_the_bucket_verifies_the_recorded_sha256(self):
        outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_SCHEDULED)
        dest = os.path.join(self.tmp_dir.name, "restored.dump")

        result = svc.download_db_backup(outcome.object_key, dest)

        self.assertEqual(result["sha256"], outcome.sha256)
        self.assertEqual(os.path.getsize(dest), outcome.size_bytes)

    def test_download_rejects_an_object_whose_bytes_changed(self):
        outcome = svc.create_db_backup(triggered_by=VaDbBackup.TRIGGER_SCHEDULED)
        self.store.put_key(
            outcome.object_key,
            io.BytesIO(b"not the dump you recorded"),
            content_type=None,
        )
        dest = os.path.join(self.tmp_dir.name, "restored.dump")

        with self.assertRaises(svc.DbBackupError):
            svc.download_db_backup(outcome.object_key, dest)

        self.assertFalse(os.path.exists(dest))
