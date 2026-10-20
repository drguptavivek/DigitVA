"""The shared case list API: ``/api/v1/cases`` (docs/policy/case-list-views.md).

Read-only GETs for the Deaths, VA Interview, VA Code and Supervision presets,
either credential. Gated by ``login_required`` on purpose: any grant reaches
some cases, and a caller with none gets an empty list (200), not a 403. Scope
and field visibility are decided per row in the service
(``app.services.case_list_service``); nothing here changes state, so there is
no CSRF surface. The supervision preset is empty under device credentials.
"""
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app import db, limiter
from app.routes.api.request_helpers import intake_error
from app.services import case_list_service as case_list
from app.services.web_intake_service import WebIntakeError

bp = Blueprint("cases_api", __name__)


@bp.after_request
def _no_store(response):
    # Case rows carry identifiers, errors included.
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.errorhandler(WebIntakeError)
def _bad_query(exc):
    db.session.rollback()
    return intake_error(exc)


@bp.get("")
@login_required
@limiter.limit("120 per minute")
def list_cases():
    """``{cases, counts, [tiles,] next_cursor}``; ``counts`` and ``tiles`` only
    without a ``cursor``. Query: ``preset``
    (``deaths`` default, ``interview``, ``coding``, ``supervision``),
    ``project_id``, ``site_id``, ``org_unit_id``, ``status`` (repeatable),
    ``state``, ``dod_from``, ``dod_to``, ``reported_from``, ``reported_to``,
    ``sex``, ``age_min``, ``age_max``, ``attention``, ``visit_note``, ``sort``, ``cursor``,
    ``limit``."""
    return jsonify(case_list.case_list_page(current_user._get_current_object(), request.args))


@bp.get("/filter-options")
@login_required
@limiter.limit("120 per minute")
def filter_options():
    """Projects, sites, units the caller's cases span."""
    return jsonify(case_list.filter_options(current_user._get_current_object()))
