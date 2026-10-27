"""Translated labels showing another question's code (digitva-fb5)."""
import json
import os
import tempfile
from datetime import UTC, datetime

from app import db
from app.models.mas_instrument_locales import MapInstrumentTranslations, MasInstrumentLocales
from app.services import instrument_translation_service as svc
from app.services import translation_label_code_audit as audit
from tests.base import BaseTestCase

CODE = "WHO_2022_VA"


def _english(key):
    return svc.reference_items(CODE)[("question", key, "label")]


class LabelCodeAuditTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        db.session.add(MasInstrumentLocales(
            instrument_code=CODE, locale_code="zz", language_name="Test", version=1,
            is_active=False, updated_at=datetime.now(UTC), lifecycle_state="draft",
        ))
        db.session.flush()
        self.cases = {  # key -> (shown code, expected kind)
            "id10161_unit": ("Id10161_unit", audit.CASE_ONLY),
            "Id10010": ("Id100010", audit.MISTYPED),
            "Id10192": ("Id10191", audit.NEEDS_REVIEW),
            "Id10191": ("Id10191", None),  # own code: not a mismatch
        }
        for key, (shown, _kind) in self.cases.items():
            body = audit._PREFIX_RE.sub("", _english(key), count=1)
            db.session.add(MapInstrumentTranslations(
                instrument_code=CODE, locale_code="zz", item_kind="question", item_key=key,
                field="label", text=f"({shown}){body}", source="imported",
                updated_at=datetime.now(UTC),
            ))
        db.session.flush()

    def _text(self, key):
        return db.session.get(
            MapInstrumentTranslations, (CODE, "zz", "question", key, "label")
        ).text

    def test_detector_classifies_every_mismatch_and_skips_own_codes(self):
        found = {i["item_key"]: i["kind"] for i in audit.find_label_code_mismatches(CODE, "zz")}
        self.assertEqual(
            found,
            {k: kind for k, (_s, kind) in self.cases.items() if kind},
        )

    def test_dry_run_changes_nothing(self):
        before = {k: self._text(k) for k in self.cases}
        result = audit.fix_code_only_labels(CODE, locale_code="zz")
        self.assertEqual((result["fixed"], result["needs_review"]), (2, 1))
        self.assertEqual(before, {k: self._text(k) for k in self.cases})

    def test_apply_fixes_only_the_code_is_idempotent_and_reversible(self):
        before = {k: self._text(k) for k in self.cases}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "backup.json")
            with self.assertRaises(svc.InstrumentTranslationError):
                audit.fix_code_only_labels(CODE, locale_code="zz", dry_run=False)
            audit.fix_code_only_labels(CODE, locale_code="zz", dry_run=False, backup_path=path)

            self.assertTrue(self._text("Id10010").startswith("(Id10010)"))
            self.assertTrue(self._text("id10161_unit").startswith("(id10161_unit)"))
            self.assertEqual(self._text("Id10010")[len("(Id10010)"):], before["Id10010"][len("(Id100010)"):])
            # Wrong wording and correct rows are left alone.
            self.assertEqual(self._text("Id10192"), before["Id10192"])
            self.assertEqual(self._text("Id10191"), before["Id10191"])
            self.assertEqual(len(json.load(open(path))["rows"]), 2)

            again = audit.fix_code_only_labels(CODE, locale_code="zz")
            self.assertEqual((again["fixed"], again["needs_review"]), (0, 1))

            self.assertEqual(audit.restore_from_snapshot(path), {"restored": 2, "skipped": 0})
            self.assertEqual(before, {k: self._text(k) for k in self.cases})
            self.assertEqual(
                db.session.get(MapInstrumentTranslations, (CODE, "zz", "question", "Id10010", "label")).source,
                "imported",
            )

    def test_restore_skips_a_row_edited_after_apply(self):
        before = {k: self._text(k) for k in self.cases}
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "backup.json")
            audit.fix_code_only_labels(CODE, locale_code="zz", dry_run=False, backup_path=path)
            row = db.session.get(MapInstrumentTranslations, (CODE, "zz", "question", "Id10010", "label"))
            row.text = row.text + " (reviewed)"
            db.session.flush()

            with self.assertLogs(audit.log, "INFO") as logs:
                result = audit.restore_from_snapshot(path)

            self.assertEqual(result, {"restored": 1, "skipped": 1})
            self.assertTrue(self._text("Id10010").endswith("(reviewed)"))  # not overwritten
            self.assertEqual(self._text("id10161_unit"), before["id10161_unit"])  # restored
            self.assertEqual(len(logs.records), 1)
            self.assertIn("id10161_unit", logs.output[0])


class FixLabelCodesCliTests(LabelCodeAuditTests):
    def _run(self, *args):
        return self.app.test_cli_runner().invoke(
            args=["instrument-translations", "fix-label-codes", CODE, "--locale", "zz", *args]
        )

    def test_dry_run_apply_and_restore(self):
        before = {k: self._text(k) for k in self.cases}
        dry = self._run()
        self.assertEqual(dry.exit_code, 0, dry.output)
        self.assertIn("dry-run: fixable=2 needs_review=1", dry.output)
        self.assertEqual(before, {k: self._text(k) for k in self.cases})

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "backup.json")
            applied = self._run("--apply", "--backup", path)
            self.assertEqual(applied.exit_code, 0, applied.output)
            self.assertIn("applied: fixable=2", applied.output)
            self.assertNotEqual(self._text("Id10010"), before["Id10010"])  # the subject changed

            both = self._run("--apply", "--backup", path + "2", "--restore", path)
            self.assertNotEqual(both.exit_code, 0)
            self.assertIn("cannot be combined", both.output)

            restored = self._run("--restore", path)
            self.assertEqual(restored.exit_code, 0, restored.output)
            self.assertIn("restored=2 skipped=0", restored.output)
            self.assertEqual(before, {k: self._text(k) for k in self.cases})
