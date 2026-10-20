"""Contextual in-page help API (/api/v1/help/contextual)."""

from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from app import limiter
from app.routes.api.request_helpers import error
from app.services import contextual_help_service
from app.services.authz import effective_roles

bp = Blueprint("help_contextual_api", __name__)


@bp.get("/contextual")
@login_required
@limiter.limit("120 per minute")
def all_contextual_help():
    """Return all contextual in-page help entries keyed by page_key."""
    effective_roles(current_user._get_current_object())
    return jsonify({"pages": contextual_help_service.list_contextual_help()})


@bp.get("/contextual/<string:page_key>")
@login_required
@limiter.limit("120 per minute")
def get_page_contextual_help(page_key: str):
    """Return the contextual in-page help for a single page_key."""
    effective_roles(current_user._get_current_object())
    entry = contextual_help_service.get_contextual_help(page_key)
    if entry is None:
        return error("Unknown contextual help page key.", "not_found", 404)
    return jsonify(entry)
