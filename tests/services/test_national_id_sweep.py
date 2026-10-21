"""``flask pii sweep-national-id`` (PII slice 1a; docs/kb/pii-slice-1a.md)."""

from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models import VaDbBackup, VaForms, VaSubmissionPayloadVersion, VaSubmissions
from app.services import national_id_sweep_service as sweep
from app.services.submission_payload_version_service import (
    canonical_payload_fingerprint,
    ensure_active_payload_version,
)
from app.services.va_data_sync.va_data_sync_01_odkcentral import _upsert_form_submissions
from tests.base import BaseTestCase
from tests.services.test_national_id_sync_rerun import FULL_ID, REDUCED_ID, create_form

TABLE = "va_submission_payload_versions"
SHA = "ab" * 32


class NationalIdSweepTests(BaseTestCase):
    FORM_ID = "NIS01NS0101"
    PROJECT_ID = "NIS01"
    SITE_ID = "NS01"
    AT = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_form(cls.PROJECT_ID, cls.SITE_ID, cls.FORM_ID)

    def _record(self, instance_id):
        return {
            "KEY": instance_id, "sid": f"{instance_id}-{self.FORM_ID.lower()}", "form_def": self.FORM_ID,
            "SubmissionDate": self.AT.isoformat(), "updatedAt": self.AT.isoformat(),
            "SubmitterName": "Collector", "instanceName": instance_id, "unique_id": instance_id,
            "Id10013": "yes", "Id10019": "female", "finalAgeInYears": "52",
            "Id10073": FULL_ID, "Id10070": "234567890123", "Id10476": f"Card {FULL_ID}.",
        }

    def _legacy_version(self, instance_id):
        """A version stored before slice 1a: full national ID in payload_data."""
        record = self._record(instance_id)
        sub = VaSubmissions(
            va_sid=record["sid"], va_form_id=self.FORM_ID, va_submission_date=self.AT,
            va_odk_updatedat=self.AT.replace(tzinfo=None), va_data_collector="Collector",
            va_consent="yes", va_narration_language="English", va_deceased_age=52,
            va_deceased_gender="female", va_uniqueid_masked="masked",
            va_summary=[], va_catcount={}, va_category_list=[],
        )
        db.session.add(sub)
        db.session.flush()
        version = ensure_active_payload_version(sub, payload_data=record, created_by_role="vasystem")
        db.session.execute(
            sa.update(VaSubmissionPayloadVersion)
            .where(VaSubmissionPayloadVersion.payload_version_id == version.payload_version_id)
            .values(payload_data=record, payload_fingerprint="legacy")
        )
        db.session.commit()
        return version.payload_version_id, record

    def _stored(self, version_id):
        db.session.expire_all()
        return db.session.get(VaSubmissionPayloadVersion, version_id)

    def _backup(self):
        db.session.add(VaDbBackup(
            started_at=datetime.now(UTC), triggered_by="cli", status=VaDbBackup.STATUS_SUCCESS,
            store="local", object_key="db-backups/test.dump", sha256=SHA,
        ))
        db.session.flush()

    def test_dry_run_counts_by_field_and_writes_nothing(self):
        version_id, record = self._legacy_version("uuid:nis-dry")
        self.assertEqual(self._stored(version_id).payload_data["Id10073"], FULL_ID)

        report = sweep.sweep_national_ids(tables=(TABLE,))

        self.assertGreaterEqual(report["tables"][TABLE]["changed"], 1)
        self.assertEqual(report["tables"][TABLE]["written"], 0)
        self.assertGreaterEqual(report["redacted"][f"{TABLE}.payload_data.Id10073"], 1)
        self.assertGreaterEqual(report["redacted"][f"{TABLE}.payload_data.Id10476"], 1)
        self.assertGreaterEqual(report["flagged"][f"{TABLE}.payload_data.Id10070"], 1)
        self.assertNotIn(FULL_ID, repr(report))
        self.assertEqual(self._stored(version_id).payload_data, record)

    def test_apply_reduces_in_place_recomputes_the_fingerprint_and_reruns_as_a_no_op(self):
        version_id, record = self._legacy_version("uuid:nis-apply")

        report = sweep.sweep_national_ids(apply=True, tables=(TABLE,))

        self.assertGreaterEqual(report["tables"][TABLE]["written"], 1)
        stored = self._stored(version_id)
        self.assertEqual(stored.payload_data["Id10073"], REDUCED_ID)
        self.assertEqual(stored.payload_data["Id10476"], f"Card {REDUCED_ID}.")
        self.assertEqual(stored.payload_data["Id10070"], record["Id10070"])  # flagged, kept
        self.assertEqual(stored.payload_fingerprint, canonical_payload_fingerprint(stored.payload_data))
        again = sweep.sweep_national_ids(apply=True, tables=(TABLE,))
        self.assertEqual(again["tables"][TABLE]["changed"], 0)

    def test_after_apply_an_unchanged_odk_rerun_adds_no_version(self):
        version_id, record = self._legacy_version("uuid:nis-rerun")
        sweep.sweep_national_ids(apply=True, tables=(TABLE,))
        self.assertEqual(self._stored(version_id).payload_data["Id10073"], REDUCED_ID)

        _upsert_form_submissions(db.session.get(VaForms, self.FORM_ID), [record], set(), {}, enrich_payloads=False)
        db.session.flush()

        count = db.session.scalar(
            sa.select(sa.func.count()).select_from(VaSubmissionPayloadVersion)
            .where(VaSubmissionPayloadVersion.va_sid == record["sid"])
        )
        self.assertEqual(count, 1)

    def test_a_row_changed_since_it_was_read_is_skipped(self):
        version_id, record = self._legacy_version("uuid:nis-race")
        target = next(t for t in sweep.TARGETS if t.table == TABLE)
        changed = {**record, "Id10019": "male"}
        db.session.execute(
            sa.update(VaSubmissionPayloadVersion)
            .where(VaSubmissionPayloadVersion.payload_version_id == version_id)
            .values(payload_data=changed)
        )
        self.assertFalse(sweep._write_row(target, version_id, {"payload_data": (record, {"x": 1})}))
        self.assertEqual(self._stored(version_id).payload_data, changed)

    def test_every_table_dry_runs(self):
        report = sweep.sweep_national_ids()
        self.assertEqual(set(report["tables"]), set(sweep.TABLES))

    def test_backup_gate(self):
        with self.assertRaises(sweep.SweepRefused):
            sweep.confirm_db_backup(None)
        with self.assertRaises(sweep.SweepRefused):
            sweep.confirm_db_backup("cd" * 32)
        self._backup()
        self.assertEqual(sweep.confirm_db_backup(SHA.upper()).sha256, SHA)
        self.assertEqual(sweep.confirm_db_backup("db-backups/test.dump").sha256, SHA)

    def test_cli_apply_refuses_without_a_backup_and_dry_run_prints_counts(self):
        version_id, _ = self._legacy_version("uuid:nis-cli")
        runner = self.app.test_cli_runner()
        refused = runner.invoke(args=["pii", "sweep-national-id", "--apply", "--table", TABLE])
        self.assertNotEqual(refused.exit_code, 0)
        self.assertIn("--confirm-backup", refused.output)
        self.assertEqual(self._stored(version_id).payload_data["Id10073"], FULL_ID)

        dry = runner.invoke(args=["pii", "sweep-national-id", "--table", TABLE])
        self.assertEqual(dry.exit_code, 0, dry.output)
        self.assertIn(f"redact {TABLE}.payload_data.Id10073=", dry.output)
        self.assertNotIn("6789", dry.output)
