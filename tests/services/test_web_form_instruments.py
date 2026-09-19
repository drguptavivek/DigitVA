"""The web form instrument locale registry matches the vendored bundle.

`app/services/web_form_instruments.py` claims which display languages each
bundled VA questionnaire has. Nothing else can check that claim: the bundle is
built outside this repo, so a code added to the registry without a bundle that
carries it would serve an untranslated form. These tests read the bundle and
hold the registry to it. Policy: docs/policy/va-web-form-options.md.
"""
import re
from pathlib import Path

from app.services.web_form_instruments import (
    DEFAULT_LOCALE,
    INSTRUMENT_LOCALES,
    all_instrument_locales,
    instrument_locales,
)
from tests.base import BaseTestCase

#: instrument_code -> the vendored bundle that must carry its translations.
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


class WebFormInstrumentRegistryTests(BaseTestCase):
    def test_every_instrument_offers_the_base_locale(self):
        for instrument_code, locales in INSTRUMENT_LOCALES.items():
            with self.subTest(instrument=instrument_code):
                self.assertIn(DEFAULT_LOCALE, locales)

    def test_every_registered_locale_is_in_the_vendored_bundle(self):
        """Positive and negative controls first, then the registry itself.

        Without them a regex that matched nothing — or everything — would make
        this test pass for the wrong reason.
        """
        text = _bundle_text("WHO_2022_VA")
        self.assertTrue(
            _has_label_translations(text, DEFAULT_LOCALE),
            "the WHO 2022 bundle must carry English labels",
        )
        self.assertFalse(
            _has_label_translations(text, "zz"),
            "a made-up locale must not match, or the check proves nothing",
        )

        for instrument_code, locales in INSTRUMENT_LOCALES.items():
            bundle = _bundle_text(instrument_code)
            for code in locales:
                with self.subTest(instrument=instrument_code, locale=code):
                    self.assertTrue(
                        _has_label_translations(bundle, code),
                        f"{instrument_code} claims {code!r} but its bundle has "
                        "no label translations for it",
                    )

    def test_all_instrument_locales_starts_with_the_base_locale(self):
        merged = all_instrument_locales()
        self.assertEqual(list(merged)[0], DEFAULT_LOCALE)
        self.assertEqual(merged[DEFAULT_LOCALE], "English")

    def test_an_unknown_or_missing_instrument_falls_back_to_who_2022(self):
        who = INSTRUMENT_LOCALES["WHO_2022_VA"]
        self.assertEqual(instrument_locales("WHO_2022_VA"), who)
        self.assertEqual(instrument_locales(None), who)
        self.assertEqual(instrument_locales("UNKNOWN"), who)
