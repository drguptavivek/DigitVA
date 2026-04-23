"""Shared query helpers for admin language routes."""

import sqlalchemy as sa

from app import db


def _language_aliases_by_code(language_code):
    from app.models.mas_languages import MapLanguageAliases

    return db.session.scalars(
        sa.select(MapLanguageAliases.alias)
        .where(MapLanguageAliases.language_code == language_code)
        .order_by(MapLanguageAliases.alias)
    ).all()


def _language_submission_counts():
    return dict(
        db.session.execute(
            sa.text(
                """
                SELECT va_narration_language, COUNT(*)
                FROM va_submissions
                GROUP BY va_narration_language
                """
            )
        ).all()
    )


def _unmapped_submission_languages():
    from app.models.mas_languages import MapLanguageAliases, MasLanguages

    all_aliases = set(
        db.session.scalars(sa.select(sa.func.lower(MapLanguageAliases.alias))).all()
    )
    all_codes = set(
        db.session.scalars(sa.select(MasLanguages.language_code)).all()
    )
    known = all_aliases | all_codes

    unmapped_rows = db.session.execute(
        sa.text(
            """
            SELECT va_narration_language, COUNT(*) as cnt
            FROM va_submissions
            WHERE va_narration_language IS NOT NULL
              AND va_narration_language != ''
            GROUP BY va_narration_language
            ORDER BY cnt DESC
            """
        )
    ).all()
    return [
        {"value": row[0], "count": row[1]}
        for row in unmapped_rows
        if row[0].lower() not in known
    ]
