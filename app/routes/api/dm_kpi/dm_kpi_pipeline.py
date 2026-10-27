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
    through ``bucket_flow_by_day`` in the viewer's timezone)
  - va_submission_upstream_changes (resolution times)

Core KPIs (C-04, C-07, C-08, C-19) are ``compute_<id>(scope, period, by)``
functions; their routes are thin wrappers.

Submissions retired from ODK are excluded from every count, list,
grouping and average below (docs/policy/odk-retired-submissions.md).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from flask import Blueprint, jsonify, request

from app import db
from app.decorators import role_required
from app.routes.api.request_helpers import clamped_int_arg, error as api_error
from app.services.duplicate_exclusion import not_confirmed_duplicate_sql
from app.services.odk_retirement_service import IN_ODK_BIND, in_odk_sql
from app.services.workflow.definition import (
    CODER_READY_POOL_STATES_SQL,
    PENDING_STATES,
    PENDING_STATES_SQL,
)
from app.routes.api.dm_kpi.dm_kpi_scope import (
    NOT_DEMO_OUTPUT_SQL,
    DmScope,
    bucket_flow_by_day,
    cached_kpi,
    dm_scope,
    local_day_start,
    local_today,
)
from app.routes.api.dm_kpi.dm_kpi_workflow import DM_ACTIONS, STATE_LABELS
from app.services.workflow.revision_request_sql import (
    SENT_BACK_FOR_REVISION,
    dm_reopen_event_sql,
    effective_workflow_state_sql,
    odk_detected_event_sql,
    revision_request_open_sql,
)

bp = Blueprint("dm_kpi_pipeline", __name__)
log = logging.getLogger(__name__)

# Retired submissions are not counted (docs/policy/odk-retired-submissions.md).
_IN_ODK_SQL = in_odk_sql("s")
# Confirmed-duplicate web cases leave every count (app/services/duplicate_exclusion.py).
_NOT_DUPLICATE_SQL = not_confirmed_duplicate_sql("s.va_sid")

#: Days of outflow behind C-04's days to clear and C-19's net (forecast view).
FLOW_AVERAGE_DAYS = 28
#: The project's recode window, for a query joining ``va_project_master pm``.
_RECODE_WINDOW_SQL = "(COALESCE(pm.recode_window_minutes, 1440) * INTERVAL '1 minute')"

#: D-WF-03 stagnation thresholds (docs/policy/kpis.md, C-07): state ->
#: (alert after, critical after) in hours. coder_finalized alerts after the
#: project's recode window instead; reviewer_eligible has no threshold.
C07_STATE_THRESHOLDS: dict[str, tuple[int | None, int | None]] = {
    "attachment_sync_pending": (2, 24),
    "screening_pending": (48, 168),
    "smartva_pending": (6, 24),
    "ready_for_coding": (48, 168),
    "coding_in_progress": (2, 24),
    "coder_step1_saved": (24, 168),
    "coder_finalized": (None, 168),
    "reviewer_eligible": (None, None),
    "reviewer_coding_in_progress": (24, 168),
    "finalized_upstream_changed": (48, 168),
    SENT_BACK_FOR_REVISION: (48, 168),
}


@bp.get("/pending")
@role_required("data_manager", "admin")
def pending_rate():
    """KPI: C-04 — % Uncoded (Pending Rate), thin wrapper over ``compute_c04``."""
    scope = dm_scope()
    if not scope:
        return jsonify({"pending": 0, "coding_pool": 0, "rate": 0.0, "days_to_clear": None})

    def compute():
        result = compute_c04(scope)
        result.pop("series")
        return result

    return jsonify(cached_kpi("pending_rate", compute))


def compute_c04(scope: DmScope, period: int = FLOW_AVERAGE_DAYS, by: str | None = None) -> dict:
    """C-04: pending, coding pool, rate, days to clear and the pending series.

    - pending: the 6 PENDING_STATES now; coding_pool: every case but
      consent_refused / not_codeable_by_data_manager; rate = pending / pool.
    - days_to_clear = pending / mean daily outflow of the last 28 days
      (forecast view); None when nothing left the pending set in 28 days.
    - series: end-of-day pending for the last *period* days (the trend view,
      formerly D-WT-03), replayed from events.

    Two queries. Raises ``ValueError`` for an unsupported *by*.
    """
    if by is not None:
        raise ValueError(f"C-04 does not support by={by!r}")
    row = db.session.execute(
        sa.text(f"""
            SELECT
                COUNT(*) FILTER (WHERE w.workflow_state NOT IN (
                    'consent_refused', 'not_codeable_by_data_manager'
                )) AS coding_pool,
                COUNT(*) FILTER (WHERE w.workflow_state IN {PENDING_STATES_SQL}) AS pending
            FROM va_submissions s
            JOIN va_forms f ON f.form_id = s.va_form_id
            JOIN va_submission_workflow w ON w.va_sid = s.va_sid
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
        """),
        {**IN_ODK_BIND, **scope.params},
    ).mappings().first()
    pool = row["coding_pool"] or 0
    pending = row["pending"] or 0

    flow = _pending_flow(scope, max(period, FLOW_AVERAGE_DAYS))
    outflow_28d = sum(d["outflow"] for d in flow[-FLOW_AVERAGE_DAYS:])
    mean_outflow = outflow_28d / FLOW_AVERAGE_DAYS
    return {
        "pending": pending,
        "coding_pool": pool,
        "rate": round(pending / pool * 100, 1) if pool > 0 else 0.0,
        "outflow_28d": outflow_28d,
        "mean_daily_outflow_28d": round(mean_outflow, 2),
        "days_to_clear": round(pending / mean_outflow, 1) if mean_outflow > 0 else None,
        "series": [{"date": d["date"], "pending": d["end_of_day"]} for d in flow[-period:]],
    }


def _pending_flow(scope: DmScope, days: int) -> list[dict]:
    """``bucket_flow_by_day`` over the pending set for the last *days* viewer days."""
    today = local_today(scope.tz)
    return bucket_flow_by_day(
        scope.sql(), scope.params, PENDING_STATES,
        today - timedelta(days=days - 1), today, scope.tz,
    )


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


def compute_c07(scope: DmScope, period=None, by: str | None = None) -> dict:
    """C-07: aged cases (snapshot; *period* is unused).

    - by=None: the ready pool (ready_for_coding) not updated for over 48 h,
      7 d and 30 d.
    - by="state": every non-terminal state (the effective one, so open
      send-backs read as ``sent_back_for_revision``) with its age buckets,
      p50 / max age and the D-WF-03 alert and critical counts
      (``C07_STATE_THRESHOLDS``). coder_finalized alerts after the project's
      ``recode_window_minutes`` and carries ``within_window`` /
      ``beyond_window``; ``within_24h`` / ``gt_24h`` stay one release for
      the Expo client.

    One query. Raises ``ValueError`` for an unsupported *by*.
    """
    if by is None:
        return _ready_pool_aging(scope)
    if by != "state":
        raise ValueError(f"C-07 does not support by={by!r}")

    states = list(C07_STATE_THRESHOLDS)
    rows = db.session.execute(
        sa.text(f"""
            WITH th AS (
                SELECT * FROM unnest(
                    CAST(:th_states AS text[]),
                    CAST(:th_alert_h AS int[]),
                    CAST(:th_critical_h AS int[])
                ) AS t(state, alert_h, critical_h)
            ), aged AS (
                SELECT {effective_workflow_state_sql("w")} AS state,
                       EXTRACT(EPOCH FROM (NOW() - timezone('UTC', w.workflow_updated_at))) AS age_s,
                       EXTRACT(EPOCH FROM {_RECODE_WINDOW_SQL}) AS window_s
                FROM va_submission_workflow w
                JOIN va_submissions s ON s.va_sid = w.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                JOIN va_project_master pm ON pm.project_id = f.project_id
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND w.workflow_state = ANY(CAST(:th_states AS text[]))
            )
            SELECT a.state,
                   COUNT(*) AS total,
                   COUNT(*) FILTER (WHERE a.age_s > 48 * 3600) AS gt_48h,
                   COUNT(*) FILTER (WHERE a.age_s > 7 * 86400) AS gt_7d,
                   COUNT(*) FILTER (WHERE a.age_s > 30 * 86400) AS gt_30d,
                   COUNT(*) FILTER (WHERE a.age_s > CASE
                       WHEN a.state = 'coder_finalized' THEN a.window_s
                       ELSE th.alert_h * 3600 END) AS alert_count,
                   COUNT(*) FILTER (WHERE a.age_s > th.critical_h * 3600) AS critical_count,
                   COUNT(*) FILTER (WHERE a.age_s <= a.window_s) AS within_window,
                   COUNT(*) FILTER (WHERE a.age_s <= 86400) AS within_24h,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY a.age_s) AS p50_age_s,
                   MAX(a.age_s) AS max_age_s
            FROM aged a
            JOIN th ON th.state = a.state
            GROUP BY a.state
        """),
        {
            **IN_ODK_BIND,
            **scope.params,
            "th_states": states,
            "th_alert_h": [C07_STATE_THRESHOLDS[s][0] for s in states],
            "th_critical_h": [C07_STATE_THRESHOLDS[s][1] for s in states],
        },
    ).mappings().all()

    out = []
    for r in rows:
        if r["critical_count"]:
            level = "critical"
        elif r["alert_count"]:
            level = "warning"
        else:
            level = "normal"
        item = {
            "state": r["state"],
            "label": STATE_LABELS.get(r["state"], r["state"]),
            "total": r["total"],
            "gt_48h": r["gt_48h"],
            "gt_7d": r["gt_7d"],
            "gt_30d": r["gt_30d"],
            "alert_count": r["alert_count"],
            "critical_count": r["critical_count"],
            "p50_age_hours": round(float(r["p50_age_s"]) / 3600, 1),
            "max_age_hours": round(float(r["max_age_s"]) / 3600, 1),
            "alert_level": level,
            "dm_action": DM_ACTIONS.get(r["state"], ""),
        }
        if r["state"] == "coder_finalized":
            item["within_window"] = r["within_window"]
            item["beyond_window"] = r["total"] - r["within_window"]
            # One release of overlap for the Expo client (docs/policy/kpis.md, Recode window).
            item["within_24h"] = r["within_24h"]
            item["gt_24h"] = r["total"] - r["within_24h"]
        out.append(item)
    order = {state: i for i, state in enumerate(states)}
    out.sort(key=lambda item: order[item["state"]])
    return {"by": "state", "states": out}


def _ready_pool_aging(scope: DmScope) -> dict:
    """Ready-pool cases not updated for over 48 h, 7 d and 30 d."""
    row = db.session.execute(
        sa.text(f"""
            SELECT
                COUNT(*) FILTER (WHERE w.workflow_updated_at < NOW() - INTERVAL '48 hours') AS gt_48h,
                COUNT(*) FILTER (WHERE w.workflow_updated_at < NOW() - INTERVAL '7 days') AS gt_7d,
                COUNT(*) FILTER (WHERE w.workflow_updated_at < NOW() - INTERVAL '30 days') AS gt_30d
            FROM va_submission_workflow w
            JOIN va_submissions s ON s.va_sid = w.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
              AND w.workflow_state IN {CODER_READY_POOL_STATES_SQL}
        """),
        {**IN_ODK_BIND, **scope.params},
    ).mappings().first()
    return {"gt_48h": row["gt_48h"] or 0, "gt_7d": row["gt_7d"] or 0, "gt_30d": row["gt_30d"] or 0}


@bp.get("/time-to-code")
@role_required("data_manager", "admin")
def time_to_code():
    """KPI: C-08 — Time to Code, thin wrapper over ``compute_c08``.

    ``range=today`` is since midnight in the viewer's timezone; anything else
    is the last 7 days including today.
    """
    scope = dm_scope()
    range_param = "today" if request.args.get("range") == "today" else "7d"
    if not scope:
        return jsonify({
            "count": 0, "min_seconds": None, "max_seconds": None,
            "p50_seconds": None, "p90_seconds": None, "range": range_param,
        })

    def compute():
        return {**compute_c08(scope, 1 if range_param == "today" else 7), "range": range_param}

    return jsonify(cached_kpi(f"time_to_code:{range_param}", compute))


def compute_c08(scope: DmScope, period: int = 7, by: str | None = None) -> dict:
    """C-08: coding-episode durations finalized in the last *period* viewer days.

    Each non-demo coder_finalized / recode_finalized event is paired, through
    a LATERAL lookup, with the latest coding_started / recode_started of the
    same submission at or before it, so a recoded case yields one duration
    per finalize and none is negative. A finalize with no start is skipped.
    Returns count, min, max, p50 (median) and p90 in seconds. One query.
    Raises ``ValueError`` for an unsupported *by*.
    """
    if by is not None:
        raise ValueError(f"C-08 does not support by={by!r}")
    cutoff = local_day_start(local_today(scope.tz) - timedelta(days=period - 1), scope.tz)
    row = db.session.execute(
        sa.text(f"""
            SELECT
                COUNT(*) AS cnt,
                MIN(x.secs) AS min_dur,
                MAX(x.secs) AS max_dur,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY x.secs) AS p50_dur,
                PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY x.secs) AS p90_dur
            FROM va_submission_workflow_events e
            JOIN va_submissions s ON s.va_sid = e.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            CROSS JOIN LATERAL (
                SELECT EXTRACT(EPOCH FROM (e.event_created_at - MAX(st.event_created_at))) AS secs
                FROM va_submission_workflow_events st
                WHERE st.va_sid = e.va_sid
                  AND st.transition_id IN ('coding_started', 'recode_started')
                  AND st.event_created_at <= e.event_created_at
                HAVING MAX(st.event_created_at) IS NOT NULL
            ) x
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
              AND e.transition_id IN ('coder_finalized', 'recode_finalized')
              AND e.event_created_at >= :cutoff
              AND {NOT_DEMO_OUTPUT_SQL}
        """),
        {**IN_ODK_BIND, **scope.params, "cutoff": cutoff},
    ).mappings().first()

    def _fmt(val):
        return round(float(val), 1) if val is not None else None

    return {
        "count": row["cnt"] or 0,
        "min_seconds": _fmt(row["min_dur"]),
        "max_seconds": _fmt(row["max_dur"]),
        "p50_seconds": _fmt(row["p50_dur"]),
        "p90_seconds": _fmt(row["p90_dur"]),
    }


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

    def compute():
        row = db.session.execute(
            sa.text(f"""
                WITH coded AS (
                    SELECT s.va_sid
                    FROM va_submissions s
                    JOIN va_forms f ON f.form_id = s.va_form_id
                    JOIN va_project_master pm ON pm.project_id = f.project_id
                    JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                    WHERE {scope.sql()}
                      AND {_IN_ODK_SQL}
                      AND {_NOT_DUPLICATE_SQL}
                      AND (
                          w.workflow_state IN (
                              'reviewer_eligible', 'reviewer_coding_in_progress',
                              'reviewer_finalized', 'finalized_upstream_changed'
                          )
                          OR EXISTS (
                              SELECT 1 FROM va_submission_workflow_events e
                              WHERE e.va_sid = s.va_sid
                                AND e.transition_id = 'coder_finalized'
                                AND e.event_created_at < NOW() - {_RECODE_WINDOW_SQL}
                          )
                      )
                ),
                with_review AS (
                    SELECT DISTINCT c.va_sid
                    FROM coded c
                    WHERE EXISTS (
                        SELECT 1 FROM va_reviewer_final_assessments rf
                        WHERE rf.va_sid = c.va_sid
                          AND rf.va_rfinassess_status = 'active'
                    )
                )
                SELECT
                    (SELECT COUNT(*) FROM coded) AS eligible,
                    (SELECT COUNT(*) FROM with_review) AS reviewed
            """),
            {**IN_ODK_BIND, **scope.params},
        ).mappings().first()

        eligible = row["eligible"] or 0 if row else 0
        reviewed = row["reviewed"] or 0 if row else 0
        rate = round(reviewed / eligible * 100, 1) if eligible > 0 else 0.0

        return {"reviewed": reviewed, "eligible": eligible, "rate": rate}

    return jsonify(cached_kpi("review_rate", compute))


@bp.get("/upstream-changes")
@role_required("data_manager", "admin")
def upstream_changes():
    """KPIs: C-10 (Upstream Change Queue), C-11 (% Forms with Upstream Changes),
    D-WT-02 (Upstream Change Resolution Time), D-WT-04 (Reopen Rate).

    C-10 — Upstream Change Queue:
      Definition: COUNT WHERE workflow_state = 'finalized_upstream_changed'
                  and the latest workflow event is not a send-back or reopen
                  (ODK upstream changes only). The open send-backs and reopens
                  are counted apart as ``c10_sent_back_count``.
      Scope: CODED.
      Time frame: Snapshot.
      Source: va_submission_workflow (direct query, no MV).

    C-11 — % Forms with Upstream Changes:
      Numerator: COUNT of submissions with at least one
                 upstream_change_detected event that is an ODK change (a
                 send-back or reopen reuses the event; its reason excludes it).
      Denominator: COUNT of CODED submissions.
      Rate: N / D × 100.
      Time frames: 7d, cumulative.

    D-WT-02 — Upstream Change Resolution Time:
      Definition: For resolved upstream changes in 7d, resolved_at − created_at.
      Aggregate: PERCENTILE(0.5).
      Source: va_submission_upstream_changes (rows exist for ODK changes
              only, so send-backs are already excluded).
      Time frame: 7d.

    D-WT-04 — Reopen Rate:
      Numerator: COUNT of events with transition_id IN
                 ('upstream_change_accepted', 'admin_override_to_recode') in window,
                 minus the interviewer's revision restarts and a supervisor's
                 chosen interview (transition_reason ``interviewer_revision`` /
                 ``interview_chosen``), which are not data-manager reopens.
                 Those restarts are ``d_wt_04_revision_restarts_7d``.
      Denominator: COUNT of coder_finalized events in window.
      Rate: N / D × 100.
      Scope: CODED.
      Time frames: 7d, cumulative.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({})

    def compute():
        # C-10: upstream change queue (snapshot)
        queue_row = db.session.execute(
            sa.text(f"""
                SELECT COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE {revision_request_open_sql("w.va_sid")}) AS sent_back
                FROM va_submission_workflow w
                JOIN va_submissions s ON s.va_sid = w.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND w.workflow_state = 'finalized_upstream_changed'
            """),
            {**IN_ODK_BIND, **scope.params},
        ).mappings().first()
        sent_back_count = queue_row["sent_back"] or 0
        queue_count = (queue_row["total"] or 0) - sent_back_count

        # C-11: % forms with upstream changes (cumulative)
        upstream_pct = db.session.execute(
            sa.text(f"""
                WITH coded AS (
                    SELECT s.va_sid
                    FROM va_submissions s
                    JOIN va_forms f ON f.form_id = s.va_form_id
                    JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                    WHERE {scope.sql()}
                      AND {_IN_ODK_SQL}
                      AND {_NOT_DUPLICATE_SQL}
                      AND w.workflow_state IN (
                          'coder_finalized', 'reviewer_eligible',
                          'reviewer_coding_in_progress', 'reviewer_finalized',
                          'finalized_upstream_changed'
                      )
                )
                SELECT
                    COUNT(*) AS total_coded,
                    COUNT(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM va_submission_workflow_events e
                        WHERE e.va_sid = c.va_sid
                          AND e.transition_id = 'upstream_change_detected'
                          AND {odk_detected_event_sql("e")}
                    )) AS with_upstream
                FROM coded c
            """),
            {**IN_ODK_BIND, **scope.params},
        ).mappings().first()

        total_coded = upstream_pct["total_coded"] or 0 if upstream_pct else 0
        with_upstream = upstream_pct["with_upstream"] or 0 if upstream_pct else 0
        upstream_rate = round(with_upstream / total_coded * 100, 1) if total_coded > 0 else 0.0

        # D-WT-02: resolution time (7d)
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        resolution = db.session.execute(
            sa.text(f"""
                SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY
                    EXTRACT(EPOCH FROM (uc.resolved_at - uc.created_at))
                ) AS p50_seconds
                FROM va_submission_upstream_changes uc
                JOIN va_submissions s ON s.va_sid = uc.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND uc.resolved_at IS NOT NULL
                  AND uc.resolved_at >= :cutoff
            """),
            {**IN_ODK_BIND, **scope.params, "cutoff": seven_days_ago},
        ).scalar()

        # D-WT-04: reopen rate (7d)
        reopen = db.session.execute(
            sa.text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE e.transition_id IN (
                        'upstream_change_accepted', 'admin_override_to_recode'
                    ) AND {dm_reopen_event_sql("e")}) AS reopened,
                    COUNT(*) FILTER (
                        WHERE e.transition_id = 'upstream_change_accepted'
                          AND e.transition_reason = 'interviewer_revision'
                    ) AS revision_restarts,
                    COUNT(*) FILTER (WHERE e.transition_id = 'coder_finalized') AS finalized
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND e.event_created_at >= :cutoff
            """),
            {**IN_ODK_BIND, **scope.params, "cutoff": seven_days_ago},
        ).mappings().first()

        reopened = reopen["reopened"] or 0 if reopen else 0
        finalized = reopen["finalized"] or 0 if reopen else 0
        revision_restarts = reopen["revision_restarts"] or 0 if reopen else 0
        reopen_rate = round(reopened / finalized * 100, 1) if finalized > 0 else 0.0

        return {
            "c10_queue_count": queue_count,
            "c10_sent_back_count": sent_back_count,
            "c11_with_upstream": with_upstream,
            "c11_total_coded": total_coded,
            "c11_rate": upstream_rate,
            "d_wt_02_resolution_p50_seconds": round(resolution, 1) if resolution else None,
            "d_wt_04_reopened_7d": reopened,
            "d_wt_04_finalized_7d": finalized,
            "d_wt_04_reopen_rate": reopen_rate,
            "d_wt_04_revision_restarts_7d": revision_restarts,
        }

    return jsonify(cached_kpi("upstream_changes", compute))


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


def compute_c19(scope: DmScope, period: int = 7, by: str | None = None) -> dict:
    """C-19: cases crossing the pending boundary per viewer day, newest first.

    Inflow enters the 6 pending states, outflow leaves them (split into
    ``outflow_coded`` and ``outflow_other``); demo events are dropped
    (``bucket_flow_by_day``). Every day of the last *period* has a row.
    ``net_28d`` is inflow minus outflow over the last 28 days and
    ``does_not_clear`` flags it above 0 (forecast view). One query. Raises
    ``ValueError`` for an unsupported *by*.
    """
    if by is not None:
        raise ValueError(f"C-19 does not support by={by!r}")
    flow = _pending_flow(scope, max(period, FLOW_AVERAGE_DAYS))
    net_28d = sum(d["inflow"] - d["outflow"] for d in flow[-FLOW_AVERAGE_DAYS:])
    return {
        "data": [
            {
                "date": d["date"],
                "inflow": d["inflow"],
                "outflow": d["outflow"],
                "outflow_coded": d["outflow_coded"],
                "outflow_other": d["outflow_other"],
                "net_delta": d["inflow"] - d["outflow"],
            }
            for d in reversed(flow[-period:])
        ],
        "net_28d": net_28d,
        "does_not_clear": net_28d > 0,
    }


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

    def compute():
        rows = db.session.execute(
            sa.text(f"""
                SELECT
                    f.site_id,
                    COUNT(*) FILTER (WHERE w.workflow_state NOT IN (
                        'consent_refused', 'not_codeable_by_data_manager'
                    )) AS total_coding_pool,
                    COUNT(*) FILTER (WHERE w.workflow_state IN {PENDING_STATES_SQL}) AS pending
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                GROUP BY f.site_id
                ORDER BY (COUNT(*) FILTER (WHERE w.workflow_state IN {PENDING_STATES_SQL})::FLOAT / NULLIF(
                    COUNT(*) FILTER (WHERE w.workflow_state NOT IN (
                        'consent_refused', 'not_codeable_by_data_manager'
                    )), 0
                )) DESC
            """),
            {**IN_ODK_BIND, **scope.params},
        ).mappings().all()

        return {
            "sites": [
                {
                    "site_id": r["site_id"],
                    "total_coding_pool": r["total_coding_pool"] or 0,
                    "pending": r["pending"] or 0,
                    "pct_uncoded": round(
                        (r["pending"] or 0) / (r["total_coding_pool"] or 1) * 100, 1
                    ),
                }
                for r in rows
            ]
        }

    return jsonify(cached_kpi("site_bottleneck", compute))


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

    def compute():
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seven_days_ago = now - timedelta(days=7)

        row = db.session.execute(
            sa.text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE e.event_created_at >= :today) AS today,
                    COUNT(*) FILTER (WHERE e.event_created_at >= :seven_d) AS last_7d,
                    COUNT(*) AS cumulative
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND e.transition_id = 'reviewer_finalized'
            """),
            {**IN_ODK_BIND, **scope.params, "today": today_start, "seven_d": seven_days_ago},
        ).mappings().first()

        return {
            "today": row["today"] or 0 if row else 0,
            "last_7d": row["last_7d"] or 0 if row else 0,
            "cumulative": row["cumulative"] or 0 if row else 0,
        }

    return jsonify(cached_kpi("reviewer_throughput", compute))


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
