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
  rebuilds end-of-day counts from workflow events in the viewer's timezone
  (``DmScope.tz``), so a unit subtree is counted with the same one WHERE as
  every other panel.
- Coder counts keyed by coder grant project (utilization denominator, coders
  per language) include a unit grant's project; they are counts only. The
  coder roster names coders, so it stays on the direct projects: a unit grant
  never resolves to its whole project (docs/policy/access-control-model.md).
  Every grant resolves to its project through ``GRANT_PROJECT_JOINS`` /
  ``GRANT_PROJECT_SQL``; a NULL ``project_id`` is never a wildcard.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import sqlalchemy as sa
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user

from app import cache, db, limiter
from app.decorators import role_required
from app.services.authz import grant_cache
from app.services.data_management_service import dm_grant_scope
from app.services.duplicate_exclusion import not_confirmed_duplicate_sql
from app.services.odk_retirement_service import IN_ODK_BIND, in_odk_sql
from app.services.workflow.definition import (
    CODING_BUCKET_CODED,
    NOT_DEMO_EVENT_SQL,
    TRANSITION_DEMO_STARTED,
    WORKFLOW_CODING_BUCKETS,
)
from app.utils.va_render.va_render_07_serialisedates import va_user_timezone_name

log = logging.getLogger(__name__)

_CACHE_TTL = 300  # 5 minutes

# The project of a grant row ``g``: a project grant names it, a pair or unit
# grant resolves through its row, and only while that pair or unit is active
# (as authz's grant relation does). Only project grants carry ``project_id``,
# so the NULL there is never a wildcard. Joins are on primary keys.
GRANT_PROJECT_JOINS = """
    LEFT JOIN va_project_sites gps
           ON gps.project_site_id = g.project_site_id
          AND gps.project_site_status = 'active'
    LEFT JOIN mas_org_unit gou
           ON gou.org_unit_id = g.org_unit_id
          AND gou.is_active
"""
GRANT_PROJECT_SQL = "COALESCE(g.project_id, gps.project_id, gou.project_id)"

bp = Blueprint("dm_kpi_cache", __name__)


# Retired submissions are not counted (docs/policy/odk-retired-submissions.md).
_IN_ODK_SQL = in_odk_sql("s")
# Confirmed-duplicate web cases leave every count (app/services/duplicate_exclusion.py).
_NOT_DUPLICATE_SQL = not_confirmed_duplicate_sql("s.va_sid")

#: Viewer timezone when the user has none (docs/policy/kpis.md, Time Frames).
DEFAULT_KPI_TZ = "Asia/Kolkata"

#: Demo exclusion for output and rate KPIs (docs/policy/kpis.md, "Demo
#: exclusion"): no ``demo_started`` event on the submission and the form's
#: project is not ``demo_training_enabled``. Over ``va_submission_workflow_events
#: e`` joined to ``va_forms f``.
NOT_DEMO_OUTPUT_SQL = (
    f"({NOT_DEMO_EVENT_SQL} AND NOT EXISTS (SELECT 1 FROM va_project_master dm_demo_pm"
    " WHERE dm_demo_pm.project_id = f.project_id AND dm_demo_pm.demo_training_enabled))"
)

_CODED_STATES = sorted(
    state for state, bucket in WORKFLOW_CODING_BUCKETS.items() if bucket == CODING_BUCKET_CODED
)


@dataclass(frozen=True)
class DmScope:
    """The current DM's KPI scope: direct (project, site) pairs plus a unit subtree.

    ``pairs`` are bound as two parallel text arrays and ``unit_ids`` (string
    UUIDs of the DM's granted units, the subtree anchors) as a ``uuid[]``;
    nothing is interpolated. ``tz`` is the viewer's timezone, the day
    boundary of every per-day figure. ``unit_project_ids`` are the unit grants' projects (counts and project
    metadata only); ``direct`` says the DM holds a project or pair grant
    (authz ``Lens.DM_DIRECT``), which the system-level sync panels need.
    """

    pairs: list[tuple[str, str]]
    unit_ids: list[str]
    tz: str = DEFAULT_KPI_TZ
    unit_project_ids: tuple[str, ...] = ()
    direct: bool = True
    grant_project_ids: tuple[str, ...] = ()

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
        subtree_sql = self.subtree_sql()
        # The form's pair is active (authz.active_pair as text): the grid
        # stops at a deactivated (project, site) pair for unit grants too.
        active_pair_sql = (
            "EXISTS (SELECT 1 FROM va_project_sites dm_scope_ps"
            f" WHERE dm_scope_ps.project_id = {form}.project_id"
            f" AND dm_scope_ps.site_id = {form}.site_id"
            " AND dm_scope_ps.project_site_status = 'active')"
        )
        return f"({pair_sql} OR ({sub}.org_unit_id IN ({subtree_sql}) AND {active_pair_sql}))"

    @staticmethod
    def subtree_sql() -> str:
        """Unit ids in the subtree of the granted units (authz.subtree_select
        as text): anchored on the grant ids, served by the ltree GiST index."""
        return (
            "SELECT dm_scope_cu.org_unit_id FROM mas_org_unit dm_scope_gu"
            " JOIN mas_org_unit dm_scope_cu"
            " ON dm_scope_cu.project_id = dm_scope_gu.project_id"
            " AND dm_scope_cu.path <@ dm_scope_gu.path"
            " WHERE dm_scope_gu.org_unit_id = ANY(CAST(:unit_ids AS uuid[]))"
            " AND dm_scope_cu.is_active"
        )

    def grant_in_scope_sql(self, grant: str = "g") -> str:
        """WHERE fragment: grant row *grant* sits inside this scope -- a project
        grant on a project the DM holds whole, a pair grant on one of the DM's
        pairs, a unit grant inside the DM's subtree or a project held whole.
        Binds ``params`` plus ``grant_project_ids``. Names coders, so it is
        never wider than the DM's own scope (owner decision 2026-10-03)."""
        return (
            f"(({grant}.scope_type = 'project'"
            f" AND {grant}.project_id = ANY(CAST(:grant_project_ids AS text[])))"
            f" OR ({grant}.scope_type = 'project_site' AND EXISTS ("
            "SELECT 1 FROM va_project_sites dm_scope_gps"
            f" WHERE dm_scope_gps.project_site_id = {grant}.project_site_id"
            " AND dm_scope_gps.project_site_status = 'active'"
            " AND (dm_scope_gps.project_id, dm_scope_gps.site_id) IN (SELECT * FROM unnest("
            "CAST(:pair_project_ids AS text[]), CAST(:pair_site_ids AS text[])))))"
            f" OR ({grant}.scope_type = 'org_unit' AND EXISTS ("
            "SELECT 1 FROM mas_org_unit dm_scope_gun"
            f" WHERE dm_scope_gun.org_unit_id = {grant}.org_unit_id"
            " AND dm_scope_gun.is_active"
            " AND (dm_scope_gun.project_id = ANY(CAST(:grant_project_ids AS text[]))"
            f" OR dm_scope_gun.org_unit_id IN ({self.subtree_sql()})))))"
        )

    @property
    def direct_project_ids(self) -> list[str]:
        """Projects of the direct pairs: a unit grant never names its project's coders."""
        return sorted({project_id for project_id, _ in self.pairs})

    @property
    def all_project_ids(self) -> list[str]:
        """Direct projects plus the unit grants' projects, for counts and
        project metadata only."""
        return sorted(set(self.direct_project_ids) | set(self.unit_project_ids))

    @property
    def params(self) -> dict:
        """Bind parameters matching ``sql`` and ``grant_in_scope_sql``."""
        return {
            "pair_project_ids": [project_id for project_id, _ in self.pairs],
            "pair_site_ids": [site_id for _, site_id in self.pairs],
            "unit_ids": self.unit_ids,
            "grant_project_ids": list(self.grant_project_ids),
        }

    def digest(self) -> str:
        """Short stable hash of the scope, for cache keys. Pairs, not sites:
        the same site in another project is another scope; the unit grant
        ids, not their subtrees: two grants are two scopes. The timezone moves
        every day boundary, so it is part of the scope too."""
        raw = (
            "|".join(f"{project_id}/{site_id}" for project_id, site_id in self.pairs)
            + "#" + "|".join(self.unit_ids) + "#" + self.tz
        )
        return hashlib.sha1(raw.encode()).hexdigest()[:16]


def local_today(tz: str) -> date:
    """Today's date in *tz*: the grid's last row, never the database's or the server's day."""
    return datetime.now(ZoneInfo(tz)).date()


def local_day_start(day: date, tz: str) -> datetime:
    """Midnight of *day* in *tz*, as an aware datetime (binds as timestamptz)."""
    return datetime.combine(day, time(), ZoneInfo(tz))


def bucket_flow_by_day(
    scope_sql: str,
    params: dict,
    states,
    from_date: date,
    to_date: date,
    tz: str,
) -> list[dict]:
    """Daily flow across the boundary of the state set *states*, one query.

    For each day from *from_date* to *to_date* (days in *tz*, ascending):
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

    *scope_sql* / *params* are ``DmScope.sql()`` / ``DmScope.params`` (aliases
    ``f`` and ``s``). *states* are fixed state names, bound as an array.

    ponytail: a case with no events (imported before workflow events) is
    counted in ``end_of_day`` for every past day. Add its created date as a
    synthetic entry if that history matters.
    """
    today = local_today(tz)
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
                    DATE(timezone(:flow_tz, e.event_created_at)) AS d,
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
            **params,
            "flow_states": list(states),
            "flow_coded_states": _CODED_STATES,
            "flow_tz": tz,
            "flow_start": local_day_start(from_date, tz),
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
        tz=va_user_timezone_name(current_user),
        unit_project_ids=tuple(sorted(grants.unit_project_ids)),
        direct=grants.has_direct,
        grant_project_ids=tuple(sorted(grants.project_ids)),
    )
    request.environ[_SCOPE_ENVIRON_KEY] = (current_user.user_id, scope)
    return scope


# ---------------------------------------------------------------------------
# Caching helpers (same pattern as analytics.py)
# ---------------------------------------------------------------------------

def _cache_key(suffix: str) -> str:
    """Per user and per scope: a grant change, or two DMs with different
    units, never share an entry. The digest sits after the user id so
    ``bust_dm_kpi_cache``'s ``dm_kpi:{uid}:*`` pattern still matches.

    The digest names the grants, not the status of the pairs and units they
    reach; a pair deactivation moves what the scope counts (a unit grant
    counts only active pairs) without moving the digest. The authz global
    version, bumped by every such write, is part of the key so figures never
    lag one by the cache life."""
    qs = request.query_string.decode()
    return (
        f"dm_kpi:{current_user.user_id}:{dm_scope().digest()}"
        f":{grant_cache.global_version()}:{suffix}:{qs}"
    )


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
