"""Shared DM scope helpers for KPI endpoints.

All KPI endpoints use these to resolve the current data-manager's scope and
build scoped sub-queries.  The key design decisions:

- **Direct scope is keyed on (project_id, site_id) pairs, never the bare
  site id** (digitva-lh1h). A site_id is shared across projects; a DM on
  (P1, S1) sees P1's forms at S1 and nothing of P2's forms at the same S1.
  Project grants expand to their currently active pairs via
  ``va_project_sites``.
- **The grants are authz's** (``data_management_service.dm_grant_scope``,
  digitva-0wc stage 3): data_manager at any scope, the In-charge (site_pi at
  a unit) and project_pi on a tree project; admin holds every project.
- **Unit grants count their subtree, per submission.** A unit grant covers
  part of a site, so it is never resolved to a site: a live query passes a
  row when its form's (project, site) pair is in the direct scope OR the
  submission's ``org_unit_id`` is in the subtree of the granted units, a
  subquery anchored on the grant ids (``DmScope.sql``), never a materialised
  id list, and its form's pair is active, as the grid requires
  (``authz.active_pair``; digitva-26pg). Each row is tested once in one
  WHERE, so a submission both in a direct pair and in the subtree is
  counted once.
- **Every panel is live** (digitva-0hul): ``va_daily_kpi_aggregates`` is
  no longer read. Per-day series come from ``bucket_flow_by_day``, which
  rebuilds end-of-day counts from workflow events, so a unit subtree is
  counted with the same one WHERE as every other panel.
- **Days follow the project clock** (docs/policy/kpis.md, "Days follow the
  project clock"): an event's day, "today" and "the last N days" are taken in
  the timezone of the event's own project (``va_project_master.timezone``),
  never the viewer's. A query joins ``CLOCK_JOIN_SQL`` and buckets with
  ``clock_day_sql``; a window filter keeps a raw-timestamp floor beside the
  per-project date test (``in_last_days_sql``) so the timestamp index still
  applies. A day series ends on the latest project today in scope
  (``DmScope.today``).
- Coder counts keyed by coder grant project (utilization denominator, coders
  per language) include a unit grant's project; they are counts only. The
  coder roster names coders, so it stays on the direct projects: a unit grant
  never resolves to its whole project (docs/policy/access-control-model.md).
  Every grant resolves to its project through ``GRANT_PROJECT_JOINS`` /
  ``GRANT_PROJECT_SQL``; a NULL ``project_id`` is never a wildcard.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import sqlalchemy as sa
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from app import cache, db, limiter
from app.decorators import role_required
from app.services import dm_dashboard_cache
from app.services.authz import grant_cache
from app.services.data_management_service import dm_grant_scope
from app.services.kpi.common import IN_ODK_SQL as _IN_ODK_SQL
from app.services.kpi.common import NOT_DUPLICATE_SQL as _NOT_DUPLICATE_SQL
from app.services.kpi.scope import (  # noqa: F401  (re-exported; moved to services/kpi/scope.py)
    CLOCK_JOIN_SQL,
    GRANT_PROJECT_JOINS,
    GRANT_PROJECT_SQL,
    NOT_DEMO_OUTPUT_SQL,
    DmScope,
    clock_day_sql,
    clock_params,
    clock_tz_sql,
    in_last_days_sql,
    local_day_start,
)
from app.services.odk_retirement_service import IN_ODK_BIND
from app.services.workflow.definition import (
    CODING_BUCKET_CODED,
    TRANSITION_DEMO_STARTED,
    WORKFLOW_CODING_BUCKETS,
)

log = logging.getLogger(__name__)

_CACHE_TTL = 300  # 5 minutes

bp = Blueprint("dm_kpi_cache", __name__)

_CODED_STATES = sorted(
    state for state, bucket in WORKFLOW_CODING_BUCKETS.items() if bucket == CODING_BUCKET_CODED
)


def bucket_flow_by_day(
    scope: DmScope,
    states,
    from_date: date,
    to_date: date,
) -> list[dict]:
    """Daily flow across the boundary of the state set *states*, one query.

    For each day from *from_date* to *to_date* (ascending; each event on its
    own project's clock, the series ending on ``scope.today()``):
    ``inflow`` (events whose ``previous_state`` is outside *states* and
    ``current_state`` inside), ``outflow`` (the reverse), split into
    ``outflow_coded`` (left for the coded bucket) and ``outflow_other``, and
    ``end_of_day``, the count in *states* at the end of that day.

    ``end_of_day`` is replayed from events: the current count minus the net
    crossings of every later event (docs/policy/kpis.md, "Aggregates are
    retired"), so the scan runs from *from_date* to now, not to *to_date*.
    The replay counts every event; inflow and outflow drop demo events (the
    ``NOT_DEMO_OUTPUT_SQL`` rule, written as joins here: as correlated
    subqueries over a year of events the planner's estimate tripped JIT,
    ~95% of the run time on dev), so ``inflow - outflow`` need not equal the
    day's change in ``end_of_day`` when demo cases moved.

    *scope* gives the WHERE (aliases ``f`` and ``s``). *states* are fixed
    state names, bound as an array. The scan starts at
    ``scope.day_floor(from_date)``; events from before a project's own
    *from_date* fall on days the series does not show.

    ponytail: a case with no events (imported before workflow events) is
    counted in ``end_of_day`` for every past day. Add its created date as a
    synthetic entry if that history matters.
    """
    scope_sql = scope.sql()
    today = scope.today()
    to_date = min(to_date, today)
    rows = db.session.execute(
        sa.text(f"""
            WITH now_count AS (
                SELECT COUNT(*) AS n
                FROM va_submission_workflow w
                JOIN va_submissions s ON s.va_sid = w.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE {scope_sql}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND w.workflow_state = ANY(CAST(:flow_states AS text[]))
            ), crossings AS (
                SELECT
                    {clock_day_sql("e.event_created_at", "pm")} AS d,
                    CASE WHEN e.current_state = ANY(CAST(:flow_states AS text[])) THEN 1 ELSE 0 END
                      - CASE WHEN e.previous_state = ANY(CAST(:flow_states AS text[])) THEN 1 ELSE 0 END
                      AS net,
                    e.current_state = ANY(CAST(:flow_coded_states AS text[])) AS to_coded,
                    demo.va_sid IS NULL AND pm.demo_training_enabled IS NOT TRUE AS counted
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                JOIN va_project_master pm ON pm.project_id = f.project_id
                LEFT JOIN (
                    SELECT DISTINCT va_sid FROM va_submission_workflow_events
                    WHERE transition_id = :flow_demo_started
                ) demo ON demo.va_sid = e.va_sid
                WHERE {scope_sql}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND e.event_created_at >= :flow_start
            ), per_day AS (
                SELECT d,
                       SUM(net) AS net,
                       COUNT(*) FILTER (WHERE net = 1 AND counted) AS inflow,
                       COUNT(*) FILTER (WHERE net = -1 AND counted AND to_coded) AS outflow_coded,
                       COUNT(*) FILTER (WHERE net = -1 AND counted AND NOT to_coded) AS outflow_other
                FROM crossings
                WHERE net <> 0
                GROUP BY d
            )
            SELECT n.n AS now_n, p.d, p.net, p.inflow, p.outflow_coded, p.outflow_other
            FROM now_count n
            LEFT JOIN per_day p ON TRUE
        """),
        {
            **IN_ODK_BIND,
            **scope.params,
            "flow_states": list(states),
            "flow_coded_states": _CODED_STATES,
            "flow_start": scope.day_floor(from_date),
            "flow_demo_started": TRANSITION_DEMO_STARTED,
        },
    ).mappings().all()

    now_n = rows[0]["now_n"] if rows else 0
    by_day = {r["d"]: r for r in rows if r["d"] is not None}
    series = []
    running = now_n
    day = today
    while day >= from_date:
        r = by_day.get(day)
        if day <= to_date:
            coded = r["outflow_coded"] if r else 0
            other = r["outflow_other"] if r else 0
            series.append({
                "date": day.isoformat(),
                "inflow": r["inflow"] if r else 0,
                "outflow": coded + other,
                "outflow_coded": coded,
                "outflow_other": other,
                "end_of_day": running,
            })
        running -= r["net"] if r else 0
        day -= timedelta(days=1)
    series.reverse()
    return series


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
    grants = dm_grant_scope(current_user)
    pairs = grants.active_pairs()
    scope = DmScope(
        pairs=sorted(pairs),
        unit_ids=sorted(str(u) for u in grants.unit_grant_ids),
        unit_project_ids=tuple(sorted(grants.unit_project_ids)),
        direct=grants.has_direct,
        grant_project_ids=tuple(sorted(grants.project_ids)),
    )
    request.environ[_SCOPE_ENVIRON_KEY] = (current_user.user_id, scope)
    return scope


# ---------------------------------------------------------------------------
# Caching helpers (same pattern as analytics.py)
# ---------------------------------------------------------------------------

def _cache_key(suffix: str) -> str | None:
    """Per user and per scope: a grant change, or two DMs with different
    units, never share an entry. The digest sits after the user id so
    ``bust_dm_kpi_cache``'s ``dm_kpi:{uid}:*`` pattern still matches.

    The digest names the grants, not the status of the pairs and units they
    reach; a pair deactivation moves what the scope counts (a unit grant
    counts only active pairs) without moving the digest. The authz global
    version, bumped by every such write, is part of the key so figures never
    lag one by the cache life."""
    version = grant_cache.global_version()
    if not version:
        return None
    qs = request.query_string.decode()
    return (
        f"dm_kpi:{current_user.user_id}:{dm_scope().digest()}"
        f":{version}:{dm_dashboard_cache.generation()}:{suffix}:{qs}"
    )


def cached_kpi(key: str, compute_fn, timeout: int = _CACHE_TTL):
    """Cache-aside wrapper for KPI compute functions.

    Returns cached data if available, otherwise calls compute_fn() and
    caches the result for `timeout` seconds.
    """
    full_key = _cache_key(key)
    if full_key is None:
        return compute_fn()
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
@role_required("data_manager", "admin")
def cache_bust():
    """Clear all cached KPI data for the current DM."""
    deleted = bust_dm_kpi_cache()
    return jsonify({"deleted": deleted}), 200


@bp.post("/refresh")
@role_required("data_manager", "admin")
@limiter.limit("2 per minute")
def refresh_dashboard():
    """Full dashboard refresh: refresh MVs, bust cache.

    KPIs are computed live (digitva-0hul), so there is nothing to recompute.

    Steps:
      1. Refresh all materialized views
      2. Clear cached KPI data and analytics cache
    """
    from app.services.submission_analytics_mv import refresh_submission_analytics_mv

    # Step 1: Refresh materialized views
    mv_ok = False
    try:
        refresh_submission_analytics_mv(concurrently=True)
        mv_ok = True
    except Exception as exc:
        log.exception("MV refresh failed: %s", exc)

    # Step 2: Bust caches
    cache_deleted = bust_dm_kpi_cache()
    try:
        from app.routes.api.analytics import _bust_user_analytics_cache
        _bust_user_analytics_cache()
    except Exception as exc:
        log.warning("Analytics cache bust failed: %s", exc, exc_info=True)

    return jsonify({
        "mv_refreshed": mv_ok,
        "cache_deleted": cache_deleted,
    }), 200
