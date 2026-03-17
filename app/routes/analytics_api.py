"""Analytics API blueprint — resource-oriented analytics endpoints from the submissions MV.

Routes are organised by resource:
  /api/analytics/kpi               — headline KPI counts
  /api/analytics/submissions       — submission volume aggregations
  /api/analytics/demographics      — age-band and sex distribution
  /api/analytics/workflow          — workflow-state breakdown
  /api/analytics/cod               — cause-of-death (ICD) summary
  /api/analytics/mv/refresh        — on-demand MV refresh (POST)

All GET endpoints are scoped to the current user's data-manager grants.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from flask import request as flask_request
from app import db, limiter, cache
from app.services.submission_analytics_mv import (
    MV_NAME,
    get_dm_kpi_from_mv,
    refresh_submission_analytics_mv,
)

analytics_api = Blueprint("analytics_api", __name__)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared MV table reference
# ---------------------------------------------------------------------------

_mv = sa.table(
    MV_NAME,
    sa.column("va_sid"),
    sa.column("project_id"),
    sa.column("site_id"),
    sa.column("submission_date"),
    sa.column("submission_week_start"),
    sa.column("submission_month_start"),
    sa.column("workflow_state"),
    sa.column("odk_review_state"),
    sa.column("has_sync_issue"),
    sa.column("has_smartva"),
    sa.column("sex"),
    sa.column("analytics_age_band"),
    sa.column("has_human_final_cod"),
    sa.column("final_icd"),
    sa.column("final_cod_text"),
    sa.column("has_human_initial_cod"),
    sa.column("initial_immediate_icd"),
)


def _dm_scope_filter():
    """WHERE clause restricted to the current data-manager user's grants."""
    project_ids = sorted(current_user.get_data_manager_projects())
    project_site_pairs = current_user.get_data_manager_project_sites()

    project_clause = sa.false()
    if project_ids:
        project_clause = _mv.c.project_id.in_(project_ids)

    site_clause = sa.false()
    if project_site_pairs:
        site_clause = sa.tuple_(_mv.c.project_id, _mv.c.site_id).in_(
            list(project_site_pairs)
        )

    return sa.or_(project_clause, site_clause)


def _require_data_manager():
    if not current_user.is_data_manager():
        return jsonify({"error": "Data-manager access is required."}), 403
    return None


def _user_cache_key():
    """Per-user cache key: endpoint + query string, namespaced by user ID."""
    qs = flask_request.query_string.decode()
    return f"analytics_api:{current_user.id}:{flask_request.endpoint}:{qs}"


def _bust_user_analytics_cache():
    """Delete all analytics cache entries for the current user."""
    pattern = f"{cache.config.get('CACHE_KEY_PREFIX', '')}analytics_api:{current_user.id}:*"
    try:
        redis_client = cache.cache._write_client
        keys = redis_client.keys(pattern)
        if keys:
            redis_client.delete(*keys)
    except Exception as exc:
        log.warning("Could not bust analytics cache for user %s: %s", current_user.id, exc)


# ---------------------------------------------------------------------------
# Resource: KPI
# ---------------------------------------------------------------------------


@analytics_api.get("/kpi")
@login_required
@cache.cached(timeout=300, make_cache_key=_user_cache_key)
def kpi():
    """Headline KPI counts from the analytics MV, scoped to the user's grants.

    Response:
        {
            "total_submissions": int,
            "flagged_submissions": int,
            "odk_has_issues_submissions": int,
            "smartva_missing_submissions": int
        }
    """
    err = _require_data_manager()
    if err:
        return err

    return jsonify(
        get_dm_kpi_from_mv(
            project_ids=sorted(current_user.get_data_manager_projects()),
            project_site_pairs=current_user.get_data_manager_project_sites(),
        )
    )


# ---------------------------------------------------------------------------
# Resource: Submissions
# ---------------------------------------------------------------------------


@analytics_api.get("/submissions/by-date")
@login_required
@cache.cached(timeout=300, make_cache_key=_user_cache_key)
def submissions_by_date():
    """Submission counts grouped by calendar date.

    Query params:
        limit (int, default 90): number of most-recent dates to return

    Response:
        {"data": [{"date": "YYYY-MM-DD", "count": int}, ...]}
    """
    err = _require_data_manager()
    if err:
        return err

    limit = min(int(request.args.get("limit", 90)), 365)
    scope = _dm_scope_filter()

    rows = db.session.execute(
        sa.select(
            _mv.c.submission_date.label("date"),
            sa.func.count().label("count"),
        )
        .where(scope)
        .where(_mv.c.submission_date.isnot(None))
        .group_by(_mv.c.submission_date)
        .order_by(_mv.c.submission_date.desc())
        .limit(limit)
    ).mappings().all()

    return jsonify({"data": [{"date": str(r["date"]), "count": r["count"]} for r in rows]})


@analytics_api.get("/submissions/by-week")
@login_required
@cache.cached(timeout=300, make_cache_key=_user_cache_key)
def submissions_by_week():
    """Submission counts grouped by ISO week start (Monday).

    Query params:
        limit (int, default 26): number of most-recent weeks to return

    Response:
        {"data": [{"week_start": "YYYY-MM-DD", "count": int}, ...]}
    """
    err = _require_data_manager()
    if err:
        return err

    limit = min(int(request.args.get("limit", 26)), 104)
    scope = _dm_scope_filter()

    rows = db.session.execute(
        sa.select(
            _mv.c.submission_week_start.label("week_start"),
            sa.func.count().label("count"),
        )
        .where(scope)
        .where(_mv.c.submission_week_start.isnot(None))
        .group_by(_mv.c.submission_week_start)
        .order_by(_mv.c.submission_week_start.desc())
        .limit(limit)
    ).mappings().all()

    return jsonify(
        {"data": [{"week_start": str(r["week_start"]), "count": r["count"]} for r in rows]}
    )


@analytics_api.get("/submissions/by-month")
@login_required
@cache.cached(timeout=300, make_cache_key=_user_cache_key)
def submissions_by_month():
    """Submission counts grouped by month start.

    Query params:
        limit (int, default 12): number of most-recent months to return

    Response:
        {"data": [{"month_start": "YYYY-MM-DD", "count": int}, ...]}
    """
    err = _require_data_manager()
    if err:
        return err

    limit = min(int(request.args.get("limit", 12)), 60)
    scope = _dm_scope_filter()

    rows = db.session.execute(
        sa.select(
            _mv.c.submission_month_start.label("month_start"),
            sa.func.count().label("count"),
        )
        .where(scope)
        .where(_mv.c.submission_month_start.isnot(None))
        .group_by(_mv.c.submission_month_start)
        .order_by(_mv.c.submission_month_start.desc())
        .limit(limit)
    ).mappings().all()

    return jsonify(
        {"data": [{"month_start": str(r["month_start"]), "count": r["count"]} for r in rows]}
    )


# ---------------------------------------------------------------------------
# Resource: Demographics
# ---------------------------------------------------------------------------


@analytics_api.get("/demographics")
@login_required
@cache.cached(timeout=300, make_cache_key=_user_cache_key)
def demographics():
    """Age-band and sex distribution from the analytics MV.

    Response:
        {
            "age_bands": [{"band": str, "count": int}, ...],
            "sex": [{"sex": str, "count": int}, ...]
        }
    """
    err = _require_data_manager()
    if err:
        return err

    scope = _dm_scope_filter()

    age_rows = db.session.execute(
        sa.select(
            _mv.c.analytics_age_band.label("band"),
            sa.func.count().label("count"),
        )
        .where(scope)
        .group_by(_mv.c.analytics_age_band)
        .order_by(sa.func.count().desc())
    ).mappings().all()

    sex_rows = db.session.execute(
        sa.select(
            _mv.c.sex.label("sex"),
            sa.func.count().label("count"),
        )
        .where(scope)
        .group_by(_mv.c.sex)
        .order_by(sa.func.count().desc())
    ).mappings().all()

    return jsonify(
        {
            "age_bands": [{"band": r["band"], "count": r["count"]} for r in age_rows],
            "sex": [{"sex": r["sex"], "count": r["count"]} for r in sex_rows],
        }
    )


# ---------------------------------------------------------------------------
# Resource: Workflow
# ---------------------------------------------------------------------------


@analytics_api.get("/workflow")
@login_required
@cache.cached(timeout=300, make_cache_key=_user_cache_key)
def workflow():
    """Workflow-state breakdown from the analytics MV.

    Response:
        {"data": [{"state": str, "count": int}, ...]}
    """
    err = _require_data_manager()
    if err:
        return err

    scope = _dm_scope_filter()

    rows = db.session.execute(
        sa.select(
            _mv.c.workflow_state.label("state"),
            sa.func.count().label("count"),
        )
        .where(scope)
        .group_by(_mv.c.workflow_state)
        .order_by(sa.func.count().desc())
    ).mappings().all()

    return jsonify({"data": [{"state": r["state"], "count": r["count"]} for r in rows]})


# ---------------------------------------------------------------------------
# Resource: Cause of Death (COD)
# ---------------------------------------------------------------------------


@analytics_api.get("/cod")
@login_required
@cache.cached(timeout=300, make_cache_key=_user_cache_key)
def cod():
    """Top cause-of-death ICD codes from the analytics MV.

    Query params:
        limit (int, default 20): max ICD codes to return per category
        type ("final"|"initial", default "final"): which COD to aggregate

    Response:
        {"data": [{"icd": str, "cod_text": str, "count": int}, ...], "type": str}
    """
    err = _require_data_manager()
    if err:
        return err

    cod_type = request.args.get("type", "final")
    limit = min(int(request.args.get("limit", 20)), 100)
    scope = _dm_scope_filter()

    if cod_type == "initial":
        icd_col = _mv.c.initial_immediate_icd
        text_col = sa.literal(None)
        has_col = _mv.c.has_human_initial_cod
    else:
        icd_col = _mv.c.final_icd
        text_col = _mv.c.final_cod_text
        has_col = _mv.c.has_human_final_cod

    rows = db.session.execute(
        sa.select(
            icd_col.label("icd"),
            sa.func.max(text_col).label("cod_text"),
            sa.func.count().label("count"),
        )
        .where(scope)
        .where(has_col.is_(True))
        .where(icd_col.isnot(None))
        .group_by(icd_col)
        .order_by(sa.func.count().desc())
        .limit(limit)
    ).mappings().all()

    return jsonify(
        {
            "type": cod_type,
            "data": [
                {"icd": r["icd"], "cod_text": r["cod_text"], "count": r["count"]}
                for r in rows
            ],
        }
    )


# ---------------------------------------------------------------------------
# Resource: MV management
# ---------------------------------------------------------------------------


@analytics_api.post("/mv/refresh")
@login_required
@limiter.limit("1 per minute")
def mv_refresh():
    """Refresh the submission analytics materialized view on demand.

    Response (200):  {"message": "..."}
    Response (500):  {"error": "..."}
    """
    err = _require_data_manager()
    if err:
        return err

    try:
        refresh_submission_analytics_mv(concurrently=True)
    except Exception as exc:
        log.exception("On-demand analytics MV refresh failed: %s", exc)
        return jsonify({"error": "Analytics refresh failed. Check server logs."}), 500

    _bust_user_analytics_cache()
    return jsonify({"message": "Analytics data refreshed successfully."}), 200
