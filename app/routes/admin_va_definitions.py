"""Admin VA Definitions panel and API — WHO VA cause definitions master data.

Extends the ``admin`` blueprint the same way app/routes/admin_translations.py
does. Admin-only; writes are JSON with the X-CSRFToken header (global
CSRFProtect), sanitized server-side, stamped with ``updated_by`` and logged.
Policy: docs/policy/va-cause-definitions.md.
"""

import logging
import uuid

from flask import jsonify, render_template, request
from flask_login import current_user

from app.decorators import role_required
from app.routes.admin import _json_error, admin
from app.services.va_cause_definition_service import (
    create_va_definition,
    list_admin_va_definitions,
    update_va_definition,
)

log = logging.getLogger(__name__)


@admin.get("/panels/va-definitions")
@role_required("admin")
def admin_panel_va_definitions():
    return render_template("admin/panels/va_definitions.html")


@admin.get("/api/va-definitions")
@role_required("admin")
def admin_va_definitions_list():
    return jsonify({"definitions": list_admin_va_definitions()})


@admin.post("/api/va-definitions")
@role_required("admin")
def admin_va_definitions_create():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _json_error("A JSON object body is required.", 400)
    try:
        row = create_va_definition(body, user_id=current_user.user_id)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    log.info("va definition created | code=%s | by=%s", row["va_code"], current_user.user_id)
    return jsonify({"definition": row}), 201


@admin.patch("/api/va-definitions/<definition_id>")
@role_required("admin")
def admin_va_definitions_update(definition_id):
    try:
        definition_uuid = uuid.UUID(definition_id)
    except ValueError:
        return _json_error("VA definition not found.", 404)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _json_error("A JSON object body is required.", 400)
    try:
        row, changed = update_va_definition(definition_uuid, body, user_id=current_user.user_id)
    except LookupError:
        return _json_error("VA definition not found.", 404)
    except ValueError as exc:
        return _json_error(str(exc), 400)
    log.info(
        "va definition updated | code=%s | fields=%s | by=%s",
        row["va_code"], ",".join(changed) or "none", current_user.user_id,
    )
    return jsonify({"definition": row})
