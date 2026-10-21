"""PII slice 1b part II-A: the write side and the backfill behind
``PAYLOAD_PII_SPLIT_ENABLED`` (docs/kb/pii-slice-1b.md).

The merge gates of docs/policy/pii-encryption-at-rest.md, "Fingerprint and
change detection": after ``flask pii split-payloads --apply`` and with the
flag on, a rerun of unchanged ODK data creates no version, no upstream-change
row and no release, and nothing a write stores holds a sealed value in
plaintext. Fixtures follow tests/services/test_national_id_sync_rerun.py.
"""

import contextlib
import logging
from datetime import UTC, datetime
from unittest import mock

import sqlalchemy as sa
from click.testing import CliRunner

from app import db
from app.commands.pii import pii_group, rewrap_pending
from app.models import (
    MapPayloadVersionPii,
    VaAllocation,
    VaAllocations,
    VaDbBackup,
    VaForms,
    VaInitialAssessments,
    VaStatuses,
    VaSubmissionPayloadVersion,
    VaSubmissions,
    VaSubmissionUpstreamChange,
)
from app.services import national_id_sweep_service as sweep
from app.services import payload_pii_accessor as accessor
from app.services import payload_pii_backfill_service as backfill
from app.services.data_management_service import _upstream_pii_changed, dm_upstream_change_details
from app.services.field_mapping_service import get_mapping_service
from app.services.payload_enrichment_backfill_service import _flush_single_update
from app.services.payload_pii_split import fingerprint_of, stored_fingerprint
from app.services.pii_field_registry import PII_FIELDS
from app.services.submission_payload_version_service import (
    PayloadSplitStateError,
    canonical_payload_fingerprint,
    create_or_update_pending_upstream_payload_version,
    ensure_active_payload_version,
    get_active_payload_version,
    opened_payload,
    payload_matches,
    sealed_ids_for_sid,
    stored_payload_fingerprint,
    write_payload_version,
)
from app.services.va_data_sync.va_data_sync_01_odkcentral import (
    _finalize_enriched_submissions_for_form,
    _upsert_form_submissions,
)
from app.services.workflow.definition import WORKFLOW_CODER_FINALIZED, WORKFLOW_CODING_IN_PROGRESS
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    set_submission_workflow_state,
)
from app.utils import pii_crypto
from tests.base import BaseTestCase
from tests.services.test_national_id_sync_rerun import FULL_ID, REDUCED_ID, create_form

SEALED = frozenset(PII_FIELDS)
SHA = "cd" * 32
# Plaintext sealed values of the fixture; none may appear in a stored copy.
PLAIN = ("Sunita", "Verma", "Ramesh Kumar", "Mohan Lal", "6789")


class PayloadSplitWriteTests(BaseTestCase):
    FORM_ID = "PSW01PW0101"
    PROJECT_ID = "PSW01"
    SITE_ID = "PW01"
    AT = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_form(cls.PROJECT_ID, cls.SITE_ID, cls.FORM_ID)

    def setUp(self):
        super().setUp()
        self._flag(False)

    # -- helpers -------------------------------------------------------------

    def _flag(self, on: bool):
        previous = self.app.config.get("PAYLOAD_PII_SPLIT_ENABLED", False)
        self.app.config["PAYLOAD_PII_SPLIT_ENABLED"] = on
        self.addCleanup(self.app.config.__setitem__, "PAYLOAD_PII_SPLIT_ENABLED", previous)

    def _record(self, instance_id: str, **over) -> dict:
        """The ODK record as Central sends it: names, informant, full national ID."""
        record = {
            "KEY": instance_id, "sid": f"{instance_id}-{self.FORM_ID.lower()}", "form_def": self.FORM_ID,
            "SubmissionDate": self.AT.isoformat(), "updatedAt": self.AT.isoformat(),
            "SubmitterName": "Collector", "ReviewState": None, "instanceName": instance_id,
            "unique_id": instance_id, "unique_id2": f"{instance_id}-masked",
            "Id10013": "yes", "language": "English", "finalAgeInYears": "52", "Id10019": "female",
            "Id10017": "Sunita", "Id10018": "Verma", "Id10007": "Ramesh Kumar", "Id10061": "Mohan Lal",
            "Id10073": FULL_ID, "Id10476": "Fever for a week.",
        }
        record.update(over)
        return record

    def _case(self, instance_id: str, *, state=None, stored_full=False) -> VaSubmissions:
        """A submission synced before the split (flag off: PII in payload_data)."""
        record = self._record(instance_id)
        sub = VaSubmissions(
            va_sid=record["sid"], va_form_id=self.FORM_ID, va_submission_date=self.AT,
            va_odk_updatedat=self.AT.replace(tzinfo=None), va_data_collector="Collector", va_odk_reviewstate=None,
            va_consent="yes", va_narration_language="English", va_deceased_age=52, va_deceased_gender="female",
            va_uniqueid_masked="masked", va_summary=[], va_catcount={}, va_category_list=[],
        )
        db.session.add(sub)
        db.session.flush()
        version = ensure_active_payload_version(
            sub, payload_data=record, source_updated_at=sub.va_odk_updatedat, created_by_role="vasystem",
        )
        if stored_full:
            version.payload_data = record  # written before slice 1a
        if state:
            set_submission_workflow_state(sub.va_sid, state, reason="test", by_role="test")
        db.session.flush()
        return sub

    def _backup(self):
        db.session.add(VaDbBackup(
            started_at=datetime.now(UTC), triggered_by="cli", status=VaDbBackup.STATUS_SUCCESS,
            store="local", object_key="db-backups/split.dump", sha256=SHA,
        ))
        db.session.flush()

    def _apply(self, **kwargs) -> dict:
        db.session.commit()
        return backfill.split_payloads(apply=True, **kwargs)

    def _rerun(self, record):
        amended: set = set()
        counts = _upsert_form_submissions(
            db.session.get(VaForms, self.FORM_ID), [record], amended, {}, enrich_payloads=False,
        )
        db.session.flush()
        return counts, amended

    def _count(self, model, va_sid):
        return db.session.scalar(sa.select(sa.func.count()).select_from(model).where(model.va_sid == va_sid))

    def _assert_split(self, version):
        """Side row present and holding the sealed answers; payload_data none."""
        row = accessor.get_side_row(version)
        self.assertIsNotNone(row)
        self.assertIn("Id10073", row.sealed)
        self.assertIn("Id10017", row.sealed)
        self.assertIn("Id10019", version.payload_data)  # subject present
        self.assertFalse(SEALED & set(version.payload_data))
        for plain in PLAIN:
            self.assertNotIn(plain, repr(version.payload_data))
            self.assertNotIn(plain, repr(row.sealed))
        self.assertEqual(version.payload_fingerprint, stored_fingerprint(version.payload_data, row, SEALED))
        return row

    # -- (a) the merge gate --------------------------------------------------

    def test_merge_gate_unchanged_rerun_after_apply_creates_nothing(self):
        finalised = self._case("uuid:psw-final", state=WORKFLOW_CODER_FINALIZED)
        full = self._case("uuid:psw-full", state=WORKFLOW_CODER_FINALIZED, stored_full=True)
        coding = self._case("uuid:psw-coding", state=WORKFLOW_CODING_IN_PROGRESS)
        allocation = VaAllocations(
            va_sid=coding.va_sid, va_allocated_to=self.base_coder_user.user_id,
            va_allocation_for=VaAllocation.coding, va_allocation_status=VaStatuses.active,
        )
        initial = VaInitialAssessments(
            va_sid=coding.va_sid, va_iniassess_by=self.base_coder_user.user_id,
            va_immediate_cod="R99", va_antecedent_cod="R99", va_iniassess_status=VaStatuses.active,
        )
        db.session.add_all([allocation, initial])
        self.assertEqual(get_active_payload_version(full.va_sid).payload_data["Id10073"], FULL_ID)

        report = self._apply()
        self.assertGreaterEqual(report["stripped"], 3)
        self._flag(True)

        for sub, instance in ((finalised, "uuid:psw-final"), (full, "uuid:psw-full"), (coding, "uuid:psw-coding")):
            with self.subTest(instance=instance):
                self._assert_split(get_active_payload_version(sub.va_sid))
                (added, updated, discarded, _), amended = self._rerun(self._record(instance))
                self.assertEqual((added, updated, discarded), (0, 0, 0))
                self.assertEqual(amended, set())
                self.assertEqual(self._count(VaSubmissionPayloadVersion, sub.va_sid), 1)
                self.assertEqual(self._count(VaSubmissionUpstreamChange, sub.va_sid), 0)
        self.assertEqual(get_submission_workflow_state(finalised.va_sid), WORKFLOW_CODER_FINALIZED)
        self.assertEqual(get_submission_workflow_state(coding.va_sid), WORKFLOW_CODING_IN_PROGRESS)
        self.assertEqual(allocation.va_allocation_status, VaStatuses.active)
        self.assertEqual(initial.va_iniassess_status, VaStatuses.active)

    def test_a_real_change_on_a_protected_case_makes_one_version_and_one_stripped_upstream_row(self):
        sub = self._case("uuid:psw-change", state=WORKFLOW_CODER_FINALIZED)
        self._apply()
        self._flag(True)

        self._rerun(self._record("uuid:psw-change", Id10019="male"))

        self.assertEqual(self._count(VaSubmissionPayloadVersion, sub.va_sid), 2)
        self.assertEqual(self._count(VaSubmissionUpstreamChange, sub.va_sid), 1)
        change = db.session.scalar(sa.select(VaSubmissionUpstreamChange).where(VaSubmissionUpstreamChange.va_sid == sub.va_sid))
        for copy in (change.previous_va_data, change.incoming_va_data):
            self.assertIn("Id10019", copy)
            self.assertFalse(SEALED & set(copy))
            for plain in PLAIN:
                self.assertNotIn(plain, repr(copy))
        pending = db.session.get(VaSubmissionPayloadVersion, change.incoming_payload_version_id)
        self.assertEqual(pending.version_status, "pending_upstream")
        self._assert_split(pending)
        self.assertFalse(_upstream_pii_changed(change))  # only a non-sealed field moved

        # The same change again: still one upstream row, one pending version.
        self._rerun(self._record("uuid:psw-change", Id10019="male"))
        self.assertEqual(self._count(VaSubmissionPayloadVersion, sub.va_sid), 2)
        self.assertEqual(self._count(VaSubmissionUpstreamChange, sub.va_sid), 1)

    def test_a_sealed_only_change_is_detected_and_reported_by_digest(self):
        sub = self._case("uuid:psw-name", state=WORKFLOW_CODER_FINALIZED)
        self._apply()
        self._flag(True)

        self._rerun(self._record("uuid:psw-name", Id10017="Sunaina"))

        change = db.session.scalar(sa.select(VaSubmissionUpstreamChange).where(VaSubmissionUpstreamChange.va_sid == sub.va_sid))
        self.assertIsNotNone(change)
        self.assertTrue(_upstream_pii_changed(change))
        self.assertNotIn("Sunaina", repr(change.incoming_va_data))
        pending = db.session.get(VaSubmissionPayloadVersion, change.incoming_payload_version_id)
        self.assertEqual(accessor.get_pii(pending)["Id10017"], "Sunaina")

    def test_same_last_three_national_id_digits_are_not_a_change_a_different_one_is(self):
        sub = self._case("uuid:psw-nid", state=WORKFLOW_CODER_FINALIZED)
        self._apply()
        self._flag(True)
        self._rerun(self._record("uuid:psw-nid", Id10073="9999 9999 9123"))  # OD1, accepted
        self.assertEqual(self._count(VaSubmissionUpstreamChange, sub.va_sid), 0)
        self._rerun(self._record("uuid:psw-nid", Id10073="2345 6789 0999"))
        self.assertEqual(self._count(VaSubmissionUpstreamChange, sub.va_sid), 1)

    def test_a_non_protected_change_releases_and_writes_one_split_version(self):
        sub = self._case("uuid:psw-open")
        self._apply()
        self._flag(True)
        (_, updated, _, _), _ = self._rerun(self._record("uuid:psw-open", Id10476="Cough."))
        self.assertEqual(updated, 1)
        self.assertEqual(self._count(VaSubmissionPayloadVersion, sub.va_sid), 2)
        self._assert_split(get_active_payload_version(sub.va_sid))

    # -- (b) the "unchanged" branches never write plaintext back --------------

    def test_unchanged_branches_store_the_stripped_payload(self):
        sub = self._case("uuid:psw-noop", state=WORKFLOW_CODER_FINALIZED)
        self._apply()
        self._flag(True)
        record = self._record("uuid:psw-noop")

        # The enrichment pass: ensure_active_payload_version's unchanged branch.
        finalized = _finalize_enriched_submissions_for_form(
            db.session.get(VaForms, self.FORM_ID), [record], {sub.va_sid: record["KEY"]}, set(), client=None,
        )
        db.session.flush()
        self.assertEqual(finalized, 1)
        version = get_active_payload_version(sub.va_sid)
        self.assertEqual(self._count(VaSubmissionPayloadVersion, sub.va_sid), 1)
        self._assert_split(version)
        self.assertEqual(accessor.get_pii(version)["Id10073"], REDUCED_ID)

        # The pending-upstream unchanged branch, called twice with one record.
        first = create_or_update_pending_upstream_payload_version(sub, payload_data=self._record("uuid:psw-noop", Id10019="male"))
        again = create_or_update_pending_upstream_payload_version(sub, payload_data=self._record("uuid:psw-noop", Id10019="male"))
        self.assertIs(first, again)
        self._assert_split(again)

    def test_a_new_submission_with_the_flag_on_is_split_and_logs_no_value(self):
        self._flag(True)
        record = self._record("uuid:psw-new")
        with self.assertLogs(level=logging.DEBUG) as logs:
            logging.getLogger(__name__).debug("probe")
            self._rerun(record)
        version = get_active_payload_version(record["sid"])
        self.assertIsNotNone(version)
        self._assert_split(version)
        self.assertEqual(accessor.get_full_payload(version)["Id10007"], "Ramesh Kumar")
        joined = "\n".join(logs.output)
        for plain in PLAIN:
            self.assertNotIn(plain, joined)

    def test_flag_off_writes_stay_as_before(self):
        sub = self._case("uuid:psw-off")
        version = get_active_payload_version(sub.va_sid)
        self.assertEqual(version.payload_data["Id10017"], "Sunita")
        self.assertIsNone(accessor.get_side_row(version))
        self.assertEqual(version.payload_fingerprint, canonical_payload_fingerprint(version.payload_data))

    # -- other writers ---------------------------------------------------------

    def test_enrichment_flush_keeps_the_sealed_fields(self):
        sub = self._case("uuid:psw-enrich")
        self._apply()
        self._flag(True)
        version = get_active_payload_version(sub.va_sid)
        enriched = {**version.payload_data, "FormVersion": "2", "DeviceID": "d", "SubmitterID": "1",
                    "instanceID": "uuid:psw-enrich", "AttachmentsExpected": "0", "AttachmentsPresent": "0"}
        _flush_single_update(pv_id=version.payload_version_id, payload_data=enriched,
                             has_required_metadata=True, attachments_expected=0)
        db.session.expire_all()
        version = get_active_payload_version(sub.va_sid)
        self.assertEqual(version.payload_data["FormVersion"], "2")
        self._assert_split(version)
        self.assertEqual(accessor.get_pii(version)["Id10017"], "Sunita")

    def test_national_id_sweep_writes_the_new_rule_fingerprint(self):
        sub = self._case("uuid:psw-sweep")
        self._apply()
        self._flag(True)
        version = get_active_payload_version(sub.va_sid)
        db.session.execute(
            sa.update(VaSubmissionPayloadVersion)
            .where(VaSubmissionPayloadVersion.payload_version_id == version.payload_version_id)
            .values(payload_data={**version.payload_data, "Id10476": f"Card {FULL_ID}."})
        )
        db.session.commit()
        self._backup()
        sweep.sweep_national_ids(apply=True, tables=("va_submission_payload_versions",))
        db.session.expire_all()
        version = get_active_payload_version(sub.va_sid)
        self.assertNotIn("6789", version.payload_data["Id10476"])
        self._assert_split(version)

    # -- (e, f) the backfill -------------------------------------------------

    def _every_status(self):
        """One submission with an active, a superseded, a rejected and a
        pending_upstream version, all written before the split."""
        sub = self._case("uuid:psw-all")
        ensure_active_payload_version(sub, payload_data=self._record("uuid:psw-all", Id10476="Second."))
        create_or_update_pending_upstream_payload_version(sub, payload_data=self._record("uuid:psw-all", Id10476="Third."))
        create_or_update_pending_upstream_payload_version(sub, payload_data=self._record("uuid:psw-all", Id10476="Fourth."))
        db.session.flush()
        return sub

    def _versions(self, va_sid):
        db.session.expire_all()
        return db.session.scalars(
            sa.select(VaSubmissionPayloadVersion).where(VaSubmissionPayloadVersion.va_sid == va_sid)
        ).all()

    def test_dry_run_counts_by_status_and_writes_nothing(self):
        sub = self._every_status()
        statuses = {v.version_status for v in self._versions(sub.va_sid)}
        self.assertEqual(statuses, {"active", "superseded", "rejected", "pending_upstream"})
        db.session.commit()

        report = backfill.split_payloads()

        for status in statuses:
            counts = report["by_status"][status]
            self.assertGreaterEqual(counts["with_sealed_fields"], 1)
            self.assertGreaterEqual(counts["to_strip"], 1)
        self.assertEqual(report["written"], 0)
        for version in self._versions(sub.va_sid):
            self.assertEqual(version.payload_data["Id10017"], "Sunita")
            self.assertIsNone(accessor.get_side_row(version))

    def test_apply_covers_every_status_is_idempotent_and_verifies(self):
        sub = self._every_status()
        no_pii = self._case("uuid:psw-nopii")
        db.session.execute(
            sa.update(VaSubmissionPayloadVersion)
            .where(VaSubmissionPayloadVersion.va_sid == no_pii.va_sid)
            .values(payload_data={"KEY": "uuid:psw-nopii", "Id10019": "male"}, payload_fingerprint="old")
        )
        before = {v.payload_version_id: accessor.get_full_payload(v) for v in self._versions(sub.va_sid)}

        report = self._apply(batch_size=2)

        self.assertEqual(report["verified"], report["written"])
        self.assertGreaterEqual(report["recomputed_only"], 1)
        for version in self._versions(sub.va_sid):
            with self.subTest(status=version.version_status):
                row = self._assert_split(version)
                self.assertEqual(
                    accessor.get_full_payload(version),
                    {**before[version.payload_version_id], "Id10073": REDUCED_ID},
                )
                self.assertEqual(version.payload_fingerprint, fingerprint_of(accessor.get_full_payload(version), SEALED))
                self.assertIsNotNone(row)
        plain = self._versions(no_pii.va_sid)[0]
        self.assertEqual(accessor.get_side_row(plain).sealed, {})
        self.assertNotEqual(plain.payload_fingerprint, "old")

        wrapped = {r.payload_version_id: (r.dek_wrapped, dict(r.sealed))
                   for r in db.session.scalars(sa.select(MapPayloadVersionPii))}
        rerun = backfill.split_payloads(apply=True)
        self.assertEqual(rerun["written"], 0)
        db.session.expire_all()
        self.assertEqual(
            {r.payload_version_id: (r.dek_wrapped, dict(r.sealed)) for r in db.session.scalars(sa.select(MapPayloadVersionPii))},
            wrapped,
        )
        verified = backfill.verify_split(sample=50)
        self.assertTrue(verified["ok"], verified)
        self.assertGreaterEqual(verified["sampled"], 5)

    def test_an_interrupted_apply_resumes(self):
        sub = self._every_status()
        real = accessor.strip_version
        calls = {"n": 0}

        def failing(version, sealed, **kwargs):
            calls["n"] += 1
            if calls["n"] == 3:
                raise RuntimeError("interrupted")
            return real(version, sealed, **kwargs)

        db.session.commit()
        with mock.patch.object(accessor, "strip_version", failing), self.assertRaises(RuntimeError):
            backfill.split_payloads(apply=True, batch_size=2)
        db.session.rollback()
        done = [v for v in self._versions(sub.va_sid) if accessor.get_side_row(v) is not None]
        self.assertTrue(done)  # the first batch committed
        backfill.split_payloads(apply=True, batch_size=2)
        for version in self._versions(sub.va_sid):
            self._assert_split(version)

    def test_verify_fails_on_a_tampered_or_unsplit_row(self):
        sub = self._case("uuid:psw-tamper")
        self.assertFalse(backfill.verify_split()["ok"])  # not split yet
        self._apply()
        self.assertTrue(backfill.verify_split()["ok"])
        row = accessor.get_side_row(get_active_payload_version(sub.va_sid))
        row.pii_digest = "0" * 64
        db.session.commit()
        report = backfill.verify_split()
        self.assertFalse(report["ok"])
        self.assertGreaterEqual(report["fingerprint_mismatch"] + report["sample_failed"], 1)

    def test_restore_joins_back_and_is_refused_with_the_flag_on(self):
        sub = self._every_status()
        self._apply()
        self._flag(True)
        with self.assertRaises(backfill.BackfillRefused):
            backfill.restore_split()
        self._flag(False)

        counts = backfill.restore_split()

        self.assertGreaterEqual(counts["restored"], 4)
        self.assertEqual(counts["failed"], 0)
        for version in self._versions(sub.va_sid):
            self.assertEqual(version.payload_data["Id10017"], "Sunita")
            self.assertEqual(version.payload_data["Id10073"], REDUCED_ID)
            self.assertIsNone(accessor.get_side_row(version))
            self.assertEqual(version.payload_fingerprint, canonical_payload_fingerprint(version.payload_data))

    def test_cli_refuses_apply_and_restore_without_a_verified_backup(self):
        self._case("uuid:psw-cli")
        db.session.commit()
        runner = CliRunner()
        for args in (["--apply"], ["--apply", "--confirm-backup", "ee" * 32], ["--restore"]):
            with self.subTest(args=args):
                result = runner.invoke(pii_group, ["split-payloads", *args])
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("backup", result.output)
        self.assertFalse(db.session.scalar(sa.select(sa.func.count()).select_from(MapPayloadVersionPii)))
        dry = runner.invoke(pii_group, ["split-payloads"])
        self.assertEqual(dry.exit_code, 0, dry.output)
        self.assertIn("dry-run active:", dry.output)
        for plain in PLAIN:
            self.assertNotIn(plain, dry.output)

        self._backup()
        db.session.commit()
        applied = runner.invoke(pii_group, ["split-payloads", "--apply", "--confirm-backup", SHA])
        self.assertEqual(applied.exit_code, 0, applied.output)
        verified = runner.invoke(pii_group, ["split-payloads", "--verify"])
        self.assertEqual(verified.exit_code, 0, verified.output)

    # -- (g) rewrap of the side table -----------------------------------------

    def test_rewrap_moves_side_rows_and_leaves_ciphertext_byte_identical(self):
        sub = self._every_status()
        self._apply()
        rows = db.session.scalars(sa.select(MapPayloadVersionPii)).all()
        self.assertTrue(rows)
        before = {r.payload_version_id: (dict(r.sealed), r.dek_wrapped) for r in rows}

        old = self.app.extensions["pii_keyring"]
        new_public, new_private = pii_crypto.generate_keyset("rotsp")
        rotated = pii_crypto.Keyring(new_public, {**old.private, "rotsp": new_private}, old.blind_key)
        with mock.patch.dict(self.app.extensions, {"pii_keyring": rotated}):
            counts = rewrap_pending(batch_size=2)
            self.assertEqual(counts["rewrapped"], len(rows))
            self.assertEqual(rewrap_pending()["rewrapped"], 0)  # idempotent
        db.session.expire_all()
        new_only = pii_crypto.Keyring(new_public, {"rotsp": new_private}, old.blind_key)
        with mock.patch.dict(self.app.extensions, {"pii_keyring": new_only}):
            pii_crypto.clear_dek_cache()
            for row in db.session.scalars(sa.select(MapPayloadVersionPii)):
                self.assertEqual(row.key_id, "rotsp")
                self.assertEqual(dict(row.sealed), before[row.payload_version_id][0])
                self.assertNotEqual(row.dek_wrapped, before[row.payload_version_id][1])
            for version in self._versions(sub.va_sid):
                self.assertEqual(accessor.get_pii(version)["Id10017"], "Sunita")


class PayloadSplitFixBatchTests(PayloadSplitWriteTests):
    """The review fix batch (2026-10-21): flag-off guard, sealed-set drift,
    unchanged passes that keep the side row, the per-context sealed-set
    cache, blind-key rotation, upstream-change copies. Inherits the fixtures
    only; the parent's tests are disabled below, not rerun."""

    FORM_ID = "PSF01PF0101"
    PROJECT_ID = "PSF01"
    SITE_ID = "PF01"

    @contextlib.contextmanager
    def _sealed_as(self, sealed: frozenset[str]):
        """The registry answers *sealed* (an admin is_pii toggle), for the
        version service and the backfill; cached sets are dropped the way the
        admin route does (``clear_cache``), on entry and on exit."""
        get_mapping_service().clear_cache()
        with mock.patch("app.services.pii_field_registry.sealed_field_ids", return_value=sealed), \
                mock.patch("app.services.payload_pii_backfill_service.sealed_field_ids", return_value=sealed):
            yield
        get_mapping_service().clear_cache()

    def _rows_by_id(self):
        db.session.expire_all()
        return {r.payload_version_id: (r.dek_wrapped, dict(r.sealed), r.updated_at)
                for r in db.session.scalars(sa.select(MapPayloadVersionPii))}

    # -- item 2: flag off over split rows -----------------------------------

    def test_flag_off_refuses_a_version_that_has_a_side_row(self):
        sub = self._case("uuid:fix-off", state=WORKFLOW_CODER_FINALIZED)
        self._apply()  # the flag stays off: a mis-set process after the split
        version = get_active_payload_version(sub.va_sid)
        self.assertIsNotNone(accessor.get_side_row(version))
        record = self._record("uuid:fix-off")

        for call in (lambda: payload_matches(version, record), lambda: write_payload_version(version, record),
                     lambda: opened_payload(version), lambda: stored_payload_fingerprint(version, record),
                     lambda: ensure_active_payload_version(sub, payload_data=record)):
            with self.subTest(call=call), self.assertRaises(PayloadSplitStateError):
                call()
        db.session.expire_all()
        self.assertNotIn("Id10017", get_active_payload_version(sub.va_sid).payload_data)  # nothing rewritten
        self.assertEqual(self._count(VaSubmissionPayloadVersion, sub.va_sid), 1)

    def test_flag_off_without_side_rows_is_unchanged(self):
        sub = self._case("uuid:fix-off-plain")
        version = get_active_payload_version(sub.va_sid)
        self.assertTrue(payload_matches(version, self._record("uuid:fix-off-plain")))
        self.assertEqual(opened_payload(version)["Id10017"], "Sunita")
        self.assertEqual(stored_payload_fingerprint(version, version.payload_data),
                         canonical_payload_fingerprint(version.payload_data))

    def test_an_admin_flagged_date_of_death_stays_in_payload_data(self):
        """Owner decision A: Id10023 is never sealed, even when the form
        type flags it is_pii."""
        from app.services.submission_payload_version_service import clear_payload_pii_request_cache

        sub = self._case("uuid:fix-dod")
        self._flag(True)
        clear_payload_pii_request_cache()
        self.addCleanup(clear_payload_pii_request_cache)
        with mock.patch("app.utils.va_form.va_form_02_formtyperesolution.va_get_form_type_code_for_form",
                        return_value="WHO_2022_VA"), \
                mock.patch("app.services.field_mapping_service.FieldMappingService.get_pii_field_ids",
                           return_value={"Id10023"}) as flagged:
            version = get_active_payload_version(sub.va_sid)
            write_payload_version(version, self._record("uuid:fix-dod", Id10023="2024-01-05"))
            db.session.flush()
        flagged.assert_called()
        self.assertEqual(version.payload_data["Id10023"], "2024-01-05")
        row = accessor.get_side_row(version)
        self.assertIn("Id10073", row.sealed)
        self.assertNotIn("Id10023", row.sealed)
        self.assertNotIn("Id10023", row.sealed_ids)

    # -- item 3: sealed-set drift -------------------------------------------

    def test_an_is_pii_toggle_after_the_split_is_not_a_change_until_rerun(self):
        sub = self._case("uuid:fix-drift", state=WORKFLOW_CODER_FINALIZED)
        self._apply()
        self._flag(True)
        row = accessor.get_side_row(get_active_payload_version(sub.va_sid))
        # Today's set: PII_FIELDS plus whatever another test file left flagged.
        base = frozenset(row.sealed_ids)
        self.assertEqual(base, sealed_ids_for_sid(sub.va_sid))
        self.assertTrue(SEALED <= base)

        toggles = {
            "flag a present field": base | {"Id10476"},
            "unflag a sealed field": base - {"Id10061"},
        }
        for label, sealed in toggles.items():
            with self.subTest(toggle=label), self._sealed_as(sealed):
                # A sealed field absent at the split now arrives empty: the
                # row's own set digests absent and "" alike.
                record = self._record("uuid:fix-drift", Id10010c="")
                (added, updated, discarded, _), amended = self._rerun(record)
                self.assertEqual((added, updated, discarded), (0, 0, 0))
                self.assertEqual(amended, set())
                self.assertEqual(self._count(VaSubmissionPayloadVersion, sub.va_sid), 1)
                self.assertEqual(self._count(VaSubmissionUpstreamChange, sub.va_sid), 0)
        with self._sealed_as(base | {"Id10476"}):
            db.session.commit()
            self.assertGreaterEqual(backfill.verify_split()["sealed_set_changed"], 1)
            self.assertGreaterEqual(backfill.split_payloads(apply=True)["written"], 1)  # the rerun the admin is told to do
            version = get_active_payload_version(sub.va_sid)
            self.assertNotIn("Id10476", version.payload_data)
            self.assertEqual(accessor.get_pii(version)["Id10476"], "Fever for a week.")
            self.assertEqual(backfill.verify_split()["sealed_set_changed"], 0)
            (added, updated, _, _), _ = self._rerun(self._record("uuid:fix-drift"))
            self.assertEqual((added, updated), (0, 0))
            self.assertEqual(self._count(VaSubmissionUpstreamChange, sub.va_sid), 0)

    # -- item 7: an unchanged pass keeps the side row -------------------------

    def test_unchanged_passes_leave_the_side_row_byte_identical(self):
        sub = self._case("uuid:fix-same", state=WORKFLOW_CODER_FINALIZED)
        self._apply()
        self._flag(True)
        before = self._rows_by_id()
        record = self._record("uuid:fix-same")

        with mock.patch.object(pii_crypto, "seal_record", wraps=pii_crypto.seal_record) as seal:
            self._rerun(record)
            _finalize_enriched_submissions_for_form(
                db.session.get(VaForms, self.FORM_ID), [record], {sub.va_sid: record["KEY"]}, set(), client=None,
            )
            ensure_active_payload_version(sub, payload_data=record)
            db.session.flush()
        self.assertEqual(seal.call_count, 0)  # no fresh DEK, no KEM wrap
        db.session.commit()
        self.assertEqual(self._rows_by_id(), before)
        self._assert_split(get_active_payload_version(sub.va_sid))

        # A changed sealed value still rewrites the row.
        ensure_active_payload_version(sub, payload_data=self._record("uuid:fix-same", Id10017="Sunaina"))
        db.session.flush()
        self.assertEqual(accessor.get_pii(get_active_payload_version(sub.va_sid))["Id10017"], "Sunaina")

    # -- item 8: the sealed set is resolved once per form, not per submission --

    def test_sync_statements_are_constant_per_submission_with_one_pii_set_lookup(self):
        self._flag(True)
        from app.services import pii_field_registry
        from app.services.submission_payload_version_service import clear_payload_pii_request_cache

        def run(n: int, tag: str):
            clear_payload_pii_request_cache()  # a fresh request or task
            statements = []

            def record(_conn, _cursor, statement, *_args):
                statements.append(statement)

            sa.event.listen(db.engine, "before_cursor_execute", record)
            try:
                with mock.patch.object(pii_field_registry, "sealed_field_ids",
                                       wraps=pii_field_registry.sealed_field_ids) as lookup:
                    self._rerun_many([self._record(f"uuid:fix-cnt-{tag}-{i}") for i in range(n)])
            finally:
                sa.event.remove(db.engine, "before_cursor_execute", record)
            return len(statements), lookup.call_count

        # The first run warms the identity map (the form row), so the
        # per-submission step is measured from the second run on.
        counts = [run(n, tag) for n, tag in ((1, "a"), (2, "b"), (3, "c"), (4, "d"))]
        steps = {counts[i + 1][0] - counts[i][0] for i in range(1, len(counts) - 1)}
        self.assertEqual(len(steps), 1, counts)
        # The sealed set (form type, mapping version check) is resolved once
        # per request or task, whatever the number of submissions.
        self.assertEqual([lookups for _, lookups in counts], [1, 1, 1, 1], counts)

    def _rerun_many(self, records):
        _upsert_form_submissions(db.session.get(VaForms, self.FORM_ID), records, set(), {}, enrich_payloads=False)
        db.session.flush()

    # -- item 9: blind-key rotation ------------------------------------------

    def test_blind_key_rotation_then_recompute_keeps_an_unchanged_sync_quiet(self):
        sub = self._case("uuid:fix-rot", state=WORKFLOW_CODER_FINALIZED)
        version = get_active_payload_version(sub.va_sid)
        version.payload_data = {**version.payload_data, "abha_number": "12-3456-7890-1234"}
        db.session.flush()
        self._apply()
        self._flag(True)
        old = self.app.extensions["pii_keyring"]
        old_row = accessor.get_side_row(get_active_payload_version(sub.va_sid))
        old_bidx, old_dek = old_row.abha_number_bidx, old_row.dek_wrapped
        self.assertIsNotNone(old_bidx)
        record = self._record("uuid:fix-rot", abha_number="12-3456-7890-1234")

        rotated = pii_crypto.Keyring(old.public, old.private, b"\x07" * 32)
        with mock.patch.dict(self.app.extensions, {"pii_keyring": rotated}):
            self.assertFalse(payload_matches(get_active_payload_version(sub.va_sid), record))  # would change
            db.session.commit()
            self.assertGreaterEqual(backfill.verify_split()["blind_key_stale"], 1)
            self.assertGreaterEqual(backfill.split_payloads()["by_status"]["active"].get("already_split", 0), 0)
            self.assertGreaterEqual(backfill.recompute_digests()["to_recompute"], 1)  # dry run
            counts = backfill.recompute_digests(apply=True, batch_size=1)
            self.assertGreaterEqual(counts["recomputed"], 1)
            self.assertEqual(counts["failed"], 0)
            self.assertEqual(backfill.recompute_digests(apply=True)["to_recompute"], 0)  # idempotent
            db.session.expire_all()
            row = accessor.get_side_row(get_active_payload_version(sub.va_sid))
            self.assertEqual(row.dek_wrapped, old_dek)  # never re-sealed
            self.assertEqual(row.blind_key_id, pii_crypto.blind_key_id())
            self.assertEqual(row.abha_number_bidx, pii_crypto.class_index("abha_number", "12345678901234"))
            self.assertNotEqual(row.abha_number_bidx, old_bidx)
            self.assertTrue(backfill.verify_split()["ok"])

            (added, updated, discarded, _), amended = self._rerun(record)

            self.assertEqual((added, updated, discarded), (0, 0, 0))
            self.assertEqual(amended, set())
            self.assertEqual(self._count(VaSubmissionPayloadVersion, sub.va_sid), 1)
            self.assertEqual(self._count(VaSubmissionUpstreamChange, sub.va_sid), 0)

    def test_apply_does_not_treat_a_rotated_row_as_split(self):
        self._case("uuid:fix-rot-apply")
        self._apply()
        old = self.app.extensions["pii_keyring"]
        with mock.patch.dict(self.app.extensions, {"pii_keyring": pii_crypto.Keyring(old.public, old.private, b"\x09" * 32)}):
            db.session.commit()
            self.assertGreaterEqual(backfill.split_payloads()["by_status"]["active"]["to_recompute"], 1)

    # -- item 10: a tampered digest fails the open ----------------------------

    def test_open_fails_when_the_digest_does_not_match_the_blob(self):
        sub = self._case("uuid:fix-tamper")
        self._apply()
        version = get_active_payload_version(sub.va_sid)
        self.assertEqual(accessor.get_pii(version)["Id10017"], "Sunita")
        accessor.get_side_row(version).pii_digest = "0" * 64
        with self.assertRaises(pii_crypto.PiiCryptoError):
            accessor.get_pii(version)

    # -- item 5: upstream-change copies ---------------------------------------

    def _plaintext_change(self, instance):
        """A protected change recorded before the split: plaintext copies."""
        sub = self._case(instance, state=WORKFLOW_CODER_FINALIZED)
        self._rerun(self._record(instance, Id10019="male"))
        change = db.session.scalar(sa.select(VaSubmissionUpstreamChange).where(VaSubmissionUpstreamChange.va_sid == sub.va_sid))
        self.assertEqual(change.previous_va_data["Id10017"], "Sunita")
        self.assertEqual(change.incoming_va_data["Id10017"], "Sunita")
        return sub, change

    def test_strip_upstream_copies_is_lossless_idempotent_and_counts_only(self):
        sub, change = self._plaintext_change("uuid:fix-copies")
        db.session.commit()
        dry = backfill.strip_upstream_copies()
        self.assertGreaterEqual(dry["changed"], 1)
        self.assertEqual(dry["written"], 0)

        applied = backfill.strip_upstream_copies(apply=True, batch_size=1)

        self.assertGreaterEqual(applied["written"], 1)
        db.session.expire_all()
        change = db.session.get(VaSubmissionUpstreamChange, change.upstream_change_id)
        for copy in (change.previous_va_data, change.incoming_va_data):
            self.assertEqual(copy["Id10019"] in ("female", "male"), True)
            self.assertFalse(SEALED & set(copy))
        self.assertEqual(backfill.strip_upstream_copies(apply=True)["changed"], 0)
        # Lossless: the referenced versions still hold the sealed fields.
        previous = db.session.get(VaSubmissionPayloadVersion, change.previous_payload_version_id)
        self.assertEqual(opened_payload(previous)["Id10017"], "Sunita")

    def test_strip_upstream_copies_cli_needs_a_backup(self):
        self._plaintext_change("uuid:fix-copies-cli")
        db.session.commit()
        runner = CliRunner()
        refused = runner.invoke(pii_group, ["strip-upstream-copies", "--apply"])
        self.assertNotEqual(refused.exit_code, 0)
        self.assertIn("backup", refused.output)
        self._backup()
        db.session.commit()
        applied = runner.invoke(pii_group, ["strip-upstream-copies", "--apply", "--confirm-backup", SHA])
        self.assertEqual(applied.exit_code, 0, applied.output)
        for plain in PLAIN:
            self.assertNotIn(plain, applied.output)

    def test_a_later_sync_strips_the_old_previous_copy_and_the_review_shows_no_plaintext(self):
        sub, change = self._plaintext_change("uuid:fix-mixed")
        self._apply()
        self._flag(True)
        # The mixed row of a pending change opened before the flip.
        change.incoming_va_data = {k: v for k, v in change.incoming_va_data.items() if k not in SEALED}
        db.session.flush()

        details = dm_upstream_change_details(self.base_admin_user, sub.va_sid)

        self.assertIn("changed_fields", details)
        for plain in PLAIN:
            self.assertNotIn(plain, repr(details))
        self.assertNotIn("Id10017", [row["field_id"] for row in details["changed_fields"]])

        self._rerun(self._record("uuid:fix-mixed", Id10019="male", Id10476="Cough."))
        db.session.refresh(change)
        self.assertFalse(SEALED & set(change.previous_va_data))
        self.assertIn("Id10019", change.previous_va_data)

    # -- item 10: the backup gate's age bound ---------------------------------

    def test_backup_gate_refuses_an_old_dump_unless_allowed(self):
        from datetime import timedelta

        db.session.add(VaDbBackup(
            started_at=datetime.now(UTC) - timedelta(hours=30), triggered_by="cli",
            status=VaDbBackup.STATUS_SUCCESS, store="local", object_key="db-backups/old.dump", sha256="ef" * 32,
        ))
        db.session.flush()
        with self.assertRaises(sweep.SweepRefused) as raised:
            sweep.confirm_db_backup("ef" * 32)
        self.assertIn("--allow-old-backup", str(raised.exception))
        with self.assertLogs("app.services.national_id_sweep_service", level="WARNING"):
            self.assertEqual(sweep.confirm_db_backup("ef" * 32, allow_old=True).object_key, "db-backups/old.dump")


# The fixture class's own tests run once, in PayloadSplitWriteTests.
for _name in dir(PayloadSplitWriteTests):
    if _name.startswith("test_"):
        setattr(PayloadSplitFixBatchTests, _name, None)
