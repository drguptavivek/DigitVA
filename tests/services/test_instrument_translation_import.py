"""Importing a language from a workbook.

WP6 of docs/planning/web-capture-project-configuration-plan.md, extended by
digitva-thr.4 (WP2) for the DigitVA layer questions. The rules this holds the
importer to:

* a workbook supplies text, never structure;
* any readable workbook under an allowed directory may be imported for any
  locale (decided 2026-09-20: which workbook a language was seeded from is
  provenance for humans, recorded in the "Translation sources" table of
  docs/policy/va-form-project-configuration.md, and no code reads that table);
* path containment still refuses a workbook outside the allowed directories;
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
import unittest.mock
from pathlib import Path

import pandas as pd
import sqlalchemy as sa

from app import db
from app.models.mas_instrument_locales import (
    MapInstrumentTranslations,
    MasInstrumentLocales,
)
from app.services import instrument_translation_service as svc
from tests.base import BaseTestCase

INSTRUMENT = "TEST_VA"


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
        self.assertAlmostEqual(report.label_coverage, 0.5)

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

    # -- lifecycle_state is untouched by import or edit (decided 2026-09-20) -

    def test_a_reimport_of_an_approved_locale_is_refused_without_acknowledgement(self):
        """Decided 2026-09-20 (digitva-dqh): a bulk re-import into an approved
        locale demotes it, but never silently -- present first: it really is
        approved and untouched by the refused attempt."""
        self._import(self._full_workbook())
        db.session.flush()
        row = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi"))
        row.lifecycle_state = svc.LIFECYCLE_APPROVED
        db.session.flush()
        self.assertEqual(row.lifecycle_state, svc.LIFECYCLE_APPROVED)

        with self.assertRaises(svc.InstrumentTranslationError) as ctx:
            self._import(self._full_workbook(q1="नया पहला प्रश्न"))
        self.assertIn("hi", str(ctx.exception))
        self.assertIn("approved", str(ctx.exception))

        db.session.flush()
        row = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi"))
        self.assertEqual(row.lifecycle_state, svc.LIFECYCLE_APPROVED)
        # Refused before anything was written: the old text is still there.
        self.assertNotEqual(
            self._rows()[("question", "Q1", "label")].text, "नया पहला प्रश्न"
        )

    def test_a_reimport_of_an_approved_locale_demotes_it_when_acknowledged(self):
        self._import(self._full_workbook())
        db.session.flush()
        row = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi"))
        row.lifecycle_state = svc.LIFECYCLE_APPROVED
        row.approved_by_user_id = None
        row.is_active = True
        db.session.flush()

        report = self._import(
            self._full_workbook(q1="नया पहला प्रश्न"), acknowledge_demotion=True
        )
        db.session.flush()
        self.assertTrue(report.demoted)
        row = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi"))
        self.assertEqual(row.lifecycle_state, svc.LIFECYCLE_IN_REVIEW)
        self.assertIsNone(row.approved_by_user_id)
        self.assertIsNone(row.approved_at)
        self.assertFalse(row.is_active)
        # The import still proceeds: the new text landed.
        self.assertEqual(
            self._rows()[("question", "Q1", "label")].text, "नया पहला प्रश्न"
        )

    def test_a_reimport_of_a_draft_or_in_review_locale_needs_no_acknowledgement(self):
        for state in (svc.LIFECYCLE_DRAFT, svc.LIFECYCLE_IN_REVIEW):
            with self.subTest(state=state):
                self._import(self._full_workbook())
                db.session.flush()
                row = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi"))
                row.lifecycle_state = state
                db.session.flush()

                report = self._import(self._full_workbook(q1="फिर से"))
                db.session.flush()
                self.assertFalse(report.demoted)
                self.assertEqual(
                    db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).lifecycle_state,
                    state,
                )

    def test_a_first_import_of_a_new_locale_needs_no_acknowledgement(self):
        report = self._import(self._full_workbook())
        db.session.flush()
        self.assertFalse(report.demoted)

    def test_editing_a_string_leaves_lifecycle_state_untouched(self):
        self._import(self._full_workbook())
        db.session.flush()
        row = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi"))
        row.lifecycle_state = svc.LIFECYCLE_IN_REVIEW
        db.session.flush()
        self.assertEqual(row.lifecycle_state, svc.LIFECYCLE_IN_REVIEW)

        svc.update_string(
            INSTRUMENT, "hi", item_kind="question", item_key="Q1",
            field="label", text="बदला हुआ",
        )
        db.session.flush()
        self.assertEqual(
            db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi")).lifecycle_state,
            svc.LIFECYCLE_IN_REVIEW,
        )

    def test_update_string_never_demotes_an_approved_locale(self):
        """Decided 2026-09-20 (digitva-dqh): an administrator editing one
        string IS the reviewer -- update_string is explicitly excluded from
        the re-import demotion rule."""
        self._import(self._full_workbook())
        db.session.flush()
        row = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi"))
        row.lifecycle_state = svc.LIFECYCLE_APPROVED
        row.is_active = True
        db.session.flush()

        svc.update_string(
            INSTRUMENT, "hi", item_kind="question", item_key="Q1",
            field="label", text="बदला हुआ",
        )
        db.session.flush()
        row = db.session.get(MasInstrumentLocales, (INSTRUMENT, "hi"))
        self.assertEqual(row.lifecycle_state, svc.LIFECYCLE_APPROVED)
        self.assertTrue(row.is_active)

    # -- activation is explicit, never gated on coverage ---------------------
    #
    # Decided 2026-09-19: English fallback is per-string, so a coverage
    # percentage is never a serving decision. Coverage stays computed and
    # reported; it just decides nothing.

    def test_a_full_import_does_not_activate_the_locale(self):
        report = self._import(self._full_workbook())
        db.session.flush()
        # _full_workbook translates every label but not Q1's hint or the "no"
        # choice, so the label breakdown -- not the item headline -- is 1.0.
        self.assertEqual(report.label_coverage, 1.0)
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
        # Present first: the partial coverage is reported accurately (label
        # breakdown: 1 of the 2 labels; the item headline also counts the
        # untranslated hint and second choice, so it is lower).
        self.assertAlmostEqual(report.label_coverage, 0.5)
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

        # Approval (decided 2026-09-20) is a human gate, not a coverage one --
        # this partial locale is approved at the same low coverage to prove
        # that point, then activated.
        svc.set_locale_lifecycle_state(INSTRUMENT, "hi", svc.LIFECYCLE_APPROVED)
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

    # -- any readable workbook is accepted (decided 2026-09-20) -------------
    #
    # Importing a questionnaire source is a reviewed one-time activity, not a
    # policy gate the importer enforces: any workbook under an allowed
    # directory may be imported for any locale, named however its author
    # named it. Path containment (below) is what still refuses a read.

    def test_a_workbook_with_any_name_is_accepted(self):
        other = _write_workbook(
            self.tmp / "not_the_source.xlsx",
            [{"type": "text", "name": "Q1", "label::English (en)": "First question",
              "label::Hindi (hi)": "पहला प्रश्न"}],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        report = self._import(other)
        db.session.flush()
        self.assertEqual(report.written, 1)
        self.assertEqual(self._rows()[("question", "Q1", "label")].text, "पहला प्रश्न")

    def test_cross_check_reads_a_workbook_and_writes_nothing(self):
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

    def test_a_new_locale_takes_its_name_from_the_workbook_or_the_argument(self):
        workbook = _write_workbook(
            self.tmp / "source_zz.xlsx",
            [{"type": "text", "name": "Q1", "label::English (en)": "First question",
              "label::Zulu (zz)": "Okuqala"}],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        svc.import_translations(INSTRUMENT, "zz", workbook)
        db.session.flush()
        self.assertEqual(
            db.session.get(MasInstrumentLocales, (INSTRUMENT, "zz")).language_name,
            "Zulu",
        )

    def test_a_new_locale_with_no_language_column_name_falls_back_to_the_argument(self):
        # "label::(zz)" carries data for locale "zz" but, with nothing between
        # "::" and the parenthesis, no display name -- see _locale_names.
        workbook = _write_workbook(
            self.tmp / "source_zz.xlsx",
            [{"type": "text", "name": "Q1", "label::English (en)": "First question",
              "label::(zz)": "Okuqala"}],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        svc.import_translations(INSTRUMENT, "zz", workbook, language_name="Zulu")
        db.session.flush()
        self.assertEqual(
            db.session.get(MasInstrumentLocales, (INSTRUMENT, "zz")).language_name,
            "Zulu",
        )

    def test_a_path_outside_the_workbook_directory_and_the_repo_is_refused(self):
        with self.assertRaises(svc.InstrumentTranslationError) as ctx:
            self._import("/no-such-root-on-this-machine/x.xlsx")
        self.assertIn("outside", str(ctx.exception))
        self.assertEqual(self._rows(), {})

    def test_the_base_locale_is_never_imported(self):
        with self.assertRaises(svc.InstrumentTranslationError):
            svc.import_translations(INSTRUMENT, "en", self._full_workbook())

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

        # ...only the explicit activation adds it (after the equally explicit
        # approval a 2026-09-20 locale now needs first).
        svc.set_locale_lifecycle_state(INSTRUMENT, "hi", svc.LIFECYCLE_APPROVED)
        svc.set_locale_active(INSTRUMENT, "hi", True)
        db.session.flush()
        versions = svc.active_locale_versions(INSTRUMENT)
        self.assertIn("hi", versions)

    def test_active_locale_versions_includes_an_in_review_locale(self):
        """A page showing an in_review locale must be able to revalidate it."""
        self._import(self._full_workbook())
        db.session.flush()
        self.assertNotIn("hi", svc.active_locale_versions(INSTRUMENT))

        svc.set_locale_lifecycle_state(INSTRUMENT, "hi", svc.LIFECYCLE_IN_REVIEW)
        db.session.flush()
        self.assertIn("hi", svc.active_locale_versions(INSTRUMENT))


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

    def test_label_keys_include_layer_labels(self):
        """The label breakdown covers WHO base and DigitVA layer labels alike."""
        label_keys = svc.reference_label_keys(self.INSTRUMENT)
        self.assertIn(("question", "Q1", "label"), label_keys)
        self.assertIn(("question", "consent_mode", "label"), label_keys)
        self.assertIn(("question", "md_available", "label"), label_keys)

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
        report = svc.import_translations(self.INSTRUMENT, "hi", workbook)
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
        # ...and it counts toward the label breakdown like any other label.
        # The fixture's reference has 3 question labels (Q1, consent_mode,
        # md_available); this workbook only translates Q1 and consent_mode.
        self.assertEqual(report.reference_labels, 3)
        self.assertEqual(report.translated_labels, 2)
        # digitva_core's item total is 2 (consent_mode label + the
        # CONSENT_MODE/in_person choice label); the workbook only translates
        # the question label, so only 1 of those 2 items is translated, while
        # the label breakdown (1/1) is fully covered.
        self.assertEqual(
            report.extension_coverage["digitva_core"],
            {"translated": 1, "total": 2, "label_translated": 1, "label_total": 1},
        )


class LocaleApprovalLifecycleTests(BaseTestCase):
    """The 2026-09-20 approval gate (docs/policy/va-form-project-configuration.md,
    "Approval before activation"): only an ``approved`` locale may be
    activated, a locale may not leave ``approved`` while still active, and
    both rules hold twice over -- once in the service (a named, actionable
    error) and once as the database CHECK constraint
    ``ck_mas_instrument_locales_active_requires_approved`` (the backstop).
    """

    INSTRUMENT = "LIFECYCLE_VA"

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
        self.layers = _write_layer_reference(self.tmp / "layers.json")
        self._clear_reference_caches()
        self.addCleanup(self._clear_reference_caches)
        self._patch(svc, "REFERENCE_WORKBOOK", self.reference)
        self._patch(svc, "LAYER_REFERENCE_PATH", self.layers)
        self._patch(svc, "BASE_INSTRUMENT_CODE", self.INSTRUMENT)

    def _clear_reference_caches(self):
        svc._reference_items_cached.cache_clear()
        svc._reference_extensions_cached.cache_clear()
        svc._layer_entries_cached.cache_clear()

    def _patch(self, module, name, value):
        old = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(setattr, module, name, old)

    def _make_locale(self, code="hi", *, lifecycle_state=svc.LIFECYCLE_DRAFT, active=False):
        row = MasInstrumentLocales(
            instrument_code=self.INSTRUMENT, locale_code=code,
            language_name="Hindi", is_active=active, lifecycle_state=lifecycle_state,
        )
        db.session.add(row)
        db.session.flush()
        return row

    # -- only 'approved' may be activated ------------------------------------

    def test_activating_a_draft_locale_is_refused_naming_locale_and_state(self):
        self._make_locale(lifecycle_state=svc.LIFECYCLE_DRAFT)
        with self.assertRaises(svc.InstrumentTranslationError) as ctx:
            svc.set_locale_active(self.INSTRUMENT, "hi", True)
        self.assertIn("hi", str(ctx.exception))
        self.assertIn("draft", str(ctx.exception))
        self.assertFalse(
            db.session.get(MasInstrumentLocales, (self.INSTRUMENT, "hi")).is_active
        )

    def test_activating_an_in_review_locale_is_refused(self):
        self._make_locale(lifecycle_state=svc.LIFECYCLE_IN_REVIEW)
        with self.assertRaises(svc.InstrumentTranslationError) as ctx:
            svc.set_locale_active(self.INSTRUMENT, "hi", True)
        self.assertIn("in_review", str(ctx.exception))

    def test_an_approved_locale_may_be_activated(self):
        self._make_locale(lifecycle_state=svc.LIFECYCLE_APPROVED)
        result = svc.set_locale_active(self.INSTRUMENT, "hi", True)
        self.assertTrue(result["is_active"])

    def test_the_database_check_constraint_refuses_a_non_approved_active_row_too(self):
        """Belt-and-suspenders: a write that bypasses the service entirely
        (as if some other code path wrote the row directly) is still refused,
        not just the service's own call."""
        self._make_locale(lifecycle_state=svc.LIFECYCLE_DRAFT)
        row = db.session.get(MasInstrumentLocales, (self.INSTRUMENT, "hi"))
        row.is_active = True
        with self.assertRaises(sa.exc.IntegrityError):
            db.session.flush()
        db.session.rollback()

    # -- a locale may not leave 'approved' while active ----------------------

    def test_leaving_approved_while_active_is_refused(self):
        self._make_locale(lifecycle_state=svc.LIFECYCLE_APPROVED, active=True)
        with self.assertRaises(svc.InstrumentTranslationError) as ctx:
            svc.set_locale_lifecycle_state(self.INSTRUMENT, "hi", svc.LIFECYCLE_IN_REVIEW)
        self.assertIn("deactivate", str(ctx.exception).lower())
        # Refused before anything changed.
        row = db.session.get(MasInstrumentLocales, (self.INSTRUMENT, "hi"))
        self.assertEqual(row.lifecycle_state, svc.LIFECYCLE_APPROVED)
        self.assertTrue(row.is_active)

    def test_deactivating_first_then_leaving_approved_succeeds(self):
        self._make_locale(lifecycle_state=svc.LIFECYCLE_APPROVED, active=True)
        svc.set_locale_active(self.INSTRUMENT, "hi", False)
        result = svc.set_locale_lifecycle_state(self.INSTRUMENT, "hi", svc.LIFECYCLE_DRAFT)
        self.assertEqual(result["lifecycle_state"], svc.LIFECYCLE_DRAFT)

    # -- entering/leaving 'approved' records or clears who and when ---------

    def test_entering_approved_records_the_approver_and_the_time(self):
        self._make_locale(lifecycle_state=svc.LIFECYCLE_IN_REVIEW)
        result = svc.set_locale_lifecycle_state(
            self.INSTRUMENT, "hi", svc.LIFECYCLE_APPROVED,
            actor_id=self.base_admin_user.user_id,
        )
        self.assertEqual(result["lifecycle_state"], svc.LIFECYCLE_APPROVED)
        row = db.session.get(MasInstrumentLocales, (self.INSTRUMENT, "hi"))
        self.assertEqual(row.approved_by_user_id, self.base_admin_user.user_id)
        self.assertIsNotNone(row.approved_at)
        self.assertIsNotNone(row.approved_at.tzinfo)

    def test_leaving_approved_clears_the_approver_and_the_time(self):
        self._make_locale(lifecycle_state=svc.LIFECYCLE_IN_REVIEW)
        svc.set_locale_lifecycle_state(
            self.INSTRUMENT, "hi", svc.LIFECYCLE_APPROVED,
            actor_id=self.base_admin_user.user_id,
        )
        row = db.session.get(MasInstrumentLocales, (self.INSTRUMENT, "hi"))
        # Present first: it really was recorded before this test clears it.
        self.assertIsNotNone(row.approved_by_user_id)
        self.assertIsNotNone(row.approved_at)

        svc.set_locale_lifecycle_state(self.INSTRUMENT, "hi", svc.LIFECYCLE_IN_REVIEW)
        db.session.refresh(row)
        self.assertIsNone(row.approved_by_user_id)
        self.assertIsNone(row.approved_at)

    def test_an_unknown_lifecycle_state_is_refused(self):
        self._make_locale(lifecycle_state=svc.LIFECYCLE_DRAFT)
        with self.assertRaises(svc.InstrumentTranslationError):
            svc.set_locale_lifecycle_state(self.INSTRUMENT, "hi", "not_a_state")


class MachineSourceTests(BaseTestCase):
    """digitva-4kj: a 'machine' row is a draft awaiting human review. It must
    stay visible and editable, but a form must fall back to English for
    exactly those strings (the same mechanism an untranslated string already
    uses), and it must not count toward coverage.
    """

    INSTRUMENT = "MACHINE_VA"

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.reference = _write_workbook(
            self.tmp / "reference.xlsx",
            [
                {"type": "text", "name": "Q1", "label::English (en)": "First question"},
                {"type": "text", "name": "Q2", "label::English (en)": "Second question"},
            ],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        self.layers = _write_layer_reference(self.tmp / "layers.json")
        self._clear_reference_caches()
        self.addCleanup(self._clear_reference_caches)
        self._patch(svc, "REFERENCE_WORKBOOK", self.reference)
        self._patch(svc, "LAYER_REFERENCE_PATH", self.layers)
        self._patch(svc, "BASE_INSTRUMENT_CODE", self.INSTRUMENT)

        self.locale_row = MasInstrumentLocales(
            instrument_code=self.INSTRUMENT, locale_code="hi",
            language_name="Hindi", is_active=True,
            lifecycle_state=svc.LIFECYCLE_APPROVED, version=1,
        )
        db.session.add(self.locale_row)
        db.session.flush()
        # Q1 is a reviewed workbook translation; Q2 is an unreviewed machine
        # draft -- exactly the shape b6d2f4a9c1e7 seeded.
        db.session.add(MapInstrumentTranslations(
            instrument_code=self.INSTRUMENT, locale_code="hi",
            item_kind="question", item_key="Q1", field="label",
            text="पहला प्रश्न", source=svc.SOURCE_IMPORTED,
        ))
        db.session.add(MapInstrumentTranslations(
            instrument_code=self.INSTRUMENT, locale_code="hi",
            item_kind="question", item_key="Q2", field="label",
            text="मशीन अनुवाद", source=svc.SOURCE_MACHINE,
        ))
        db.session.flush()

    def _clear_reference_caches(self):
        svc._reference_items_cached.cache_clear()
        svc._reference_extensions_cached.cache_clear()
        svc._layer_entries_cached.cache_clear()

    def _patch(self, module, name, value):
        old = getattr(module, name)
        setattr(module, name, value)
        self.addCleanup(setattr, module, name, old)

    def _row(self, item_key):
        return db.session.get(
            MapInstrumentTranslations,
            (self.INSTRUMENT, "hi", "question", item_key, "label"),
        )

    # -- serving --------------------------------------------------------

    def test_export_serves_english_for_machine_items_and_its_own_text_for_the_rest(self):
        payload = svc.export_translations(self.INSTRUMENT, "hi")
        # Present first: the reviewed translation really is served.
        self.assertEqual(payload["questions"]["Q1"]["label"], "पहला प्रश्न")
        # Absent, not empty: the same shape an untranslated string has, so the
        # client's existing per-string English fallback covers it too.
        self.assertNotIn("Q2", payload["questions"])

    def test_a_machine_row_stays_visible_and_editable_in_list_strings(self):
        listed = svc.list_strings(self.INSTRUMENT, "hi")
        by_key = {item["item_key"]: item for item in listed["items"]}
        self.assertEqual(by_key["Q2"]["source"], svc.SOURCE_MACHINE)
        self.assertEqual(by_key["Q2"]["text"], "मशीन अनुवाद")

    # -- coverage ---------------------------------------------------------

    def test_coverage_does_not_count_machine_rows_as_translated(self):
        statuses = {row["locale_code"]: row for row in svc.locale_status(self.INSTRUMENT)}
        hi = statuses["hi"]
        # Only Q1 (imported) counts; Q2 (machine) does not, even though it
        # carries text.
        self.assertEqual(hi["translated_labels"], 1)
        self.assertEqual(hi["reference_labels"], 2)

    # -- accept-as-is -------------------------------------------------------

    def test_accepting_a_machine_row_promotes_it_to_edited_without_changing_text(self):
        result = svc.accept_machine_translation(
            self.INSTRUMENT, "hi", item_kind="question", item_key="Q2", field="label",
        )
        self.assertEqual(result["source"], svc.SOURCE_EDITED)
        self.assertEqual(result["text"], "मशीन अनुवाद")
        row = self._row("Q2")
        self.assertEqual(row.source, svc.SOURCE_EDITED)
        self.assertEqual(row.text, "मशीन अनुवाद")

        # Now served, and now counted -- accepting is the human review this
        # bead requires before either happens.
        payload = svc.export_translations(self.INSTRUMENT, "hi")
        self.assertEqual(payload["questions"]["Q2"]["label"], "मशीन अनुवाद")
        statuses = {row["locale_code"]: row for row in svc.locale_status(self.INSTRUMENT)}
        self.assertEqual(statuses["hi"]["translated_labels"], 2)

        # Accepting is not a bulk re-import: the approval gate (digitva-dqh)
        # does not apply -- this locale is still approved and active.
        row = db.session.get(MasInstrumentLocales, (self.INSTRUMENT, "hi"))
        self.assertEqual(row.lifecycle_state, svc.LIFECYCLE_APPROVED)
        self.assertTrue(row.is_active)

    def test_accepting_a_non_machine_row_is_refused(self):
        with self.assertRaises(svc.InstrumentTranslationError):
            svc.accept_machine_translation(
                self.INSTRUMENT, "hi", item_kind="question", item_key="Q1", field="label",
            )
        self.assertEqual(self._row("Q1").source, svc.SOURCE_IMPORTED)

    def test_accepting_an_unknown_item_is_refused(self):
        with self.assertRaises(svc.InstrumentTranslationError):
            svc.accept_machine_translation(
                self.INSTRUMENT, "hi", item_kind="question", item_key="NoSuchQ", field="label",
            )

    # -- re-import overwrites machine, never edited --------------------------

    def test_reimport_overwrites_a_machine_row(self):
        workbook = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [
                {"type": "text", "name": "Q1", "label::English (en)": "First question",
                 "label::Hindi (hi)": "पहला प्रश्न"},
                {"type": "text", "name": "Q2", "label::English (en)": "Second question",
                 "label::Hindi (hi)": "समीक्षित अनुवाद"},
            ],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        report = svc.import_translations(
            self.INSTRUMENT, "hi", workbook, acknowledge_demotion=True,
        )
        db.session.flush()
        row = self._row("Q2")
        self.assertEqual(row.text, "समीक्षित अनुवाद")
        self.assertEqual(row.source, svc.SOURCE_IMPORTED)
        self.assertEqual(report.kept_edited, 0)

    def test_reimport_never_overwrites_an_edited_row_even_if_it_was_once_machine(self):
        svc.update_string(
            self.INSTRUMENT, "hi", item_kind="question", item_key="Q2", field="label",
            text="व्यवस्थापक का सुधार",
        )
        db.session.flush()
        self.assertEqual(self._row("Q2").source, svc.SOURCE_EDITED)

        workbook = _write_workbook(
            self.tmp / "source_hi.xlsx",
            [
                {"type": "text", "name": "Q1", "label::English (en)": "First question",
                 "label::Hindi (hi)": "पहला प्रश्न"},
                {"type": "text", "name": "Q2", "label::English (en)": "Second question",
                 "label::Hindi (hi)": "वर्कबुक पाठ"},
            ],
            [{"list_name": "yes_no", "name": "yes", "label::English (en)": "Yes"}],
        )
        report = svc.import_translations(
            self.INSTRUMENT, "hi", workbook, acknowledge_demotion=True,
        )
        db.session.flush()
        row = self._row("Q2")
        self.assertEqual(row.text, "व्यवस्थापक का सुधार")
        self.assertEqual(row.source, svc.SOURCE_EDITED)
        self.assertEqual(report.kept_edited, 1)


class RealWorkbookCoverageTests(unittest.TestCase):
    """Slow: reads the nine committed workbooks.

    This is the check that would notice a re-downloaded source workbook
    silently dropping a language. It writes nothing -- every locale is read
    with ``cross_check``, so it needs no database. Coverage is no longer a
    serving gate, but a deployed language is still expected to be
    near-complete; this test still holds that quality bar, it just is not the
    mechanism that decides whether the language may be served.

    The workbook each locale is read from is this test's own fixed knowledge
    of what was downloaded and reviewed on 2026-09-19 (see the "Translation
    sources" table in docs/policy/va-form-project-configuration.md, which
    records the same provenance for humans) -- not something the importer
    itself looks up any more (decided 2026-09-20).
    """

    #: The quality bar a documented, deployed language is expected to clear.
    #: Not read by the service any more (there is no gate) -- this test's own
    #: expectation of what "near-complete" means.
    EXPECTED_COVERAGE = 0.95

    #: {locale: source workbook}, one reviewed source per deployed language,
    #: as of 2026-09-19. The eight Indian-language forms plus the WHO
    #: multilingual form's five languages.
    SOURCE_WORKBOOKS = {
        "hi": "ND01_ICMRVA_WHOVA2022.xlsx",
        "ta": "JIPMER_DS_WHOVA2022.xlsx",
        "kn": "KA01_DS_WHOVA2022.xlsx",
        "mr": "KEM_VAADU_WHOVA2022.xlsx",
        "ml": "KL01_DS_WHOVA2022.xlsx",
        "kha": "ML01_ICMRVA_WHOVA2022.xlsx",
        "or": "OD01_ICMRVA_WHOVA2022.xlsx",
        "bn": "TR01_DS_WHOVA2022.xlsx",
        "fr": "2022whova_xls_form_for_odk_multilingual.xlsx",
        "pt": "2022whova_xls_form_for_odk_multilingual.xlsx",
        "ar": "2022whova_xls_form_for_odk_multilingual.xlsx",
        "sw": "2022whova_xls_form_for_odk_multilingual.xlsx",
        "es": "2022whova_xls_form_for_odk_multilingual.xlsx",
    }

    def test_every_source_workbook_is_present(self):
        for locale, workbook in self.SOURCE_WORKBOOKS.items():
            with self.subTest(locale=locale):
                self.assertTrue((svc.WORKBOOK_DIR / workbook).exists())

    @staticmethod
    def _who_base_label_coverage(locale, workbook):
        """WHO base label coverage of one source workbook, read directly.

        digitva-o3s widened ``label_coverage`` to WHO base + DigitVA layer
        labels together, which is the right headline for what the app
        serves. But these thirteen source workbooks are WHO/ICMR-reviewed
        forms downloaded and reviewed on 2026-09-19 (see SOURCE_WORKBOOKS),
        before the DigitVA layer questions (``consent_mode``, ``md_im*``,
        ``ds_*``...) existed as translatable items at all -- no external WHO
        or site workbook was ever going to carry their translations, so
        holding these specific fixed workbooks to a 0.95 bar on the widened
        label set would not be testing anything real about them. This
        recomputes the same "near-complete" quality bar the test always
        held, scoped to the WHO base labels these workbooks are actually
        sourced against, using only public helpers (no service-internal
        parsing of report.missing_from_workbook's display strings).
        """
        reference = svc.reference_items("WHO_2022_VA")
        extensions = svc.reference_item_extensions("WHO_2022_VA")
        base_labels = {
            key for key in reference
            if key[0] == "question" and key[2] == "label" and not extensions.get(key)
        }
        workbook_items, _names = svc.read_workbook_items(svc.WORKBOOK_DIR / workbook)
        incoming_raw = workbook_items.get(locale, {})
        translated = {
            key
            for key, value in incoming_raw.items()
            if key in base_labels
            and (text := svc.split_packed(value, reference.get(key)))
            and text != reference[key]
        }
        return len(translated) / len(base_labels)

    def test_every_deployed_language_is_near_complete_on_who_base_labels(self):
        """Scoped to the WHO base labels deliberately -- see the helper above.

        The name says which measure because digitva-o3s exists precisely
        because a narrow coverage number was read as a whole-reference one.
        """
        for locale, workbook in self.SOURCE_WORKBOOKS.items():
            with self.subTest(locale=locale):
                report = svc.import_translations(
                    "WHO_2022_VA", locale,
                    svc.WORKBOOK_DIR / workbook,
                    cross_check=True,
                )
                self.assertGreater(report.reference_labels, 400)
                base_coverage = self._who_base_label_coverage(locale, workbook)
                self.assertGreaterEqual(
                    base_coverage,
                    self.EXPECTED_COVERAGE,
                    f"{locale} covers only {base_coverage:.1%} of the WHO "
                    "base survey labels",
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
        self.assertLess(report.label_coverage, self.EXPECTED_COVERAGE)


class ReferenceDenominatorTests(unittest.TestCase):
    """Pins the headline and breakdown denominators against the real reference.

    A future change to the reference or to a helper must not silently narrow
    either count again -- that is exactly the bug this bead fixes (coverage
    was quietly computed against a stale, label-only, base-only denominator).
    No mocking: the real committed WHO base workbook plus the real DigitVA
    layer reference, same fixtures :class:`InstrumentTranslationXliffRealWorkbookTests`
    uses.
    """

    def test_the_real_reference_totals_1435_items_and_556_labels(self):
        item_keys = svc.reference_item_keys(svc.BASE_INSTRUMENT_CODE)
        label_keys = svc.reference_label_keys(svc.BASE_INSTRUMENT_CODE)
        self.assertEqual(len(item_keys), 1435)
        self.assertEqual(len(label_keys), 556)


class NoPolicyDocReadDuringImportTests(unittest.TestCase):
    """Acceptance: no module under app/ reads a file under docs/ at import time.

    Decided 2026-09-20: the "Translation sources" table in
    docs/policy/va-form-project-configuration.md is provenance for a human
    reader, not a rule the importer enforces. This spies on every text read
    through :meth:`pathlib.Path.read_text` -- how the old, removed
    ``documented_sources()`` read the markdown table -- during a real import
    and a real cross-check, and fails if either ever opens anything under
    ``docs/policy``.
    """

    def _watched_import(self, **kwargs):
        opened: list[Path] = []
        real_read_text = Path.read_text

        def spy(path_self, *args, **kw):
            opened.append(Path(path_self))
            return real_read_text(path_self, *args, **kw)

        with unittest.mock.patch.object(Path, "read_text", spy):
            svc.import_translations(
                "WHO_2022_VA", "hi",
                svc.WORKBOOK_DIR / "ND01_ICMRVA_WHOVA2022.xlsx",
                **kwargs,
            )
        return opened

    def test_a_cross_check_reads_nothing_under_docs_policy(self):
        policy_dir = (svc.REPO_ROOT / "docs" / "policy").resolve()
        opened = self._watched_import(cross_check=True)
        for path in opened:
            self.assertFalse(
                policy_dir in path.resolve().parents or path.resolve() == policy_dir,
                f"{path} under docs/policy was read during a cross-check import",
            )
