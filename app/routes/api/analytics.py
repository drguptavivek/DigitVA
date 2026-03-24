"""Analytics API — /api/v1/analytics/

Resources:
  GET  kpi                    — headline KPI counts
  GET  submissions/by-date    — daily submission volumes
  GET  submissions/by-week    — weekly submission volumes
  GET  submissions/by-month   — monthly submission volumes
  GET  demographics           — age-band and sex distribution
  GET  workflow               — workflow-state breakdown
  GET  cod                    — cause-of-death (ICD) summary
  POST mv/refresh             — on-demand MV refresh (rate-limited 1/min)

All endpoints scoped to the current user's data-manager grants.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user

from app import db, limiter, cache
from app.services.submission_analytics_mv import (
    MV_NAME,
    build_dm_mv_filter_conditions,
    get_dm_kpi_from_mv,
    refresh_submission_analytics_mv,
)

bp = Blueprint("analytics", __name__)
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

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CACHE_TTL = 300  # 5 minutes


def _require_data_manager():
    if not current_user.is_data_manager():
        return jsonify({"error": "Data-manager access is required."}), 403
    return None


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


def _cache_key(suffix: str) -> str:
    qs = request.query_string.decode()
    return f"analytics:{current_user.user_id}:{suffix}:{qs}"


def _cached(key: str, compute_fn, timeout: int = _CACHE_TTL):
    full_key = _cache_key(key)
    try:
        data = cache.get(full_key)
    except Exception:
        data = None
    if data is not None and not isinstance(data, BaseException):
        return data
    data = compute_fn()
    try:
        cache.set(full_key, data, timeout=timeout)
    except Exception as exc:
        log.warning("Analytics cache set failed (%s): %s", full_key, exc)
    return data


def _bust_user_analytics_cache():
    prefix = cache.config.get("CACHE_KEY_PREFIX", "")
    pattern = f"{prefix}analytics:{current_user.user_id}:*"
    try:
        redis_client = cache.cache._write_client
        keys = redis_client.keys(pattern)
        if keys:
            redis_client.delete(*keys)
    except Exception as exc:
        log.warning("Could not bust analytics cache for user %s: %s", current_user.user_id, exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.get("/kpi")
@login_required
def kpi():
    err = _require_data_manager()
    if err:
        return err

    data = _cached("kpi", lambda: get_dm_kpi_from_mv(
        project_ids=sorted(current_user.get_data_manager_projects()),
        project_site_pairs=current_user.get_data_manager_project_sites(),
    ))
    return jsonify(data)


@bp.get("/submissions/by-date")
@login_required
def submissions_by_date():
    err = _require_data_manager()
    if err:
        return err

    limit = min(int(request.args.get("limit", 90)), 365)

    def compute():
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
        return [{"date": str(r["date"]), "count": r["count"]} for r in rows]

    return jsonify({"data": _cached(f"submissions_by_date:{limit}", compute)})


@bp.get("/submissions/by-week")
@login_required
def submissions_by_week():
    err = _require_data_manager()
    if err:
        return err

    limit = min(int(request.args.get("limit", 26)), 104)

    def compute():
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
        return [{"week_start": str(r["week_start"]), "count": r["count"]} for r in rows]

    return jsonify({"data": _cached(f"submissions_by_week:{limit}", compute)})


@bp.get("/submissions/by-month")
@login_required
def submissions_by_month():
    err = _require_data_manager()
    if err:
        return err

    limit = min(int(request.args.get("limit", 12)), 60)

    def compute():
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
        return [{"month_start": str(r["month_start"]), "count": r["count"]} for r in rows]

    return jsonify({"data": _cached(f"submissions_by_month:{limit}", compute)})


@bp.get("/demographics")
@login_required
@limiter.limit("120 per minute")
def demographics():
    err = _require_data_manager()
    if err:
        return err

    def compute():
        scope = sa.and_(
            *build_dm_mv_filter_conditions(
                _mv,
                project_ids=sorted(current_user.get_data_manager_projects()),
                project_site_pairs=current_user.get_data_manager_project_sites(),
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
            )
        )
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
        return {
            "age_bands": [{"band": r["band"], "count": r["count"]} for r in age_rows],
            "sex": [{"sex": r["sex"], "count": r["count"]} for r in sex_rows],
        }

    return jsonify(_cached("demographics", compute))


@bp.get("/workflow")
@login_required
def workflow():
    err = _require_data_manager()
    if err:
        return err

    def compute():
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
        return [{"state": r["state"], "count": r["count"]} for r in rows]

    return jsonify({"data": _cached("workflow", compute)})


@bp.get("/cod")
@login_required
def cod():
    err = _require_data_manager()
    if err:
        return err

    cod_type = request.args.get("type", "final")
    limit = min(int(request.args.get("limit", 20)), 100)

    def compute():
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
        return [{"icd": r["icd"], "cod_text": r["cod_text"], "count": r["count"]} for r in rows]

    return jsonify({"type": cod_type, "data": _cached(f"cod:{cod_type}:{limit}", compute)})


@bp.post("/mv/refresh")
@login_required
@limiter.limit("1 per minute")
def mv_refresh():
    """Refresh the submission analytics materialized view on demand."""
    try:
        err = _require_data_manager()
        if err:
            return err
        refresh_submission_analytics_mv(concurrently=True)
        _bust_user_analytics_cache()
        return jsonify({"message": "Analytics data refreshed successfully."}), 200
    except Exception as exc:
        log.exception("On-demand analytics MV refresh failed: %s", exc)
        return jsonify({"error": "Analytics refresh failed. Check server logs."}), 500
