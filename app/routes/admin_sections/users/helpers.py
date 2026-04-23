import sqlalchemy as sa

from app import db


def _active_language_codes():
    from app.models.mas_languages import MasLanguages

    return set(
        db.session.scalars(
            sa.select(MasLanguages.language_code).where(MasLanguages.is_active == True)
        ).all()
    )


def _available_languages():
    from app.models.mas_languages import MasLanguages

    languages = db.session.scalars(
        sa.select(MasLanguages)
        .where(MasLanguages.is_active == True)
        .order_by(MasLanguages.language_name)
    ).all()
    return [
        {"code": language.language_code, "name": language.language_name}
        for language in languages
    ]


def _validate_languages(languages):
    if not isinstance(languages, list) or not languages:
        return "At least one language must be selected."

    valid_codes = _active_language_codes()
    invalid = [code for code in languages if code not in valid_codes]
    if invalid:
        return f"Invalid language codes: {invalid}"

    return None
