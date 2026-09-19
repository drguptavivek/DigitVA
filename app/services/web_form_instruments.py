"""Which display languages each bundled VA web form instrument really has.

Policy: docs/policy/va-web-form-options.md. The languages the browser VA form
may be switched to are a property of the *instrument bundle* shipped under
``app/static/vendor/``, not of ``mas_languages``: a code only belongs here once
the vendored bundle carries label translations for it. ``mas_languages`` stays
the source for narration languages, which describe the language a narrative was
*recorded* in and say nothing about what the screen can render.

``DEFAULT_LOCALE`` (``"en"``) is the base language of every bundled instrument
and is therefore mandatory in every ``INSTRUMENT_LOCALES`` entry. A project adds
languages on top of it; it can never be removed.

Both rules -- "en" in every entry, and every listed code actually present in the
bundle -- are enforced by tests/services/test_web_form_instruments.py, so adding
a code here without vendoring a bundle that carries it fails the suite.
"""

#: The base language of every bundled instrument, always offered.
DEFAULT_LOCALE = "en"

#: instrument_code -> {locale_code: label}. Add a code only when the vendored
#: bundle carries translations for it (see the module docstring).
INSTRUMENT_LOCALES: dict[str, dict[str, str]] = {
    "WHO_2022_VA": {"en": "English"},
}


def instrument_locales(instrument_code: str | None) -> dict[str, str]:
    """The ``{code: label}`` display languages of one bundled instrument.

    ``None`` or an unknown code falls back to the ``WHO_2022_VA`` entry: it is
    the only instrument DigitVA bundles today, so serving its locales is the
    honest answer for any project whose form type has not resolved to something
    else. The fallback must be revisited when a second standard instrument
    (PHMRC) is bundled.
    """
    return INSTRUMENT_LOCALES.get(
        instrument_code or "", INSTRUMENT_LOCALES["WHO_2022_VA"]
    )


def all_instrument_locales() -> dict[str, str]:
    """Every display language any bundled instrument has, ``"en"`` first.

    This is the set an administrator may choose from: the Projects panel and
    the project create/update routes validate against it, because a project's
    form type can change and a language stored for one instrument must not be
    rejected outright by the other.
    """
    merged: dict[str, str] = {
        DEFAULT_LOCALE: INSTRUMENT_LOCALES["WHO_2022_VA"][DEFAULT_LOCALE]
    }
    for locales in INSTRUMENT_LOCALES.values():
        for code, label in locales.items():
            merged.setdefault(code, label)
    return merged
