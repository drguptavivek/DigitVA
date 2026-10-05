"""Area dashboard JSON API: counts for the part of a project a user oversees.

Read-only GETs, so no CSRF surface. Gated by ``login_required`` rather than a
role list on purpose: any grant of any role opens an area, and a user with no
grant gets an empty project list, not an error (docs/policy/area-dashboard.md).
A project, unit or site outside the user's area is a 404, never a 403, so its
existence does not leak. Counts only: no case lists or subject data; links go
only to screens the user's role already has. Staff names come only from
``/staff``, and only for a viewer ``should_redact_pii`` allows.
"""

from datetime import UTC, datetime

from flask import Blueprint, current_app, jsonify, request, url_for
from flask_login import current_user, login_required

from app import limiter
from app.routes.api.request_helpers import error as api_error
from app.services import area_dashboard_service as area
from app.services import authz

bp = Blueprint("area_api", __name__)

_MAX_PARAM_LENGTH = 64


def _param(name: str) -> str:
    return (request.args.get(name) or "").strip()


def _display_time(value) -> str | None:
    return current_app.jinja_env.filters["user_timezone"](value, "%Y-%m-%d %H:%M") or None


def _link_urls(links: dict) -> dict:
    """Count key -> URL. Endpoints come from the service's fixed screen list;
    params are project, site and workflow codes only, never subject data."""
    return {key: url_for(link["endpoint"], **link["params"]) for key, link in links.items()}


@bp.get("/projects")
@login_required
@limiter.limit("120 per minute")
def projects():
    return jsonify({"projects": area.area_projects(current_user)})


def _area_params():
    """(project, unit, site) from the query string, or an error response.

    No grant of any role is no area anywhere: authz decides that first, so
    such a user is told "not found" whatever the parameters.
    """
    if not authz.effective_roles(current_user):
        return None, api_error("Not found.", status_code=404)
    project_id, unit_id, site_id = _param("project"), _param("unit"), _param("site")
    if not project_id:
        return None, api_error("project is required.", status_code=400)
    if any(len(value) > _MAX_PARAM_LENGTH for value in (project_id, unit_id, site_id)):
        return None, api_error("Not found.", status_code=404)
    return (project_id, unit_id, site_id), None


@bp.get("/staff")
@login_required
@limiter.limit("120 per minute")
def staff():
    """Per-interviewer and per-coder counts for the selected unit or site
    (or a project-wide root). A viewer barred from staff identity gets
    ``staff_identity_redacted`` and no rows."""
    params, error = _area_params()
    if error:
        return error
    project_id, unit_id, site_id = params
    try:
        result = area.area_staff(
            current_user, project_id, unit_id=unit_id or None, site_id=site_id or None
        )
    except area.AreaNotFound:
        return api_error("Not found.", status_code=404)
    return jsonify(result)


@bp.get("/summary")
@login_required
@limiter.limit("120 per minute")
def summary():
    params, error = _area_params()
    if error:
        return error
    project_id, unit_id, site_id = params
    try:
        result = area.area_summary(
            current_user, project_id, unit_id=unit_id or None, site_id=site_id or None
        )
    except area.AreaNotFound:
        return api_error("Not found.", status_code=404)

    if result["project_card"]:
        result["project_card"]["links"] = _link_urls(result["project_card"]["links"])
    for row in result["rows"]:
        if row.get("links"):
            row["links"] = _link_urls(row["links"])

    refreshed_at = area.snapshot_refreshed_at()
    result["freshness"] = {
        "snapshot_refreshed_at": refreshed_at.isoformat() if refreshed_at else None,
        "snapshot_refreshed_display": _display_time(refreshed_at),
        "live_at_display": _display_time(datetime.now(UTC)),
    }
    return jsonify(result)
