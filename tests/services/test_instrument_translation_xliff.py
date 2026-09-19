"""XLIFF 2.0 as the interchange format for instrument translations.

WP6 of docs/planning/web-capture-project-configuration-plan.md, decision
"i18n method". The rules held here, from
docs/policy/va-form-project-configuration.md ("Interchange format"):

* a resource id round-trips to exactly one stored string, and back;
* an export carries every reference item, so an untranslated one is visible as
  an empty target in state ``initial`` rather than absent -- which is the form
  falling back to English, stated in the exchange format;
* an import may correct a string and may never create an item: a unit the
  reference form does not have is reported and skipped;
* an empty target leaves what is stored alone;
* a document that is not XLIFF 2.0 ``en`` -> this locale is refused, and a
  DOCTYPE is refused before anything parses it.

Most tests run against a small synthetic reference form. Exactly one runs the
real Hindi workbook through import -> export -> re-import, which is the test
that would notice the round trip losing or re-writing a string.
"""
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from app import db
from app.models.mas_instrument_locales import (
    SOURCE_EDITED,
    SOURCE_IMPORTED,
    MapInstrumentTranslations,
    MasInstrumentLocales,
)
from app.services import instrument_translation_service as svc
from tests.base import BaseTestCase

INSTRUMENT = "XLIFF_VA"
NS = svc.XLIFF_NAMESPACE
Q = f"{{{NS}}}"

# Re-serializing a parsed export (the way a translator's tool hands one back)
# should write the same default-namespaced form the service writes.
ET.register_namespace("", NS)

POLICY_DOC = """---
title: test
---

# Test

## Translation sources

| Language | Locale | Source workbook | Project | ODK form id | Download date | Assigned by |
| --- | --- | --- | --- | --- | --- | --- |
| Hindi | hi | source_hi.xlsx | TESTPROJ | TEST_FORM | 2026-09-19 | tester |

## After
"""


def _write_workbook(path, survey_rows, choice_rows):
    settings = pd.DataFrame(
        [{"form_id": "t", "form_title": "T", "version": "1",
          "default_language": "English (en)"}]
    )
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame(survey_rows).to_excel(writer, sheet_name="survey", index=False)
        pd.DataFrame(choice_rows).to_excel(writer, sheet_name="choices", index=False)
        settings.to_excel(writer, sheet_name="settings", index=False)
    return path


def _units(document):
    """``{unit id: (state, source text, target text or None)}``."""
    root = ET.fromstring(document)
    out = {}
    for unit in root.iter(f"{Q}unit"):
        segment = unit.find(f"{Q}segment")
        target = segment.find(f"{Q}target")
        out[unit.get("id")] = (
            segment.get("state"),
            segment.find(f"{Q}source").text,
            target.text,
        )
    return out


class ResourceIdTests(unittest.TestCase):
    """The id scheme, which everything XLIFF is keyed by. No database needed."""

    def test_a_question_and_a_choice_round_trip_through_their_ids(self):
        self.assertEqual(
            svc.resource_id("question", "Id10004", "label"), "question.Id10004.label"
        )
        self.assertEqual(
            svc.resource_id("question", "Id10004", "guidance_hint"),
            "question.Id10004.guidance_hint",
        )
        self.assertEqual(
            svc.resource_id("choice", "yes_no/yes", "label"), "choice.yes_no.yes.label"
        )
        for key in (
            ("question", "Id10004", "label"),
            ("question", "Id10004", "hint"),
            ("question", "Id10004", "guidance_hint"),
            ("choice", "yes_no-list/opt_1", "label"),
        ):
            with self.subTest(key=key):
                self.assertEqual(svc.parse_resource_id(svc.resource_id(*key)), key)

    def test_every_real_reference_item_round_trips(self):
        """The scheme is only safe if it is unambiguous over the real form."""
        reference = svc.reference_items(svc.BASE_INSTRUMENT_CODE)
        self.assertGreater(len(reference), 1000, "fixture guard: the reference loaded")
        ids = {}
        for key in reference:
            rid = svc.resource_id(*key)
            self.assertNotIn(rid, ids, f"{rid} is shared by two items")
            ids[rid] = key
            self.assertEqual(svc.parse_resource_id(rid), key)

    def test_a_malformed_id_is_refused(self):
        for rid in ("", "question", "question.Q1", "widget.Q1.label",
                    "question.Q1.notafield", "choice.onlyone.label", "choice..x.label"):
            with self.subTest(rid=rid):
                with self.assertRaises(svc.InstrumentTranslationError):
                    svc.parse_resource_id(rid)

    def test_a_name_with_a_dot_is_refused_rather_than_made_ambiguous(self):
        with self.assertRaises(svc.InstrumentTranslationError):
            svc.resource_id("question", "Q.1", "label")


class InstrumentTranslationXliffTests(BaseTestCase):
    """Export and import against a two-question synthetic reference."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

        self.doc = self.tmp / "policy.md"
        self.doc.write_text(POLICY_DOC, encoding="utf-8")

        self.reference = _write_workbook(
            self.tmp / "reference.xlsx",
            [
                {"type": "begin_group", "name": "consent",
                 "label::English (en)": "Consent"},
                {"type": "text", "name": "Q1", "label::English (en)": "First question",
                 "hint::English (en)": "First hint"},
                {"type": "end_group", "name": None, "label::English (en)": None},
                {"type": "select_one yes_no", "name": "Q2",
                 "label::English (en)": "Second question"},
            ],
            [
                {"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"},
                {"list_name": "yes_no", "name": "no", "label::English (en)": "No"},
            ],
        )
        for cache in (svc._reference_items_cached, svc._reference_notes_cached):
            cache.cache_clear()
            self.addCleanup(cache.cache_clear)
        self._patch(svc, "REFERENCE_WORKBOOK", self.reference)
        self._patch(svc, "BASE_INSTRUMENT_CODE", INSTRUMENT)

        self.source = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [
                {"type": "begin_group", "name": "consent",
                 "label::English (en)": "Consent", "label::Hindi (hi)": "सहमति"},
                {"type": "text", "name": "Q1", "label::English (en)": "First question",
                 "label::Hindi (hi)": "पहला प्रश्न",
                 "hint::English (en)": "First hint", "hint::Hindi (hi)": "पहला संकेत"},
                {"type": "end_group", "name": None},
                {"type": "select_one yes_no", "name": "Q2",
                 "label::English (en)": "Second question",
                 "label::Hindi (hi)": "दूसरा प्रश्न"},
            ],
            [
                {"list_name": "yes_no", "name": "yes",
                 "label::English (en)": "Yes", "label::Hindi (hi)": "हाँ"},
                {"list_name": "yes_no", "name": "no", "label::English (en)": "No"},
            ],
        )
        svc.import_translations(
            INSTRUMENT, "hi", self.source, doc_path=self.doc, force=True
        )
        db.session.flush()

    def _patch(self, module, name, value):
        old = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(setattr, module, name, old)

    def _locale(self):
        return db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi"))

    def _row(self, item_kind, item_key, field):
        return db.session.get(
            MapInstrumentTranslations, (INSTRUMENT, "hi", item_kind, item_key, field)
        )

    # -- export -------------------------------------------------------------

    def test_export_is_xliff_2_with_one_unit_per_reference_item(self):
        document = svc.export_xliff(INSTRUMENT, "hi")
        root = ET.fromstring(document)

        self.assertEqual(root.tag, f"{Q}xliff")
        self.assertEqual(root.get("version"), "2.0")
        self.assertEqual(root.get("srcLang"), "en")
        self.assertEqual(root.get("trgLang"), "hi")
        files = root.findall(f"{Q}file")
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].get("id"), INSTRUMENT)

        reference = svc.reference_items(INSTRUMENT)
        units = _units(document)
        self.assertEqual(
            set(units), {svc.resource_id(*key) for key in reference}
        )
        self.assertEqual(len(units), len(reference))
        # Sources are the English reference text, not the translation.
        self.assertEqual(units["question.Q1.label"][1], "First question")
        self.assertEqual(units["choice.yes_no.yes.label"][1], "Yes")

    def test_export_states_and_targets_follow_the_stored_rows(self):
        svc.update_string(
            INSTRUMENT, "hi", item_kind="question", item_key="Q2",
            field="label", text="संशोधित",
        )
        db.session.flush()
        units = _units(svc.export_xliff(INSTRUMENT, "hi"))

        # imported -> translated, with the stored text as the target.
        self.assertEqual(units["question.Q1.label"], ("translated", "First question", "पहला प्रश्न"))
        # edited -> reviewed: an administrator's correction.
        self.assertEqual(units["question.Q2.label"][0], "reviewed")
        self.assertEqual(units["question.Q2.label"][2], "संशोधित")
        # Nothing stored -> initial with an empty target: the form shows English.
        self.assertIsNone(self._row("choice", "yes_no/no", "label"))
        self.assertEqual(units["choice.yes_no.no.label"], ("initial", "No", None))

    def test_export_carries_a_translator_note_naming_the_section_or_list(self):
        root = ET.fromstring(svc.export_xliff(INSTRUMENT, "hi"))
        notes = {
            unit.get("id"): [n.text for n in unit.iterfind(f"{Q}notes/{Q}note")]
            for unit in root.iter(f"{Q}unit")
        }
        self.assertEqual(notes["question.Q1.label"], ["Consent"])
        self.assertEqual(notes["choice.yes_no.yes.label"], ["yes_no"])

    def test_export_escapes_rather_than_concatenating_markup(self):
        svc.update_string(
            INSTRUMENT, "hi", item_kind="question", item_key="Q1",
            field="label", text='<b>"क"</b> & more',
        )
        db.session.flush()
        document = svc.export_xliff(INSTRUMENT, "hi")
        self.assertNotIn("<b>", document)
        self.assertEqual(
            _units(document)["question.Q1.label"][2], '<b>"क"</b> & more'
        )

    def test_the_base_locale_and_an_unknown_locale_are_refused(self):
        for locale in ("en", "zz"):
            with self.subTest(locale=locale):
                with self.assertRaises(svc.InstrumentTranslationError):
                    svc.export_xliff(INSTRUMENT, locale)

    # -- import -------------------------------------------------------------

    def _retarget(self, document, rid, text):
        """Set one unit's target, the way a translator's tool would."""
        root = ET.fromstring(document)
        for unit in root.iter(f"{Q}unit"):
            if unit.get("id") == rid:
                unit.find(f"{Q}segment/{Q}target").text = text
                return ET.tostring(root, encoding="unicode")
        raise AssertionError(f"{rid} is not in the document")

    def test_a_round_trip_writes_one_edited_target_and_bumps_the_version(self):
        before = self._locale().version
        self.assertEqual(self._row("question", "Q1", "label").text, "पहला प्रश्न")

        document = self._retarget(
            svc.export_xliff(INSTRUMENT, "hi"), "question.Q1.label", "नया पहला प्रश्न"
        )
        report = svc.import_xliff(
            INSTRUMENT, "hi", document, mark_as=SOURCE_EDITED
        )
        db.session.flush()

        self.assertEqual(report["units"], len(svc.reference_items(INSTRUMENT)))
        # Every non-empty target is written, because marking the file as
        # `edited` re-stamps the source of rows that came in as `imported`;
        # only the empty ones are left alone.
        self.assertEqual(
            report["written"], report["units"] - report["skipped_empty"], report
        )
        row = self._row("question", "Q1", "label")
        self.assertEqual(row.text, "नया पहला प्रश्न")
        self.assertEqual(row.source, SOURCE_EDITED)
        self.assertEqual(self._locale().version, before + 1)

    def test_a_re_import_of_an_unchanged_export_writes_nothing(self):
        before = self._locale().version
        document = svc.export_xliff(INSTRUMENT, "hi")
        report = svc.import_xliff(INSTRUMENT, "hi", document)
        db.session.flush()

        self.assertEqual(report["written"], 0, report)
        self.assertGreater(report["unchanged"], 0)
        self.assertEqual(
            report["unchanged"] + report["skipped_empty"], report["units"]
        )
        self.assertEqual(self._locale().version, before)

    def test_an_unknown_unit_id_is_skipped_and_reported_never_created(self):
        document = svc.export_xliff(INSTRUMENT, "hi")
        root = ET.fromstring(document)
        file_el = root.find(f"{Q}file")
        unit = ET.SubElement(file_el, f"{Q}unit", {"id": "question.NoSuchQ.label"})
        segment = ET.SubElement(unit, f"{Q}segment", {"state": "translated"})
        ET.SubElement(segment, f"{Q}source").text = "Invented"
        ET.SubElement(segment, f"{Q}target").text = "आविष्कृत"
        ET.SubElement(file_el, f"{Q}unit", {"id": "not-a-resource-id"})

        report = svc.import_xliff(
            INSTRUMENT, "hi",
            ET.tostring(root, encoding="unicode"),
        )
        db.session.flush()

        self.assertEqual(report["skipped_unknown_count"], 2, report)
        self.assertIn("question.NoSuchQ.label", report["skipped_unknown"])
        self.assertIsNone(self._row("question", "NoSuchQ", "label"))

    def test_an_empty_target_leaves_the_stored_text_alone(self):
        # Present first: Q1 has a stored Hindi label to preserve.
        self.assertEqual(self._row("question", "Q1", "label").text, "पहला प्रश्न")
        document = self._retarget(
            svc.export_xliff(INSTRUMENT, "hi"), "question.Q1.label", ""
        )
        report = svc.import_xliff(INSTRUMENT, "hi", document)
        db.session.flush()

        self.assertGreaterEqual(report["skipped_empty"], 1)
        self.assertEqual(self._row("question", "Q1", "label").text, "पहला प्रश्न")

    def test_a_bulk_hand_back_keeps_an_administrators_edit(self):
        svc.update_string(
            INSTRUMENT, "hi", item_kind="question", item_key="Q1",
            field="label", text="व्यवस्थापक का पाठ",
        )
        db.session.flush()
        document = self._retarget(
            svc.export_xliff(INSTRUMENT, "hi"), "question.Q1.label", "मशीन का पाठ"
        )
        report = svc.import_xliff(INSTRUMENT, "hi", document, mark_as=SOURCE_IMPORTED)
        db.session.flush()

        self.assertGreaterEqual(report["kept_edited"], 1)
        self.assertEqual(self._row("question", "Q1", "label").text, "व्यवस्थापक का पाठ")

    def test_an_over_long_target_is_skipped_and_reported_never_truncated(self):
        document = self._retarget(
            svc.export_xliff(INSTRUMENT, "hi"),
            "question.Q1.label",
            "क" * (svc.MAX_TRANSLATION_TEXT_CHARS + 1),
        )
        report = svc.import_xliff(INSTRUMENT, "hi", document)
        db.session.flush()

        self.assertEqual(report["skipped_too_long_count"], 1, report)
        self.assertEqual(self._row("question", "Q1", "label").text, "पहला प्रश्न")

    # -- what an import refuses ---------------------------------------------

    def test_a_doctype_document_is_refused_before_it_is_parsed(self):
        document = svc.export_xliff(INSTRUMENT, "hi")
        bomb = document.replace(
            "<xliff",
            '<!DOCTYPE xliff [<!ENTITY lol "lol">]>\n<xliff',
            1,
        )
        with self.assertRaises(svc.InstrumentTranslationError) as caught:
            svc.import_xliff(INSTRUMENT, "hi", bomb)
        self.assertIn("DOCTYPE", str(caught.exception))

    def test_a_document_for_another_language_is_refused(self):
        document = svc.export_xliff(INSTRUMENT, "hi")
        other = document.replace('trgLang="hi"', 'trgLang="ta"', 1)
        self.assertIn('trgLang="ta"', other, "fixture guard: the language was changed")
        with self.assertRaises(svc.InstrumentTranslationError) as caught:
            svc.import_xliff(INSTRUMENT, "hi", other)
        self.assertIn("target language", str(caught.exception))

    def test_a_wrong_version_namespace_or_source_language_is_refused(self):
        document = svc.export_xliff(INSTRUMENT, "hi")
        for broken, needle in (
            (document.replace('version="2.0"', 'version="1.2"', 1), "2.0"),
            (document.replace(NS, "urn:oasis:names:tc:xliff:document:1.2", 1), "xliff"),
            (document.replace('srcLang="en"', 'srcLang="fr"', 1), "source language"),
            ("<notxliff/>", "xliff"),
            ("not xml at all", "valid XML"),
        ):
            with self.subTest(needle=needle):
                with self.assertRaises(svc.InstrumentTranslationError) as caught:
                    svc.import_xliff(INSTRUMENT, "hi", broken)
                self.assertIn(needle, str(caught.exception))

    def test_an_unknown_mark_as_is_refused(self):
        document = svc.export_xliff(INSTRUMENT, "hi")
        with self.assertRaises(svc.InstrumentTranslationError):
            svc.import_xliff(INSTRUMENT, "hi", document, mark_as="whatever")


class InstrumentTranslationXliffRealWorkbookTests(BaseTestCase):
    """The real Hindi workbook, through import -> export -> re-import.

    The one test that would notice the round trip losing a string, re-writing
    an unchanged one, or producing a document the importer cannot read back.
    """

    REAL = "WHO_2022_VA"

    def test_the_real_hindi_round_trip_changes_nothing(self):
        report = svc.import_translations(
            self.REAL, "hi", svc.WORKBOOK_DIR / svc.documented_sources()["hi"].workbook
        )
        db.session.flush()
        self.assertGreater(report.written, 400, "fixture guard: Hindi was imported")
        version = db.session.get(MasInstrumentLocales, (self.REAL, "hi")).version

        document = svc.export_xliff(self.REAL, "hi")
        again = svc.import_xliff(self.REAL, "hi", document)
        db.session.flush()

        reference = svc.reference_items(self.REAL)
        self.assertEqual(again["units"], len(reference))
        self.assertEqual(again["written"], 0, again)
        self.assertEqual(again["skipped_unknown_count"], 0, again)
        self.assertGreater(again["unchanged"], 400)
        # Every unit is either an unchanged stored string or an untranslated
        # item the form falls back to English for. Nothing else.
        self.assertEqual(
            again["unchanged"] + again["skipped_empty"], again["units"], again
        )
        self.assertEqual(
            db.session.get(MasInstrumentLocales, (self.REAL, "hi")).version, version
        )


class InstrumentTranslationEnglishFallbackTests(BaseTestCase):
    """The serving JSON omits what is not translated; it never sends "".

    "Absent means fall back to English" is the whole contract the browser form
    relies on (docs/policy/va-web-form-options.md, "Adding a language"): the
    bundle's ``localeCandidates`` resolves locale, base language, ``en``, so an
    item that is absent from the map is rendered in English. An empty string
    would be a *present* value and would blank the question.
    """

    REAL = "WHO_2022_VA"

    def setUp(self):
        super().setUp()
        row = db.session.get(MasInstrumentLocales, (self.REAL, "hi"))
        if row is None:
            row = MasInstrumentLocales(
                instrument_code=self.REAL, locale_code="hi", language_name="Hindi",
                version=3, is_active=True, updated_at=datetime.now(UTC),
            )
            db.session.add(row)
            db.session.flush()
        self.translated, self.untranslated = sorted(
            key[1] for key in svc.reference_label_keys(self.REAL)
        )[:2]
        db.session.add(
            MapInstrumentTranslations(
                instrument_code=self.REAL, locale_code="hi", item_kind="question",
                item_key=self.translated, field="label", text="पहला प्रश्न",
                source=SOURCE_IMPORTED, updated_at=datetime.now(UTC),
            )
        )
        db.session.flush()

    def test_an_untranslated_item_is_absent_from_the_payload_not_empty(self):
        payload = svc.export_translations(self.REAL, "hi")
        # Present first: the translated item is there with its text.
        self.assertEqual(payload["questions"][self.translated]["label"], "पहला प्रश्न")
        # The untranslated one is absent entirely -- not "" and not null.
        self.assertNotIn(self.untranslated, payload["questions"])
        for entry in payload["questions"].values():
            for field, text in entry.items():
                self.assertTrue(text, f"{field} was served as an empty string")

    def test_the_base_locale_carries_no_strings_at_all(self):
        payload = svc.export_translations(self.REAL, "en")
        self.assertEqual(payload["questions"], {})
        self.assertEqual(payload["choices"], {})
        self.assertEqual(payload["version"], 0)
