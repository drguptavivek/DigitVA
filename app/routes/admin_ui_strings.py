"""Admin page and JSON API for correcting the Expo UI strings (digitva-fsjz).

Thin HTTP layer over ``app.services.ui_string_service``; every rule lives
there. Admin only, as the questionnaire translations editor is (decided
2026-10-12). Policy: docs/policy/ui-strings.md.

The panel renders the table on the server, the Google Translate link included,
so the page is complete without script. The script only sends the edit and
revert calls and reloads the panel after each one.
"""

import json
import logging
from urllib.parse import urlencode

from flask import Response, jsonify, render_template, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.routes.admin import _json_error, admin
from app.services.ui_string_service import (
    FILTERS,
    InvalidUiStringText,
    UiStringError,
    export,
    locales,
    revert,
    set_override,
    strings_for_admin,
)

log = logging.getLogger(__name__)

_API = "/api/ui-strings"
_PANEL = "/admin/panels/ui-strings"
_DEFAULT_PAGE_SIZE = 50


def _guard():
    """Admin only, checked again in the body as the translations editor does."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
    return None


def _panel_url(locale: str, status: str, page: int) -> str:
    return _PANEL + "?" + urlencode({"locale": locale, "status": status, "page": page})


@admin.get("/panels/ui-strings")
@role_required("admin")
def admin_panel_ui_strings():
    """The UI string table for one locale, one filter and one page."""
    locale = (request.args.get("locale") or "").strip()
    status = (request.args.get("status") or "all").strip()
    try:
        page = int(request.args.get("page") or 1)
    except ValueError:
        page = 1
    available = locales()
    if not locale and available:
        locale = available[0]

    error = None
    data = None
    if locale:
        try:
            data = strings_for_admin(locale, status, page, _DEFAULT_PAGE_SIZE)
        except UiStringError as exc:
            error = str(exc)
    if data is not None:
        last_page = max(1, -(-data["total"] // data["page_size"]))
    else:
        last_page = 1

    return render_template(
        "admin/panels/ui_strings.html",
        locales=available,
        locale=locale,
        status=status if status in FILTERS else "all",
        filters=FILTERS,
        data=data,
        error=error,
        page=data["page"] if data else 1,
        last_page=last_page,
        panel_url=_panel_url,
    )


@admin.get(f"{_API}/<locale>/export")
@role_required("admin")
def admin_ui_string_export(locale):
    """The bundled JSON with the corrections applied, as a download."""
    if err := _guard():
        return err
    try:
        body = export(locale)
    except UiStringError as exc:
        return _json_error(str(exc), 404)
    text = json.dumps(body, ensure_ascii=False, indent=2)
    return Response(
        text,
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{locale}.json"'},
    )


@admin.put(f"{_API}/<locale>/<path:string_key>")
@role_required("admin")
def admin_ui_string_put(locale, string_key):
    if err := _guard():
        return err
    payload = request.get_json(silent=True) or {}
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip():
        return _json_error("text is required.", 400)
    try:
        result = set_override(locale, string_key, text, current_user.user_id)
    except InvalidUiStringText as exc:
        db.session.rollback()
        return jsonify({"error": str(exc), "code": "invalid_translation"}), 422
    except UiStringError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    db.session.commit()
    return jsonify(result)


@admin.delete(f"{_API}/<locale>/<path:string_key>")
@role_required("admin")
def admin_ui_string_delete(locale, string_key):
    if err := _guard():
        return err
    try:
        result = revert(locale, string_key, current_user.user_id)
    except UiStringError as exc:
        db.session.rollback()
        return _json_error(str(exc), 400)
    db.session.commit()
    return jsonify(result)
