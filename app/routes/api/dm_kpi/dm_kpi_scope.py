"""Shared DM scope helpers for KPI endpoints.

All KPI endpoints use these to resolve the current data-manager's visible
site_ids and build scoped sub-queries.  The key design decision:

- **Site-project attribution uses current `va_project_sites` active membership**,
  not the frozen `va_forms.project_id`.
- **DM scoping uses `site_id` resolved from current `va_project_sites`**.
  The `project_id` column in `va_daily_kpi_aggregates` is audit data,
  not the access gate.
- A DM sees **all rows for their currently-owned site_ids**, regardless of
  which project owned those sites historically.
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from app import cache, db
from app.decorators import role_required
from app.services.submission_analytics_mv import (
    _expand_project_ids_to_active_pairs,
)

log = logging.getLogger(__name__)

_CACHE_TTL = 300  # 5 minutes

bp = Blueprint("dm_kpi_cache", __name__)


# ---------------------------------------------------------------------------
# DM scope → site_ids
# ---------------------------------------------------------------------------

def dm_site_ids() -> list[str]:
    """Resolve the current DM's grants → active site_ids.

    - Project-level grants (`scope_type = 'project'`): expanded to all
      currently active sites within those projects via `va_project_sites`.
    - Project-site grants (`scope_type = 'project_site'`): looked up
      individually.

    Returns a deduplicated, sorted list of site_ids the DM can see.
    """
    project_ids = sorted(current_user.get_data_manager_projects())
    project_site_pairs = current_user.get_data_manager_project_sites()

    # project_site_pairs is set of (project_id, site_id)
    site_set: set[str] = {sid for _pid, sid in project_site_pairs}

    # Expand project-level grants
    expanded = _expand_project_ids_to_active_pairs(project_ids)
    site_set |= {sid for _pid, sid in expanded}

    return sorted(site_set)


def dm_project_site_pairs() -> set[tuple[str, str]]:
    """Resolve the current DM's grants → active (project_id, site_id) pairs.

    Used when the query needs project_id grouping (e.g. burndown per project).
    """
    project_ids = sorted(current_user.get_data_manager_projects())
    pairs: set[tuple[str, str]] = set(current_user.get_data_manager_project_sites())
    pairs |= _expand_project_ids_to_active_pairs(project_ids)
    return pairs


# ---------------------------------------------------------------------------
# Scoped subquery builders
# ---------------------------------------------------------------------------

def dm_scoped_submission_sid_subquery(site_ids: list[str] | None = None):
    """Return a subquery of va_sid values scoped to the DM's sites.

    Filters submissions via the site attribution path:
        va_submissions → va_forms.site_id
    using the same COALESCE(ps.project_id, f.project_id) pattern as the
    core analytics MV for site-level attribution.
    """
    if site_ids is None:
        site_ids = dm_site_ids()
    if not site_ids:
        # Return an impossible subquery so IN () never matches
        return sa.select(sa.literal(None)).where(sa.false())

    return (
        sa.select(sa.column("va_sid"))
        .select_from(
            sa.text(
                "va_submissions s JOIN va_forms f ON f.form_id = s.va_form_id"
            )
        )
        .where(sa.column("site_id").in_(site_ids))
        .correlate(None)
    )


# ---------------------------------------------------------------------------
# Caching helpers (same pattern as analytics.py)
# ---------------------------------------------------------------------------

def _cache_key(suffix: str) -> str:
    qs = request.query_string.decode()
    return f"dm_kpi:{current_user.user_id}:{suffix}:{qs}"


def cached_kpi(key: str, compute_fn, timeout: int = _CACHE_TTL):
    """Cache-aside wrapper for KPI compute functions.

    Returns cached data if available, otherwise calls compute_fn() and
    caches the result for `timeout` seconds.
    """
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
        log.warning("KPI cache set failed (%s): %s", full_key, exc, exc_info=True)
    return data


def bust_dm_kpi_cache(user_id: int | None = None) -> int:
    """Delete all cached KPI entries for the given user.

    Returns the number of keys deleted.
    """
    uid = user_id or current_user.user_id
    key_prefix = current_app.config.get("CACHE_KEY_PREFIX", "")
    pattern = f"{key_prefix}dm_kpi:{uid}:*"
    deleted = 0
    try:
        redis_client = cache.cache._write_client  # type: ignore[attr-defined]
        keys = redis_client.keys(pattern)
        if keys:
            deleted = redis_client.delete(*keys)
    except Exception as exc:
        log.warning("KPI cache bust failed: %s", exc, exc_info=True)
    return deleted


@bp.post("/cache/bust")
@role_required("data_manager")
def cache_bust():
    """Clear all cached KPI data for the current DM."""
    deleted = bust_dm_kpi_cache()
    return jsonify({"deleted": deleted}), 200


@bp.post("/refresh")
@role_required("data_manager")
def refresh_dashboard():
    """Full dashboard refresh: recompute daily KPIs, refresh MVs, bust cache.

    Steps:
      1. Recompute today's daily KPI aggregates for the DM's sites
      2. Refresh all materialized views
      3. Clear cached KPI data and analytics cache
    """
    from app.services.submission_analytics_mv import refresh_submission_analytics_mv
    from app.tasks.kpi_tasks import compute_daily_kpi_snapshot

    # Step 1: Recompute today's KPI aggregates for the DM's sites
    site_ids = dm_site_ids()
    kpi_result = {"status": "skipped", "sites_processed": 0}
    if site_ids:
        try:
            from datetime import date as _date
            result = compute_daily_kpi_snapshot.apply(kwargs={
                "snapshot_date": _date.today().isoformat(),
                "site_ids": site_ids,
            })
            kpi_result = result.result if result.successful() else {
                "status": "error",
                "reason": str(result.result),
            }
        except Exception as exc:
            log.exception("KPI snapshot recomputation failed: %s", exc)
            kpi_result = {"status": "error", "reason": "KPI recomputation failed. Check server logs."}

    # Step 2: Refresh materialized views
    mv_ok = False
    try:
        refresh_submission_analytics_mv(concurrently=True)
        mv_ok = True
    except Exception as exc:
        log.exception("MV refresh failed: %s", exc)

    # Step 3: Bust caches
    cache_deleted = bust_dm_kpi_cache()
    try:
        from app.routes.api.analytics import _bust_user_analytics_cache
        _bust_user_analytics_cache()
    except Exception as exc:
        log.warning("Analytics cache bust failed: %s", exc, exc_info=True)

    return jsonify({
        "kpi_snapshot": kpi_result,
        "mv_refreshed": mv_ok,
        "cache_deleted": cache_deleted,
    }), 200
