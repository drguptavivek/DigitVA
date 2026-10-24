"""Dump/load of translation rows across servers, and the UI-string bake (digitva-3b65)."""
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import mock

from app import db
from app.models.mas_instrument_locales import MapInstrumentTranslations as T
from app.models.mas_instrument_locales import MasInstrumentLocales as L
from app.models.mas_ui_string_override import MasUiStringOverride as U
from app.services import translation_transfer_service as svc
from app.services import ui_string_service as ui
from app.services.ui_string_bake import bake
from tests.base import BaseTestCase
from tests.ui_string_fixtures import EN, HI, write_export

INST = "WHO_2022_VA"
REF = {
    ("question", "q1", "label"): "One",
    ("question", "q2", "label"): "Two",
    ("question", "q3", "label"): "Three",
}
WHEN = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class TransferTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self._old = self.app.config.get("EXPO_CLIENT_DIST")
        self.app.config["EXPO_CLIENT_DIST"] = self._tmp.name
        write_export(Path(self._tmp.name), {"en": EN, "hi": HI})
        patcher = mock.patch.object(svc, "reference_items", return_value=REF)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.admin = self.base_admin_user

    def tearDown(self):
        db.session.rollback()
        if self._old is None:
            self.app.config.pop("EXPO_CLIENT_DIST", None)
        else:
            self.app.config["EXPO_CLIENT_DIST"] = self._old
        self._tmp.cleanup()
        super().tearDown()

    def _seed(self):
        db.session.add_all([
            U(locale_code="hi", string_key="loginHelp", text="मदद", source="edited",
              updated_by=self.admin.user_id, updated_at=WHEN),
            U(locale_code="pa", string_key="navCoding", text="ਕੋਡ", source="machine", updated_at=WHEN),
        ])
        db.session.add(L(instrument_code=INST, locale_code="hi", language_name="Hindi",
                         version=3, updated_at=WHEN))
        db.session.flush()
        db.session.add_all([
            T(instrument_code=INST, locale_code="hi", item_kind="question", item_key="q1",
              field="label", text="एक", source="edited", updated_by=self.admin.user_id, updated_at=WHEN),
            T(instrument_code=INST, locale_code="hi", item_kind="question", item_key="q2",
              field="label", text="दो", source="machine", updated_at=WHEN),
        ])
        db.session.flush()

    def _wipe(self):
        db.session.query(T).delete()
        db.session.query(L).delete()
        db.session.query(U).delete()
        db.session.flush()

    def _natural(self):
        ui_rows = {(r.locale_code, r.string_key): (r.text, r.source, r.updated_by)
                   for r in db.session.query(U)}
        q_rows = {(r.instrument_code, r.locale_code, r.item_kind, r.item_key, r.field):
                  (r.text, r.source, r.updated_by) for r in db.session.query(T)}
        return ui_rows, q_rows

    # -- round trip ------------------------------------------------------

    def test_round_trip_into_empty_tables(self):
        self._seed()
        before = self._natural()
        data = json.loads(json.dumps(svc.dump()))
        self.assertEqual(data["format"], "digitva-translations")
        self.assertEqual(data["ui_strings"][0]["updated_by_email"], self.admin.email)
        self._wipe()

        counts = svc.load(data)
        self.assertEqual(self._natural(), before)
        self.assertEqual(counts["ui_strings"][("hi", "edited")]["inserted"], 1)
        self.assertEqual(counts["questionnaire"][(f"{INST}/hi", "machine")]["inserted"], 1)
        loc = db.session.get(L, (INST, "hi"))
        self.assertEqual((loc.version, loc.is_active, loc.lifecycle_state), (1, False, "draft"))
        self.assertEqual(counts["locales_created"], [f"{INST}/hi"])

    def test_load_is_idempotent_and_never_overwrites(self):
        self._seed()
        data = svc.dump()
        counts = svc.load(data)
        self.assertEqual(counts["ui_strings"][("hi", "edited")]["skipped_existing"], 1)
        self.assertEqual(counts["questionnaire"][(f"{INST}/hi", "edited")]["skipped_existing"], 1)

        # The target holds different text for a dumped key: it must survive.
        row = db.session.get(U, ("hi", "loginHelp"))
        row.text = "लक्ष्य"
        row.source = "machine"
        t = db.session.get(T, (INST, "hi", "question", "q1", "label"))
        t.text = "लक्ष्य"
        db.session.flush()
        version = db.session.get(L, (INST, "hi")).version
        svc.load(data)
        self.assertEqual(db.session.get(U, ("hi", "loginHelp")).text, "लक्ष्य")
        self.assertEqual(db.session.get(U, ("hi", "loginHelp")).source, "machine")
        self.assertEqual(db.session.get(T, (INST, "hi", "question", "q1", "label")).text, "लक्ष्य")
        self.assertEqual(db.session.get(L, (INST, "hi")).version, version)

    def test_dry_run_writes_nothing(self):
        self._seed()
        data = svc.dump()
        self._wipe()
        counts = svc.load(data, dry_run=True)
        self.assertEqual(counts["ui_strings"][("hi", "edited")]["inserted"], 1)
        self.assertEqual(self._natural(), ({}, {}))
        self.assertIsNone(db.session.get(L, (INST, "hi")))

    # -- authors ---------------------------------------------------------

    def test_authors_map_by_email_and_unknown_is_null(self):
        self._seed()
        data = svc.dump()
        data["questionnaire"]["translations"][0]["updated_by_email"] = "nobody@nowhere.invalid"
        data["ui_strings"][0]["updated_by_email"] = self.admin.email.upper()
        self._wipe()
        counts = svc.load(data)
        ui_row = db.session.get(U, ("hi", "loginHelp"))
        q_row = db.session.get(T, (INST, "hi", "question", "q1", "label"))
        self.assertEqual(ui_row.updated_by, self.admin.user_id)
        self.assertIsNone(q_row.updated_by)
        self.assertEqual(counts["unknown_authors"]["questionnaire"], 1)

    # -- served version --------------------------------------------------

    def test_version_bumps_only_for_served_rows(self):
        db.session.add(L(instrument_code=INST, locale_code="hi", language_name="Hindi",
                         version=5, updated_at=WHEN))
        db.session.flush()

        def block(source, key):
            return {"format": "digitva-translations", "version": 1, "questionnaire": {
                "locales": [{"instrument_code": INST, "locale_code": "hi", "language_name": "Hindi"}],
                "translations": [{"instrument_code": INST, "locale_code": "hi", "item_kind": "question",
                                  "item_key": key, "field": "label", "text": "x", "source": source}]}}

        svc.load(block("machine", "q1"))
        self.assertEqual(db.session.get(L, (INST, "hi")).version, 5)
        svc.load(block("edited", "q2"))
        self.assertEqual(db.session.get(L, (INST, "hi")).version, 6)

    def test_unknown_item_and_bad_rows_are_counted_not_loaded(self):
        data = {"format": "digitva-translations", "version": 1, "questionnaire": {
            "locales": [{"instrument_code": INST, "locale_code": "hi", "language_name": "Hindi"}],
            "translations": [
                {"instrument_code": INST, "locale_code": "hi", "item_kind": "question",
                 "item_key": "nope", "field": "label", "text": "x", "source": "edited"},
                {"instrument_code": INST, "locale_code": "hi", "item_kind": "question",
                 "item_key": "q1", "field": "label", "text": "x", "source": "bogus"}]},
            "ui_strings": [{"locale": "hi", "key": "noSuchKey", "text": "x", "source": "edited"}]}
        counts = svc.load(data)
        self.assertEqual(counts["questionnaire"][(f"{INST}/hi", "edited")]["skipped_unknown"], 1)
        self.assertEqual(counts["questionnaire"][(f"{INST}/hi", "bogus")]["errors"], 1)
        self.assertEqual(counts["ui_strings"][("hi", "edited")]["skipped_unknown"], 1)
        self.assertEqual(self._natural(), ({}, {}))

    def test_wrong_format_or_version_refused(self):
        for bad in ({}, {"format": "digitva-translations", "version": 2}, []):
            with self.assertRaises(svc.TransferError):
                svc.load(bad)

    def test_dump_flags_and_locale_filter(self):
        self._seed()
        self.assertNotIn("ui_strings", svc.dump(ui_strings=False))
        self.assertNotIn("questionnaire", svc.dump(questionnaire=False))
        only_pa = svc.dump(locales=("pa",))
        self.assertEqual([r["locale"] for r in only_pa["ui_strings"]], ["pa"])
        self.assertEqual(only_pa["questionnaire"]["translations"], [])


class BakeTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name)
        # en order is deliberately not alphabetical.
        (self.src / "en.json").write_text(json.dumps(EN), encoding="utf-8")
        (self.src / "hi.json").write_text(json.dumps(HI), encoding="utf-8")

    def tearDown(self):
        db.session.rollback()
        self._tmp.cleanup()
        super().tearDown()

    def _add(self, locale, key, text, source="edited"):
        db.session.add(U(locale_code=locale, string_key=key, text=text, source=source,
                         updated_at=datetime.now(UTC) - timedelta(days=1)))
        db.session.flush()

    def test_merge_excludes_machine_keeps_en_order(self):
        self._add("hi", "loginHelp", "मौजूदा साइन-इन")
        self._add("hi", "navCoding", "नया कोडिंग")
        self._add("hi", "extraKey", "x")                       # not an en key
        db.session.add(U(locale_code="hi", string_key="loginTitle", text="मशीन", source="machine"))
        db.session.flush()
        text, changed = bake("hi", self.src)
        out = json.loads(text)
        self.assertEqual(list(out), [k for k in EN if k in out])
        self.assertEqual(out["loginHelp"], "मौजूदा साइन-इन")
        self.assertEqual(out["navCoding"], "नया कोडिंग")
        self.assertEqual(out["loginTitle"], HI["loginTitle"])   # machine draft not baked
        self.assertNotIn("extraKey", out)
        self.assertEqual(changed, 2)
        self.assertTrue(text.endswith("}\n"))
        self.assertIn("मौजूदा", text)                           # not ASCII-escaped

    def test_placeholder_mismatch_rejected(self):
        self._add("hi", "syncResult", "भेजे {sent}")
        with self.assertRaises(ui.UiStringError):
            bake("hi", self.src)

    def test_new_locale_from_accepted_rows_only(self):
        self._add("pa", "navCoding", "ਕੋਡਿੰਗ")
        self._add("pa", "loginTitle", "ਮਸ਼ੀਨ", source="machine")
        out = json.loads(bake("pa", self.src)[0])
        self.assertEqual(out, {"navCoding": "ਕੋਡਿੰਗ"})
        with self.assertRaises(ui.UiStringError):
            bake("mr", self.src)

    def test_base_and_bad_locale_refused(self):
        for locale in ("en", "../x", "HI"):
            with self.assertRaises(ui.UiStringError):
                bake(locale, self.src)
