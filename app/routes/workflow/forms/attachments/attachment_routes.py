"""Storage-token attachment routes."""

from __future__ import annotations

import os

from flask import abort, send_file

from app.authz.access import action_authorized
from app.authz.resources import attachment_form_from_storage_name

from .. import va_form
from .common import (
    enforce_attachment_file_access,
    get_attachment_lookup,
    validate_storage_name,
)


@va_form.route("/attachment/<path:storage_name_raw>")
@action_authorized(
    "attachment_view",
    resource_resolver=attachment_form_from_storage_name("storage_name_raw"),
)
def serve_attachment(storage_name_raw):
    from app import cache as flask_cache

    storage_name = validate_storage_name(storage_name_raw)

    cached = flask_cache.get(f"att:{storage_name}")
    if cached:
        local_path = cached["local_path"]
        mime_type = cached["mime_type"]
        va_form_id = cached["va_form_id"]
        va_sid = cached["va_sid"]
    else:
        local_path, mime_type, va_form_id, va_sid = get_attachment_lookup(storage_name)

    resolved = enforce_attachment_file_access(
        va_form_id=va_form_id,
        va_sid=va_sid,
        local_path=local_path,
    )

    if not os.path.isfile(resolved):
        flask_cache.delete(f"att:{storage_name}")
        abort(404)

    if not cached:
        flask_cache.set(
            f"att:{storage_name}",
            {
                "local_path": local_path,
                "mime_type": mime_type,
                "va_form_id": va_form_id,
                "va_sid": va_sid,
            },
            timeout=3600,
        )

    return send_file(resolved, mimetype=mime_type)
