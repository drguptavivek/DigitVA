"""COD bucket reporting API — /api/v1/cod-buckets/"""

from __future__ import annotations

import uuid
from datetime import datetime

from flask import Blueprint, Response, jsonify, request, session
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import VaUsers
from app.services.cod_bucket_mapping_service import (
    aggregate_coded_submissions_by_bucket,
    export_cod_bucket_reporting_csv,
    list_unmatched_coded_submission_icds_by_bucket,
    list_cod_bucket_schemes,
    SCHEME_CODE_WHO_2022_VA,
    summarize_cod_bucket_reporting_breakdowns,
    summarize_unmatched_coded_submissions_by_bucket,
)
from app.services.data_management_service import dm_scoped_forms

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


def _csv_response(csv_text: str, filename_prefix: str) -> Response:
    filename = f"{filename_prefix}-{datetime.utcnow():%Y%m%d-%H%M%S}.csv"
    return Response(
        "\ufeff" + csv_text,
        content_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


@bp.get("/schemes")
@role_required("data_manager", "admin")
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
@role_required("data_manager", "admin")
def aggregates():
    forms = dm_scoped_forms(_resolved_scope_user())
    allowed_pairs = {(row["project_id"], row["site_id"]) for row in forms}
    form_ids = {row["form_id"] for row in forms}

    project_id = (request.args.get("project_id") or "").strip() or None
    site_id = (request.args.get("site_id") or "").strip() or None
    form_id = (request.args.get("form_id") or "").strip() or None
    gender = (request.args.get("gender") or "").strip() or None
    if form_id and form_id not in form_ids:
        return jsonify({"error": "Form is outside your data-manager scope."}), 403

    rows = aggregate_coded_submissions_by_bucket(
        scheme_code=request.args.get("scheme_code", "").strip() or SCHEME_CODE_WHO_2022_VA,
        project_id=project_id,
        site_id=site_id,
        form_id=form_id,
        gender=gender,
        submission_date_from=_parse_iso_date(request.args.get("date_from")),
        submission_date_to=_parse_iso_date(request.args.get("date_to")),
        allowed_project_site_pairs=allowed_pairs,
        collapse_scope=True,
    )
    unmatched_rows = summarize_unmatched_coded_submissions_by_bucket(
        scheme_code=request.args.get("scheme_code", "").strip() or SCHEME_CODE_WHO_2022_VA,
        project_id=project_id,
        site_id=site_id,
        form_id=form_id,
        gender=gender,
        submission_date_from=_parse_iso_date(request.args.get("date_from")),
        submission_date_to=_parse_iso_date(request.args.get("date_to")),
        allowed_project_site_pairs=allowed_pairs,
        collapse_scope=True,
    )
    unmatched_icd_rows = list_unmatched_coded_submission_icds_by_bucket(
        scheme_code=request.args.get("scheme_code", "").strip() or SCHEME_CODE_WHO_2022_VA,
        project_id=project_id,
        site_id=site_id,
        form_id=form_id,
        gender=gender,
        submission_date_from=_parse_iso_date(request.args.get("date_from")),
        submission_date_to=_parse_iso_date(request.args.get("date_to")),
        allowed_project_site_pairs=allowed_pairs,
        collapse_scope=True,
    )
    reporting_breakdowns = summarize_cod_bucket_reporting_breakdowns(
        scheme_code=request.args.get("scheme_code", "").strip() or SCHEME_CODE_WHO_2022_VA,
        project_id=project_id,
        site_id=site_id,
        form_id=form_id,
        gender=gender,
        submission_date_from=_parse_iso_date(request.args.get("date_from")),
        submission_date_to=_parse_iso_date(request.args.get("date_to")),
        allowed_project_site_pairs=allowed_pairs,
        top_n=10,
    )
    return jsonify(
        {
            "data": rows,
            "summary": {
                "unmatched_by_age_scope": unmatched_rows,
                "unmatched_icd_breakdown": unmatched_icd_rows,
                "scheme_used": reporting_breakdowns["scheme_used"],
                "top_causes": reporting_breakdowns["top_causes"],
                "top_causes_by_age": reporting_breakdowns["top_causes_by_age"],
                "first_level_counts": reporting_breakdowns["first_level_counts"],
                "first_level_counts_by_age": reporting_breakdowns["first_level_counts_by_age"],
                "age_filters": reporting_breakdowns["age_filters"],
                "age_sex_distribution": reporting_breakdowns["age_sex_distribution"],
                "gender_distribution": reporting_breakdowns["gender_distribution"],
                "heatmap": reporting_breakdowns["heatmap"],
                "treemap": reporting_breakdowns["treemap"],
                "matched_total": reporting_breakdowns["matched_total"],
            },
            "filters": {
                "scheme_code": request.args.get("scheme_code", "").strip() or SCHEME_CODE_WHO_2022_VA,
                "project_id": project_id,
                "site_id": site_id,
                "form_id": form_id,
                "gender": gender,
                "date_from": request.args.get("date_from") or None,
                "date_to": request.args.get("date_to") or None,
            },
        }
    )


@bp.get("/export.csv")
@role_required("data_manager", "admin")
def export_csv():
    forms = dm_scoped_forms(_resolved_scope_user())
    allowed_pairs = {(row["project_id"], row["site_id"]) for row in forms}
    form_ids = {row["form_id"] for row in forms}

    project_id = (request.args.get("project_id") or "").strip() or None
    site_id = (request.args.get("site_id") or "").strip() or None
    form_id = (request.args.get("form_id") or "").strip() or None
    gender = (request.args.get("gender") or "").strip() or None
    if form_id and form_id not in form_ids:
        return jsonify({"error": "Form is outside your data-manager scope."}), 403

    csv_text = export_cod_bucket_reporting_csv(
        scheme_code=request.args.get("scheme_code", "").strip() or SCHEME_CODE_WHO_2022_VA,
        project_id=project_id,
        site_id=site_id,
        form_id=form_id,
        gender=gender,
        submission_date_from=_parse_iso_date(request.args.get("date_from")),
        submission_date_to=_parse_iso_date(request.args.get("date_to")),
        allowed_project_site_pairs=allowed_pairs,
    )
    return _csv_response(csv_text, filename_prefix="cod-bucket-report")
