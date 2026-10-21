"""Blanking personal data in existing SmartVA run files (PII policy OD7).

The S3 half runs inside moto through the archive tests' base class; no test
reaches a real bucket. docs/kb/pii-slice-1a.md.
"""

import csv
import io
import os
from datetime import UTC, datetime, timedelta

import tests.services.test_smartva_run_archive as archive_tests
from app import db
from app.models import VaDbBackup
from app.services import smartva_run_archive_service as archive_svc
from app.services import smartva_run_scrub_service as scrub

SHA = "ab" * 32


def _record_backup(started_at=None):
    db.session.add(VaDbBackup(
        started_at=started_at or datetime.now(UTC), triggered_by="cli", status=VaDbBackup.STATUS_SUCCESS,
        store="local", object_key="db-backups/scrub.dump", sha256=SHA,
    ))
    db.session.flush()

INPUT = "sid,Id10017,Id10073,Id10019,ageInYears\nsid-1,Jane,234567890123,female,52\nsid-2,,,male,40\n"
RAW = "sid,gen_5_0,gen_6_7,gen_5_2\nsid-1,Jane,234567890123,2\n"
PREDICTIONS = "sid,national_id,name,surname,geography1,cause34,age\nsid-1,234567890123,Jane,Doe,Village,Stroke,52\n"
CSMF = "cause,name,CSMF\nStroke,Stroke,0.5\n"


def _rows(text):
    return list(csv.reader(io.StringIO(text)))


class LocalScrubTests(archive_tests.SmartvaArchiveBase):
    def _run(self):
        form_run, rel_path = self._make_form_run(with_files=False)
        run_dir = self._run_dir(rel_path)
        os.makedirs(os.path.join(run_dir, "smartva_output", "intermediate-files"), exist_ok=True)
        self._write(run_dir, "smartva_input.csv", INPUT.encode())
        self._write(run_dir, "smartva_output/intermediate-files/adult-raw-data.csv", RAW.encode())
        self._write(run_dir, "smartva_output/adult-predictions.csv", PREDICTIONS.encode())
        self._write(run_dir, "smartva_output/csmf.csv", CSMF.encode())
        return run_dir

    def _read(self, run_dir, relpath):
        with open(os.path.join(run_dir, relpath), newline="") as handle:
            return list(csv.reader(handle))

    def test_dry_run_counts_and_writes_nothing(self):
        run_dir = self._run()
        counts = scrub.scrub_local_runs(apply=False)
        self.assertEqual(counts["cells"]["smartva_input.csv"], 2)
        self.assertEqual(counts["cells"]["adult-raw-data.csv"], 2)
        self.assertEqual(counts["cells"]["adult-predictions.csv"], 4)
        self.assertEqual(counts["files_with_cells"]["csmf.csv"], 0)
        self.assertEqual(counts["errors"], 0)
        self.assertEqual(self._read(run_dir, "smartva_input.csv"), _rows(INPUT))

    def test_apply_blanks_only_the_personal_cells_and_is_idempotent(self):
        run_dir = self._run()
        before = self._read(run_dir, "smartva_input.csv")
        self.assertEqual(before[1][2], "234567890123")

        scrub.scrub_local_runs(apply=True)

        after = self._read(run_dir, "smartva_input.csv")
        self.assertEqual(after[0], before[0])
        self.assertEqual(after[1], ["sid-1", "", "", "female", "52"])
        self.assertEqual(self._read(run_dir, "smartva_output/intermediate-files/adult-raw-data.csv")[1],
                         ["sid-1", "", "", "2"])
        self.assertEqual(self._read(run_dir, "smartva_output/adult-predictions.csv")[1],
                         ["sid-1", "", "", "", "", "Stroke", "52"])
        # "name" in an aggregate file is a cause name, not a person's: kept.
        self.assertEqual(self._read(run_dir, "smartva_output/csmf.csv"), _rows(CSMF))
        again = scrub.scrub_local_runs(apply=True)
        self.assertEqual(sum(again["cells"].values()), 0)
        self.assertGreater(sum(again["files"].values()), 0)

    def test_a_symlink_out_of_the_runs_root_is_never_followed(self):
        run_dir = self._run()
        outside = os.path.join(self.runs_dir.name, "..", f"outside-{os.getpid()}.csv")
        with open(outside, "w") as handle:
            handle.write(INPUT)
        self.addCleanup(os.remove, outside)
        os.symlink(outside, os.path.join(run_dir, "link.csv"))

        scrub.scrub_local_runs(apply=True)

        with open(outside) as handle:
            self.assertEqual(handle.read(), INPUT)

    def test_cli_apply_refuses_without_a_backup_sha256(self):
        self._run()
        refused = self.app.test_cli_runner().invoke(args=["smartva", "scrub-runs", "--apply"])
        self.assertNotEqual(refused.exit_code, 0)
        self.assertIn("--confirm-backup", refused.output)

    def test_cli_apply_needs_a_recorded_recent_backup(self):
        run_dir = self._run()
        runner = self.app.test_cli_runner()
        unrecorded = runner.invoke(args=["smartva", "scrub-runs", "--apply", "--confirm-backup", "cd" * 32])
        self.assertNotEqual(unrecorded.exit_code, 0)
        self.assertIn("No successful backup", unrecorded.output)
        _record_backup(datetime.now(UTC) - timedelta(hours=48))
        old = runner.invoke(args=["smartva", "scrub-runs", "--apply", "--confirm-backup", SHA])
        self.assertNotEqual(old.exit_code, 0)
        self.assertIn("--allow-old-backup", old.output)
        self.assertEqual(self._read(run_dir, "smartva_input.csv"), _rows(INPUT))  # untouched so far

        applied = runner.invoke(args=["smartva", "scrub-runs", "--apply", "--confirm-backup", SHA,
                                      "--allow-old-backup"])

        self.assertEqual(applied.exit_code, 0, applied.output)
        self.assertEqual(self._read(run_dir, "smartva_input.csv")[1], ["sid-1", "", "", "female", "52"])

    def test_cli_dry_run_prints_counts_only(self):
        self._run()
        result = self.app.test_cli_runner().invoke(args=["smartva", "scrub-runs"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("dry-run local smartva_input.csv: files=1 files_with_cells=1 cells=2", result.output)
        self.assertNotIn("Jane", result.output)
        self.assertNotIn("234567890123", result.output)


class S3ScrubTests(archive_tests.S3ArchiveBase):
    KEY = "smartva_runs/P/F/run-1/smartva_input.csv"

    def _put(self, key, text):
        local = os.path.join(self.runs_dir.name, "upload.csv")
        with open(local, "w") as handle:
            handle.write(text)
        self.store.put_key(key, local, content_type="text/csv")
        os.remove(local)  # the runs root is scanned by the local-first check

    def _get(self, key):
        local = os.path.join(self.runs_dir.name, "download.csv")
        self.store.get_key(key, local)
        try:
            with open(local, newline="") as handle:
                return list(csv.reader(handle))
        finally:
            os.remove(local)  # the runs root is scanned by the local-first check

    def test_dry_run_counts_and_leaves_the_object(self):
        self._put(self.KEY, INPUT)
        counts = scrub.scrub_archived_runs(apply=False)
        self.assertFalse(counts["skipped_local_store"])
        self.assertEqual(counts["cells"]["smartva_input.csv"], 2)
        self.assertEqual(self._get(self.KEY), _rows(INPUT))

    def test_apply_rewrites_the_same_key_and_is_idempotent(self):
        self._put(self.KEY, INPUT)
        self.assertEqual(self._get(self.KEY)[1][2], "234567890123")

        counts = scrub.scrub_archived_runs(apply=True)

        self.assertEqual(counts["errors"], 0)
        self.assertEqual(self._get(self.KEY)[1], ["sid-1", "", "", "female", "52"])
        self.assertEqual(self._keys(), {self.KEY})
        again = scrub.scrub_archived_runs(apply=True)
        self.assertEqual(sum(again["cells"].values()), 0)

    def test_cli_s3_apply_needs_versioning_noted(self):
        self._put(self.KEY, INPUT)
        result = self.app.test_cli_runner().invoke(
            args=["smartva", "scrub-runs", "--s3", "--apply", "--confirm-backup", SHA]
        )
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("--versioning-noted", result.output)
        self.assertEqual(self._get(self.KEY), _rows(INPUT))


class S3ScrubOrderTests(archive_tests.S3ArchiveBase):
    """An S3 scrub must not be undone by the archive sweep re-uploading an
    unscrubbed local copy (sizes differ, so archive_form_run uploads it)."""

    def _archived_run(self):
        form_run, rel_path = self._make_form_run(with_files=False)
        run_dir = self._run_dir(rel_path)
        os.makedirs(run_dir, exist_ok=True)
        self._write(run_dir, "smartva_input.csv", INPUT.encode())
        form_run.disk_path = rel_path
        db.session.flush()
        archive_svc.archive_form_run(form_run, delete_local=False)
        key = next(k for k in self._keys() if k.endswith("smartva_input.csv"))
        return form_run, run_dir, key

    def _get(self, key):
        local = os.path.join(self.runs_dir.name, "download.csv")
        self.store.get_key(key, local)
        try:
            with open(local, newline="") as handle:
                return list(csv.reader(handle))
        finally:
            os.remove(local)  # the runs root is scanned by the local-first check

    def test_s3_apply_refuses_while_a_local_copy_is_unscrubbed(self):
        _form_run, _run_dir, key = self._archived_run()
        self.assertEqual(self._get(key)[1][2], "234567890123")  # archived unscrubbed

        with self.assertRaises(scrub.ScrubRefused):
            scrub.scrub_archived_runs(apply=True)

        self.assertEqual(self._get(key)[1][2], "234567890123")
        self.assertEqual(scrub.scrub_archived_runs(apply=False)["cells"]["smartva_input.csv"], 2)  # dry run allowed

    def test_local_then_s3_then_archive_keeps_the_object_scrubbed(self):
        form_run, run_dir, key = self._archived_run()

        scrub.scrub_local_runs(apply=True)
        counts = scrub.scrub_archived_runs(apply=True)
        self.assertEqual(counts["errors"], 0)
        archive_svc.archive_form_run(form_run, delete_local=False)

        self.assertEqual(self._get(key)[1], ["sid-1", "", "", "female", "52"])
        with open(os.path.join(run_dir, "smartva_input.csv"), newline="") as handle:
            self.assertEqual(list(csv.reader(handle))[1], ["sid-1", "", "", "female", "52"])
