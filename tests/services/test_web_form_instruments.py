"""The web form's display languages come from the active locale rows.

Until 2026-09-19 `app/services/web_form_instruments.py` was a hand-maintained
registry, and these tests held it to the vendored bundle. Translations are now
server data (WP6 of
docs/planning/web-capture-project-configuration-plan.md): a language is a row
in `mas_instrument_locales`, activated when an import passes the coverage
threshold, and it reaches interviewers without a bundle rebuild.

So the bundle check narrows to the one thing still true of it -- `en` is the
instrument's own language and the bundle carries it -- and everything else is
a test of the query. Policy: docs/policy/va-web-form-options.md.
"""
import re
from datetime import UTC, datetime
from pathlib import Path

from app import db
from app.models.mas_instrument_locales import (
    LIFECYCLE_APPROVED,
    LIFECYCLE_IN_REVIEW,
    MasInstrumentLocales,
)
from app.services.web_form_instruments import (
    DEFAULT_LOCALE,
    FALLBACK_INSTRUMENT_CODE,
    all_instrument_locales,
    all_instrument_locales_under_review,
    instrument_locales,
    instrument_locales_under_review,
)
from tests.base import BaseTestCase

#: instrument_code -> the vendored bundle that must carry its base language.
BUNDLES = {
    "WHO_2022_VA": "app/static/vendor/who-va-2022/who-va-2022.web-component.js",
}


def _bundle_text(instrument_code):
    path = Path(__file__).resolve().parents[2] / BUNDLES[instrument_code]
    return path.read_text(encoding="utf-8")


def _has_label_translations(text, code):
    """True when the bundle uses ``code`` as a key inside a ``label:{...}``.

    The bundle is minified, so every question label is emitted as
    ``label:{en:"...",...}``. A locale the instrument really has therefore
    appears as a key in at least one of those objects.
    """
    return bool(re.search(r"label:\{[^}]*\b" + re.escape(code) + r":", text))


def _locale(instrument_code, code, name, *, active, lifecycle_state=None):
    # An active row must be 'approved' (ck_mas_instrument_locales_active_
    # requires_approved, decided 2026-09-20).
    if lifecycle_state is None:
        lifecycle_state = LIFECYCLE_APPROVED if active else "draft"
    row = db.session.get(MasInstrumentLocales, (instrument_code, code))
    if row is None:
        row = MasInstrumentLocales(
            instrument_code=instrument_code, locale_code=code, language_name=name,
            version=1, is_active=active, updated_at=datetime.now(UTC),
            lifecycle_state=lifecycle_state,
        )
        db.session.add(row)
    row.is_active = active
    row.lifecycle_state = lifecycle_state
    db.session.flush()
    return row


class BundledBaseLocaleTests(BaseTestCase):
    """The one bundle claim that survives: ``en`` is in it."""

    def test_the_bundle_carries_the_base_locale(self):
        """Positive and negative controls, so the regex cannot pass vacuously."""
        text = _bundle_text(FALLBACK_INSTRUMENT_CODE)
        self.assertTrue(
            _has_label_translations(text, DEFAULT_LOCALE),
            "the WHO 2022 bundle must carry English labels",
        )
        self.assertFalse(
            _has_label_translations(text, "zz"),
            "a made-up locale must not match, or the check proves nothing",
        )


class InstrumentLocaleQueryTests(BaseTestCase):
    """``instrument_locales`` / ``all_instrument_locales`` read active rows."""

    def test_the_base_locale_is_served_with_no_rows_at_all(self):
        self.assertEqual(
            instrument_locales(FALLBACK_INSTRUMENT_CODE),
            {DEFAULT_LOCALE: "English"},
        )

    def test_an_active_locale_row_is_served_and_an_inactive_one_is_not(self):
        """Present first: the row exists; it is still withheld until active."""
        _locale(FALLBACK_INSTRUMENT_CODE, "hi", "Hindi", active=False)
        db.session.flush()
        self.assertIsNotNone(
            db.session.get(MasInstrumentLocales, (FALLBACK_INSTRUMENT_CODE, "hi")),
            "fixture guard: the row is there to be withheld",
        )
        self.assertNotIn("hi", instrument_locales(FALLBACK_INSTRUMENT_CODE))

        _locale(FALLBACK_INSTRUMENT_CODE, "hi", "Hindi", active=True)
        db.session.flush()
        locales = instrument_locales(FALLBACK_INSTRUMENT_CODE)
        self.assertEqual(locales["hi"], "Hindi")
        self.assertEqual(list(locales)[0], DEFAULT_LOCALE)

    def test_an_unknown_or_missing_instrument_falls_back_to_who_2022(self):
        _locale(FALLBACK_INSTRUMENT_CODE, "hi", "Hindi", active=True)
        db.session.flush()
        who = instrument_locales(FALLBACK_INSTRUMENT_CODE)
        self.assertEqual(instrument_locales(None), who)
        self.assertEqual(instrument_locales("UNKNOWN"), who)

    def test_another_instruments_locale_does_not_leak_into_this_one(self):
        _locale("OTHER_VA", "ta", "Tamil", active=True)
        _locale(FALLBACK_INSTRUMENT_CODE, "hi", "Hindi", active=True)
        db.session.flush()
        self.assertIn("ta", instrument_locales("OTHER_VA"))
        self.assertNotIn("ta", instrument_locales(FALLBACK_INSTRUMENT_CODE))

    def test_all_instrument_locales_starts_with_the_base_locale(self):
        merged = all_instrument_locales()
        self.assertEqual(list(merged)[0], DEFAULT_LOCALE)
        self.assertEqual(merged[DEFAULT_LOCALE], "English")

    def test_all_instrument_locales_merges_every_instruments_active_rows(self):
        _locale(FALLBACK_INSTRUMENT_CODE, "hi", "Hindi", active=True)
        _locale("OTHER_VA", "ta", "Tamil", active=True)
        _locale("OTHER_VA", "kn", "Kannada", active=False)
        db.session.flush()
        merged = all_instrument_locales()
        self.assertEqual(merged["hi"], "Hindi")
        self.assertEqual(merged["ta"], "Tamil")
        self.assertNotIn("kn", merged)


class ServableLocaleTests(BaseTestCase):
    """An ``in_review`` locale is served (English forced on); ``draft`` never.

    Decided 2026-09-21 (digitva-mxn), "English alongside the translation" in
    docs/policy/va-web-form-options.md.
    """

    def test_an_in_review_locale_is_served_and_marked_under_review(self):
        _locale(FALLBACK_INSTRUMENT_CODE, "hi", "Hindi", active=True)
        _locale(
            FALLBACK_INSTRUMENT_CODE, "kn", "Kannada",
            active=False, lifecycle_state=LIFECYCLE_IN_REVIEW,
        )
        db.session.flush()
        locales = instrument_locales(FALLBACK_INSTRUMENT_CODE)
        self.assertEqual(locales["kn"], "Kannada")
        self.assertEqual(locales["hi"], "Hindi")
        self.assertEqual(
            instrument_locales_under_review(FALLBACK_INSTRUMENT_CODE), {"kn"}
        )

    def test_a_draft_locale_is_not_served(self):
        """Present first: the draft row exists; it is still withheld."""
        _locale(FALLBACK_INSTRUMENT_CODE, "ta", "Tamil", active=False)
        db.session.flush()
        row = db.session.get(MasInstrumentLocales, (FALLBACK_INSTRUMENT_CODE, "ta"))
        self.assertEqual(row.lifecycle_state, "draft", "fixture guard")
        self.assertNotIn("ta", instrument_locales(FALLBACK_INSTRUMENT_CODE))
        self.assertNotIn("ta", all_instrument_locales())
        self.assertNotIn("ta", instrument_locales_under_review(FALLBACK_INSTRUMENT_CODE))

    def test_an_in_review_locale_alone_does_not_trigger_the_fallback(self):
        _locale("OTHER_VA", "ta", "Tamil", active=False, lifecycle_state=LIFECYCLE_IN_REVIEW)
        db.session.flush()
        self.assertIn("ta", instrument_locales("OTHER_VA"))
        self.assertEqual(instrument_locales_under_review("OTHER_VA"), {"ta"})

    def test_all_locales_under_review_excludes_a_code_active_elsewhere(self):
        _locale(FALLBACK_INSTRUMENT_CODE, "hi", "Hindi", active=True)
        _locale("OTHER_VA", "hi", "Hindi", active=False, lifecycle_state=LIFECYCLE_IN_REVIEW)
        _locale("OTHER_VA", "kn", "Kannada", active=False, lifecycle_state=LIFECYCLE_IN_REVIEW)
        db.session.flush()
        self.assertIn("hi", all_instrument_locales())
        self.assertIn("kn", all_instrument_locales())
        self.assertEqual(all_instrument_locales_under_review(), {"kn"})
