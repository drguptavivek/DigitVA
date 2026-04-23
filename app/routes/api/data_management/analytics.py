from __future__ import annotations

from flask import jsonify, request
from flask_login import current_user

from app import limiter
from app.routes.api import data_management as dm_routes
from app.authz.access import action_authorized
from app.services.data_management_service import (
    dm_coder_daily_statistics,
    dm_filter_options,
    reporting_scope_pairs,
)
from app.services.submission_analytics_mv import get_dm_project_site_stats_from_mv

from . import bp
from .helpers import cache_result, export_filters_from_request


@bp.get("/kpi")
@action_authorized("dm_kpi_view")
@limiter.limit("120 per minute")
def kpi():
    scope_pairs = reporting_scope_pairs(current_user)
    return jsonify(
        cache_result(
            "kpi",
            lambda: dm_routes.get_dm_kpi_from_mv(
                [],
                scope_pairs,
                project=request.args.get("project", ""),
                site=request.args.get("site", ""),
                date_from=request.args.get("date_from") or None,
                date_to=request.args.get("date_to") or None,
                odk_status=request.args.get("odk_status", ""),
                smartva=request.args.get("smartva", ""),
                age_group=request.args.get("age_group", ""),
                gender=request.args.get("gender", ""),
                odk_sync=request.args.get("odk_sync", ""),
                workflow=request.args.get("workflow", ""),
            ),
        )
    )


@bp.get("/coder-daily-stats")
@action_authorized("dm_kpi_view")
@limiter.limit("120 per minute")
def coder_daily_stats():
    filters = export_filters_from_request()
    return jsonify(
        cache_result(
            "coder_daily_stats",
            lambda: dm_coder_daily_statistics(
                current_user,
                **filters,
                days=7,
                timezone_name=getattr(current_user, "timezone", "Asia/Kolkata"),
            ),
        )
    )


@bp.get("/filter-options")
@action_authorized("dm_filter_options_view")
@limiter.limit("120 per minute")
def filter_options():
    return jsonify(dm_filter_options(current_user))


@bp.get("/project-site-submissions")
@action_authorized("dm_project_site_submissions_view")
@limiter.limit("120 per minute")
def project_site_submissions():
    return run_project_site_submissions()


def run_project_site_submissions():
    timezone_name = getattr(current_user, "timezone", "Asia/Kolkata") or "Asia/Kolkata"
    scope_pairs = reporting_scope_pairs(current_user)
    return jsonify(
        {
            "stats": get_dm_project_site_stats_from_mv(
                project_ids=[],
                project_site_pairs=scope_pairs,
                timezone_name=timezone_name,
                project=request.args.get("project", ""),
                site=request.args.get("site", ""),
                date_from=request.args.get("date_from") or None,
                date_to=request.args.get("date_to") or None,
                odk_status=request.args.get("odk_status", ""),
                smartva=request.args.get("smartva", ""),
                age_group=request.args.get("age_group", ""),
                gender=request.args.get("gender", ""),
                odk_sync=request.args.get("odk_sync", ""),
                workflow=request.args.get("workflow", ""),
            ),
            "timezone": timezone_name,
        }
    )
