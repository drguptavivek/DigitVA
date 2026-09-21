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

Since 2026-09-21 (``digitva-mxn``) a locale is *servable* when it is active or
``in_review``: an ``in_review`` locale is offered with its English forced on
beside every string ("English alongside the translation" in the policy). A
``draft`` locale is never served. The database CHECK keeps ``in_review`` rows
inactive, so the two halves of the predicate never overlap.

``DEFAULT_LOCALE`` (``"en"``) is the base language of every bundled instrument.
It needs no rows, is always active, and always comes first; a project adds
languages on top of it and can never remove it.
"""

import sqlalchemy as sa

from app import db
from app.models.mas_instrument_locales import LIFECYCLE_IN_REVIEW, MasInstrumentLocales

#: The base language of every bundled instrument, always offered.
DEFAULT_LOCALE = "en"

#: Its label. The base locale has no row to read a language name from.
DEFAULT_LOCALE_LABEL = "English"

#: The only standard instrument DigitVA bundles today. It is the fallback for
#: a form type whose instrument has not resolved, and must be revisited when a
#: second standard instrument (PHMRC) is bundled.
FALLBACK_INSTRUMENT_CODE = "WHO_2022_VA"


#: The one definition of a locale a form may be served in: active, or under
#: review (served only with its English beside it). Never ``draft``.
SERVABLE_LOCALE = sa.or_(
    MasInstrumentLocales.is_active.is_(True),
    MasInstrumentLocales.lifecycle_state == LIFECYCLE_IN_REVIEW,
)


def is_servable(row: MasInstrumentLocales) -> bool:
    """``SERVABLE_LOCALE`` for one loaded row."""
    return row.is_active or row.lifecycle_state == LIFECYCLE_IN_REVIEW


def _servable_rows(instrument_code: str | None = None) -> list:
    """Servable locale rows of one instrument, or of every instrument for None."""
    stmt = (
        sa.select(
            MasInstrumentLocales.locale_code,
            MasInstrumentLocales.language_name,
            MasInstrumentLocales.is_active,
        )
        .where(SERVABLE_LOCALE)
        .order_by(MasInstrumentLocales.locale_code)
    )
    if instrument_code is not None:
        stmt = stmt.where(MasInstrumentLocales.instrument_code == instrument_code)
    return db.session.execute(stmt).all()


def _instrument_rows(instrument_code: str | None) -> list:
    """One instrument's servable rows, falling back to ``WHO_2022_VA``'s.

    ``None``, a blank code, or a code with no servable locales of its own falls
    back to ``WHO_2022_VA``: it is the only instrument DigitVA bundles today,
    so serving its locales is the honest answer for any project whose form
    type has not resolved to something else.
    """
    code = (instrument_code or "").strip().upper()
    rows = _servable_rows(code) if code else []
    if not rows and code != FALLBACK_INSTRUMENT_CODE:
        rows = _servable_rows(FALLBACK_INSTRUMENT_CODE)
    return rows


def _catalogue(rows) -> tuple[dict[str, str], set[str]]:
    """``({code: label}, under_review)`` from servable rows, ``"en"`` first.

    A code is under review only when no row for it is active: merged across
    instruments, one may have it active while another has it in review.
    """
    locales = {DEFAULT_LOCALE: DEFAULT_LOCALE_LABEL}
    for row in rows:
        locales.setdefault(row.locale_code, row.language_name)
    active = {row.locale_code for row in rows if row.is_active}
    return locales, {code for code in locales if code != DEFAULT_LOCALE} - active


def instrument_locale_catalogue(
    instrument_code: str | None,
) -> tuple[dict[str, str], set[str]]:
    """``instrument_locales`` and ``instrument_locales_under_review`` in one query."""
    return _catalogue(_instrument_rows(instrument_code))


def instrument_locales(instrument_code: str | None) -> dict[str, str]:
    """The ``{code: label}`` servable display languages of one instrument.

    Active and ``in_review`` locales, ``"en"`` first; see ``_instrument_rows``
    for the ``WHO_2022_VA`` fallback.
    """
    return instrument_locale_catalogue(instrument_code)[0]


def instrument_locales_under_review(instrument_code: str | None) -> set[str]:
    """The codes in ``instrument_locales`` that are ``in_review``, not active.

    Same fallback as ``instrument_locales``. A form must show the English
    beside these and must not let the interviewer hide it.
    """
    return instrument_locale_catalogue(instrument_code)[1]


def all_instrument_locale_catalogue() -> tuple[dict[str, str], set[str]]:
    """``all_instrument_locales`` and its under-review codes in one query."""
    return _catalogue(_servable_rows())


def all_instrument_locales() -> dict[str, str]:
    """Every display language any instrument can serve, ``"en"`` first.

    Active and ``in_review`` locales alike. This is the set an administrator
    may choose from: the Projects panel and the project create/update routes
    validate against it, because a project's form type can change and a
    language stored for one instrument must not be rejected outright by the
    other.
    """
    return all_instrument_locale_catalogue()[0]


def all_instrument_locales_under_review() -> set[str]:
    """Codes in ``all_instrument_locales`` that no instrument has active."""
    return all_instrument_locale_catalogue()[1]
