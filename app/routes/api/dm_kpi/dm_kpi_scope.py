"""Shared DM scope helpers for KPI endpoints.

All KPI endpoints use these to resolve the current data-manager's scope and
build scoped sub-queries.  The key design decisions:

- **Direct scope is keyed on (project_id, site_id) pairs, never the bare
  site id** (digitva-lh1h). A site_id is shared across projects; a DM on
  (P1, S1) sees P1's forms at S1 and nothing of P2's forms at the same S1.
  Project grants expand to their currently active pairs via
  ``va_project_sites``.
- **Unit-scope data_manager grants count their subtree, per submission.** A
  unit grant covers part of a site, so it is never resolved to a site: a live
  query passes a row when its form's (project, site) pair is in the direct
  scope OR the submission's ``org_unit_id`` is in the DM's unit subtree
  (``DmScope.sql``). Each row is tested once in one WHERE, so a submission
  both in a direct pair and in the subtree is counted once.
- **Aggregate panels** (daily grid, burndown, backlog trend) read
  ``va_daily_kpi_aggregates``, which holds one row per (date, site) counting
  every project's forms at that site (``app/tasks/kpi_tasks.py``; its
  ``project_id`` is only the site's latest owner). So a row is read only for
  a site whose every project with forms there is in the DM's pairs for that
  site (``aggregate_site_ids``). The rest of the scope -- shared sites and
  the unit subtree outside those sites -- is added live with
  ``DmScope.outside_aggregates_sql``, disjoint from the aggregate part, so
  nothing is double-counted.
- Coder counts keyed by coder grant project (utilization denominator, coders
  per language) include a unit grant's project; they are counts only. The
  coder roster names coders, so it stays on the direct projects: a unit grant
  never resolves to its whole project (docs/policy/access-control-model.md).
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass

import sqlalchemy as sa
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from app import cache, db
from app.decorators import role_required
from app.models import VaForms
from app.services.submission_analytics_mv import (
    _expand_project_ids_to_active_pairs,
)

log = logging.getLogger(__name__)

_CACHE_TTL = 300  # 5 minutes

bp = Blueprint("dm_kpi_cache", __name__)


# ---------------------------------------------------------------------------
# DM scope → (project_id, site_id) pairs
# ---------------------------------------------------------------------------

def dm_project_site_pairs() -> set[tuple[str, str]]:
    """Resolve the current DM's grants → active (project_id, site_id) pairs.

    Project grants expand to every currently active site of the project;
    project_site grants are taken as they are.
    """
    project_ids = sorted(current_user.get_data_manager_projects())
    pairs: set[tuple[str, str]] = set(current_user.get_data_manager_project_sites())
    pairs |= _expand_project_ids_to_active_pairs(project_ids)
    return pairs


def _aggregate_safe_sites(pairs: set[tuple[str, str]]) -> list[str]:
    """Sites of *pairs* whose aggregate rows hold only projects in *pairs*.

    A ``va_daily_kpi_aggregates`` row counts every form at its site whatever
    the project, so it may be read only when every project with a form at
    the site is one the DM holds there. A site with no forms has nothing of
    another project in it. One query.

    ponytail: a site that ever held a form of a project outside the DM's
    pairs (a closed or departed project's old forms included) is served live
    for good -- slower, never a leak. Per-project aggregate rows
    (``(snapshot_date, project_id, site_id)``) would lift that.
    """
    if not pairs:
        return []
    held: dict[str, set[str]] = {}
    for project_id, site_id in pairs:
        held.setdefault(site_id, set()).add(project_id)
    rows = db.session.execute(
        sa.select(VaForms.site_id, VaForms.project_id)
        .where(VaForms.site_id.in_(sorted(held)))
        .distinct()
    ).all()
    unsafe = {site_id for site_id, project_id in rows if project_id not in held[site_id]}
    return sorted(set(held) - unsafe)


@dataclass(frozen=True)
class DmScope:
    """The current DM's KPI scope: direct (project, site) pairs plus a unit subtree.

    ``pairs`` are bound as two parallel text arrays and ``unit_ids`` (string
    UUIDs of every active unit under the DM's unit-scope data_manager grants)
    as a ``uuid[]``; nothing is interpolated. ``aggregate_site_ids`` are the
    direct sites whose daily aggregate rows may be read (``_aggregate_safe_sites``).
    """

    pairs: list[tuple[str, str]]
    unit_ids: list[str]
    aggregate_site_ids: list[str]

    def __bool__(self) -> bool:
        return bool(self.pairs or self.unit_ids)

    def sql(self, form: str = "f", sub: str = "s") -> str:
        """WHERE fragment for live queries joining va_forms *form* and va_submissions *sub*."""
        pair_sql = (
            f"({form}.project_id, {form}.site_id) IN (SELECT * FROM unnest("
            "CAST(:pair_project_ids AS text[]), CAST(:pair_site_ids AS text[])))"
        )
        if not self.unit_ids:
            return pair_sql
        return f"({pair_sql} OR {sub}.org_unit_id = ANY(CAST(:unit_ids AS uuid[])))"

    @property
    def has_outside_aggregates(self) -> bool:
        """Whether some of the scope is not covered by readable aggregate rows."""
        covered = set(self.aggregate_site_ids)
        return bool(self.unit_ids) or any(site_id not in covered for _, site_id in self.pairs)

    def outside_aggregates_sql(self, form: str = "f", sub: str = "s") -> str:
        """The scope minus the aggregate sites, for adding live figures to
        aggregate rows without counting a submission twice."""
        return (
            f"{self.sql(form, sub)}"
            f" AND NOT COALESCE({form}.site_id = ANY(:aggregate_site_ids), FALSE)"
        )

    @property
    def params(self) -> dict:
        """Bind parameters matching ``sql`` / ``outside_aggregates_sql``."""
        return {
            "pair_project_ids": [project_id for project_id, _ in self.pairs],
            "pair_site_ids": [site_id for _, site_id in self.pairs],
            "unit_ids": self.unit_ids,
            "aggregate_site_ids": self.aggregate_site_ids,
        }

    def digest(self) -> str:
        """Short stable hash of the scope, for cache keys. Pairs, not sites:
        the same site in another project is another scope."""
        raw = (
            "|".join(f"{project_id}/{site_id}" for project_id, site_id in self.pairs)
            + "#" + "|".join(self.unit_ids)
        )
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
    pairs = dm_project_site_pairs()
    scope = DmScope(
        pairs=sorted(pairs),
        unit_ids=sorted(str(u) for u in current_user.get_data_manager_org_unit_ids()),
        aggregate_site_ids=_aggregate_safe_sites(pairs),
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

    # Step 1: Recompute today's KPI aggregates for the DM's sites (the rows
    # are site-keyed; dm_scope decides which of them the DM may read)
    site_ids = sorted({site_id for _project_id, site_id in dm_project_site_pairs()})
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
