"""DM KPI — Pipeline Health.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/pipeline``

KPIs served:
  C-04  % Uncoded (Pending Rate)
  C-07  Pipeline Aging (Stagnation)
  C-08  Time to Code (Min / Max / Median / P90)
  C-09  % Forms Reviewed
  C-10  Upstream Change Queue
  C-11  % Forms with Upstream Changes
  C-19  Daily Inflow vs Outflow
  C-22  Site-Level Bottleneck
  D-WT-01  Reviewer Throughput
  D-WT-02  Upstream Change Resolution Time
  D-WT-03  Coding Backlog Trend
  D-WT-04  Reopen Rate

Sources (live, digitva-0hul; ``va_daily_kpi_aggregates`` is not read):
  - va_submission_workflow (current states)
  - va_submission_workflow_events (transitions, durations; per-day series
    through ``bucket_flow_by_day``, each event on its project's clock)
  - va_submission_upstream_changes (resolution times)

Core KPIs (C-04, C-07, C-08, C-19) are ``compute_<id>(scope, period, by)``
functions; their routes are thin wrappers.

Submissions retired from ODK are excluded from every count, list,
grouping and average below (docs/policy/odk-retired-submissions.md).
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_scope import (
    cached_kpi,
    dm_scope,
)
from app.routes.api.request_helpers import clamped_int_arg
from app.routes.api.request_helpers import error as api_error
from app.services.kpi.pipeline import (  # noqa: F401
    compute_c04,
    compute_c07,
    compute_c08,
    compute_c19,
    compute_pending_rate,
    compute_review_rate,
    compute_reviewer_throughput,
    compute_site_bottleneck,
    compute_time_to_code,
    compute_upstream_changes,
)

bp = Blueprint("dm_kpi_pipeline", __name__)
log = logging.getLogger(__name__)


@bp.get("/pending")
@role_required("data_manager", "admin")
def pending_rate():
    """KPI: C-04 — % Uncoded (Pending Rate), thin wrapper over ``compute_c04``."""
    scope = dm_scope()
    if not scope:
        return jsonify({"pending": 0, "coding_pool": 0, "rate": 0.0, "days_to_clear": None})

    return jsonify(cached_kpi("pending_rate", lambda: compute_pending_rate(scope)))


@bp.get("/aging")
@role_required("data_manager", "admin")
def pipeline_aging():
    """KPI: C-07 — Pipeline Aging, thin wrapper over ``compute_c07``.

    ``?by=state`` returns the per-state stagnation rows (merged D-WF-03).
    """
    scope = dm_scope()
    by = request.args.get("by") or None
    if by not in (None, "state"):
        return api_error("by must be 'state' or omitted.", "invalid_request", 400)
    if not scope:
        return jsonify({"by": "state", "states": []} if by else {"gt_48h": 0, "gt_7d": 0, "gt_30d": 0})
    return jsonify(cached_kpi(f"pipeline_aging:{by}", lambda: compute_c07(scope, by=by)))


@bp.get("/time-to-code")
@role_required("data_manager", "admin")
def time_to_code():
    """KPI: C-08 — Time to Code, thin wrapper over ``compute_c08``.

    ``range=today`` is since midnight on each project's clock; anything else
    is the last 7 project days including today.
    """
    scope = dm_scope()
    range_param = "today" if request.args.get("range") == "today" else "7d"
    if not scope:
        return jsonify({
            "count": 0, "min_seconds": None, "max_seconds": None,
            "p50_seconds": None, "p90_seconds": None, "range": range_param,
        })

    return jsonify(cached_kpi(f"time_to_code:{range_param}", lambda: compute_time_to_code(scope, range_param)))


@bp.get("/reviewed")
@role_required("data_manager", "admin")
def review_rate():
    """KPI: C-09 — % Forms Reviewed.

    Numerator: COUNT of submissions that have at least one
               va_reviewer_final_assessments row with active status.
    Denominator: COUNT of submissions that ever reached coder_finalized
                 (CODED scope, excluding coder_finalized forms still inside
                 the project's recode window).
    Rate: N / D × 100.
    Scope: CODED.
    Time frames: 7d, cumulative.
    Note: reviewer-eligible forms can't be reviewed inside the recode
          window (``recode_window_minutes``, docs/policy/kpis.md "Recode
          window"), so the denominator excludes coder_finalized forms
          finalized within it.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({"reviewed": 0, "eligible": 0, "rate": 0.0})

    return jsonify(cached_kpi("review_rate", lambda: compute_review_rate(scope)))


@bp.get("/upstream-changes")
@role_required("data_manager", "admin")
def upstream_changes():
    """KPIs: C-10, C-11, D-WT-02, D-WT-04 (definitions on compute_upstream_changes)."""
    scope = dm_scope()
    if not scope:
        return jsonify({})

    return jsonify(cached_kpi("upstream_changes", lambda: compute_upstream_changes(scope)))


@bp.get("/inflow-outflow")
@role_required("data_manager", "admin")
def inflow_outflow():
    """KPI: C-19 — Daily Inflow vs Outflow, thin wrapper over ``compute_c19``."""
    scope = dm_scope()
    if not scope:
        return jsonify({"data": [], "net_28d": 0, "does_not_clear": False})

    days = clamped_int_arg("days", 7, 90)
    if days is None:
        return api_error("days must be a positive whole number.", "invalid_request", 400)

    return jsonify(cached_kpi(f"inflow_outflow:{days}", lambda: compute_c19(scope, days)))


@bp.get("/site-bottleneck")
@role_required("data_manager", "admin")
def site_bottleneck():
    """KPI: C-22 — Site-Level Bottleneck.

    Definition: Per site: (pending_count / total_count) × 100 — the %
                of a site's submissions that are still uncoded.
    Display: Table ranked by % uncoded DESC.
    Scope: CODING-POOL, grouped by site.
    Time frame: Snapshot.
    Actionable: The site at the top of this list is the bottleneck.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({"sites": []})

    return jsonify(cached_kpi("site_bottleneck", lambda: compute_site_bottleneck(scope)))


@bp.get("/reviewer-throughput")
@role_required("data_manager", "admin")
def reviewer_throughput():
    """KPI: D-WT-01 — Reviewer Throughput.

    Numerator: COUNT of events with transition_id = 'reviewer_finalized'
               in window.
    Time frames: Today, 7d, cumulative.
    Scope: CODED.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({"today": 0, "last_7d": 0, "cumulative": 0})

    return jsonify(cached_kpi("reviewer_throughput", lambda: compute_reviewer_throughput(scope)))


@bp.get("/backlog-trend")
@role_required("data_manager", "admin")
def backlog_trend():
    """KPI: D-WT-03 — Coding Backlog Trend, merged into C-04 as its trend view.

    End-of-day pending (6 states) per viewer day, replayed from events
    (``compute_c04`` series). Display: line chart, default 90-day window.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({"data": [], "source": "none"})

    days = clamped_int_arg("days", 90, 365)
    if days is None:
        return api_error("days must be a positive whole number.", "invalid_request", 400)

    return jsonify(cached_kpi(
        f"backlog_trend:{days}",
        lambda: {"data": compute_c04(scope, days)["series"], "source": "live"},
    ))
