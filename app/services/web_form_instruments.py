"""Which display languages each standard VA web form instrument really has.

Policy: docs/policy/va-web-form-options.md. The languages the browser VA form
may be switched to are a property of the *instrument*, not of ``mas_languages``:
``mas_languages`` stays the source for narration languages, which describe the
language a narrative was *recorded* in and say nothing about what the screen
can render.

Until 2026-09-19 this was a hand-maintained registry that could only list what
the vendored bundle already carried. Translations are now server data
(``mas_instrument_locales`` / ``map_instrument_translations``, imported by
``app/services/instrument_translation_service.py``), so the answer is a query
over the locales an administrator has imported and activated, and a language
reaches interviewers without a bundle rebuild.

``DEFAULT_LOCALE`` (``"en"``) is the base language of every bundled instrument.
It needs no rows, is always active, and always comes first; a project adds
languages on top of it and can never remove it.
"""

import sqlalchemy as sa

from app import db
from app.models.mas_instrument_locales import MasInstrumentLocales

#: The base language of every bundled instrument, always offered.
DEFAULT_LOCALE = "en"

#: Its label. The base locale has no row to read a language name from.
DEFAULT_LOCALE_LABEL = "English"

#: The only standard instrument DigitVA bundles today. It is the fallback for
#: a form type whose instrument has not resolved, and must be revisited when a
#: second standard instrument (PHMRC) is bundled.
FALLBACK_INSTRUMENT_CODE = "WHO_2022_VA"


def _active_rows(instrument_code: str) -> dict[str, str]:
    rows = db.session.execute(
        sa.select(MasInstrumentLocales.locale_code, MasInstrumentLocales.language_name)
        .where(
            MasInstrumentLocales.instrument_code == instrument_code,
            MasInstrumentLocales.is_active.is_(True),
        )
        .order_by(MasInstrumentLocales.locale_code)
    ).all()
    return {row.locale_code: row.language_name for row in rows}


def instrument_locales(instrument_code: str | None) -> dict[str, str]:
    """The ``{code: label}`` display languages of one standard instrument.

    ``None``, a blank code, or a code with no active locales of its own falls
    back to ``WHO_2022_VA``'s locales: it is the only instrument DigitVA
    bundles today, so serving its locales is the honest answer for any project
    whose form type has not resolved to something else.
    """
    code = (instrument_code or "").strip().upper()
    locales = _active_rows(code) if code else {}
    if not locales and code != FALLBACK_INSTRUMENT_CODE:
        locales = _active_rows(FALLBACK_INSTRUMENT_CODE)
    return {DEFAULT_LOCALE: DEFAULT_LOCALE_LABEL, **locales}


def all_instrument_locales() -> dict[str, str]:
    """Every display language any instrument has active, ``"en"`` first.

    This is the set an administrator may choose from: the Projects panel and
    the project create/update routes validate against it, because a project's
    form type can change and a language stored for one instrument must not be
    rejected outright by the other.
    """
    rows = db.session.execute(
        sa.select(MasInstrumentLocales.locale_code, MasInstrumentLocales.language_name)
        .where(MasInstrumentLocales.is_active.is_(True))
        .order_by(MasInstrumentLocales.locale_code)
    ).all()
    merged = {DEFAULT_LOCALE: DEFAULT_LOCALE_LABEL}
    for row in rows:
        merged.setdefault(row.locale_code, row.language_name)
    return merged
