"""Read-only admin language API routes."""

import sqlalchemy as sa
from flask import jsonify, request

from app import db
from app.decorators import role_required
from app.routes.admin import admin

from .queries import (
    _language_aliases_by_code,
    _language_submission_counts,
    _unmapped_submission_languages,
)


@admin.get("/api/languages")
@role_required("admin")
def admin_languages_list():
    from app.models.mas_languages import MasLanguages

    include_inactive = request.args.get("include_inactive") == "1"
    include_unmapped = request.args.get("include_unmapped") == "1"

    stmt = sa.select(MasLanguages).order_by(MasLanguages.language_name)
    if not include_inactive:
        stmt = stmt.where(MasLanguages.is_active == True)
    languages = db.session.scalars(stmt).all()

    submission_counts = _language_submission_counts()
    response = {
        "languages": [
            {
                "language_code": language.language_code,
                "language_name": language.language_name,
                "is_active": language.is_active,
                "aliases": _language_aliases_by_code(language.language_code),
                "submission_count": submission_counts.get(language.language_code, 0),
            }
            for language in languages
        ]
    }

    if include_unmapped:
        response["unmapped"] = _unmapped_submission_languages()

    return jsonify(response)
