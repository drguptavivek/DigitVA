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
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from flask import Blueprint, jsonify, request

from app import db
from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_scope import cached_kpi, dm_site_ids

bp = Blueprint("dm_kpi_workflow", __name__)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State metadata — labels, phases, stagnation thresholds
# ---------------------------------------------------------------------------

STATE_LABELS: dict[str, str] = {
    "screening_pending": "DM Screening",
    "attachment_sync_pending": "Attachment Sync",
    "smartva_pending": "SmartVA Processing",
    "ready_for_coding": "Ready for Coding",
    "coding_in_progress": "Coding in Progress",
    "coder_step1_saved": "Step 1 Saved",
    "coder_finalized": "Coder Finalized",
    "reviewer_eligible": "Reviewer Eligible",
    "reviewer_coding_in_progress": "Reviewer in Progress",
    "reviewer_finalized": "Reviewer Finalized",
    "finalized_upstream_changed": "Upstream Changed",
    "not_codeable_by_coder": "Not Codeable (Coder)",
    "not_codeable_by_data_manager": "Not Codeable (DM)",
    "consent_refused": "Consent Refused",
}

STATE_PHASES: dict[str, str] = {
    "screening_pending": "intake",
    "attachment_sync_pending": "intake",
    "smartva_pending": "preprocessing",
    "ready_for_coding": "coding",
    "coding_in_progress": "coding",
    "coder_step1_saved": "coding",
    "coder_finalized": "finalization",
    "reviewer_eligible": "review",
    "reviewer_coding_in_progress": "review",
    "reviewer_finalized": "review",
    "finalized_upstream_changed": "exception",
    "not_codeable_by_coder": "exclusion",
    "not_codeable_by_data_manager": "exclusion",
    "consent_refused": "exclusion",
}

# Ordered trunk nodes (main pipeline flow in sequence)
TRUNK_ORDER = [
    "attachment_sync_pending",
    "screening_pending",
    "smartva_pending",
    "ready_for_coding",
    "coding_in_progress",
    "coder_step1_saved",
    "coder_finalized",
    "reviewer_eligible",
    "reviewer_coding_in_progress",
    "reviewer_finalized",
]

# Terminal states that branch off specific trunk nodes
BRANCHES = {
    "consent_refused": {"branch_from": "__entry__", "kind": "exclusion"},
    "not_codeable_by_data_manager": {"branch_from": "screening_pending", "kind": "exclusion"},
    "not_codeable_by_coder": {"branch_from": "coding_in_progress", "kind": "exclusion"},
    "finalized_upstream_changed": {"branch_from": "reviewer_eligible", "kind": "exception"},
}

# States that are optional (not traversed by all submissions)
OPTIONAL_STATES = frozenset({
    "screening_pending",
    "coder_step1_saved",
    "reviewer_eligible",
    "reviewer_coding_in_progress",
    "reviewer_finalized",
})

# Stagnation thresholds per state (hours)
STAGNATION_THRESHOLDS: dict[str, dict] = {
    "attachment_sync_pending": {"normal": 2, "alert": 24},
    "screening_pending": {"normal": 24, "alert": 48, "critical": 168},
    "smartva_pending": {"normal": 2, "alert": 6, "critical": 24},
    "ready_for_coding": {"normal": 48, "alert": 168},
    "coding_in_progress": {"normal": 1, "alert": 24},
    "coder_step1_saved": {"normal": 4, "alert": 168},
    "coder_finalized": {"normal": 24, "alert": 168},  # 24h recode window
    "reviewer_eligible": {"normal": None, "alert": None, "critical": None},
    "reviewer_coding_in_progress": {"normal": 4, "alert": 168},
    "finalized_upstream_changed": {"normal": 48, "alert": 168},
}

DM_ACTIONS: dict[str, str] = {
    "screening_pending": "Pass or reject screening",
    "attachment_sync_pending": "Trigger attachment sync",
    "smartva_pending": "Check SmartVA queue",
    "ready_for_coding": "Allocate coders or check capacity",
    "coding_in_progress": "Check coder allocation timeout",
    "coder_step1_saved": "Coder should return to complete",
    "coder_finalized": "Auto-progresses to reviewer_eligible after 24h",
    "reviewer_eligible": "Assign reviewers or leave as-is",
    "reviewer_coding_in_progress": "Check reviewer allocation timeout",
    "finalized_upstream_changed": "Accept or reject upstream change",
}


# ---------------------------------------------------------------------------
# Shared base query: state counts grouped by workflow_state
# ---------------------------------------------------------------------------

def _state_counts(site_ids: list[str]) -> dict[str, int]:
    """Return {workflow_state: count} for the DM's scoped submissions."""
    rows = db.session.execute(
        sa.text("""
            SELECT w.workflow_state AS state, COUNT(*) AS count
            FROM va_submission_workflow w
            JOIN va_submissions s ON s.va_sid = w.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = ANY(:site_ids)
            GROUP BY w.workflow_state
        """),
        {"site_ids": site_ids},
    ).mappings().all()
    return {r["state"]: r["count"] for r in rows}


def _coder_finalized_24h_split(site_ids: list[str]) -> dict:
    """Return within_24h and beyond_24h counts for coder_finalized."""
    row = db.session.execute(
        sa.text("""
            SELECT
                COUNT(*) FILTER (
                    WHERE w.workflow_updated_at >= NOW() - INTERVAL '24 hours'
                ) AS within_24h,
                COUNT(*) FILTER (
                    WHERE w.workflow_updated_at < NOW() - INTERVAL '24 hours'
                ) AS beyond_24h
            FROM va_submission_workflow w
            JOIN va_submissions s ON s.va_sid = w.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = ANY(:site_ids)
              AND w.workflow_state = 'coder_finalized'
        """),
        {"site_ids": site_ids},
    ).mappings().first()
    return {
        "within_24h": row["within_24h"] or 0,
        "beyond_24h": row["beyond_24h"] or 0,
    }


# ---------------------------------------------------------------------------
# D-WF-01: CONSORT Pipeline Flowchart
# ---------------------------------------------------------------------------

@bp.get("/flowchart")
@role_required("data_manager")
def flowchart():
    """KPI: D-WF-01 — CONSORT Pipeline Flowchart.

    Returns a simplified CONSORT-style flow:
      All Synced
        → Excluded: Consent Refused + Not Codeable (DM)
        → Eligible for Coding
            → Excluded: Not Codeable (Coder)
            → Coded [within 24h / beyond 24h]
                → Reviewed
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"total_synced": 0, "stages": {}})

    def compute():
        counts = _state_counts(site_ids)
        total = sum(counts.values())
        split = _coder_finalized_24h_split(site_ids)

        # Counts per group
        consent_refused = counts.get("consent_refused", 0)
        not_codeable_dm = counts.get("not_codeable_by_data_manager", 0)
        not_codeable_coder = counts.get("not_codeable_by_coder", 0)

        eligible = total - consent_refused - not_codeable_dm
        # Currently uncoded = in pre-coding or coding states
        uncoded_eligible = (
            counts.get("attachment_sync_pending", 0)
            + counts.get("screening_pending", 0)
            + counts.get("smartva_pending", 0)
            + counts.get("ready_for_coding", 0)
            + counts.get("coding_in_progress", 0)
            + counts.get("coder_step1_saved", 0)
        )
        coded = (
            counts.get("coder_finalized", 0)
            + counts.get("reviewer_eligible", 0)
            + counts.get("reviewer_coding_in_progress", 0)
            + counts.get("reviewer_finalized", 0)
            + counts.get("finalized_upstream_changed", 0)
        )
        upstream_changed = counts.get("finalized_upstream_changed", 0)
        reviewed = counts.get("reviewer_finalized", 0)

        # coder_finalized breakdown
        coder_finalized = counts.get("coder_finalized", 0)
        within_24h = split["within_24h"]
        beyond_24h = split["beyond_24h"]

        return {
            "total_synced": total,
            "stages": {
                "all_synced": total,
                "excluded_entry": {
                    "consent_refused": consent_refused,
                    "not_codeable_dm": not_codeable_dm,
                    "total": consent_refused + not_codeable_dm,
                },
                "eligible_for_coding": eligible,
                "excluded_coding": {
                    "not_codeable_coder": not_codeable_coder,
                },
                "uncoded_eligible": uncoded_eligible,
                "coded": coded,
                "coder_finalized": {
                    "total": coder_finalized,
                    "within_24h": within_24h,
                    "beyond_24h": beyond_24h,
                },
                "upstream_changed": upstream_changed,
                "reviewed": reviewed,
            },
            "conversion": {
                "eligible_rate": round(eligible / total, 3) if total > 0 else 0,
                "coding_rate": round(coded / eligible, 3) if eligible > 0 else 0,
                "review_rate": round(reviewed / coded, 3) if coded > 0 else 0,
            },
        }

    return jsonify(cached_kpi("flowchart", compute))


# ---------------------------------------------------------------------------
# D-WF-02: State Velocity
# ---------------------------------------------------------------------------

@bp.get("/state-velocity")
@role_required("data_manager")
def state_velocity():
    """KPI: D-WF-02 — State Velocity.

    Average time spent in each state before transitioning out.
    Uses a CTE on va_submission_workflow_events to compute per-transition
    durations, then aggregates per previous_state.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"range_days": 30, "states": []})

    range_days = min(int(request.args.get("days", 30)), 90)

    def compute():
        cutoff = datetime.now(timezone.utc) - timedelta(days=range_days)

        rows = db.session.execute(
            sa.text("""
                WITH transition_durations AS (
                    SELECT
                        cur.va_sid,
                        cur.previous_state,
                        cur.current_state,
                        EXTRACT(EPOCH FROM (
                            cur.event_created_at - prev.event_created_at
                        ))::float AS duration_seconds
                    FROM va_submission_workflow_events cur
                    JOIN va_submission_workflow_events prev
                        ON prev.va_sid = cur.va_sid
                        AND prev.event_created_at < cur.event_created_at
                    JOIN va_submissions s ON s.va_sid = cur.va_sid
                    JOIN va_forms f ON f.form_id = s.va_form_id
                    WHERE f.site_id = ANY(:site_ids)
                      AND cur.event_created_at >= :cutoff
                      AND cur.previous_state IS NOT NULL
                      AND prev.current_state = cur.previous_state
                )
                SELECT
                    previous_state AS state,
                    COUNT(*) AS transition_count,
                    AVG(duration_seconds) AS avg_seconds,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (
                        ORDER BY duration_seconds
                    ) AS p50_seconds,
                    PERCENTILE_CONT(0.9) WITHIN GROUP (
                        ORDER BY duration_seconds
                    ) AS p90_seconds
                FROM transition_durations
                GROUP BY previous_state
                ORDER BY avg_seconds DESC
            """),
            {"site_ids": site_ids, "cutoff": cutoff},
        ).mappings().all()

        states = []
        for r in rows:
            avg_s = r["avg_seconds"] or 0
            p50_s = r["p50_seconds"] or 0
            p90_s = r["p90_seconds"] or 0
            states.append({
                "state": r["state"],
                "label": STATE_LABELS.get(r["state"], r["state"]),
                "transition_count": r["transition_count"] or 0,
                "avg_hours": round(avg_s / 3600, 1),
                "p50_hours": round(p50_s / 3600, 1),
                "p90_hours": round(p90_s / 3600, 1),
            })

        return {"range_days": range_days, "states": states}

    return jsonify(cached_kpi(f"state_velocity:{range_days}", compute))


# ---------------------------------------------------------------------------
# D-WF-03: State Stagnation Alerts
# ---------------------------------------------------------------------------

@bp.get("/stagnation")
@role_required("data_manager")
def stagnation():
    """KPI: D-WF-03 — State Stagnation Alerts.

    Submissions stuck in non-terminal states beyond configurable thresholds.
    Returns per-state counts with age buckets and alert levels.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"alerts": [], "total_stagnant_gt_48h": 0, "total_stagnant_gt_7d": 0})

    def compute():
        non_terminal = list(STAGNATION_THRESHOLDS.keys())

        rows = db.session.execute(
            sa.text("""
                SELECT
                    w.workflow_state AS state,
                    COUNT(*) AS total,
                    COUNT(*) FILTER (
                        WHERE w.workflow_updated_at < NOW() - INTERVAL '2 hours'
                    ) AS gt_2h,
                    COUNT(*) FILTER (
                        WHERE w.workflow_updated_at < NOW() - INTERVAL '24 hours'
                    ) AS gt_24h,
                    COUNT(*) FILTER (
                        WHERE w.workflow_updated_at < NOW() - INTERVAL '48 hours'
                    ) AS gt_48h,
                    COUNT(*) FILTER (
                        WHERE w.workflow_updated_at < NOW() - INTERVAL '7 days'
                    ) AS gt_7d,
                    COUNT(*) FILTER (
                        WHERE w.workflow_updated_at < NOW() - INTERVAL '30 days'
                    ) AS gt_30d,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (
                        ORDER BY EXTRACT(EPOCH FROM (NOW() - w.workflow_updated_at))
                    ) AS p50_age_seconds,
                    MAX(EXTRACT(EPOCH FROM (NOW() - w.workflow_updated_at))) AS max_age_seconds
                FROM va_submission_workflow w
                JOIN va_submissions s ON s.va_sid = w.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND w.workflow_state = ANY(:non_terminal)
                GROUP BY w.workflow_state
                ORDER BY gt_7d DESC
            """),
            {"site_ids": site_ids, "non_terminal": non_terminal},
        ).mappings().all()

        alerts = []
        total_gt_48h = 0
        total_gt_7d = 0

        for r in rows:
            state = r["state"]
            thresholds = STAGNATION_THRESHOLDS.get(state, {})
            p50_s = r["p50_age_seconds"] or 0
            gt_7d = r["gt_7d"] or 0
            gt_48h = r["gt_48h"] or 0

            # Determine alert level
            if thresholds.get("critical") and gt_7d > 0:
                level = "critical"
            elif thresholds.get("alert") and gt_48h > 0:
                level = "warning"
            elif state == "coder_finalized":
                # Special: within 24h is normal recode window
                gt_24h_val = r["gt_24h"] or 0
                level = "info" if gt_24h_val == 0 else "warning"
            elif thresholds.get("alert") is None:
                level = "normal"  # e.g., reviewer_eligible
            else:
                level = "normal"

            alert: dict = {
                "state": state,
                "label": STATE_LABELS.get(state, state),
                "total": r["total"] or 0,
                "gt_48h": gt_48h,
                "gt_7d": gt_7d,
                "gt_30d": r["gt_30d"] or 0,
                "p50_age_hours": round(p50_s / 3600, 1) if p50_s else 0,
                "alert_level": level,
                "dm_action": DM_ACTIONS.get(state, ""),
            }

            # Special sub-phases for coder_finalized
            if state == "coder_finalized":
                alert["within_24h"] = (r["total"] or 0) - (r["gt_24h"] or 0)
                alert["gt_24h"] = r["gt_24h"] or 0
                alert["note"] = "Within 24h is normal recode window"

            alerts.append(alert)

            # Skip reviewer_eligible from global stagnation counts
            if state != "reviewer_eligible":
                total_gt_48h += gt_48h
                total_gt_7d += gt_7d

        return {
            "alerts": alerts,
            "total_stagnant_gt_48h": total_gt_48h,
            "total_stagnant_gt_7d": total_gt_7d,
        }

    return jsonify(cached_kpi("stagnation", compute))


# ---------------------------------------------------------------------------
# D-WF-04: Daily State Transitions
# ---------------------------------------------------------------------------

@bp.get("/daily-transitions")
@role_required("data_manager")
def daily_transitions():
    """KPI: D-WF-04 — Daily State Transitions.

    How many submissions entered each state per day over the trailing window.
    Extends C-19 inflow/outflow to all states.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"days": []})

    days = min(int(request.args.get("days", 7)), 90)

    def compute():
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        rows = db.session.execute(
            sa.text("""
                SELECT
                    DATE(e.event_created_at) AS day,
                    e.current_state AS target_state,
                    COUNT(*) AS count
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND e.event_created_at >= :cutoff
                GROUP BY DATE(e.event_created_at), e.current_state
                ORDER BY day ASC
            """),
            {"site_ids": site_ids, "cutoff": cutoff},
        ).mappings().all()

        # Pivot into per-day dicts
        day_map: dict[str, dict] = {}
        for r in rows:
            day_str = str(r["day"])
            if day_str not in day_map:
                day_map[day_str] = {"date": day_str, "transitions": {}, "total": 0}
            day_map[day_str]["transitions"][r["target_state"]] = r["count"]
            day_map[day_str]["total"] += r["count"]

        return {"days": list(day_map.values())}

    return jsonify(cached_kpi(f"daily_transitions:{days}", compute))
