"""The Celery sweep that copies the attachment upload backlog into the bucket.

``run_attachment_s3_upload`` is the scheduled form of ``flask attachments
s3-upload``; ``run_attachment_local_quarantine`` is the manual-only form of
``flask attachments local-quarantine``. Both run against moto here — nothing
ever reaches AWS.

The task bodies are invoked through ``.run()`` rather than by calling the task,
for the reason ``tests/test_db_backup_cli_and_task.py`` gives: a bound task
resolves its app through the *current* Celery, and the suite's other modules
make that unpredictable.

Policy baseline: docs/policy/attachment-storage.md.
"""

import os
import uuid
from unittest.mock import patch

import sqlalchemy as sa

from app import db
from app.models.va_sync_runs import VaSyncRun
from app.services import attachment_service as svc
from app.tasks import sync_tasks
from tests.base import BaseTestCase
from tests.test_attachments_s3_cli import S3UploadBase


class _Recorder:
    """Stands in for ``_log_progress``; the progress log itself is another
    connection and cannot see rows held in the class transaction."""

    def __init__(self):
        self.messages = []

    def __call__(self, db_, run_id, msg):
        self.messages.append(msg)

    @property
    def text(self):
        return "\n".join(self.messages)


class AttachmentS3UploadTaskTests(S3UploadBase):
    FORM_ID = "S3TASK_FORM"

    def setUp(self):
        super().setUp()
        self.progress = _Recorder()
        patcher = patch.object(sync_tasks, "_log_progress", self.progress)
        patcher.start()
        self.addCleanup(patcher.stop)
        # No Redis mutex unless a test asks for one: the suite shares a Redis
        # with whatever else is running, and a sweep must not depend on it.
        lock_patcher = patch.object(sync_tasks, "_lock_client", lambda: None)
        lock_patcher.start()
        self.addCleanup(lock_patcher.stop)
        self.addCleanup(self._delete_runs)

    def _delete_runs(self):
        """The task commits, so the per-test savepoint cannot undo its rows."""
        db.session.execute(
            sa.delete(VaSyncRun).where(
                VaSyncRun.triggered_by.in_(
                    [svc.S3_UPLOAD_TRIGGER, svc.QUARANTINE_TRIGGER]
                )
            )
        )
        db.session.commit()

    def _runs(self):
        return list(
            db.session.scalars(
                sa.select(VaSyncRun)
                .where(VaSyncRun.triggered_by == svc.S3_UPLOAD_TRIGGER)
                .order_by(VaSyncRun.started_at)
            ).all()
        )

    def _sweep(self, **kwargs):
        kwargs.setdefault("form_id", self.FORM_ID)
        return sync_tasks.run_attachment_s3_upload.run(**kwargs)

    # -- success ----------------------------------------------------------

    def test_a_sweep_uploads_verifies_and_records_a_run_row(self):
        storage_name = uuid.uuid4().hex + ".jpg"
        row = self._row(storage_name=storage_name)

        result = self._sweep()

        self.assertEqual(result["scanned"], 1)
        self.assertEqual(result["uploaded"], 1)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["remaining"], 0)

        head = self.store.head(self._key(storage_name))
        self.assertEqual(head["ContentLength"], len(b"payload"))
        refreshed = self._reload(row)
        self.assertEqual(refreshed.store_state, svc.STORE_STATE_S3)
        # The upload never deletes a local file.
        self.assertTrue(os.path.isfile(
            os.path.join(self._tmp.name, self.FORM_ID, "media", storage_name)
        ))

        runs = self._runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status, "success")
        self.assertEqual(runs[0].records_updated, 1)
        self.assertEqual(runs[0].records_skipped, 0)
        self.assertIsNotNone(runs[0].finished_at)

    def test_the_progress_log_holds_counts_and_no_identifiers(self):
        storage_name = uuid.uuid4().hex + ".jpg"
        self._row(storage_name=storage_name)

        self._sweep()

        self.assertIn("scanned=1", self.progress.text)
        self.assertIn("uploaded=1", self.progress.text)
        self.assertIn("failed=0", self.progress.text)
        self.assertIn("remaining=0", self.progress.text)
        self.assertNotIn(storage_name, self.progress.text)
        self.assertNotIn(self._tmp.name, self.progress.text)

    def test_the_limit_bounds_one_sweep(self):
        for _ in range(3):
            self._row(storage_name=uuid.uuid4().hex + ".jpg")

        result = self._sweep(limit=2)

        self.assertEqual(result["scanned"], 2)
        self.assertEqual(result["uploaded"], 2)
        self.assertEqual(result["remaining"], 1)
        self.assertEqual(self._runs()[0].records_skipped, 1)

    # -- no-ops -----------------------------------------------------------

    def test_the_local_store_is_an_instant_no_op_with_no_run_row(self):
        self._row(storage_name=uuid.uuid4().hex + ".jpg")
        self.app.config["ATTACHMENT_STORE"] = svc.STORE_STATE_LOCAL
        self.app.extensions.pop("attachment_store", None)

        result = self._sweep()

        self.assertEqual(result["skipped"], "local_store")
        self.assertEqual(self._runs(), [])

    def test_an_empty_backlog_is_a_no_op_with_no_run_row(self):
        result = self._sweep()

        self.assertEqual(result["skipped"], "empty_backlog")
        self.assertEqual(result["remaining"], 0)
        self.assertEqual(self._runs(), [])

    def test_a_no_op_still_closes_a_run_row_the_caller_created(self):
        run = VaSyncRun(triggered_by=svc.S3_UPLOAD_TRIGGER, status="running")
        db.session.add(run)
        db.session.commit()

        result = self._sweep(run_id=str(run.sync_run_id))

        self.assertEqual(result["skipped"], "empty_backlog")
        runs = self._runs()
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].status, "success")
        self.assertEqual(runs[0].records_skipped, 0)

    # -- failure ----------------------------------------------------------

    def test_an_upload_failure_is_counted_and_the_task_still_returns(self):
        self._row(storage_name=uuid.uuid4().hex + ".jpg", with_file=False)

        result = self._sweep()

        self.assertEqual(result["failed"], 1)
        self.assertEqual(result["uploaded"], 0)
        self.assertEqual(result["remaining"], 1)
        run = self._runs()[0]
        self.assertEqual(run.status, "partial")
        self.assertIn("could not be uploaded", run.error_message)

    def test_a_service_error_marks_the_run_and_never_raises(self):
        self._row(storage_name=uuid.uuid4().hex + ".jpg")
        with patch.object(
            svc, "s3_upload_backlog", side_effect=RuntimeError("bucket exploded")
        ):
            result = self._sweep()

        self.assertEqual(result["skipped"], "error")
        run = self._runs()[0]
        self.assertEqual(run.status, "error")
        self.assertIn("bucket exploded", run.error_message)

    # -- concurrency ------------------------------------------------------

    def test_a_second_sweep_is_skipped_while_one_holds_the_lock(self):
        self._row(storage_name=uuid.uuid4().hex + ".jpg")
        client = _FakeLockClient()
        with patch.object(sync_tasks, "_lock_client", lambda: client):
            held = client.set(
                sync_tasks.ATTACHMENT_S3_UPLOAD_LOCK_KEY, "someone-else",
                nx=True, ex=60,
            )
            self.assertTrue(held)
            result = self._sweep()

        self.assertEqual(result["skipped"], "locked")
        self.assertEqual(result["remaining"], 1)
        # Nothing was uploaded and no run row was opened for the skipped sweep.
        self.assertEqual(self._runs(), [])

    def test_the_lock_is_released_so_the_next_sweep_runs(self):
        self._row(storage_name=uuid.uuid4().hex + ".jpg")
        client = _FakeLockClient()
        with patch.object(sync_tasks, "_lock_client", lambda: client):
            first = self._sweep()
            self._row(storage_name=uuid.uuid4().hex + ".jpg")
            second = self._sweep()

        self.assertEqual(first["uploaded"], 1)
        self.assertEqual(second["uploaded"], 1)
        self.assertEqual(client.store, {})

    def test_a_sweep_runs_when_the_lock_backend_is_unreachable(self):
        self._row(storage_name=uuid.uuid4().hex + ".jpg")
        client = _FakeLockClient(fail=True)
        with patch.object(sync_tasks, "_lock_client", lambda: client):
            result = self._sweep()

        self.assertEqual(result["uploaded"], 1)


class _FakeLockClient:
    """The two Redis calls ``_sweep_lock`` makes, without a Redis."""

    def __init__(self, fail=False):
        self.store = {}
        self.fail = fail

    def set(self, key, value, nx=False, ex=None):
        if self.fail:
            raise ConnectionError("no redis")
        if nx and key in self.store:
            return None
        self.store[key] = value.encode() if isinstance(value, str) else value
        return True

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)


class AttachmentLocalQuarantineTaskTests(S3UploadBase):
    FORM_ID = "S3QUAR_FORM"

    def setUp(self):
        super().setUp()
        self.progress = _Recorder()
        patcher = patch.object(sync_tasks, "_log_progress", self.progress)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._delete_runs)

    def _delete_runs(self):
        db.session.execute(
            sa.delete(VaSyncRun).where(
                VaSyncRun.triggered_by == svc.QUARANTINE_TRIGGER
            )
        )
        db.session.commit()

    def test_it_moves_a_verified_local_file_and_records_the_run(self):
        storage_name = uuid.uuid4().hex + ".jpg"
        self._row(storage_name=storage_name)
        sync_tasks.run_attachment_s3_upload.run(form_id=self.FORM_ID)

        counts = sync_tasks.run_attachment_local_quarantine.run(form_id=self.FORM_ID)

        self.assertEqual(counts["moved"], 1)
        media = os.path.join(self._tmp.name, self.FORM_ID, "media")
        self.assertFalse(os.path.isfile(os.path.join(media, storage_name)))
        self.assertTrue(os.path.isfile(
            os.path.join(media, svc.QUARANTINE_DIRNAME, storage_name)
        ))
        run = db.session.scalars(
            sa.select(VaSyncRun).where(
                VaSyncRun.triggered_by == svc.QUARANTINE_TRIGGER
            )
        ).one()
        self.assertEqual(run.status, "success")
        self.assertEqual(run.records_updated, 1)
        self.assertIn("moved=1", self.progress.text)

    def test_the_local_store_is_a_no_op_with_no_run_row(self):
        self.app.config["ATTACHMENT_STORE"] = svc.STORE_STATE_LOCAL
        self.app.extensions.pop("attachment_store", None)

        counts = sync_tasks.run_attachment_local_quarantine.run()

        self.assertEqual(counts["skipped"], "local_store")
        self.assertEqual(
            db.session.scalars(
                sa.select(VaSyncRun).where(
                    VaSyncRun.triggered_by == svc.QUARANTINE_TRIGGER
                )
            ).all(),
            [],
        )


class SweepMinutesParsingTests(BaseTestCase):
    """``parse_sweep_minutes`` never stops the sweep over a bad config value."""

    def test_a_valid_interval_is_parsed(self):
        self.assertEqual(sync_tasks.parse_sweep_minutes(30), 30)
        self.assertEqual(sync_tasks.parse_sweep_minutes("5"), 5)

    def test_a_missing_or_out_of_range_value_falls_back_to_the_default(self):
        default = sync_tasks.DEFAULT_ATTACHMENT_S3_UPLOAD_SWEEP_MINUTES
        for value in (None, "", "soon", 0, -1, 10000):
            self.assertEqual(sync_tasks.parse_sweep_minutes(value), default)
