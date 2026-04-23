"""Mutation-oriented admin language API routes."""

import sqlalchemy as sa
from flask import jsonify, request

from app import db
from app.decorators import role_required
from app.http.responses import json_error as _json_error
from app.routes.admin import admin


@admin.post("/api/languages")
@role_required("admin")
def admin_languages_create():
    from app.models.mas_languages import MapLanguageAliases, MasLanguages

    payload = request.get_json(silent=True) or {}
    code = (payload.get("language_code") or "").strip().lower()
    name = (payload.get("language_name") or "").strip()
    aliases = payload.get("aliases", [])

    if not code or not name:
        return _json_error("language_code and language_name are required.", 400)

    if db.session.get(MasLanguages, code):
        return _json_error(f"Language code '{code}' already exists.", 400)

    language = MasLanguages(language_code=code, language_name=name, is_active=True)
    db.session.add(language)

    alias_values = {code}
    for alias in aliases:
        alias = alias.strip().lower()
        if alias:
            alias_values.add(alias)

    for alias in alias_values:
        existing_alias = db.session.get(MapLanguageAliases, alias)
        if existing_alias:
            return _json_error(
                f"Alias '{alias}' is already mapped to '{existing_alias.language_code}'.",
                400,
            )
        db.session.add(MapLanguageAliases(alias=alias, language_code=code))

    db.session.commit()
    return jsonify({"language_code": code, "language_name": name}), 201


@admin.put("/api/languages/<language_code>")
@role_required("admin")
def admin_languages_update(language_code):
    from app.models.mas_languages import MapLanguageAliases, MasLanguages

    language = db.session.get(MasLanguages, language_code)
    if not language:
        return _json_error("Language not found.", 404)

    payload = request.get_json(silent=True) or {}

    if "language_name" in payload:
        name = (payload["language_name"] or "").strip()
        if not name:
            return _json_error("language_name cannot be empty.", 400)
        language.language_name = name

    if "aliases" in payload:
        new_aliases = set()
        for alias in payload["aliases"]:
            alias = alias.strip().lower()
            if alias:
                new_aliases.add(alias)
        new_aliases.add(language_code)

        for alias in new_aliases:
            existing_alias = db.session.get(MapLanguageAliases, alias)
            if existing_alias and existing_alias.language_code != language_code:
                return _json_error(
                    f"Alias '{alias}' is already mapped to '{existing_alias.language_code}'.",
                    400,
                )

        current_aliases = db.session.scalars(
            sa.select(MapLanguageAliases).where(
                MapLanguageAliases.language_code == language_code
            )
        ).all()
        for alias_obj in current_aliases:
            if alias_obj.alias.lower() not in new_aliases:
                db.session.delete(alias_obj)

        current_alias_set = {alias_obj.alias.lower() for alias_obj in current_aliases}
        for alias in new_aliases:
            if alias not in current_alias_set:
                db.session.add(
                    MapLanguageAliases(alias=alias, language_code=language_code)
                )

    db.session.commit()
    return jsonify(
        {
            "language_code": language.language_code,
            "language_name": language.language_name,
        }
    )


@admin.post("/api/languages/<language_code>/toggle")
@role_required("admin")
def admin_languages_toggle(language_code):
    from app.models.mas_languages import MasLanguages

    language = db.session.get(MasLanguages, language_code)
    if not language:
        return _json_error("Language not found.", 404)

    language.is_active = not language.is_active
    db.session.commit()
    return jsonify(
        {
            "language_code": language.language_code,
            "is_active": language.is_active,
        }
    )


@admin.delete("/api/languages/<language_code>/aliases/<alias>")
@role_required("admin")
def admin_languages_delete_alias(language_code, alias):
    from app.models.mas_languages import MapLanguageAliases

    if alias.lower() == language_code.lower():
        return _json_error(
            "Cannot remove the primary alias (matches language code).",
            400,
        )

    alias_obj = db.session.get(MapLanguageAliases, alias)
    if not alias_obj:
        return _json_error("Alias not found.", 404)
    if alias_obj.language_code != language_code:
        return _json_error("Alias does not belong to this language.", 400)

    db.session.delete(alias_obj)
    db.session.commit()
    return jsonify({"deleted": alias})
