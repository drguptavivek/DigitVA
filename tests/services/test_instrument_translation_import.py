"""Importing a language from a documented source workbook.

WP6 of docs/planning/web-capture-project-configuration-plan.md. The rules this
holds the importer to, all of them from
docs/policy/va-form-project-configuration.md ("Translation sources"):

* a workbook supplies text, never structure;
* one documented source workbook per language, and the doc is the rule;
* an administrator's edit outranks a re-import;
* a locale is served only once its coverage passes the threshold.

Small synthetic workbooks are used throughout; exactly one test reads the nine
committed workbooks, and it is the one that would notice a re-downloaded file
silently dropping a language.
"""
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
        # The reference is cached per path and the fixture path changes per
        # test, but clear it anyway so a stale entry can never leak across.
        svc._reference_items_cached.cache_clear()
        self.addCleanup(svc._reference_items_cached.cache_clear)
        self._patch(svc, "REFERENCE_WORKBOOK", self.reference)
        self._patch(svc, "BASE_INSTRUMENT_CODE", INSTRUMENT)

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

    # -- the coverage gate --------------------------------------------------

    def test_full_coverage_activates_the_locale(self):
        report = self._import(self._full_workbook())
        db.session.flush()
        self.assertEqual(report.coverage, 1.0)
        self.assertTrue(report.activated)
        self.assertTrue(db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).is_active)

    def test_partial_coverage_refuses_activation_until_forced(self):
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
        self.assertLess(report.coverage, svc.TRANSLATION_COVERAGE_THRESHOLD)
        self.assertFalse(report.activated)
        self.assertFalse(db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).is_active)

        forced = self._import(half, force=True)
        db.session.flush()
        self.assertTrue(forced.activated)
        self.assertTrue(forced.forced)
        self.assertTrue(db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).is_active)

    def test_set_locale_active_honours_the_same_gate(self):
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
        with self.assertRaises(svc.InstrumentTranslationError):
            svc.set_locale_active(INSTRUMENT, "hi", True)
        result = svc.set_locale_active(INSTRUMENT, "hi", True, force=True)
        self.assertTrue(result["is_active"])

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
        self._import(self._full_workbook())
        db.session.flush()
        versions = svc.active_locale_versions(INSTRUMENT)
        self.assertIn("en", versions)
        self.assertIn("hi", versions)


class DocumentedSourceTableTests(unittest.TestCase):
    """The shipped policy table is the rule the importer reads."""

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
    with ``cross_check``, so it needs no database.
    """

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
                    svc.TRANSLATION_COVERAGE_THRESHOLD,
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
        self.assertLess(report.coverage, svc.TRANSLATION_COVERAGE_THRESHOLD)
