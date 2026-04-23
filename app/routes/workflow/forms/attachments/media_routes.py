"""Filename-based form media routes."""

from __future__ import annotations

import os

from flask import current_app, send_from_directory

from app.authz.access import action_authorized
from app.authz.resources import form_from_kwarg

from .. import va_form
from ..helpers import _enforce_attachment_access
from .common import get_media_attachment_sid, validate_media_request


@va_form.route("/media/<va_form_id>/<va_filename>")
@action_authorized("attachment_view", resource_resolver=form_from_kwarg("va_form_id"))
def serve_media(va_form_id, va_filename):
    from app import cache as flask_cache

    safe_filename = validate_media_request(va_form_id, va_filename)

    att_cache_key = f"media:att:{va_form_id}:{va_filename}"
    cached_att = flask_cache.get(att_cache_key)
    if cached_att:
        cached_va_sid = cached_att["va_sid"]
    else:
        cached_va_sid = get_media_attachment_sid(
            va_form_id=va_form_id,
            va_filename=va_filename,
        )
        flask_cache.set(att_cache_key, {"va_sid": cached_va_sid}, timeout=300)

    _enforce_attachment_access(va_form_id=va_form_id, va_sid=cached_va_sid)

    media_base = os.path.join(current_app.config["APP_DATA"], va_form_id, "media")
    return send_from_directory(media_base, safe_filename)
