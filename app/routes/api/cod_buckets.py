"""COD bucket reporting API — /api/v1/cod-buckets/"""

from __future__ import annotations

import uuid
from datetime import datetime

from flask import Blueprint, jsonify, request, session
from flask_login import current_user

from app import db
from app.authz.access import action_authorized
from app.models import VaUsers
from app.services.analytics.cod_buckets import (
    aggregate_coded_submissions_by_bucket,
    list_unmatched_coded_submission_icds_by_bucket,
    list_cod_bucket_schemes,
    summarize_unmatched_coded_submissions_by_bucket,
)
from app.services.analytics.data_management import dm_scoped_forms

bp = Blueprint("cod_buckets_api", __name__)


def _parse_iso_date(value: str | None):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _resolved_scope_user():
    """Prefer the explicit session user when computing per-user DM scope."""
    raw_user_id = session.get("_user_id")
    if raw_user_id:
        try:
            session_user_id = uuid.UUID(str(raw_user_id))
        except (TypeError, ValueError):
            session_user_id = None
        if session_user_id is not None:
            session_user = db.session.get(VaUsers, session_user_id)
            if session_user is not None:
                return session_user
    return current_user


@bp.get("/schemes")
@action_authorized("cod_dashboard_view")
def schemes():
    rows = [
        {
            "scheme_code": scheme.scheme_code,
            "scheme_name": scheme.scheme_name,
            "mapping_version": scheme.mapping_version,
            "is_active": scheme.is_active,
            "source_path": scheme.source_path,
        }
        for scheme in list_cod_bucket_schemes()
        if scheme.is_active
    ]
    return jsonify({"data": rows})


@bp.get("/aggregates")
@action_authorized("cod_dashboard_view")
def aggregates():
    forms = dm_scoped_forms(_resolved_scope_user())
    allowed_pairs = {(row["project_id"], row["site_id"]) for row in forms}
    form_ids = {row["form_id"] for row in forms}

    project_id = (request.args.get("project_id") or "").strip() or None
    site_id = (request.args.get("site_id") or "").strip() or None
    form_id = (request.args.get("form_id") or "").strip() or None
    if form_id and form_id not in form_ids:
        return jsonify({"error": "Form is outside your data-manager scope."}), 403

    rows = aggregate_coded_submissions_by_bucket(
        scheme_code=request.args.get("scheme_code", "").strip() or "SRS_INDIA",
        project_id=project_id,
        site_id=site_id,
        form_id=form_id,
        submission_date_from=_parse_iso_date(request.args.get("date_from")),
        submission_date_to=_parse_iso_date(request.args.get("date_to")),
        allowed_project_site_pairs=allowed_pairs,
        collapse_scope=True,
    )
    unmatched_rows = summarize_unmatched_coded_submissions_by_bucket(
        scheme_code=request.args.get("scheme_code", "").strip() or "SRS_INDIA",
        project_id=project_id,
        site_id=site_id,
        form_id=form_id,
        submission_date_from=_parse_iso_date(request.args.get("date_from")),
        submission_date_to=_parse_iso_date(request.args.get("date_to")),
        allowed_project_site_pairs=allowed_pairs,
        collapse_scope=True,
    )
    unmatched_icd_rows = list_unmatched_coded_submission_icds_by_bucket(
        scheme_code=request.args.get("scheme_code", "").strip() or "SRS_INDIA",
        project_id=project_id,
        site_id=site_id,
        form_id=form_id,
        submission_date_from=_parse_iso_date(request.args.get("date_from")),
        submission_date_to=_parse_iso_date(request.args.get("date_to")),
        allowed_project_site_pairs=allowed_pairs,
        collapse_scope=True,
    )
    return jsonify(
        {
            "data": rows,
            "summary": {
                "unmatched_by_age_scope": unmatched_rows,
                "unmatched_icd_breakdown": unmatched_icd_rows,
            },
            "filters": {
                "scheme_code": request.args.get("scheme_code", "").strip() or "SRS_INDIA",
                "project_id": project_id,
                "site_id": site_id,
                "form_id": form_id,
                "date_from": request.args.get("date_from") or None,
                "date_to": request.args.get("date_to") or None,
            },
        }
    )
