"""DM KPI — Workflow State Distribution.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/workflow``

KPIs served:
  D-WF-01  CONSORT Pipeline Flowchart (state distribution with branches)
  D-WF-02  State Velocity (average time in each state)
  D-WF-03  State Stagnation Alerts (submissions stuck beyond thresholds)
  D-WF-04  Daily State Transitions (per-day transition counts)

Sources:
  - va_submission_workflow (current states)
  - va_submission_workflow_events (transitions, durations)
  - va_submissions, va_forms (scope filtering)

``finalized_upstream_changed`` rows split by the latest event's reason: an ODK
upstream change keeps the state, an open send-back or reopen reads as the
virtual state ``sent_back_for_revision`` (``revision_request_sql``). The split
applies to state counts, the flowchart and stagnation; ``state_velocity``
(D-WF-02) still reports raw stored states, so its ``finalized_upstream_changed``
row blends both kinds.

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
from app.services.kpi.workflow import (  # noqa: F401
    compute_daily_transitions,
    compute_flowchart,
    compute_stagnation,
    compute_state_velocity,
)

bp = Blueprint("dm_kpi_workflow", __name__)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# D-WF-01: CONSORT Pipeline Flowchart
# ---------------------------------------------------------------------------

@bp.get("/flowchart")
@role_required("data_manager", "admin")
def flowchart():
    """KPI: D-WF-01 — CONSORT Pipeline Flowchart.

    Returns a simplified CONSORT-style flow:
      All Synced
        → Excluded: Consent Refused + Not Codeable (DM)
        → Eligible for Coding
            → Excluded: Not Codeable (Coder)
            → Coded [within / beyond the recode window]
                → Reviewed
    """
    scope = dm_scope()
    if not scope:
        return jsonify({"total_synced": 0, "stages": {}})

    return jsonify(cached_kpi("flowchart", lambda: compute_flowchart(scope)))


# ---------------------------------------------------------------------------
# D-WF-02: State Velocity
# ---------------------------------------------------------------------------

@bp.get("/state-velocity")
@role_required("data_manager", "admin")
def state_velocity():
    """KPI: D-WF-02 State Velocity (definition on compute_state_velocity)."""
    scope = dm_scope()
    if not scope:
        return jsonify({"range_days": 30, "states": []})

    range_days = min(int(request.args.get("days", 30)), 90)

    return jsonify(cached_kpi(f"state_velocity:{range_days}", lambda: compute_state_velocity(scope, range_days)))


# ---------------------------------------------------------------------------
# D-WF-03: State Stagnation Alerts
# ---------------------------------------------------------------------------

@bp.get("/stagnation")
@role_required("data_manager", "admin")
def stagnation():
    """KPI: D-WF-03 — State Stagnation Alerts, thin wrapper over ``compute_c07(by="state")``.

    Thresholds are ``C07_STATE_THRESHOLDS``; coder_finalized alerts after the
    project's recode window. reviewer_eligible is left out of the totals.
    """

    scope = dm_scope()
    if not scope:
        return jsonify({"alerts": [], "total_stagnant_gt_48h": 0, "total_stagnant_gt_7d": 0})

    return jsonify(cached_kpi("stagnation", lambda: compute_stagnation(scope)))


# ---------------------------------------------------------------------------
# D-WF-04: Daily State Transitions
# ---------------------------------------------------------------------------

@bp.get("/daily-transitions")
@role_required("data_manager", "admin")
def daily_transitions():
    """KPI: D-WF-04 — Daily State Transitions.

    How many submissions entered each state per day over the trailing window.
    Extends C-19 inflow/outflow to all states.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({"days": []})

    days = min(int(request.args.get("days", 7)), 90)

    return jsonify(cached_kpi(f"daily_transitions:{days}", lambda: compute_daily_transitions(scope, days)))
