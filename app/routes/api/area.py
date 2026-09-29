"""Area dashboard JSON API: counts for the part of a project a user oversees.

Read-only GETs, so no CSRF surface. Gated by ``login_required`` rather than a
role list on purpose: any grant of any role opens an area, and a user with no
grant gets an empty project list, not an error (docs/policy/area-dashboard.md).
A project, unit or site outside the user's area is a 404, never a 403, so its
existence does not leak. Counts only: no case lists, subject data or names.
"""

from datetime import UTC, datetime

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from app import limiter
from app.services import area_dashboard_service as area

bp = Blueprint("area_api", __name__)

_MAX_PARAM_LENGTH = 64


def _param(name: str) -> str:
    return (request.args.get(name) or "").strip()


def _display_time(value) -> str | None:
    return current_app.jinja_env.filters["user_timezone"](value, "%Y-%m-%d %H:%M") or None


@bp.get("/projects")
@login_required
@limiter.limit("120 per minute")
def projects():
    return jsonify({"projects": area.area_projects(current_user)})


@bp.get("/summary")
@login_required
@limiter.limit("120 per minute")
def summary():
    project_id, unit_id, site_id = _param("project"), _param("unit"), _param("site")
    if not project_id:
        return jsonify({"error": "project is required."}), 400
    if any(len(value) > _MAX_PARAM_LENGTH for value in (project_id, unit_id, site_id)):
        return jsonify({"error": "Not found."}), 404
    try:
        result = area.area_summary(
            current_user, project_id, unit_id=unit_id or None, site_id=site_id or None
        )
    except area.AreaNotFound:
        return jsonify({"error": "Not found."}), 404

    refreshed_at = area.snapshot_refreshed_at()
    result["freshness"] = {
        "snapshot_refreshed_at": refreshed_at.isoformat() if refreshed_at else None,
        "snapshot_refreshed_display": _display_time(refreshed_at),
        "live_at_display": _display_time(datetime.now(UTC)),
    }
    return jsonify(result)
