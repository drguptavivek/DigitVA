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
from flask import request
from flask_login import current_user

from app import cache, db
from app.services.submission_analytics_mv import (
    _expand_project_ids_to_active_pairs,
)

log = logging.getLogger(__name__)

_CACHE_TTL = 300  # 5 minutes


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
