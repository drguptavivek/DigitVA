"""Importing a language from a documented source workbook.

WP6 of docs/planning/web-capture-project-configuration-plan.md, extended by
digitva-thr.4 (WP2) for the DigitVA layer questions. The rules this holds the
importer to, all of them from
docs/policy/va-form-project-configuration.md ("Translation sources" and
"The reference also carries the DigitVA layers"):

* a workbook supplies text, never structure;
* one documented source workbook per language, and the doc is the rule;
* an administrator's edit outranks a re-import;
* the reference is the WHO base workbook plus the DigitVA layer entries, and a
  layer item may never silently overwrite a WHO base one;
* activation is an explicit administrative action, independent of coverage
  (coverage is computed and reported, never a gate).

Small synthetic workbooks are used throughout; exactly one test reads the nine
committed workbooks, and it is the one that would notice a re-downloaded file
silently dropping a language.
"""
import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from app import db
from app.models.mas_instrument_locales import (
    MapInstrumentTranslations,
    MasInstrumentLocales,
)
from app.services import instrument_translation_service as svc
from tests.base import BaseTestCase

INSTRUMENT = "TEST_VA"

#: A "Translation sources" policy doc the importer parses, so these tests do
#: not depend on the real table's contents.
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


def _write_layer_reference(path, entries=()):
    """A ``digitva-layers.reference.json`` fixture, empty by default.

    Matches the schema ``tooling/who-va-2022/build-layer-reference.mjs``
    produces: ``entries[]`` with ``itemKind``, ``itemKey``, ``field``, ``text``
    and ``extensions`` (a non-empty array).
    """
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 2,
                "source": {"package": "@drguptavivek/who-2022-va"},
                "extensionCounts": {},
                "entries": list(entries),
            }
        ),
        encoding="utf-8",
    )
    return path


class InstrumentTranslationImportTests(BaseTestCase):
    """A two-question reference and the workbooks that feed it."""

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
                {"type": "text", "name": "Q1", "label::English (en)": "First question",
                 "hint::English (en)": "First hint"},
                {"type": "select_one yes_no", "name": "Q2",
                 "label::English (en)": "Second question"},
            ],
            [
                {"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"},
                {"list_name": "yes_no", "name": "no", "label::English (en)": "No"},
            ],
        )
        # No layers by default -- most of these tests are about the workbook
        # importer and must not see the real, committed layer artifact.
        self.layers = _write_layer_reference(self.tmp / "layers.json")
        self._clear_reference_caches()
        self.addCleanup(self._clear_reference_caches)
        self._patch(svc, "REFERENCE_WORKBOOK", self.reference)
        self._patch(svc, "LAYER_REFERENCE_PATH", self.layers)
        self._patch(svc, "BASE_INSTRUMENT_CODE", INSTRUMENT)

    def _clear_reference_caches(self):
        # The reference is cached per path and the fixture path changes per
        # test, but clear it anyway so a stale entry can never leak across.
        svc._reference_items_cached.cache_clear()
        svc._reference_extensions_cached.cache_clear()
        svc._layer_entries_cached.cache_clear()

    def _patch(self, module, name, value):
        old = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(setattr, module, name, old)

    def _import(self, path, **kwargs):
        kwargs.setdefault("doc_path", self.doc)
        return svc.import_translations(INSTRUMENT, "hi", path, **kwargs)

    def _rows(self):
        return {
            (r.item_kind, r.item_key, r.field): r
            for r in db.session.scalars(
                db.select(MapInstrumentTranslations).where(
                    MapInstrumentTranslations.instrument_code == INSTRUMENT
                )
            )
        }

    # -- what an import writes, and what it reports -------------------------

    def test_one_translated_label_is_stored_and_the_gap_is_reported(self):
        workbook = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [
                {"type": "text", "name": "Q1", "label::English (en)": "First question",
                 "label::Hindi (hi)": "पहला प्रश्न"},
                {"type": "select_one yes_no", "name": "Q2",
                 "label::English (en)": "Second question"},
            ],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        report = self._import(workbook)
        db.session.flush()

        # Present first: the one translation really landed.
        rows = self._rows()
        self.assertIn(("question", "Q1", "label"), rows)
        self.assertEqual(rows[("question", "Q1", "label")].text, "पहला प्रश्न")
        self.assertEqual(rows[("question", "Q1", "label")].source, "imported")

        # Then the gap the report must name.
        self.assertNotIn(("question", "Q2", "label"), rows)
        self.assertIn("question:Q2:label", report.missing_from_workbook)
        self.assertEqual(report.reference_labels, 2)
        self.assertEqual(report.translated_labels, 1)
        self.assertAlmostEqual(report.coverage, 0.5)

    def test_a_cell_packing_english_and_the_target_language_is_split(self):
        workbook = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [
                {"type": "text", "name": "Q1", "label::English (en)": "First question",
                 "label::Hindi (hi)": "First question\nपहला प्रश्न"},
                {"type": "select_one yes_no", "name": "Q2",
                 "label::English (en)": "Second question",
                 "label::Hindi (hi)": "दूसरा प्रश्न\nSecond question"},
            ],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        self._import(workbook)
        db.session.flush()
        rows = self._rows()
        self.assertEqual(rows[("question", "Q1", "label")].text, "पहला प्रश्न")
        self.assertEqual(rows[("question", "Q2", "label")].text, "दूसरा प्रश्न")

    def test_a_half_that_is_not_the_reference_english_is_kept_whole(self):
        """Only an exact English half is dropped; anything else is a translation."""
        workbook = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [{"type": "text", "name": "Q1", "label::English (en)": "First question",
              "label::Hindi (hi)": "Some other line\nपहला प्रश्न"}],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        self._import(workbook)
        db.session.flush()
        self.assertEqual(
            self._rows()[("question", "Q1", "label")].text,
            "Some other line\nपहला प्रश्न",
        )

    def _extend_reference(self, extra_choices=(), extra_survey=()):
        """Rebuild the reference workbook with extra items for one test.

        The default reference from ``setUp`` only carries ``yes_no``; a few
        packed-cell conventions are documented against real choice lists
        (``sa_tu``, ``language``) that need their own reference rows.
        """
        self.reference = _write_workbook(
            self.tmp / "reference.xlsx",
            [
                {"type": "text", "name": "Q1", "label::English (en)": "First question",
                 "hint::English (en)": "First hint"},
                {"type": "select_one yes_no", "name": "Q2",
                 "label::English (en)": "Second question"},
                *extra_survey,
            ],
            [
                {"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"},
                {"list_name": "yes_no", "name": "no", "label::English (en)": "No"},
                *extra_choices,
            ],
        )
        self._clear_reference_caches()
        self._patch(svc, "REFERENCE_WORKBOOK", self.reference)

    def test_a_slash_separated_cell_is_split(self):
        """Regression: ``sa_tu/minutes`` packed 'Minutes / मिनट' in one cell."""
        self._extend_reference(
            extra_choices=[{"list_name": "sa_tu", "name": "minutes",
                             "label::English (en)": "Minutes"}]
        )
        workbook = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [{"type": "text", "name": "Q1", "label::English (en)": "First question",
              "label::Hindi (hi)": "पहला प्रश्न"}],
            [
                {"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"},
                {"list_name": "sa_tu", "name": "minutes", "label::English (en)": "Minutes",
                 "label::Hindi (hi)": "Minutes / मिनट"},
            ],
        )
        self._import(workbook)
        db.session.flush()
        self.assertEqual(self._rows()[("choice", "sa_tu/minutes", "label")].text, "मिनट")

    def test_a_parenthetical_cell_is_split(self):
        """Regression: ``language/hindi`` packed 'Hindi (हिन्दी)' in one cell."""
        self._extend_reference(
            extra_choices=[{"list_name": "language", "name": "hindi",
                             "label::English (en)": "Hindi"}]
        )
        workbook = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [{"type": "text", "name": "Q1", "label::English (en)": "First question",
              "label::Hindi (hi)": "पहला प्रश्न"}],
            [
                {"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"},
                {"list_name": "language", "name": "hindi", "label::English (en)": "Hindi",
                 "label::Hindi (hi)": "Hindi (हिन्दी)"},
            ],
        )
        self._import(workbook)
        db.session.flush()
        self.assertEqual(self._rows()[("choice", "language/hindi", "label")].text, "हिन्दी")

    def test_a_slash_separated_cell_whose_english_half_does_not_match_is_kept_whole(self):
        """Fail-closed: a near-miss (not an exact match) is never split."""
        self._extend_reference(
            extra_choices=[{"list_name": "sa_tu", "name": "minutes",
                             "label::English (en)": "Minutes"}]
        )
        workbook = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [{"type": "text", "name": "Q1", "label::English (en)": "First question",
              "label::Hindi (hi)": "पहला प्रश्न"}],
            [
                {"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"},
                {"list_name": "sa_tu", "name": "minutes", "label::English (en)": "Minutes",
                 "label::Hindi (hi)": "Some Other Word / मिनट"},
            ],
        )
        self._import(workbook)
        db.session.flush()
        self.assertEqual(
            self._rows()[("choice", "sa_tu/minutes", "label")].text,
            "Some Other Word / मिनट",
        )

    def test_an_item_equal_to_english_after_splitting_is_untranslated(self):
        """Regression: a social-autopsy group label ND01 leaves untranslated.

        The cell is not packed at all -- both columns just carry the English
        text verbatim. It must not count as a translation, or coverage lies.
        """
        workbook = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [
                {"type": "text", "name": "Q1", "label::English (en)": "First question",
                 "label::Hindi (hi)": "पहला प्रश्न"},
                {"type": "text", "name": "socialautopsy",
                 "label::English (en)": "Social Autopsy Questionnaire",
                 "label::Hindi (hi)": "Social Autopsy Questionnaire"},
            ],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        self._extend_reference(
            extra_survey=[{"type": "text", "name": "socialautopsy",
                            "label::English (en)": "Social Autopsy Questionnaire"}]
        )
        report = self._import(workbook)
        db.session.flush()
        self.assertNotIn(("question", "socialautopsy", "label"), self._rows())
        self.assertIn("question:socialautopsy:label", report.missing_from_workbook)

    def test_a_parenthetical_that_reduces_to_english_is_untranslated(self):
        """'English (English)' unpacks to plain English -- still untranslated."""
        self._extend_reference(
            extra_choices=[{"list_name": "language", "name": "english",
                            "label::English (en)": "English"}]
        )
        workbook = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [{"type": "text", "name": "Q1", "label::English (en)": "First question",
              "label::Hindi (hi)": "पहला प्रश्न"}],
            [
                {"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"},
                {"list_name": "language", "name": "english", "label::English (en)": "English",
                 "label::Hindi (hi)": "English (English)"},
            ],
        )
        self._import(workbook)
        db.session.flush()
        self.assertNotIn(("choice", "language/english", "label"), self._rows())

    def test_an_interleaved_cell_cannot_be_split_and_is_untranslated(self):
        """Regression: sa05's hint alternates English and '*'-prefixed Hindi
        lines bullet by bullet -- there is no single boundary to cut at, so
        it is not stored as a mixed English/Hindi blob.
        """
        self._extend_reference(
            extra_survey=[{
                "type": "text", "name": "sa05",
                "label::English (en)": "Type of consultation",
                "hint::English (en)": (
                    "Note:\nSmall Hospital(small nursing homes & clinics; <30 beds)\n"
                    "Large Hospital(corporate hospitals; ≥ 200 beds)"
                ),
            }]
        )
        workbook = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [
                {"type": "text", "name": "Q1", "label::English (en)": "First question",
                 "label::Hindi (hi)": "पहला प्रश्न"},
                {"type": "text", "name": "sa05",
                 "label::English (en)": "Type of consultation",
                 "label::Hindi (hi)": "परामर्श का प्रकार",
                 "hint::English (en)": (
                     "Note:\nSmall Hospital(small nursing homes & clinics; <30 beds)\n"
                     "Large Hospital(corporate hospitals; ≥ 200 beds)"
                 ),
                 "hint::Hindi (hi)": (
                     "Note:\nSmall Hospital(small nursing homes & clinics; <30 beds)\n"
                     "*छोटा अस्पताल\n"
                     "Large Hospital(corporate hospitals; ≥ 200 beds)\n"
                     "*बड़ा अस्पताल"
                 )},
            ],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        self._import(workbook)
        db.session.flush()
        rows = self._rows()
        self.assertEqual(rows[("question", "sa05", "label")].text, "परामर्श का प्रकार")
        self.assertNotIn(("question", "sa05", "hint"), rows)

    def test_a_workbook_cannot_add_a_question(self):
        workbook = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [
                {"type": "text", "name": "Q1", "label::English (en)": "First question",
                 "label::Hindi (hi)": "पहला प्रश्न"},
                {"type": "text", "name": "Q99", "label::English (en)": "Extra question",
                 "label::Hindi (hi)": "अतिरिक्त"},
            ],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        report = self._import(workbook)
        db.session.flush()
        rows = self._rows()

        # Present first: the item the reference *does* have was written.
        self.assertIn(("question", "Q1", "label"), rows)
        # The invented one was reported and discarded.
        self.assertNotIn(("question", "Q99", "label"), rows)
        self.assertIn("question:Q99:label", report.unknown_in_workbook)

    def test_choices_and_hints_are_imported_by_their_own_keys(self):
        workbook = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [{"type": "text", "name": "Q1", "label::English (en)": "First question",
              "label::Hindi (hi)": "पहला प्रश्न",
              "hint::English (en)": "First hint", "hint::Hindi (hi)": "पहला संकेत"}],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes",
              "label::Hindi (hi)": "हाँ"}],
        )
        self._import(workbook)
        db.session.flush()
        rows = self._rows()
        self.assertEqual(rows[("question", "Q1", "hint")].text, "पहला संकेत")
        self.assertEqual(rows[("choice", "yes_no/yes", "label")].text, "हाँ")

    # -- re-import ----------------------------------------------------------

    def _full_workbook(self, q1="पहला प्रश्न"):
        return _write_workbook(
            self.tmp / "source_hi.xlsx",
            [
                {"type": "text", "name": "Q1", "label::English (en)": "First question",
                 "label::Hindi (hi)": q1},
                {"type": "select_one yes_no", "name": "Q2",
                 "label::English (en)": "Second question",
                 "label::Hindi (hi)": "दूसरा प्रश्न"},
            ],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes",
              "label::Hindi (hi)": "हाँ"}],
        )

    def test_reimport_overwrites_imported_rows_and_keeps_edited_ones(self):
        self._import(self._full_workbook())
        db.session.flush()
        svc.update_string(
            INSTRUMENT, "hi", item_kind="question", item_key="Q2", field="label",
            text="सुधारा हुआ",
        )
        db.session.flush()
        rows = self._rows()
        self.assertEqual(rows[("question", "Q2", "label")].source, "edited")

        report = self._import(self._full_workbook(q1="नया पहला प्रश्न"))
        db.session.flush()
        rows = self._rows()
        self.assertEqual(rows[("question", "Q1", "label")].text, "नया पहला प्रश्न")
        self.assertEqual(rows[("question", "Q2", "label")].text, "सुधारा हुआ")
        self.assertEqual(report.kept_edited, 1)

    def test_every_import_bumps_the_locale_version(self):
        self._import(self._full_workbook())
        db.session.flush()
        first = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).version
        self._import(self._full_workbook())
        db.session.flush()
        second = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).version
        self.assertGreater(second, first)

    # -- activation is explicit, never gated on coverage ---------------------
    #
    # Decided 2026-09-19: English fallback is per-string, so a coverage
    # percentage is never a serving decision. Coverage stays computed and
    # reported; it just decides nothing.

    def test_a_full_import_does_not_activate_the_locale(self):
        report = self._import(self._full_workbook())
        db.session.flush()
        self.assertEqual(report.coverage, 1.0)
        # Present first: the row exists (the import created it)...
        row = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi"))
        self.assertIsNotNone(row)
        # ...but is not active: an import never activates, however complete.
        self.assertFalse(row.is_active)

    def test_a_partial_import_still_reports_its_coverage(self):
        half = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [
                {"type": "text", "name": "Q1", "label::English (en)": "First question",
                 "label::Hindi (hi)": "पहला प्रश्न"},
                {"type": "select_one yes_no", "name": "Q2",
                 "label::English (en)": "Second question"},
            ],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        report = self._import(half)
        db.session.flush()
        # Present first: the partial coverage is reported accurately.
        self.assertAlmostEqual(report.coverage, 0.5)
        # An import never activates or refuses to activate; that decision
        # belongs to set_locale_active alone.
        self.assertFalse(db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).is_active)

    def test_set_locale_active_activates_regardless_of_coverage(self):
        half = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [
                {"type": "text", "name": "Q1", "label::English (en)": "First question",
                 "label::Hindi (hi)": "पहला प्रश्न"},
                {"type": "select_one yes_no", "name": "Q2",
                 "label::English (en)": "Second question"},
            ],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        self._import(half)
        db.session.flush()
        # Present first: coverage really is partial (the fixture guard).
        status = {row["locale_code"]: row for row in svc.locale_status(INSTRUMENT)}
        self.assertLess(status["hi"]["coverage"], 1.0)

        result = svc.set_locale_active(INSTRUMENT, "hi", True)
        self.assertTrue(result["is_active"])
        self.assertLess(result["coverage"], 1.0)
        self.assertTrue(db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).is_active)

    def test_import_translations_and_set_locale_active_take_no_force_argument(self):
        """The gate is gone, and so is the flag that only ever bypassed it."""
        with self.assertRaises(TypeError):
            self._import(self._full_workbook(), force=True)
        with self.assertRaises(TypeError):
            svc.set_locale_active(INSTRUMENT, "hi", True, force=True)

    # -- the documented-source rule -----------------------------------------

    def test_an_undocumented_workbook_is_refused(self):
        other = _write_workbook(
            self.tmp / "not_the_source.xlsx",
            [{"type": "text", "name": "Q1", "label::English (en)": "First question",
              "label::Hindi (hi)": "पहला प्रश्न"}],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        with self.assertRaises(svc.InstrumentTranslationError) as ctx:
            self._import(other)
        self.assertIn("source_hi.xlsx", str(ctx.exception))
        self.assertEqual(self._rows(), {})

    def test_cross_check_reads_an_undocumented_workbook_and_writes_nothing(self):
        other = _write_workbook(
            self.tmp / "not_the_source.xlsx",
            [{"type": "text", "name": "Q1", "label::English (en)": "First question",
              "label::Hindi (hi)": "पहला प्रश्न"}],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        report = self._import(other, cross_check=True)
        db.session.flush()
        self.assertTrue(report.cross_check)
        self.assertEqual(report.translated_labels, 1)
        self.assertEqual(self._rows(), {})
        self.assertIsNone(db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")))

    def test_an_undocumented_locale_is_refused(self):
        with self.assertRaises(svc.InstrumentTranslationError) as ctx:
            svc.import_translations(
                INSTRUMENT, "zz", self._full_workbook(), doc_path=self.doc
            )
        self.assertIn("Translation sources", str(ctx.exception))

    def test_the_base_locale_is_never_imported(self):
        with self.assertRaises(svc.InstrumentTranslationError):
            svc.import_translations(
                INSTRUMENT, "en", self._full_workbook(), doc_path=self.doc
            )

    # -- editing ------------------------------------------------------------

    def test_an_edit_refuses_an_item_the_reference_lacks(self):
        self._import(self._full_workbook())
        db.session.flush()
        with self.assertRaises(svc.InstrumentTranslationError):
            svc.update_string(
                INSTRUMENT, "hi", item_kind="question", item_key="Q99",
                field="label", text="कुछ",
            )

    def test_an_edit_bumps_the_version_and_reports_the_old_text(self):
        self._import(self._full_workbook())
        db.session.flush()
        before = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).version
        result = svc.update_string(
            INSTRUMENT, "hi", item_kind="question", item_key="Q1",
            field="label", text="बदला हुआ",
        )
        self.assertEqual(result["old_text"], "पहला प्रश्न")
        self.assertEqual(result["text"], "बदला हुआ")
        self.assertEqual(result["version"], before + 1)

    # -- serving shape ------------------------------------------------------

    def test_export_groups_questions_and_choices(self):
        self._import(self._full_workbook())
        db.session.flush()
        payload = svc.export_translations(INSTRUMENT, "hi")
        self.assertEqual(payload["questions"]["Q1"]["label"], "पहला प्रश्न")
        self.assertEqual(payload["choices"]["yes_no/yes"]["label"], "हाँ")
        self.assertGreaterEqual(payload["version"], 1)

    def test_active_locale_versions_always_carries_the_base_locale(self):
        versions = svc.active_locale_versions(INSTRUMENT)
        self.assertEqual(versions, {"en": 0})

        # An import alone never activates a locale, so it still does not
        # appear here...
        self._import(self._full_workbook())
        db.session.flush()
        versions = svc.active_locale_versions(INSTRUMENT)
        self.assertIn("en", versions)
        self.assertNotIn("hi", versions)

        # ...only the explicit activation adds it.
        svc.set_locale_active(INSTRUMENT, "hi", True)
        db.session.flush()
        versions = svc.active_locale_versions(INSTRUMENT)
        self.assertIn("hi", versions)


class LayerReferenceMergeTests(BaseTestCase):
    """The reference is the WHO base workbook plus the DigitVA layer entries.

    docs/policy/va-form-project-configuration.md ("The reference also carries
    the DigitVA layers").
    """

    INSTRUMENT = "LAYER_VA"

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

        self.reference = _write_workbook(
            self.tmp / "reference.xlsx",
            [{"type": "text", "name": "Q1", "label::English (en)": "First question"}],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        self.layers = _write_layer_reference(
            self.tmp / "layers.json",
            entries=[
                {"itemKind": "question", "itemKey": "consent_mode", "field": "label",
                 "text": "Mode in which consent was taken", "extensions": ["digitva_core"]},
                {"itemKind": "choice", "itemKey": "CONSENT_MODE/in_person", "field": "label",
                 "text": "In person", "extensions": ["digitva_core"]},
                {"itemKind": "question", "itemKey": "md_available", "field": "label",
                 "text": "Medical records available?", "extensions": ["medical_records"]},
            ],
        )
        self._clear_reference_caches()
        self.addCleanup(self._clear_reference_caches)
        self._patch(svc, "REFERENCE_WORKBOOK", self.reference)
        self._patch(svc, "LAYER_REFERENCE_PATH", self.layers)
        self._patch(svc, "BASE_INSTRUMENT_CODE", self.INSTRUMENT)

    def _clear_reference_caches(self):
        svc._reference_items_cached.cache_clear()
        svc._reference_extensions_cached.cache_clear()
        svc._layer_entries_cached.cache_clear()
        svc._layer_notes_cached.cache_clear()

    def _patch(self, module, name, value):
        old = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(setattr, module, name, old)

    def test_a_layer_question_and_a_who_base_question_both_appear(self):
        reference = svc.reference_items(self.INSTRUMENT)
        # Present first: the WHO base item is still there.
        self.assertIn(("question", "Q1", "label"), reference)
        # And the layer item is now there too, with its own English text.
        self.assertIn(("question", "consent_mode", "label"), reference)
        self.assertEqual(
            reference[("question", "consent_mode", "label")],
            "Mode in which consent was taken",
        )
        self.assertIn(("choice", "CONSENT_MODE/in_person", "label"), reference)

    def test_base_label_keys_exclude_layer_labels(self):
        """Base coverage keeps its original meaning as layers are added."""
        label_keys = svc.reference_label_keys(self.INSTRUMENT)
        self.assertIn(("question", "Q1", "label"), label_keys)
        self.assertNotIn(("question", "consent_mode", "label"), label_keys)
        self.assertNotIn(("question", "md_available", "label"), label_keys)

    def test_reference_item_extensions_maps_layer_and_base_items(self):
        extensions = svc.reference_item_extensions(self.INSTRUMENT)
        self.assertEqual(
            extensions[("question", "consent_mode", "label")], frozenset({"digitva_core"})
        )
        # A WHO base item belongs to no extension.
        self.assertEqual(extensions[("question", "Q1", "label")], frozenset())

    def test_extension_label_keys_groups_labels_by_extension(self):
        by_extension = svc.extension_label_keys(self.INSTRUMENT)
        self.assertIn(("question", "consent_mode", "label"), by_extension["digitva_core"])
        self.assertIn(("question", "md_available", "label"), by_extension["medical_records"])
        # A WHO base label is not counted under any extension.
        self.assertNotIn(("question", "Q1", "label"), by_extension.get("digitva_core", set()))

    def test_a_colliding_layer_entry_raises(self):
        """A layer item must never silently overwrite a WHO base item."""
        colliding = _write_layer_reference(
            self.tmp / "colliding.json",
            entries=[
                {"itemKind": "question", "itemKey": "Q1", "field": "label",
                 "text": "Collides with the WHO base item", "extensions": ["digitva_core"]},
            ],
        )
        self._patch(svc, "LAYER_REFERENCE_PATH", colliding)
        self._clear_reference_caches()
        with self.assertRaises(svc.InstrumentTranslationError) as ctx:
            svc.reference_items(self.INSTRUMENT)
        self.assertIn("Q1", str(ctx.exception))

    def test_layer_items_round_trip_through_resource_id(self):
        reference = svc.reference_items(self.INSTRUMENT)
        layer_keys = {
            key for key, extensions in svc.reference_item_extensions(self.INSTRUMENT).items()
            if extensions
        }
        self.assertTrue(layer_keys, "fixture guard: layer items loaded")
        for key in layer_keys:
            with self.subTest(key=key):
                rid = svc.resource_id(*key)
                self.assertEqual(svc.parse_resource_id(rid), key)
        self.assertGreater(len(reference), len(layer_keys), "fixture guard: base items too")

    def test_reference_notes_name_the_extension_for_a_layer_item(self):
        notes = svc.reference_notes(self.INSTRUMENT)
        self.assertEqual(notes[("question", "consent_mode")], "digitva_core")
        self.assertEqual(notes[("choice", "CONSENT_MODE/in_person")], "digitva_core")

    def test_a_layer_item_is_translated_like_any_other(self):
        doc = self.tmp / "policy.md"
        doc.write_text(POLICY_DOC, encoding="utf-8")
        workbook = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [
                {"type": "text", "name": "Q1", "label::English (en)": "First question",
                 "label::Hindi (hi)": "पहला प्रश्न"},
                {"type": "text", "name": "consent_mode",
                 "label::English (en)": "Mode in which consent was taken",
                 "label::Hindi (hi)": "सहमति का तरीका"},
            ],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        report = svc.import_translations(self.INSTRUMENT, "hi", workbook, doc_path=doc)
        db.session.flush()
        rows = {
            (r.item_kind, r.item_key, r.field): r
            for r in db.session.scalars(
                db.select(MapInstrumentTranslations).where(
                    MapInstrumentTranslations.instrument_code == self.INSTRUMENT
                )
            )
        }
        # Present first: the layer item's translation really landed...
        self.assertIn(("question", "consent_mode", "label"), rows)
        self.assertEqual(rows[("question", "consent_mode", "label")].text, "सहमति का तरीका")
        # ...and it is not double-counted into base coverage (base is 1/1: Q1
        # only), even though a layer item was also written.
        self.assertEqual(report.reference_labels, 1)
        self.assertEqual(report.translated_labels, 1)
        self.assertEqual(
            report.extension_coverage["digitva_core"], {"translated": 1, "total": 1}
        )


class DocumentedSourceTableTests(unittest.TestCase):
    """The shipped policy table is the rule the importer reads."""

    def test_a_later_table_in_the_section_is_not_read_as_sources(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "policy.md"
            path.write_text(
                "## Translation sources\n\n"
                "| Language | Locale | Source workbook | Project | ODK form id | Download date | Assigned by |\n"
                "| --- | --- | --- | --- | --- | --- | --- |\n"
                "| Hindi | hi | ND01.xlsx | ND01 | ND01 | 2026-09-19 | owner |\n\n"
                "Prose between tables.\n\n"
                "| Layer | Structure |\n| --- | --- |\n| intake_screen | begin_screen |\n",
                encoding="utf-8",
            )
            sources = svc.documented_sources(path)
        self.assertIn("hi", sources)
        self.assertEqual(set(sources), {"hi"})

    def test_the_policy_doc_documents_every_committed_language(self):
        sources = svc.documented_sources()
        self.assertEqual(
            set(sources),
            {"hi", "ta", "kn", "mr", "ml", "kha", "or", "bn",
             "fr", "pt", "ar", "sw", "es"},
        )
        for locale, source in sources.items():
            with self.subTest(locale=locale):
                self.assertTrue((svc.WORKBOOK_DIR / source.workbook).exists())
                self.assertTrue(source.project)
                self.assertTrue(source.odk_form_id)
                self.assertTrue(source.download_date)
                self.assertTrue(source.assigned_by)

    def test_each_language_has_exactly_one_source(self):
        """One source per language: the dict key enforces it, the count proves it."""
        sources = svc.documented_sources()
        workbooks = [s.workbook for s in sources.values()]
        self.assertEqual(len(sources), len(workbooks))


class RealWorkbookCoverageTests(unittest.TestCase):
    """Slow: reads the nine committed workbooks.

    This is the check that would notice a re-downloaded source workbook
    silently dropping a language. It writes nothing -- every locale is read
    with ``cross_check``, so it needs no database. Coverage is no longer a
    serving gate, but a deployed language is still expected to be
    near-complete; this test still holds that quality bar, it just is not the
    mechanism that decides whether the language may be served.
    """

    #: The quality bar a documented, deployed language is expected to clear.
    #: Not read by the service any more (there is no gate) -- this test's own
    #: expectation of what "near-complete" means.
    EXPECTED_COVERAGE = 0.95

    #: The eight deployed Indian-language forms plus the five languages of
    #: the WHO multilingual V2.0 form, all fully translated as downloaded on
    #: 2026-09-19.
    COVERED = ("hi", "ta", "kn", "mr", "ml", "kha", "or", "bn", "fr", "pt", "ar", "sw", "es")

    def test_every_deployed_language_reaches_the_threshold(self):
        sources = svc.documented_sources()
        for locale in self.COVERED:
            with self.subTest(locale=locale):
                report = svc.import_translations(
                    "WHO_2022_VA", locale,
                    svc.WORKBOOK_DIR / sources[locale].workbook,
                    cross_check=True,
                )
                self.assertGreater(report.reference_labels, 400)
                self.assertGreaterEqual(
                    report.coverage,
                    self.EXPECTED_COVERAGE,
                    f"{locale} covers only {report.coverage:.1%} of the "
                    "reference's survey labels",
                )

    def test_the_reference_form_alone_cannot_source_french(self):
        """Why French is sourced from the WHO multilingual form, not the reference.

        The curated V1.1 reference carries French on its *choices* sheet
        only, so it reaches 0% of survey labels. Pinned so the source choice
        in the policy table stays explained; the documented source is
        exercised by the coverage test above.
        """
        report = svc.import_translations(
            "WHO_2022_VA", "fr",
            svc.WORKBOOK_DIR / "whova2022_xls_form_for_odk.xlsx",
            cross_check=True,
        )
        self.assertEqual(report.translated_labels, 0)
        self.assertLess(report.coverage, self.EXPECTED_COVERAGE)
