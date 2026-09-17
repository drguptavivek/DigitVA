"""SmartVA run-directory archival to the DigitVA object store.

Everything S3 here runs inside moto: no AWS credentials exist in this project
and no test may reach a real bucket. ``TestConfig`` keeps the suite on the
local store, so the classes that need the bucket flip ``ATTACHMENT_STORE``
themselves exactly as the S3 attachment tests do.

Policy baseline: docs/policy/smartva-generation-policy.md.
"""

import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from moto import mock_aws

from app import db
from app.models import (
    VaForms,
    VaProjectMaster,
    VaResearchProjects,
    VaSites,
    VaSmartvaFormRun,
    VaStatuses,
)
from app.services import attachment_store as store_mod
from app.services import smartva_run_archive_service as archive_svc
from tests.base import BaseTestCase


class SmartvaArchiveBase(BaseTestCase):
    """A project/site/form plus an isolated APP_SMARTVA_RUNS directory."""

    PROJECT_ID = "SVAR01"
    SITE_ID = "SR01"
    FORM_ID = "SVAR01SR0101"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        now = datetime.now(timezone.utc)
        if not db.session.get(VaProjectMaster, cls.PROJECT_ID):
            db.session.add(VaProjectMaster(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="SmartVA Archive Project",
                project_nickname="SvaArch",
                project_status=VaStatuses.active,
            ))
        if not db.session.get(VaResearchProjects, cls.PROJECT_ID):
            db.session.add(VaResearchProjects(
                project_id=cls.PROJECT_ID,
                project_code=cls.PROJECT_ID,
                project_name="SmartVA Archive Project",
                project_nickname="SvaArch",
                project_status=VaStatuses.active,
                project_registered_at=now,
                project_updated_at=now,
            ))
        db.session.flush()
        if not db.session.get(VaSites, cls.SITE_ID):
            db.session.add(VaSites(
                site_id=cls.SITE_ID,
                project_id=cls.PROJECT_ID,
                site_name="SmartVA Archive Site",
                site_abbr=cls.SITE_ID,
                site_status=VaStatuses.active,
                site_registered_at=now,
                site_updated_at=now,
            ))
            db.session.flush()
        if not db.session.get(VaForms, cls.FORM_ID):
            db.session.add(VaForms(
                form_id=cls.FORM_ID,
                project_id=cls.PROJECT_ID,
                site_id=cls.SITE_ID,
                odk_form_id="SVAR_ODK",
                odk_project_id="91",
                form_type="WHO VA 2022",
                form_status=VaStatuses.active,
                form_registered_at=now,
                form_updated_at=now,
            ))
        db.session.commit()

    def setUp(self):
        super().setUp()
        self.runs_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.runs_dir.cleanup)
        self._old_runs_dir = self.app.config["APP_SMARTVA_RUNS"]
        self.app.config["APP_SMARTVA_RUNS"] = self.runs_dir.name
        self.addCleanup(
            lambda: self.app.config.__setitem__(
                "APP_SMARTVA_RUNS", self._old_runs_dir
            )
        )

    # -- fixtures ----------------------------------------------------------

    def _make_form_run(self, *, with_files=True, completed_days_ago=0):
        """A completed form run whose directory holds one file of each type."""
        completed = datetime.now(timezone.utc) - timedelta(days=completed_days_ago)
        form_run = VaSmartvaFormRun(
            form_run_id=uuid.uuid4(),
            form_id=self.FORM_ID,
            project_id=self.PROJECT_ID,
            trigger_source="test",
            pending_sid_count=1,
            outcome=VaSmartvaFormRun.OUTCOME_SUCCESS,
            run_started_at=completed,
            run_completed_at=completed,
        )
        db.session.add(form_run)
        db.session.flush()

        rel_path = f"{self.PROJECT_ID}/{self.FORM_ID}/{form_run.form_run_id}"
        if with_files:
            run_dir = os.path.join(self.runs_dir.name, rel_path)
            os.makedirs(
                os.path.join(run_dir, "smartva_output", "4-monitoring-and-quality"),
                exist_ok=True,
            )
            self._write(run_dir, "input.csv", b"sid,age\nx,45\n")
            self._write(
                run_dir,
                "smartva_output/4-monitoring-and-quality/report.txt",
                b"report\n",
            )
            self._write(
                run_dir,
                "smartva_output/4-monitoring-and-quality/chart.png",
                b"\x89PNG fake",
            )
            form_run.disk_path = rel_path
            db.session.flush()
        return form_run, rel_path

    @staticmethod
    def _write(run_dir, relpath, payload):
        path = os.path.join(run_dir, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(payload)

    def _run_dir(self, rel_path):
        return os.path.join(self.runs_dir.name, rel_path)


class LocalStoreArchiveTests(SmartvaArchiveBase):
    """With ATTACHMENT_STORE=local nothing is archived and nothing is deleted."""

    def test_archive_is_a_no_op_and_the_state_stays_local(self):
        form_run, rel_path = self._make_form_run()

        outcome = archive_svc.archive_form_run(form_run)

        self.assertEqual(outcome.state, VaSmartvaFormRun.ARCHIVE_STATE_LOCAL)
        self.assertEqual(form_run.archive_state, VaSmartvaFormRun.ARCHIVE_STATE_LOCAL)
        self.assertIsNone(form_run.archived_at)
        self.assertTrue(os.path.isdir(self._run_dir(rel_path)))
        self.assertEqual(form_run.disk_path, rel_path)

    def test_backlog_reports_that_it_skipped_the_local_store(self):
        self._make_form_run()

        counts = archive_svc.archive_run_backlog(delete_local=True)

        self.assertTrue(counts["skipped_local_store"])
        self.assertEqual(counts["archived"], 0)

    def test_overview_reports_the_local_footprint(self):
        self._make_form_run()

        report = archive_svc.smartva_archive_overview(form_id=self.FORM_ID)

        self.assertEqual(report["store"], "local")
        self.assertEqual(report["counts"][VaSmartvaFormRun.ARCHIVE_STATE_LOCAL], 1)
        self.assertEqual(report["local_run_dirs"], 1)
        self.assertGreater(report["local_bytes"], 0)
        self.assertIsNone(report["last_failure"])


class S3ArchiveBase(SmartvaArchiveBase):
    """SmartvaArchiveBase with ATTACHMENT_STORE=s3 and a moto bucket."""

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
            key for key, _size, _etag in self.store.iter_keys(
                archive_svc.ARCHIVE_KEY_ROOT
            )
        }

    def _break_put_key(self, replacement):
        """Swap S3AttachmentStore.put_key for this test only."""
        original = type(self.store).put_key
        type(self.store).put_key = replacement
        self.addCleanup(lambda: setattr(type(self.store), "put_key", original))


class S3ArchiveTests(S3ArchiveBase):
    """The real contract: upload, verify, then — and only then — delete."""

    # -- happy path --------------------------------------------------------

    def test_archives_every_file_and_removes_the_local_directory(self):
        form_run, rel_path = self._make_form_run()

        outcome = archive_svc.archive_form_run(form_run)

        prefix = (
            f"smartva_runs/{self.PROJECT_ID}/{self.FORM_ID}/{form_run.form_run_id}/"
        )
        self.assertEqual(outcome.state, VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED)
        self.assertEqual(outcome.file_count, 3)
        self.assertTrue(outcome.local_deleted)
        self.assertEqual(
            self._keys(),
            {
                prefix + "input.csv",
                prefix + "smartva_output/4-monitoring-and-quality/report.txt",
                prefix + "smartva_output/4-monitoring-and-quality/chart.png",
            },
        )
        self.assertEqual(form_run.archive_state, VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED)
        self.assertEqual(form_run.archive_key_prefix, prefix)
        self.assertEqual(form_run.archive_file_count, 3)
        self.assertGreater(form_run.archive_bytes, 0)
        self.assertIsNotNone(form_run.archived_at)
        self.assertIsNone(form_run.archive_error_code)
        self.assertIsNone(form_run.disk_path)
        self.assertFalse(os.path.exists(self._run_dir(rel_path)))

    def test_each_object_carries_the_content_type_for_its_extension(self):
        form_run, _rel_path = self._make_form_run()
        archive_svc.archive_form_run(form_run)

        prefix = form_run.archive_key_prefix
        expected = {
            prefix + "input.csv": "text/csv",
            prefix + "smartva_output/4-monitoring-and-quality/report.txt": "text/plain",
            prefix + "smartva_output/4-monitoring-and-quality/chart.png": "image/png",
        }
        for key, content_type in expected.items():
            head = self.store.client.head_object(Bucket=self.store.bucket, Key=key)
            self.assertEqual(head["ContentType"], content_type, key)
            self.assertEqual(head["ServerSideEncryption"], "AES256", key)
            self.assertEqual(head["CacheControl"], "private, no-store", key)

    def test_content_type_map_covers_the_office_report_formats(self):
        self.assertEqual(
            archive_svc.content_type_for("a/b/summary.xlsx"),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.assertEqual(
            archive_svc.content_type_for("a/b/summary.docx"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        self.assertEqual(
            archive_svc.content_type_for("a/b/unknown.bin"),
            "application/octet-stream",
        )

    def test_archiving_twice_is_idempotent(self):
        form_run, _rel_path = self._make_form_run()

        first = archive_svc.archive_form_run(form_run)
        keys_after_first = self._keys()
        second = archive_svc.archive_form_run(form_run)

        self.assertEqual(first.state, VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED)
        self.assertEqual(second.state, VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED)
        self.assertEqual(self._keys(), keys_after_first)

    # -- retention ---------------------------------------------------------

    def test_keep_days_holds_the_local_copy_until_the_window_passes(self):
        self.app.config["SMARTVA_RUNS_KEEP_LOCAL_DAYS"] = 7
        self.addCleanup(
            lambda: self.app.config.__setitem__("SMARTVA_RUNS_KEEP_LOCAL_DAYS", 0)
        )
        fresh, fresh_path = self._make_form_run(completed_days_ago=0)
        stale, stale_path = self._make_form_run(completed_days_ago=8)

        fresh_outcome = archive_svc.archive_form_run(fresh)
        stale_outcome = archive_svc.archive_form_run(stale)

        self.assertFalse(fresh_outcome.local_deleted)
        self.assertTrue(os.path.isdir(self._run_dir(fresh_path)))
        self.assertEqual(fresh.disk_path, fresh_path)
        self.assertTrue(stale_outcome.local_deleted)
        self.assertFalse(os.path.exists(self._run_dir(stale_path)))

    def test_delete_local_false_archives_but_keeps_the_directory(self):
        form_run, rel_path = self._make_form_run()

        outcome = archive_svc.archive_form_run(form_run, delete_local=False)

        self.assertEqual(outcome.state, VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED)
        self.assertFalse(outcome.local_deleted)
        self.assertTrue(os.path.isdir(self._run_dir(rel_path)))
        self.assertEqual(form_run.disk_path, rel_path)

    # -- failure -----------------------------------------------------------

    def test_a_failed_upload_keeps_the_directory_and_records_failed(self):
        form_run, rel_path = self._make_form_run()

        def explode(*args, **kwargs):
            raise store_mod.AttachmentStoreError("Attachment store write failed.")

        self._break_put_key(explode)

        outcome = archive_svc.archive_form_run(form_run)

        self.assertEqual(outcome.state, VaSmartvaFormRun.ARCHIVE_STATE_FAILED)
        self.assertEqual(outcome.error_code, archive_svc.ERROR_UPLOAD_FAILED)
        self.assertEqual(form_run.archive_state, VaSmartvaFormRun.ARCHIVE_STATE_FAILED)
        self.assertEqual(
            form_run.archive_error_code, archive_svc.ERROR_UPLOAD_FAILED
        )
        self.assertIsNone(form_run.archived_at)
        self.assertEqual(form_run.disk_path, rel_path)
        self.assertTrue(os.path.isdir(self._run_dir(rel_path)))

    def test_an_unverifiable_archive_keeps_the_directory(self):
        form_run, rel_path = self._make_form_run()

        # Uploads succeed but write nothing, so verification finds no object.
        self._break_put_key(lambda self, key, source, **kwargs: key)

        outcome = archive_svc.archive_form_run(form_run)

        self.assertEqual(outcome.state, VaSmartvaFormRun.ARCHIVE_STATE_FAILED)
        self.assertEqual(outcome.error_code, archive_svc.ERROR_VERIFY_MISMATCH)
        self.assertTrue(os.path.isdir(self._run_dir(rel_path)))

    def test_a_run_with_no_directory_is_absent_not_failed(self):
        form_run, _rel_path = self._make_form_run(with_files=False)

        outcome = archive_svc.archive_form_run(form_run)

        self.assertEqual(outcome.state, VaSmartvaFormRun.ARCHIVE_STATE_ABSENT)
        self.assertEqual(form_run.archive_state, VaSmartvaFormRun.ARCHIVE_STATE_ABSENT)
        self.assertIsNone(form_run.archive_error_code)

    # -- backlog -----------------------------------------------------------

    def test_backlog_dry_run_writes_nothing(self):
        form_run, rel_path = self._make_form_run()

        counts = archive_svc.archive_run_backlog(
            form_id=self.FORM_ID, dry_run=True, delete_local=True
        )

        self.assertEqual(counts["would_archive"], 1)
        self.assertEqual(counts["archived"], 0)
        self.assertEqual(self._keys(), set())
        self.assertTrue(os.path.isdir(self._run_dir(rel_path)))
        self.assertEqual(form_run.archive_state, VaSmartvaFormRun.ARCHIVE_STATE_LOCAL)

    def test_backlog_archives_keeps_local_by_default_and_is_resumable(self):
        form_run, rel_path = self._make_form_run()

        first = archive_svc.archive_run_backlog(form_id=self.FORM_ID)

        self.assertEqual(first["archived"], 1)
        self.assertEqual(first["deleted_local"], 0)
        self.assertTrue(os.path.isdir(self._run_dir(rel_path)))

        # A second sweep re-verifies the same run and still writes no new keys.
        keys = self._keys()
        second = archive_svc.archive_run_backlog(
            form_id=self.FORM_ID, delete_local=True
        )
        self.assertEqual(second["archived"], 1)
        self.assertEqual(second["deleted_local"], 1)
        self.assertEqual(self._keys(), keys)
        self.assertFalse(os.path.exists(self._run_dir(rel_path)))

        # Once the directory is gone the run is no longer a candidate.
        third = archive_svc.archive_run_backlog(form_id=self.FORM_ID)
        self.assertEqual(third["scanned"], 0)

    def test_backlog_limit_bounds_the_sweep(self):
        for _ in range(3):
            self._make_form_run()

        counts = archive_svc.archive_run_backlog(
            form_id=self.FORM_ID, limit=2, delete_local=True
        )

        self.assertEqual(counts["scanned"], 2)
        self.assertEqual(counts["archived"], 2)

    def test_backlog_retries_a_previously_failed_run(self):
        form_run, _rel_path = self._make_form_run()
        form_run.archive_state = VaSmartvaFormRun.ARCHIVE_STATE_FAILED
        form_run.archive_error_code = archive_svc.ERROR_UPLOAD_FAILED
        db.session.flush()

        counts = archive_svc.archive_run_backlog(
            form_id=self.FORM_ID, delete_local=True
        )

        self.assertEqual(counts["archived"], 1)
        self.assertEqual(form_run.archive_state, VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED)
        self.assertIsNone(form_run.archive_error_code)

    # -- overview ----------------------------------------------------------

    def test_overview_counts_states_and_the_last_failure_category(self):
        archived, _ = self._make_form_run()
        archive_svc.archive_form_run(archived)
        failed, _ = self._make_form_run()
        failed.archive_state = VaSmartvaFormRun.ARCHIVE_STATE_FAILED
        failed.archive_error_code = archive_svc.ERROR_VERIFY_MISMATCH
        db.session.flush()

        report = archive_svc.smartva_archive_overview(form_id=self.FORM_ID)

        self.assertEqual(report["store"], "s3")
        self.assertEqual(report["key_prefix"], "smartva_runs/")
        self.assertEqual(report["counts"][VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED], 1)
        self.assertEqual(report["counts"][VaSmartvaFormRun.ARCHIVE_STATE_FAILED], 1)
        self.assertEqual(
            report["last_failure"]["error_code"], archive_svc.ERROR_VERIFY_MISMATCH
        )
        # Only the failed run still has a directory on the VM.
        self.assertEqual(report["local_run_dirs"], 1)


class SmartvaArchiveCliTests(S3ArchiveBase):
    """``flask smartva archive-runs`` / ``archive-status`` over the service."""

    def _invoke(self, *args):
        return self.app.test_cli_runner().invoke(args=["smartva", *args])

    def test_archive_runs_dry_run_reports_without_writing(self):
        form_run, rel_path = self._make_form_run()

        result = self._invoke("archive-runs", "--form-id", self.FORM_ID, "--dry-run")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("would_archive=1", result.output)
        self.assertEqual(self._keys(), set())
        self.assertTrue(os.path.isdir(self._run_dir(rel_path)))

    def test_archive_runs_keeps_the_local_copy_without_delete_local(self):
        _form_run, rel_path = self._make_form_run()

        result = self._invoke("archive-runs", "--form-id", self.FORM_ID)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("archived=1", result.output)
        self.assertIn("deleted_local=0", result.output)
        self.assertTrue(os.path.isdir(self._run_dir(rel_path)))

    def test_archive_runs_with_delete_local_frees_the_disk(self):
        _form_run, rel_path = self._make_form_run()

        result = self._invoke(
            "archive-runs", "--form-id", self.FORM_ID, "--delete-local"
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("deleted_local=1", result.output)
        self.assertFalse(os.path.exists(self._run_dir(rel_path)))

    def test_archive_runs_exits_non_zero_on_a_failure(self):
        self._make_form_run()

        def explode(*args, **kwargs):
            raise store_mod.AttachmentStoreError("Attachment store write failed.")

        self._break_put_key(explode)

        result = self._invoke("archive-runs", "--form-id", self.FORM_ID)

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("failed=1", result.output)

    def test_archive_status_prints_the_counts(self):
        form_run, _rel_path = self._make_form_run()
        archive_svc.archive_form_run(form_run)

        result = self._invoke("archive-status", "--form-id", self.FORM_ID)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Attachment store: s3", result.output)
        self.assertIn("smartva_runs/", result.output)
        self.assertIn("archived=1", result.output)


class SmartvaArchiveLifecycleTests(S3ArchiveBase):
    """``_archive_completed_form_run`` is the seam the run lifecycle uses."""

    def test_lifecycle_hook_archives_a_completed_run(self):
        from app.services.smartva_service import _archive_completed_form_run

        form_run, rel_path = self._make_form_run()

        _archive_completed_form_run(form_run)

        self.assertEqual(form_run.archive_state, VaSmartvaFormRun.ARCHIVE_STATE_ARCHIVED)
        self.assertFalse(os.path.exists(self._run_dir(rel_path)))

    def test_lifecycle_hook_never_raises_and_keeps_the_directory(self):
        from app.services.smartva_service import _archive_completed_form_run

        form_run, rel_path = self._make_form_run()

        def explode(*args, **kwargs):
            raise RuntimeError("bucket on fire")

        self._break_put_key(explode)

        _archive_completed_form_run(form_run)

        refreshed = db.session.scalar(
            sa.select(VaSmartvaFormRun).where(
                VaSmartvaFormRun.form_run_id == form_run.form_run_id
            )
        )
        self.assertEqual(
            refreshed.archive_state, VaSmartvaFormRun.ARCHIVE_STATE_FAILED
        )
        self.assertTrue(os.path.isdir(self._run_dir(rel_path)))
