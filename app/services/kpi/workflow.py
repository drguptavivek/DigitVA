"""Query and compute code for the DM KPI endpoints of ``app/routes/api/dm_kpi/dm_kpi_workflow.py``.

Moved out of the route module unchanged (digitva-r8nh.16); the route parses
parameters, calls these functions and returns JSON.
"""


from __future__ import annotations

import logging

import sqlalchemy as sa

from app import db
from app.services.kpi.common import IN_ODK_SQL as _IN_ODK_SQL
from app.services.kpi.common import NOT_DUPLICATE_SQL as _NOT_DUPLICATE_SQL
from app.services.kpi.scope import (
    CLOCK_JOIN_SQL,
    DmScope,
    clock_day_sql,
    clock_params,
    in_last_days_sql,
)
from app.services.odk_retirement_service import IN_ODK_BIND
from app.services.workflow.revision_request_sql import (
    SENT_BACK_FOR_REVISION,
    effective_workflow_state_sql,
    revision_reasons_sql,
)

log = logging.getLogger(__name__)
_REVISION_REASONS_SQL = revision_reasons_sql()


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
    "sent_back_for_revision": "Sent Back for Revision",
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
    "sent_back_for_revision": "exception",
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
    "sent_back_for_revision": {"branch_from": "reviewer_eligible", "kind": "exception"},
}

# States that are optional (not traversed by all submissions)
OPTIONAL_STATES = frozenset({
    "screening_pending",
    "coder_step1_saved",
    "reviewer_eligible",
    "reviewer_coding_in_progress",
    "reviewer_finalized",
})

DM_ACTIONS: dict[str, str] = {
    "screening_pending": "Pass or reject screening",
    "attachment_sync_pending": "Trigger attachment sync",
    "smartva_pending": "Check SmartVA queue",
    "ready_for_coding": "Allocate coders or check capacity",
    "coding_in_progress": "Check coder allocation timeout",
    "coder_step1_saved": "Coder should return to complete",
    "coder_finalized": "Auto-progresses to reviewer_eligible after the recode window",
    "reviewer_eligible": "Assign reviewers or leave as-is",
    "reviewer_coding_in_progress": "Check reviewer allocation timeout",
    "finalized_upstream_changed": "Accept or reject upstream change",
    "sent_back_for_revision": "Wait for the interviewer or cancel the request",
}


# ---------------------------------------------------------------------------
# Shared base query: state counts grouped by workflow_state
# ---------------------------------------------------------------------------

def _state_counts(scope: DmScope) -> dict[str, int]:
    """Return {state: count} for the DM's scoped submissions.

    The state is the effective one: ``finalized_upstream_changed`` counts ODK
    changes only, open revision requests count as ``sent_back_for_revision``.
    """
    rows = db.session.execute(
        sa.text(f"""
            SELECT {effective_workflow_state_sql("w")} AS state, COUNT(*) AS count
            FROM va_submission_workflow w
            JOIN va_submissions s ON s.va_sid = w.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
            GROUP BY 1
        """),
        {**IN_ODK_BIND, **scope.params},
    ).mappings().all()
    return {r["state"]: r["count"] for r in rows}


def _coder_finalized_split(scope: DmScope) -> dict:
    """within/beyond the project's recode window for coder_finalized (C-07)."""
    from app.services.kpi.pipeline import compute_c07  # pipeline imports this module

    row = next(
        (r for r in compute_c07(scope, by="state")["states"] if r["state"] == "coder_finalized"),
        {},
    )
    return {
        "within_window": row.get("within_window", 0),
        "beyond_window": row.get("beyond_window", 0),
        "within_24h": row.get("within_24h", 0),
        "beyond_24h": row.get("gt_24h", 0),
    }


def compute_flowchart(scope: DmScope):
    counts = _state_counts(scope)
    total = sum(counts.values())
    split = _coder_finalized_split(scope)

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
        + counts.get(SENT_BACK_FOR_REVISION, 0)
    )
    upstream_changed = counts.get("finalized_upstream_changed", 0)
    sent_back = counts.get(SENT_BACK_FOR_REVISION, 0)
    reviewed = counts.get("reviewer_finalized", 0)

    # coder_finalized breakdown
    coder_finalized = counts.get("coder_finalized", 0)

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
                # within_24h / beyond_24h stay one release for the Expo client
                # (docs/policy/kpis.md, Recode window).
                **split,
            },
            "upstream_changed": upstream_changed,
            "sent_back": sent_back,
            "reviewed": reviewed,
        },
        "conversion": {
            "eligible_rate": round(eligible / total, 3) if total > 0 else 0,
            "coding_rate": round(coded / eligible, 3) if eligible > 0 else 0,
            "review_rate": round(reviewed / coded, 3) if coded > 0 else 0,
        },
    }


def compute_state_velocity(scope: DmScope, range_days: int):
    """KPI: D-WF-02 — State Velocity.

    Average time spent in each state before transitioning out.
    Uses a CTE on va_submission_workflow_events to compute per-transition
    durations, then aggregates per previous_state.
    """
    # The last range_days days on each event's project clock.

    rows = db.session.execute(
        sa.text(f"""
            WITH cur_events AS (
                SELECT
                    cur.va_sid,
                    cur.previous_state,
                    cur.current_state,
                    cur.event_created_at
                FROM va_submission_workflow_events cur
                JOIN va_submissions s ON s.va_sid = cur.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                {CLOCK_JOIN_SQL}
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND {in_last_days_sql("cur.event_created_at", "cur.event_created_at >= :clock_floor")}
                  AND cur.previous_state IS NOT NULL
                  -- Tester runs are not workflow activity (digitva-ggc3):
                  -- no event the tester wrote up to its return.
                  -- ponytail: a user who coded the case for real before
                  -- testing it loses those events too; lane-tag events
                  -- if that ever matters.
                  AND NOT EXISTS (
                      SELECT 1 FROM va_submission_workflow_events tr
                      WHERE tr.va_sid = cur.va_sid
                        AND tr.transition_id = 'tester_coding_returned'
                        AND tr.actor_user_id = cur.actor_user_id
                        AND tr.event_created_at >= cur.event_created_at
                  )
            ),
            transition_durations AS (
                SELECT
                    cur.va_sid,
                    cur.previous_state,
                    cur.current_state,
                    EXTRACT(EPOCH FROM (
                        cur.event_created_at - prev.event_created_at
                    ))::float AS duration_seconds
                FROM cur_events cur
                JOIN LATERAL (
                    SELECT
                        prev.event_created_at,
                        prev.current_state
                    FROM va_submission_workflow_events prev
                    WHERE prev.va_sid = cur.va_sid
                      AND prev.event_created_at < cur.event_created_at
                    ORDER BY prev.event_created_at DESC
                    LIMIT 1
                ) prev ON prev.current_state = cur.previous_state
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
        {**IN_ODK_BIND, **scope.params, **clock_params(range_days)},
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


def compute_stagnation(scope: DmScope):
    from app.services.kpi.pipeline import compute_c07  # pipeline imports this module

    alerts = compute_c07(scope, by="state")["states"]
    counted = [a for a in alerts if a["state"] != "reviewer_eligible"]
    return {
        "alerts": alerts,
        "total_stagnant_gt_48h": sum(a["gt_48h"] for a in counted),
        "total_stagnant_gt_7d": sum(a["gt_7d"] for a in counted),
    }


def compute_daily_transitions(scope: DmScope, days: int):
    # Each event on its own project's day, the last *days* of them.

    rows = db.session.execute(
        sa.text(f"""
            SELECT
                {clock_day_sql("e.event_created_at")} AS day,
                (CASE WHEN e.current_state = 'finalized_upstream_changed'
                       AND e.transition_reason IN {_REVISION_REASONS_SQL}
                      THEN '{SENT_BACK_FOR_REVISION}'
                      ELSE e.current_state END) AS target_state,
                COUNT(*) AS count
            FROM va_submission_workflow_events e
            JOIN va_submissions s ON s.va_sid = e.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            {CLOCK_JOIN_SQL}
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
              AND {in_last_days_sql("e.event_created_at", "e.event_created_at >= :clock_floor")}
              -- Tester runs are not workflow activity (digitva-ggc3).
              AND NOT EXISTS (
                  SELECT 1 FROM va_submission_workflow_events tr
                  WHERE tr.va_sid = e.va_sid
                    AND tr.transition_id = 'tester_coding_returned'
                    AND tr.actor_user_id = e.actor_user_id
                    AND tr.event_created_at >= e.event_created_at
              )
            GROUP BY 1, 2
            ORDER BY day ASC
        """),
        {**IN_ODK_BIND, **scope.params, **clock_params(days)},
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
