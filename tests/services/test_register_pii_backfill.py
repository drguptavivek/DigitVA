"""PII slice 2, T4: the register backfill, verify, strip, restore, rewrap CLI
(``app/services/register_pii_backfill_service.py``, ``flask pii seal-register``;
docs/kb/pii-slice-2.md). Fixtures (project WIT01, interviewer) come from the
web intake service tests; their own tests are not repeated here.
"""
import json
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from unittest import mock

import sqlalchemy as sa
from click.testing import CliRunner

from app import db
from app.commands.pii import pii_group, rewrap_pending
from app.models import MapCaseTransition, VaDbBackup, VaDeathRegister
from app.services import register_pii_accessor as accessor
from app.services import register_pii_backfill_service as backfill
from app.utils import pii_crypto
from tests.services import test_web_intake_service as intake_tests
from tests.services.test_register_pii_split import PII

SHA = "ab" * 32
OLD = datetime(2020, 1, 1, tzinfo=UTC)
PLAIN_STRINGS = ("Asha", "9876543210", "Gandhi", "18.52", "asha@abdm", "Remark")


class RegisterPiiBackfillTests(intake_tests.WebIntakeServiceTests):
    def setUp(self):
        super().setUp()
        self._flag(False)

    # -- helpers ----------------------------------------------------------

    def _flag(self, on: bool):
        previous = self.app.config.get("REGISTER_PII_SPLIT_ENABLED", False)
        self.app.config["REGISTER_PII_SPLIT_ENABLED"] = on
        self.addCleanup(self.app.config.__setitem__, "REGISTER_PII_SPLIT_ENABLED", previous)

    def _row(self, n: int = 1, personal: bool = True, **over) -> VaDeathRegister:
        """A flag-off row with plaintext and an old ``updated_at``."""
        values = {
            "project_id": self.PROJECT_ID, "site_id": self.SITE_ID, "death_number": 700 + n,
            "unique_id": f"RBF-{uuid.uuid4().hex[:10]}", "deceased_sex": "female",
            "date_of_death": date.today() - timedelta(days=3), "status": "registered", "source": "register",
            "registered_by": self.interviewer.user_id,
            **(PII if personal else {}), "captured_at": datetime.now(UTC) if personal else None,
        }
        values.update(over)
        death = VaDeathRegister(**values)
        db.session.add(death)
        db.session.flush()
        self._core(death, updated_at=OLD)
        return death

    def _core(self, death, **values):
        db.session.execute(
            sa.update(VaDeathRegister).where(VaDeathRegister.death_id == death.death_id)
            .values(**{"updated_at": VaDeathRegister.updated_at, **values})  # onupdate must not move it
        )
        db.session.expire_all()

    def _raw(self, death):
        db.session.expire_all()
        return db.session.execute(
            sa.text("SELECT * FROM va_death_register WHERE death_id = :i"), {"i": death.death_id}
        ).mappings().one()

    def _backup(self, age_hours: int = 1):
        db.session.add(VaDbBackup(
            started_at=datetime.now(UTC) - timedelta(hours=age_hours), triggered_by="cli",
            status=VaDbBackup.STATUS_SUCCESS, store="local", object_key="db-backups/rbf.dump", sha256=SHA,
        ))
        db.session.flush()

    def _audit(self, death, changes) -> MapCaseTransition:
        audit = MapCaseTransition(
            death_id=death.death_id, action="details_edited", from_state="registered", to_state="registered",
            changes=changes, actor_user_id=self.interviewer.user_id,
        )
        db.session.add(audit)
        db.session.flush()
        return audit

    def _audit_raw(self, audit):
        db.session.expire_all()
        return db.session.execute(
            sa.text("SELECT changes, changes_dek_wrapped, changes_key_id FROM map_case_transitions "
                    "WHERE transition_id = :i"), {"i": audit.transition_id}
        ).mappings().one()

    def _seal_and_age(self, death, days: int = 40):
        backfill.seal_register(apply=True)
        self._core(death, pii_sealed_at=datetime.now(UTC) - timedelta(days=days))

    def _invoke(self, *args):
        return CliRunner().invoke(pii_group, list(args))

    def _open(self, death):
        return accessor.current_values(db.session.get(VaDeathRegister, death.death_id))

    # -- apply ------------------------------------------------------------

    def test_dry_run_writes_nothing(self):
        death = self._row()
        audit = self._audit(death, {"remarks": {"old": "a", "new": "b"}})
        report = backfill.seal_register()
        self.assertEqual((report["to_seal"], report["written"]), (1, 0))
        self.assertEqual(backfill.seal_audit()["audit_to_seal"], 1)
        raw = self._raw(death)
        self.assertIsNone(raw["pii_sealed"])
        self.assertEqual(raw["deceased_name"], "Asha Devi")
        self.assertEqual(self._audit_raw(audit)["changes"], {"remarks": {"old": "a", "new": "b"}})

    def test_apply_seals_keeps_plaintext_and_pins_updated_at(self):
        death = self._row()
        empty = self._row(2, personal=False, status="draft_identity")
        report = backfill.seal_register(apply=True)
        self.assertEqual((report["written"], report["verified"]), (2, 2))
        raw = self._raw(death)
        self.assertIsNotNone(raw["pii_sealed"])
        self.assertEqual(set(raw["pii_sealed"]), set(accessor.SEALED_FIELDS))
        for name in accessor.SEALED_ATTRS:  # plaintext stays until strip
            self.assertEqual(raw[name], PII[name], name)
        self.assertEqual(raw["updated_at"], OLD)
        self.assertEqual(raw["pii_blind_key_id"], pii_crypto.blind_key_id())
        self.assertIsNotNone(raw["pii_sealed_at"])
        self.assertTrue(all(raw[f] for f in ("has_deceased_name", "has_informant_phone", "has_location")))
        self.assertEqual(raw["informant_phone_bidx"], accessor.phone_bidx("9876543210"))
        self.assertEqual(raw["abha_number_bidx"], accessor.abha_number_bidx("12345678901234"))
        stored = json.dumps(raw["pii_sealed"]) + raw["pii_dek_wrapped"]
        for plain in PLAIN_STRINGS:
            self.assertNotIn(plain, stored)
        self.assertEqual(self._open(death), PII)
        # A row with nothing to seal is sealed with an empty record.
        self.assertEqual(self._raw(empty)["pii_sealed"], {})

    def test_rerun_is_a_no_op_and_wrapped_keys_stay_identical(self):
        death = self._row()
        backfill.seal_register(apply=True)
        before = self._raw(death)
        again = backfill.seal_register(apply=True)
        self.assertEqual((again["written"], again["to_seal"]), (0, 0))
        self.assertGreaterEqual(again["already_sealed"], 1)
        after = self._raw(death)
        self.assertEqual(
            (after["pii_dek_wrapped"], after["pii_sealed"]), (before["pii_dek_wrapped"], before["pii_sealed"])
        )

    def test_interrupted_run_resumes(self):
        deaths = [self._row(i) for i in (1, 2, 3)]
        real = backfill._sealed_values
        calls = []

        def flaky(death_id, plain):
            calls.append(death_id)
            if len(calls) == 2:
                raise RuntimeError("boom")
            return real(death_id, plain)

        with mock.patch.object(backfill, "_sealed_values", flaky):
            with self.assertRaises(RuntimeError):
                backfill.seal_register(apply=True, batch_size=1)
        sealed = [d for d in deaths if self._raw(d)["pii_sealed"] is not None]
        self.assertEqual(len(sealed), 1)
        first = self._raw(sealed[0])["pii_dek_wrapped"]
        report = backfill.seal_register(apply=True, batch_size=1)
        self.assertEqual(report["written"], 2)
        self.assertEqual(self._raw(sealed[0])["pii_dek_wrapped"], first)
        self.assertTrue(all(self._raw(d)["pii_sealed"] is not None for d in deaths))

    def test_apply_leaves_audit_rows_alone_and_strip_seals_them(self):
        death = self._row()
        legacy = {
            "remarks": {"old": "first", "new": "second"}, "age_years": {"old": 62, "new": 63},
            "identifier:aadhaar": {"old": {"bidx": "ab12", "mask": "XXXX1234"}, "new": None},
        }
        audit = self._audit(death, legacy)
        only_mask = self._audit(death, {"identifier:x": {"old": None, "new": {"bidx": "cd", "mask": "XX99"}}})
        self._seal_and_age(death)
        for row in (audit, only_mask):  # apply never touches them, mask included
            raw = self._audit_raw(row)
            self.assertIsNone(raw["changes_dek_wrapped"])
            self.assertEqual(raw["changes"], row.changes)
        self.assertEqual(self._audit_raw(audit)["changes"], legacy)
        dry = backfill.seal_audit()
        self.assertEqual((dry["audit_to_seal"], dry["audit_mask_to_scrub"], dry["audit_written"]), (1, 2, 0))

        report = backfill.strip_register(hold_days=30)
        self.assertEqual((report["stripped"], report["audit_written"], report["audit_skipped"]), (1, 2, 0))
        raw = self._audit_raw(audit)
        self.assertIsNotNone(raw["changes_dek_wrapped"])
        self.assertEqual(raw["changes_key_id"], pii_crypto.current_key_id())
        stored = json.dumps(raw["changes"])
        for plain in ("first", "second", "mask", "XXXX1234"):
            self.assertNotIn(plain, stored)
        self.assertEqual(raw["changes"]["age_years"], {"old": 62, "new": 63})
        opened = accessor.open_audit_changes(db.session.get(MapCaseTransition, audit.transition_id))
        self.assertEqual(opened["remarks"], {"old": "first", "new": "second"})
        self.assertEqual(opened["identifier:aadhaar"], {"old": {"bidx": "ab12"}, "new": None})
        scrubbed = self._audit_raw(only_mask)
        self.assertEqual(scrubbed["changes"], {"identifier:x": {"old": None, "new": {"bidx": "cd"}}})
        self.assertIsNone(scrubbed["changes_dek_wrapped"])
        self.assertTrue(backfill.verify_register(after_strip=True)["ok"])
        again = backfill.strip_register(hold_days=30)
        self.assertEqual((again["audit_written"], again["stripped"]), (0, 0))

    def test_strip_leaves_audit_rows_of_held_cases_plaintext_until_a_later_run(self):
        held = self._row()
        done = self._row()
        changes = {"remarks": {"old": "first", "new": "second"}, "identifier:x": {"old": {"mask": "1"}, "new": None}}
        held_audit = self._audit(held, changes)
        done_audit = self._audit(done, changes)
        backfill.seal_register(apply=True)
        self._core(done, pii_sealed_at=datetime.now(UTC) - timedelta(days=40))
        report = backfill.strip_register(hold_days=30)
        self.assertEqual((report["stripped"], report["held"], report["audit_written"]), (1, 1, 1))
        self.assertIsNotNone(self._audit_raw(done_audit)["changes_dek_wrapped"])
        raw = self._audit_raw(held_audit)  # untouched, mask included
        self.assertEqual((raw["changes"], raw["changes_dek_wrapped"]), (changes, None))
        self.assertEqual(self._raw(held)["deceased_name"], "Asha Devi")
        self.assertEqual(backfill.seal_audit(stripped_only=True)["audit_rows"], 0)
        self.assertEqual(backfill.seal_audit()["audit_to_seal"], 1)  # the dry run still counts every case
        # verify --after-strip looks only at stripped cases, so the held audit row is no problem
        self.assertTrue(backfill.verify_register(after_strip=True)["ok"])

        self._core(held, pii_sealed_at=datetime.now(UTC) - timedelta(days=40))  # the hold ends
        later = backfill.strip_register(hold_days=30)
        self.assertEqual((later["stripped"], later["held"], later["audit_written"]), (1, 0, 1))
        self.assertIsNotNone(self._audit_raw(held_audit)["changes_dek_wrapped"])
        self.assertNotIn("first", json.dumps(self._audit_raw(held_audit)["changes"]))
        self.assertTrue(backfill.verify_register(after_strip=True)["ok"])
        rerun = backfill.strip_register(hold_days=30)
        self.assertEqual((rerun["stripped"], rerun["audit_written"]), (0, 0))

    # -- verify -----------------------------------------------------------

    def test_verify_passes_then_fails_on_tamper_and_wrong_flag(self):
        death = self._row()
        self.assertFalse(backfill.verify_register()["ok"])  # unsealed
        backfill.seal_register(apply=True)
        report = backfill.verify_register(sample=50)
        self.assertEqual((report["ok"], report["rows"], report["sampled"], report["sample_failed"]), (True, 1, 1, 0))

        sealed = dict(self._raw(death)["pii_sealed"])
        sealed["remarks"], sealed["father_name"] = sealed["father_name"], sealed["remarks"]
        self._core(death, pii_sealed=sealed)
        tampered = backfill.verify_register(sample=50)
        self.assertEqual((tampered["ok"], tampered["sample_failed"]), (False, 1))
        sealed["remarks"], sealed["father_name"] = sealed["father_name"], sealed["remarks"]
        self._core(death, pii_sealed=sealed)
        self.assertTrue(backfill.verify_register()["ok"])

        self._core(death, has_informant_phone=False)
        self.assertEqual(backfill.verify_register()["flag_mismatch"], 1)
        self.assertFalse(backfill.verify_register()["ok"])

    def test_verify_checks_audit_rows_only_after_the_strip(self):
        death = self._row()
        backfill.seal_register(apply=True)
        self._audit(death, {"remarks": {"old": "a", "new": "b"}, "identifier:x": {"old": {"mask": "1"}, "new": None}})
        before = backfill.verify_register()
        self.assertEqual((before["audit_unsealed"], before["audit_mask"], before["ok"]), (0, 0, True))
        held = backfill.verify_register(after_strip=True)  # case not stripped: its audit row is not flagged
        self.assertEqual((held["audit_unsealed"], held["audit_mask"], held["ok"]), (0, 0, True))
        self._core(death, **{attr: None for attr in accessor.SEALED_ATTRS})  # stripped by hand, audit still plain
        after = backfill.verify_register(after_strip=True)
        self.assertEqual((after["audit_unsealed"], after["audit_mask"], after["ok"]), (1, 1, False))

    # -- strip ------------------------------------------------------------

    def test_strip_refuses_without_a_passing_verify(self):
        death = self._row()
        with self.assertRaises(backfill.BackfillRefused):
            backfill.strip_register(hold_days=0)
        self.assertEqual(self._raw(death)["deceased_name"], "Asha Devi")

    def test_strip_holds_young_rows_then_nulls_after_the_hold(self):
        death = self._row()
        backfill.seal_register(apply=True)
        held = backfill.strip_register(hold_days=30)
        self.assertEqual((held["stripped"], held["held"]), (0, 1))
        self.assertEqual(self._raw(death)["deceased_name"], "Asha Devi")

        self._core(death, pii_sealed_at=datetime.now(UTC) - timedelta(days=31))
        done = backfill.strip_register(hold_days=30)
        self.assertEqual((done["stripped"], done["held"], done["failed"]), (1, 0, 0))
        raw = self._raw(death)
        for name in accessor.SEALED_ATTRS:
            self.assertIsNone(raw[name], name)
        # The CHECKs hold on the stripped row (the UPDATE would have failed), flags stay true.
        self.assertTrue(raw["has_deceased_name"] and raw["has_location"] and raw["has_informant_phone"])
        self.assertIsNotNone(raw["captured_at"])
        self.assertEqual(raw["updated_at"], OLD)
        self.assertEqual(self._open(death), PII)
        self.assertTrue(backfill.verify_register()["ok"])
        again = backfill.strip_register(hold_days=30)
        self.assertEqual((again["stripped"], again["held"]), (0, 0))

    def test_strip_keeps_a_row_whose_plaintext_differs_from_the_blob(self):
        death = self._row()
        self._seal_and_age(death)
        sealed = dict(self._raw(death)["pii_sealed"])
        self._core(death, remarks="changed after the seal")
        # verify's sample sees the divergence first.
        with self.assertRaises(backfill.BackfillRefused):
            backfill.strip_register(hold_days=30)
        counts = backfill.strip_register(hold_days=30, sample=0)
        self.assertEqual((counts["stripped"], counts["failed"]), (0, 1))
        self.assertEqual(self._raw(death)["remarks"], "changed after the seal")
        self.assertEqual(self._raw(death)["pii_sealed"], sealed)

    # -- restore ----------------------------------------------------------

    def test_restore_round_trips_and_is_refused_with_the_flag_on(self):
        death = self._row()
        audit = self._audit(death, {"remarks": {"old": "first", "new": "second"}})
        self._seal_and_age(death)
        backfill.strip_register(hold_days=30)
        self.assertIsNone(self._raw(death)["remarks"])

        self._flag(True)
        with self.assertRaises(backfill.BackfillRefused):
            backfill.restore_register()
        self.assertIsNotNone(self._raw(death)["pii_sealed"])
        self._flag(False)

        counts = backfill.restore_register()
        self.assertEqual(counts, {"restored": 1, "failed": 0, "audit_restored": 1, "audit_failed": 0})
        raw = self._raw(death)
        for name in accessor.SEALED_ATTRS:
            self.assertEqual(raw[name], PII[name], name)
        for name in ("pii_sealed", "pii_dek_wrapped", "pii_key_id", "pii_blind_key_id", "pii_sealed_at",
                     "informant_phone_bidx", "abha_number_bidx"):
            self.assertIsNone(raw[name], name)
        self.assertTrue(raw["has_deceased_name"] and raw["has_location"])
        self.assertEqual(raw["updated_at"], OLD)
        self.assertEqual(db.session.scalar(sa.text("SELECT pii_sealed IS NULL FROM va_death_register WHERE death_id = :i"),
                                           {"i": death.death_id}), True)
        restored = self._audit_raw(audit)
        self.assertEqual(restored["changes"], {"remarks": {"old": "first", "new": "second"}})
        self.assertIsNone(restored["changes_dek_wrapped"])
        self.assertEqual(
            backfill.restore_register(), {"restored": 0, "failed": 0, "audit_restored": 0, "audit_failed": 0}
        )

    # -- recompute digests ------------------------------------------------

    def test_recompute_digests_after_a_blind_key_change(self):
        death = self._row()
        backfill.seal_register(apply=True)
        before = self._raw(death)
        ring = self.app.extensions["pii_keyring"]
        rotated = pii_crypto.Keyring(ring.public, ring.private, os.urandom(32))
        with mock.patch.dict(self.app.extensions, {"pii_keyring": rotated}):
            self.assertEqual(backfill.verify_register()["blind_key_stale"], 1)
            dry = backfill.recompute_digests()
            self.assertEqual((dry["to_recompute"], dry["recomputed"]), (1, 0))
            self.assertEqual(self._raw(death)["pii_blind_key_id"], before["pii_blind_key_id"])
            counts = backfill.recompute_digests(apply=True)
            self.assertEqual((counts["recomputed"], counts["failed"]), (1, 0))
            after = self._raw(death)
            self.assertEqual(after["pii_blind_key_id"], pii_crypto.blind_key_id())
            self.assertNotEqual(after["pii_blind_key_id"], before["pii_blind_key_id"])
            self.assertNotEqual(after["informant_phone_bidx"], before["informant_phone_bidx"])
            self.assertEqual(after["informant_phone_bidx"], accessor.phone_bidx("9876543210"))
            self.assertEqual(
                (after["pii_sealed"], after["pii_dek_wrapped"]), (before["pii_sealed"], before["pii_dek_wrapped"])
            )
            self.assertEqual(after["updated_at"], OLD)
            self.assertTrue(backfill.verify_register()["ok"])
            self.assertEqual(backfill.recompute_digests(apply=True)["to_recompute"], 0)

    # -- rewrap -----------------------------------------------------------

    def test_rewrap_moves_register_and_audit_rows_with_ciphertexts_unchanged(self):
        death = self._row()
        audit = self._audit(death, {"remarks": {"old": "first", "new": "second"}})
        backfill.seal_register(apply=True)
        backfill.seal_audit(apply=True)
        before, before_audit = self._raw(death), self._audit_raw(audit)

        old = self.app.extensions["pii_keyring"]
        new_public, new_private = pii_crypto.generate_keyset("rotrb")
        rotated = pii_crypto.Keyring(new_public, {**old.private, "rotrb": new_private}, old.blind_key)
        with mock.patch.dict(self.app.extensions, {"pii_keyring": rotated}):
            counts = rewrap_pending(batch_size=1)
            self.assertGreaterEqual(counts["rewrapped"], 2)
            self.assertEqual(counts["failed"], 0)
            self.assertEqual(rewrap_pending()["rewrapped"], 0)
        after, after_audit = self._raw(death), self._audit_raw(audit)
        self.assertEqual((after["pii_key_id"], after_audit["changes_key_id"]), ("rotrb", "rotrb"))
        self.assertEqual(after["pii_sealed"], before["pii_sealed"])
        self.assertNotEqual(after["pii_dek_wrapped"], before["pii_dek_wrapped"])
        self.assertEqual(after_audit["changes"], before_audit["changes"])
        self.assertNotEqual(after_audit["changes_dek_wrapped"], before_audit["changes_dek_wrapped"])
        self.assertEqual(after["updated_at"], OLD)
        new_only = pii_crypto.Keyring(new_public, {"rotrb": new_private}, old.blind_key)
        with mock.patch.dict(self.app.extensions, {"pii_keyring": new_only}):
            pii_crypto.clear_dek_cache()
            self.assertEqual(self._open(death), PII)
            opened = accessor.open_audit_changes(db.session.get(MapCaseTransition, audit.transition_id))
            self.assertEqual(opened["remarks"], {"old": "first", "new": "second"})

    # -- CLI --------------------------------------------------------------

    def test_cli_backup_gate_refuses_missing_and_old_backups(self):
        death = self._row()
        missing = self._invoke("seal-register", "--apply")
        self.assertNotEqual(missing.exit_code, 0)
        self.assertIn("--confirm-backup", missing.output)
        unknown = self._invoke("seal-register", "--apply", "--confirm-backup", "cd" * 32)
        self.assertNotEqual(unknown.exit_code, 0)
        self._backup(age_hours=72)
        old = self._invoke("seal-register", "--apply", "--confirm-backup", SHA)
        self.assertNotEqual(old.exit_code, 0)
        self.assertIn("hours old", old.output)
        for command in ("--strip", "--restore"):
            self.assertNotEqual(self._invoke("seal-register", command).exit_code, 0)
        self.assertIsNone(self._raw(death)["pii_sealed"])
        allowed = self._invoke("seal-register", "--apply", "--confirm-backup", SHA, "--allow-old-backup")
        self.assertEqual(allowed.exit_code, 0, allowed.output)
        self.assertIsNotNone(self._raw(death)["pii_sealed"])

    def test_cli_flow_prints_counts_only_and_logs_the_backup_key(self):
        death = self._row()
        self._audit(death, {"remarks": {"old": "first", "new": "second"}})
        self._backup()
        outputs = []
        dry = self._invoke("seal-register")
        outputs.append(dry.output)
        self.assertEqual(dry.exit_code, 0, dry.output)
        self.assertIn("dry-run: ", dry.output)
        self.assertIn("to_seal=1", dry.output)
        self.assertIn("audit_to_seal=1", dry.output)
        self.assertIsNone(self._raw(death)["pii_sealed"])
        with self.assertLogs("app.commands.pii", level="WARNING") as logged:
            applied = self._invoke("seal-register", "--apply", "--confirm-backup", SHA)
        outputs.append(applied.output)
        self.assertEqual(applied.exit_code, 0, applied.output)
        self.assertTrue(any("backup_key=db-backups/rbf.dump" in line for line in logged.output))
        verified = self._invoke("seal-register", "--verify")
        outputs.append(verified.output)
        self.assertEqual(verified.exit_code, 0, verified.output)
        self.assertIn("ok=True", verified.output)
        early = self._invoke("seal-register", "--verify", "--after-strip")
        outputs.append(early.output)
        self.assertEqual(early.exit_code, 0, early.output)  # the case is not stripped: audit row not flagged
        self.assertIn("audit_unsealed=0", early.output)

        young = self._invoke("seal-register", "--strip", "--confirm-backup", SHA)
        outputs.append(young.output)
        self.assertEqual(young.exit_code, 0, young.output)
        self.assertIn("held=1", young.output)
        self.assertIn("audit_written=0", young.output)
        self.assertEqual(self._raw(death)["deceased_name"], "Asha Devi")
        stripped = self._invoke("seal-register", "--strip", "--confirm-backup", SHA, "--hold-days", "0")
        outputs.append(stripped.output)
        self.assertIn("stripped=1", stripped.output)
        self.assertIn("audit_written=1", stripped.output)
        self.assertIsNone(self._raw(death)["deceased_name"])
        final = self._invoke("seal-register", "--verify", "--after-strip")
        outputs.append(final.output)
        self.assertEqual(final.exit_code, 0, final.output)

        both = self._invoke("seal-register", "--apply", "--verify")
        self.assertNotEqual(both.exit_code, 0)
        text = "\n".join(outputs)
        for plain in (*PLAIN_STRINGS, "first", "second", str(death.death_id)):
            self.assertNotIn(plain, text)
        for line in logged.output:
            self.assertNotIn(str(death.death_id), line)

    def test_cli_verify_exits_non_zero_on_a_problem(self):
        self._row()
        failed = self._invoke("seal-register", "--verify")
        self.assertNotEqual(failed.exit_code, 0)
        self.assertIn("unsealed=1", failed.output)

    def test_cli_restore_refused_with_the_flag_on(self):
        self._row()
        self._backup()
        self._flag(True)
        refused = self._invoke("seal-register", "--restore", "--confirm-backup", SHA)
        self.assertNotEqual(refused.exit_code, 0)
        self.assertIn("REGISTER_PII_SPLIT_ENABLED", refused.output)


# The inherited intake tests run in their own module.
for _name in [n for n in dir(intake_tests.WebIntakeServiceTests) if n.startswith("test_")]:
    setattr(RegisterPiiBackfillTests, _name, None)
