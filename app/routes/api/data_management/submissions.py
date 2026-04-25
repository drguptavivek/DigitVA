from __future__ import annotations

from flask import jsonify, request
from flask_login import current_user

from app import limiter
from app.authz.access import action_authorized
from app.services.data_management.dashboard import dm_submissions_page

from . import bp


@bp.get("/submissions")
@action_authorized("dm_submissions_view")
@limiter.limit("120 per minute")
def submissions():
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(10, request.args.get("size", 25, type=int)))
    sort_field = request.args.get("sort[0][field]", "va_submission_date")
    sort_dir = request.args.get("sort[0][dir]", "desc")

    result = dm_submissions_page(
        current_user,
        page=page,
        per_page=per_page,
        search=request.args.get("search", ""),
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
        sort_field=sort_field,
        sort_dir=sort_dir,
    )
    return jsonify(result)
