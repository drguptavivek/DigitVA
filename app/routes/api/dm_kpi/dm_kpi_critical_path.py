"""DM KPI — Critical Path (D-WF-02, digitva-r5s0 step 2, group g).

Blueprint prefix: ``/api/v1/analytics/dm-kpi/critical-path``

KPI served (docs/policy/kpis.md, "Critical-path view (D-WF-02)"):
  D-WF-02  The median and p90 time in each stage, the dominant stage and the
           bottleneck against peers.

Sources:
  - va_submission_workflow_events: time in a stage is an event's
    ``event_created_at`` minus that of the event before it, when that earlier
    event entered the stage (``previous_state``), as ``state_velocity`` pairs
    them.
  - ``area_dashboard_service._medians``: the end segments, death to interview
    and interview to final cause.

Stages (``STAGES``) are the pending states (``PENDING_STATES``) plus the
upstream stage, split by the reason of the event that entered it: an ODK
change (``finalized_upstream_changed``) or the Collect correction
(``sent_back_for_revision``, CL-02). Retired, duplicate, demo and tester
events are left out; the window is the last *period* days in the viewer's
timezone.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import sqlalchemy as sa
from flask import Blueprint, jsonify

from app import db
from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_outcomes import (
    peer_params,
    peer_units_sql,
    scope_clause,
    sibling_median,
)
from app.routes.api.dm_kpi.dm_kpi_scope import (
    NOT_DEMO_OUTPUT_SQL,
    DmScope,
    cached_kpi,
    dm_scope,
    local_day_start,
    local_today,
)
from app.routes.api.dm_kpi.dm_kpi_workflow import STATE_LABELS
from app.routes.api.request_helpers import clamped_int_arg
from app.routes.api.request_helpers import error as api_error
from app.services.area_dashboard_service import PERCENT_MIN_WHOLE, _medians
from app.services.duplicate_exclusion import not_confirmed_duplicate_sql
from app.services.odk_retirement_service import IN_ODK_BIND, in_odk_sql
from app.services.submission_analytics_mv import CORE_MV_NAME
from app.services.workflow.definition import (
    PENDING_STATES,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
)
from app.services.workflow.revision_request_sql import (
    SENT_BACK_FOR_REVISION,
    revision_reasons_sql,
)

bp = Blueprint("dm_kpi_critical_path", __name__)
log = logging.getLogger(__name__)

# Retired submissions are not counted (docs/policy/odk-retired-submissions.md).
_IN_ODK_SQL = in_odk_sql("s")
# Confirmed-duplicate web cases leave every count (app/services/duplicate_exclusion.py).
_NOT_DUPLICATE_SQL = not_confirmed_duplicate_sql("s.va_sid")

STAGES = (*PENDING_STATES, WORKFLOW_FINALIZED_UPSTREAM_CHANGED, SENT_BACK_FOR_REVISION)
DEFAULT_PERIOD_DAYS = 30
MAX_PERIOD_DAYS = 90


def _stage_rows(scope: DmScope, period: int) -> list:
    """Per stage, over the scope and per peer unit: n, p50 and p90 hours. One query."""
    cutoff = local_day_start(local_today(scope.tz) - timedelta(days=period - 1), scope.tz)
    stage = (
        f"(CASE WHEN e.previous_state = '{WORKFLOW_FINALIZED_UPSTREAM_CHANGED}'"
        f" AND COALESCE(prev.transition_reason, '') IN {revision_reasons_sql()}"
        f" THEN '{SENT_BACK_FOR_REVISION}' ELSE e.previous_state END)"
    )
    return db.session.execute(
        sa.text(f"""
            WITH peers AS ({peer_units_sql()}),
            spans AS (
                SELECT {stage} AS stage,
                       pu.org_unit_id AS unit_id,
                       pu.unit_name,
                       EXTRACT(EPOCH FROM (e.event_created_at - prev.event_created_at)) / 3600.0
                           AS hours
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                LEFT JOIN mas_org_unit su ON su.org_unit_id = s.org_unit_id
                LEFT JOIN peers pu ON pu.project_id = su.project_id AND su.path <@ pu.path
                JOIN LATERAL (
                    SELECT p.event_created_at, p.current_state, p.transition_reason
                    FROM va_submission_workflow_events p
                    WHERE p.va_sid = e.va_sid
                      AND p.event_created_at < e.event_created_at
                    ORDER BY p.event_created_at DESC
                    LIMIT 1
                ) prev ON prev.current_state = e.previous_state
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND {NOT_DEMO_OUTPUT_SQL}
                  AND e.event_created_at >= :cutoff
                  AND e.previous_state = ANY(CAST(:stage_states AS text[]))
                  -- Tester runs are not workflow activity (digitva-ggc3), as
                  -- in state_velocity.
                  AND NOT EXISTS (
                      SELECT 1 FROM va_submission_workflow_events tr
                      WHERE tr.va_sid = e.va_sid
                        AND tr.transition_id = 'tester_coding_returned'
                        AND tr.actor_user_id = e.actor_user_id
                        AND tr.event_created_at >= e.event_created_at
                  )
            )
            SELECT GROUPING(unit_id) = 1 AS total_row,
                   CAST(unit_id AS text) AS unit_id,
                   unit_name,
                   stage,
                   COUNT(*) AS n,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY hours) AS p50,
                   PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY hours) AS p90
            FROM spans
            GROUP BY GROUPING SETS ((stage), (unit_id, unit_name, stage))
        """),
        {
            **IN_ODK_BIND,
            **scope.params,
            **peer_params(scope),
            "cutoff": cutoff,
            "stage_states": list(STAGES[:-1]),
        },
    ).mappings().all()


def _hours(value) -> float | None:
    return None if value is None else round(float(value), 1)


def _stage(stage: str, r) -> dict:
    return {
        "stage": stage,
        "label": STATE_LABELS.get(stage, stage),
        "n": r["n"] if r else 0,
        "p50_hours": _hours(r["p50"]) if r else None,
        "p90_hours": _hours(r["p90"]) if r else None,
    }


def dominant_stage(stages: list[dict]) -> str | None:
    """The stage with the largest share of the summed stage medians, among
    stages with n of 20 or more; sets ``median_share`` on those stages."""
    ranked = [s for s in stages if s["n"] >= PERCENT_MIN_WHOLE and s["p50_hours"] is not None]
    total = sum(s["p50_hours"] for s in ranked)
    for s in ranked:
        s["median_share"] = round(100 * s["p50_hours"] / total, 1) if total else None
    if not ranked or not total:
        return None
    return max(ranked, key=lambda s: s["p50_hours"])["stage"]


def bottlenecks(units: list[dict]) -> dict | None:
    """Set each unit's ``bottleneck``: the stage with the largest positive gap
    of its median to the median of its siblings', counting only medians over
    n of 20 or more. Returns the largest such gap over all units, or None."""
    eligible = {
        stage: {
            u["unit_id"]: s["p50_hours"]
            for u in units for s in u["stages"]
            if s["stage"] == stage and s["n"] >= PERCENT_MIN_WHOLE
        }
        for stage in STAGES
    }
    worst = None
    for unit in units:
        unit["bottleneck"] = None
        for s in unit["stages"]:
            peer = sibling_median(eligible[s["stage"]], unit["unit_id"]) if s["n"] >= PERCENT_MIN_WHOLE else None
            s["peer_median_hours"] = None if peer is None else round(peer, 1)
            s["gap_hours"] = None if peer is None else round(s["p50_hours"] - peer, 1)
            if s["gap_hours"] is not None and s["gap_hours"] > 0 and (
                unit["bottleneck"] is None or s["gap_hours"] > unit["bottleneck"]["gap_hours"]
            ):
                unit["bottleneck"] = {"stage": s["stage"], "gap_hours": s["gap_hours"]}
        b = unit["bottleneck"]
        if b and (worst is None or b["gap_hours"] > worst["gap_hours"]):
            worst = {"unit_id": unit["unit_id"], "unit_name": unit["unit_name"], **b}
    return worst


def compute_dwf02(scope: DmScope, period: int = DEFAULT_PERIOD_DAYS, by: str | None = None) -> dict:
    """D-WF-02 critical path over the last *period* viewer days (1 to 90).

    ``stages``: n, p50 and p90 hours per stage over the scope; ``dominant``:
    the stage with the largest median share; ``units``: the same per peer
    unit, each with its ``bottleneck`` (largest positive gap to the sibling
    median); ``bottleneck``: the largest of those. ``end_segments``: median
    days death to interview and interview to final cause from ``_medians``
    (all time, demo not excluded). The rows are the peers, so *by* may be
    None or ``"unit"``. Raises ``ValueError`` for anything else.
    """
    if by not in (None, "unit"):
        raise ValueError(f"D-WF-02 has no by={by!r}")
    period = max(1, min(int(period or DEFAULT_PERIOD_DAYS), MAX_PERIOD_DAYS))
    if not scope:
        return {"period_days": period, "stages": [_stage(s, None) for s in STAGES],
                "dominant": None, "units": [], "bottleneck": None, "end_segments": None}

    rows = _stage_rows(scope, period)
    total = {r["stage"]: r for r in rows if r["total_row"]}
    per_unit: dict[str, dict] = {}
    for r in rows:
        if not r["total_row"] and r["unit_id"] is not None:
            unit = per_unit.setdefault(r["unit_id"], {"unit_id": r["unit_id"], "unit_name": r["unit_name"], "rows": {}})
            unit["rows"][r["stage"]] = r

    stages = [_stage(s, total.get(s)) for s in STAGES]
    units = []
    for unit in per_unit.values():
        unit_stages = [_stage(s, unit["rows"].get(s)) for s in STAGES]
        units.append({
            "unit_id": unit["unit_id"],
            "unit_name": unit["unit_name"],
            "stages": unit_stages,
            "dominant": dominant_stage(unit_stages),
        })
    units.sort(key=lambda u: u["unit_name"])
    end_segments = _medians(lambda *_columns: scope_clause(scope, CORE_MV_NAME, CORE_MV_NAME))
    return {
        "period_days": period,
        "stages": stages,
        "dominant": dominant_stage(stages),
        "units": units,
        "bottleneck": bottlenecks(units),
        "end_segments": end_segments,
    }


@bp.get("/")
@role_required("data_manager", "admin")
def critical_path():
    """KPI: D-WF-02 critical path (``?days=``, 1 to 90, default 30)."""
    days = clamped_int_arg("days", DEFAULT_PERIOD_DAYS, MAX_PERIOD_DAYS)
    if days is None:
        return api_error("days must be a positive whole number.", "invalid_request", 400)
    scope = dm_scope()
    return jsonify(cached_kpi("critical_path", lambda: compute_dwf02(scope, days)))
