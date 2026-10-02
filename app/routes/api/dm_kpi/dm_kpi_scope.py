"""Shared DM scope helpers for KPI endpoints.

All KPI endpoints use these to resolve the current data-manager's scope and
build scoped sub-queries.  The key design decisions:

- **Site-project attribution uses current `va_project_sites` active membership**,
  not the frozen `va_forms.project_id`.
- **Direct DM scoping uses `site_id` resolved from current `va_project_sites`**.
  The `project_id` column in `va_daily_kpi_aggregates` is audit data,
  not the access gate.
- A DM sees **all rows for their currently-owned site_ids**, regardless of
  which project owned those sites historically.
- **Unit-scope data_manager grants count their subtree, per submission.** A
  unit grant covers part of a site, so it is never resolved to a site: a live
  query passes a row when its form's site is in the direct scope OR the
  submission's ``org_unit_id`` is in the DM's unit subtree
  (``DmScope.sql``). Each row is tested once in one WHERE, so a submission
  both in a direct site and in the subtree is counted once.
- **Aggregate panels** (daily grid, burndown, backlog trend) read the
  site-keyed ``va_daily_kpi_aggregates`` for the direct sites only, and add
  the unit part live from the raw tables with ``DmScope.unit_only_sql``
  (in the subtree AND not in a direct site), so the two parts are disjoint
  and nothing is double-counted. A DM without unit grants gets exactly the
  queries it got before unit grants existed.
- Coder counts keyed by coder grant project (utilization denominator, coders
  per language) include a unit grant's project; they are counts only. The
  coder roster names coders, so it stays on the direct projects: a unit grant
  never resolves to its whole project (docs/policy/access-control-model.md).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from app import cache
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


@dataclass(frozen=True)
class DmScope:
    """The current DM's KPI scope: direct site_ids plus a unit subtree.

    ``unit_ids`` are string UUIDs of every active unit under the DM's
    unit-scope data_manager grants; they are bound as an array parameter and
    cast to ``uuid[]`` in SQL, never interpolated.
    """

    site_ids: list[str]
    unit_ids: list[str]

    def __bool__(self) -> bool:
        return bool(self.site_ids or self.unit_ids)

    def sql(self, form: str = "f", sub: str = "s") -> str:
        """WHERE fragment for live queries joining va_forms *form* and va_submissions *sub*.

        Without unit grants this is exactly the pre-unit site filter.
        """
        if not self.unit_ids:
            return f"{form}.site_id = ANY(:site_ids)"
        return (
            f"({form}.site_id = ANY(:site_ids)"
            f" OR {sub}.org_unit_id = ANY(CAST(:unit_ids AS uuid[])))"
        )

    def unit_only_sql(self, form: str = "f", sub: str = "s") -> str:
        """The unit part minus the direct sites, for adding live figures to
        site-keyed aggregates without counting a submission twice."""
        return (
            f"{sub}.org_unit_id = ANY(CAST(:unit_ids AS uuid[]))"
            f" AND NOT COALESCE({form}.site_id = ANY(:site_ids), FALSE)"
        )

    @property
    def params(self) -> dict:
        """Bind parameters matching ``sql`` / ``unit_only_sql``."""
        if not self.unit_ids:
            return {"site_ids": self.site_ids}
        return {"site_ids": self.site_ids, "unit_ids": self.unit_ids}

    def digest(self) -> str:
        """Short stable hash of the scope, for cache keys."""
        raw = "|".join(self.site_ids) + "#" + "|".join(self.unit_ids)
        return hashlib.sha1(raw.encode()).hexdigest()[:16]


_SCOPE_ENVIRON_KEY = "digitva.dm_kpi_scope"


def dm_scope() -> DmScope:
    """Resolve the current DM's KPI scope once per request.

    Memoized in the WSGI environ, not ``flask.g``: the app context (and so
    ``g``) can outlive a request, which would hand one user's scope to the
    next.
    """
    cached = request.environ.get(_SCOPE_ENVIRON_KEY)
    if cached is not None and cached[0] == current_user.user_id:
        return cached[1]
    scope = DmScope(
        site_ids=dm_site_ids(),
        unit_ids=sorted(str(u) for u in current_user.get_data_manager_org_unit_ids()),
    )
    request.environ[_SCOPE_ENVIRON_KEY] = (current_user.user_id, scope)
    return scope


# ---------------------------------------------------------------------------
# Caching helpers (same pattern as analytics.py)
# ---------------------------------------------------------------------------

def _cache_key(suffix: str) -> str:
    """Per user and per scope: a grant change, or two DMs with different
    units, never share an entry. The digest sits after the user id so
    ``bust_dm_kpi_cache``'s ``dm_kpi:{uid}:*`` pattern still matches."""
    qs = request.query_string.decode()
    return f"dm_kpi:{current_user.user_id}:{dm_scope().digest()}:{suffix}:{qs}"


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
