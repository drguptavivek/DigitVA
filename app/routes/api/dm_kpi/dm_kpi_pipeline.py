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

Sources:
  - va_submission_workflow (current states)
  - va_submission_workflow_events (transitions, durations)
  - va_daily_kpi_aggregates (time-series)
  - va_submission_upstream_changes (resolution times)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_scope import cached_kpi, dm_site_ids

bp = Blueprint("dm_kpi_pipeline", __name__)
log = logging.getLogger(__name__)


@bp.get("/pending")
@role_required("data_manager")
def pending_rate():
    """KPI: C-04 — % Uncoded (Pending Rate).

    Numerator: COUNT WHERE workflow_state IN ('ready_for_coding',
      'coding_in_progress', 'coder_step1_saved', 'smartva_pending',
      'screening_pending', 'attachment_sync_pending').
    Denominator: COUNT of CODING-POOL.
    Rate: N / D × 100.
    Scope: CODING-POOL.
    Time frames: Snapshot.
    Meaning: What fraction of the eligible pipeline has NOT been coded yet.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"pending": 0, "coding_pool": 0, "rate": 0.0})

    def compute():
        row = db.session.execute(
            sa.text("""
                SELECT
                    COUNT(*) FILTER (WHERE w.workflow_state NOT IN (
                        'consent_refused', 'not_codeable_by_data_manager'
                    )) AS coding_pool,
                    COUNT(*) FILTER (WHERE w.workflow_state IN (
                        'ready_for_coding', 'coding_in_progress', 'coder_step1_saved',
                        'smartva_pending', 'screening_pending', 'attachment_sync_pending'
                    )) AS pending
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                WHERE f.site_id = ANY(:site_ids)
            """),
            {"site_ids": site_ids},
        ).mappings().first()

        pool = row["coding_pool"] or 0
        pending = row["pending"] or 0
        rate = round(pending / pool * 100, 1) if pool > 0 else 0.0

        return {"pending": pending, "coding_pool": pool, "rate": rate}

    return jsonify(cached_kpi("pending_rate", compute))


@bp.get("/aging")
@role_required("data_manager")
def pipeline_aging():
    """KPI: C-07 — Pipeline Aging (Stagnation).

    Definition: COUNT of submissions where workflow_state = 'ready_for_coding'
                AND workflow_updated_at < now() − interval thresholds.
    Also reports: Same count at thresholds: >48h, >7d, >30d.
    Source: va_submission_workflow JOIN va_forms for scope.
    Scope: CODING-POOL.
    Time frame: Snapshot.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"gt_48h": 0, "gt_7d": 0, "gt_30d": 0})

    def compute():
        row = db.session.execute(
            sa.text("""
                SELECT
                    COUNT(*) FILTER (WHERE w.workflow_updated_at < NOW() - INTERVAL '48 hours') AS gt_48h,
                    COUNT(*) FILTER (WHERE w.workflow_updated_at < NOW() - INTERVAL '7 days') AS gt_7d,
                    COUNT(*) FILTER (WHERE w.workflow_updated_at < NOW() - INTERVAL '30 days') AS gt_30d
                FROM va_submission_workflow w
                JOIN va_submissions s ON s.va_sid = w.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND w.workflow_state = 'ready_for_coding'
            """),
            {"site_ids": site_ids},
        ).mappings().first()

        return {
            "gt_48h": row["gt_48h"] or 0,
            "gt_7d": row["gt_7d"] or 0,
            "gt_30d": row["gt_30d"] or 0,
        }

    return jsonify(cached_kpi("pipeline_aging", compute))


@bp.get("/time-to-code")
@role_required("data_manager")
def time_to_code():
    """KPI: C-08 — Time to Code (Min / Max / Median / P90).

    Definition: For each submission finalized in the window, compute
      coder_finalized_event.event_created_at − coding_started_event.event_created_at.
    Aggregates: MIN, MAX, PERCENTILE(0.5), PERCENTILE(0.90).
    Source: Paired va_submission_workflow_events rows (same va_sid,
            matching coding_started → coder_finalized/recode_finalized).
    Scope: CODING-POOL.
    Inclusions: First-pass coding AND recode episodes.
    Exclusions: Demo sessions (demo_started transition).
    Time frames: 7d.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"min": None, "max": None, "p50": None, "p90": None, "count": 0})

    range_param = request.args.get("range", "7d")

    def compute():
        if range_param == "today":
            cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        row = db.session.execute(
            sa.text("""
                SELECT
                    COUNT(*) AS cnt,
                    MIN(EXTRACT(EPOCH FROM (e2.event_created_at - e1.event_created_at))) AS min_dur,
                    MAX(EXTRACT(EPOCH FROM (e2.event_created_at - e1.event_created_at))) AS max_dur,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY
                        EXTRACT(EPOCH FROM (e2.event_created_at - e1.event_created_at))
                    ) AS p50_dur,
                    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY
                        EXTRACT(EPOCH FROM (e2.event_created_at - e1.event_created_at))
                    ) AS p90_dur
                FROM va_submission_workflow_events e2
                JOIN va_submission_workflow_events e1
                    ON e1.va_sid = e2.va_sid AND e1.transition_id = 'coding_started'
                JOIN va_submissions s ON s.va_sid = e2.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND e2.transition_id IN ('coder_finalized', 'recode_finalized')
                  AND e2.event_created_at >= :cutoff
                  AND NOT EXISTS (
                      SELECT 1 FROM va_submission_workflow_events d
                      WHERE d.va_sid = e2.va_sid AND d.transition_id = 'demo_started'
                  )
            """),
            {"site_ids": site_ids, "cutoff": cutoff},
        ).mappings().first()

        def _fmt(val):
            return round(val, 1) if val is not None else None

        return {
            "count": row["cnt"] or 0,
            "min_seconds": _fmt(row["min_dur"]),
            "max_seconds": _fmt(row["max_dur"]),
            "p50_seconds": _fmt(row["p50_dur"]),
            "p90_seconds": _fmt(row["p90_dur"]),
            "range": range_param,
        }

    return jsonify(cached_kpi(f"time_to_code:{range_param}", compute))


@bp.get("/reviewed")
@role_required("data_manager")
def review_rate():
    """KPI: C-09 — % Forms Reviewed.

    Numerator: COUNT of submissions that have at least one
               va_reviewer_final_assessments row with active status.
    Denominator: COUNT of submissions that ever reached coder_finalized
                 (CODED scope, excluding coder_finalized forms less than
                 24h old due to recode window).
    Rate: N / D × 100.
    Scope: CODED.
    Time frames: 7d, cumulative.
    Note: 24h recode window means reviewer-eligible forms can't be
          reviewed immediately. Denominator excludes coder_finalized
          forms less than 24h old.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"reviewed": 0, "eligible": 0, "rate": 0.0})

    def compute():
        row = db.session.execute(
            sa.text("""
                WITH coded AS (
                    SELECT s.va_sid
                    FROM va_submissions s
                    JOIN va_forms f ON f.form_id = s.va_form_id
                    JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                    WHERE f.site_id = ANY(:site_ids)
                      AND (
                          w.workflow_state IN (
                              'reviewer_eligible', 'reviewer_coding_in_progress',
                              'reviewer_finalized', 'finalized_upstream_changed'
                          )
                          OR EXISTS (
                              SELECT 1 FROM va_submission_workflow_events e
                              WHERE e.va_sid = s.va_sid
                                AND e.transition_id = 'coder_finalized'
                                AND e.event_created_at < NOW() - INTERVAL '24 hours'
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
            {"site_ids": site_ids},
        ).mappings().first()

        eligible = row["eligible"] or 0 if row else 0
        reviewed = row["reviewed"] or 0 if row else 0
        rate = round(reviewed / eligible * 100, 1) if eligible > 0 else 0.0

        return {"reviewed": reviewed, "eligible": eligible, "rate": rate}

    return jsonify(cached_kpi("review_rate", compute))


@bp.get("/upstream-changes")
@role_required("data_manager")
def upstream_changes():
    """KPIs: C-10 (Upstream Change Queue), C-11 (% Forms with Upstream Changes),
    D-WT-02 (Upstream Change Resolution Time), D-WT-04 (Reopen Rate).

    C-10 — Upstream Change Queue:
      Definition: COUNT WHERE workflow_state = 'finalized_upstream_changed'.
      Scope: CODED.
      Time frame: Snapshot.
      Source: va_submission_workflow (direct query, no MV).

    C-11 — % Forms with Upstream Changes:
      Numerator: COUNT of submissions with at least one
                 upstream_change_detected event.
      Denominator: COUNT of CODED submissions.
      Rate: N / D × 100.
      Time frames: 7d, cumulative.

    D-WT-02 — Upstream Change Resolution Time:
      Definition: For resolved upstream changes in 7d, resolved_at − created_at.
      Aggregate: PERCENTILE(0.5).
      Source: va_submission_upstream_changes.
      Time frame: 7d.

    D-WT-04 — Reopen Rate:
      Numerator: COUNT of events with transition_id IN
                 ('upstream_change_accepted', 'admin_override_to_recode') in window.
      Denominator: COUNT of coder_finalized events in window.
      Rate: N / D × 100.
      Scope: CODED.
      Time frames: 7d, cumulative.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({})

    def compute():
        # C-10: upstream change queue (snapshot)
        queue_count = db.session.execute(
            sa.text("""
                SELECT COUNT(*) AS cnt
                FROM va_submission_workflow w
                JOIN va_submissions s ON s.va_sid = w.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND w.workflow_state = 'finalized_upstream_changed'
            """),
            {"site_ids": site_ids},
        ).scalar() or 0

        # C-11: % forms with upstream changes (cumulative)
        upstream_pct = db.session.execute(
            sa.text("""
                WITH coded AS (
                    SELECT s.va_sid
                    FROM va_submissions s
                    JOIN va_forms f ON f.form_id = s.va_form_id
                    JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                    WHERE f.site_id = ANY(:site_ids)
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
                    )) AS with_upstream
                FROM coded c
            """),
            {"site_ids": site_ids},
        ).mappings().first()

        total_coded = upstream_pct["total_coded"] or 0 if upstream_pct else 0
        with_upstream = upstream_pct["with_upstream"] or 0 if upstream_pct else 0
        upstream_rate = round(with_upstream / total_coded * 100, 1) if total_coded > 0 else 0.0

        # D-WT-02: resolution time (7d)
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        resolution = db.session.execute(
            sa.text("""
                SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY
                    EXTRACT(EPOCH FROM (uc.resolved_at - uc.created_at))
                ) AS p50_seconds
                FROM va_submission_upstream_changes uc
                JOIN va_submissions s ON s.va_sid = uc.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND uc.resolved_at IS NOT NULL
                  AND uc.resolved_at >= :cutoff
            """),
            {"site_ids": site_ids, "cutoff": seven_days_ago},
        ).scalar()

        # D-WT-04: reopen rate (7d)
        reopen = db.session.execute(
            sa.text("""
                SELECT
                    COUNT(*) FILTER (WHERE e.transition_id IN (
                        'upstream_change_accepted', 'admin_override_to_recode'
                    )) AS reopened,
                    COUNT(*) FILTER (WHERE e.transition_id = 'coder_finalized') AS finalized
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND e.event_created_at >= :cutoff
            """),
            {"site_ids": site_ids, "cutoff": seven_days_ago},
        ).mappings().first()

        reopened = reopen["reopened"] or 0 if reopen else 0
        finalized = reopen["finalized"] or 0 if reopen else 0
        reopen_rate = round(reopened / finalized * 100, 1) if finalized > 0 else 0.0

        return {
            "c10_queue_count": queue_count,
            "c11_with_upstream": with_upstream,
            "c11_total_coded": total_coded,
            "c11_rate": upstream_rate,
            "d_wt_02_resolution_p50_seconds": round(resolution, 1) if resolution else None,
            "d_wt_04_reopened_7d": reopened,
            "d_wt_04_finalized_7d": finalized,
            "d_wt_04_reopen_rate": reopen_rate,
        }

    return jsonify(cached_kpi("upstream_changes", compute))


@bp.get("/inflow-outflow")
@role_required("data_manager")
def inflow_outflow():
    """KPI: C-19 — Daily Inflow vs Outflow.

    Inflow (new forms entering pipeline): COUNT of events where
      transition_id = 'smartva_completed' that day — forms that became
      available for coding.
    Outflow (forms coded): COUNT of events where transition_id IN
      ('coder_finalized', 'recode_finalized') that day.
    Net delta: Inflow − Outflow.
    Display: Side-by-side per day, last 7d.
    Actionable: If inflow consistently exceeds outflow, backlog will grow.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"data": []})

    days = min(int(request.args.get("days", 7)), 30)

    def compute():
        from_date = date.today() - timedelta(days=days - 1)

        rows = db.session.execute(
            sa.text("""
                WITH events AS (
                    SELECT
                        DATE(e.event_created_at) AS day,
                        CASE
                            WHEN e.transition_id = 'smartva_completed' THEN 'inflow'
                            WHEN e.transition_id IN ('coder_finalized', 'recode_finalized') THEN 'outflow'
                        END AS direction
                    FROM va_submission_workflow_events e
                    JOIN va_submissions s ON s.va_sid = e.va_sid
                    JOIN va_forms f ON f.form_id = s.va_form_id
                    WHERE f.site_id = ANY(:site_ids)
                      AND e.transition_id IN (
                          'smartva_completed', 'coder_finalized', 'recode_finalized'
                      )
                      AND DATE(e.event_created_at) >= :from_date
                )
                SELECT
                    day,
                    COUNT(*) FILTER (WHERE direction = 'inflow') AS inflow,
                    COUNT(*) FILTER (WHERE direction = 'outflow') AS outflow
                FROM events
                GROUP BY day
                ORDER BY day DESC
            """),
            {"site_ids": site_ids, "from_date": from_date},
        ).mappings().all()

        return {
            "data": [
                {
                    "date": str(r["day"]),
                    "inflow": r["inflow"] or 0,
                    "outflow": r["outflow"] or 0,
                    "net_delta": (r["inflow"] or 0) - (r["outflow"] or 0),
                }
                for r in rows
            ]
        }

    return jsonify(cached_kpi(f"inflow_outflow:{days}", compute))


@bp.get("/site-bottleneck")
@role_required("data_manager")
def site_bottleneck():
    """KPI: C-22 — Site-Level Bottleneck.

    Definition: Per site: (pending_count / total_count) × 100 — the %
                of a site's submissions that are still uncoded.
    Display: Table ranked by % uncoded DESC.
    Scope: CODING-POOL, grouped by site.
    Time frame: Snapshot.
    Actionable: The site at the top of this list is the bottleneck.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"sites": []})

    def compute():
        rows = db.session.execute(
            sa.text("""
                SELECT
                    f.site_id,
                    COUNT(*) FILTER (WHERE w.workflow_state NOT IN (
                        'consent_refused', 'not_codeable_by_data_manager'
                    )) AS total_coding_pool,
                    COUNT(*) FILTER (WHERE w.workflow_state IN (
                        'ready_for_coding', 'coding_in_progress', 'coder_step1_saved'
                    )) AS pending
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                WHERE f.site_id = ANY(:site_ids)
                GROUP BY f.site_id
                ORDER BY (COUNT(*) FILTER (WHERE w.workflow_state IN (
                    'ready_for_coding', 'coding_in_progress', 'coder_step1_saved'
                ))::FLOAT / NULLIF(
                    COUNT(*) FILTER (WHERE w.workflow_state NOT IN (
                        'consent_refused', 'not_codeable_by_data_manager'
                    )), 0
                )) DESC
            """),
            {"site_ids": site_ids},
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
@role_required("data_manager")
def reviewer_throughput():
    """KPI: D-WT-01 — Reviewer Throughput.

    Numerator: COUNT of events with transition_id = 'reviewer_finalized'
               in window.
    Time frames: Today, 7d, cumulative.
    Scope: CODED.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"today": 0, "last_7d": 0, "cumulative": 0})

    def compute():
        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seven_days_ago = now - timedelta(days=7)

        row = db.session.execute(
            sa.text("""
                SELECT
                    COUNT(*) FILTER (WHERE e.event_created_at >= :today) AS today,
                    COUNT(*) FILTER (WHERE e.event_created_at >= :seven_d) AS last_7d,
                    COUNT(*) AS cumulative
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND e.transition_id = 'reviewer_finalized'
            """),
            {"site_ids": site_ids, "today": today_start, "seven_d": seven_days_ago},
        ).mappings().first()

        return {
            "today": row["today"] or 0 if row else 0,
            "last_7d": row["last_7d"] or 0 if row else 0,
            "cumulative": row["cumulative"] or 0 if row else 0,
        }

    return jsonify(cached_kpi("reviewer_throughput", compute))


@bp.get("/backlog-trend")
@role_required("data_manager")
def backlog_trend():
    """KPI: D-WT-03 — Coding Backlog Trend.

    Definition: Daily time-series of COUNT where workflow_state =
                'ready_for_coding'.
    Source: va_daily_kpi_aggregates.pending_count (primary),
            live fallback from va_submission_workflow.
    Display: Line chart, default 90-day window.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"data": [], "source": "none"})

    days = min(int(request.args.get("days", 90)), 365)

    def compute():
        from_date = date.today() - timedelta(days=days - 1)

        # Try aggregates first
        has_aggregates = False
        try:
            has_aggregates = bool(db.session.scalar(
                sa.text("""
                    SELECT COUNT(*) FROM va_daily_kpi_aggregates
                    WHERE site_id = ANY(:site_ids) AND snapshot_date >= :from_date
                """),
                {"site_ids": tuple(site_ids), "from_date": from_date},
            ))
        except Exception as e:
            # Table doesn't exist yet (migration not run) — fall back to live
            log.debug(f"va_daily_kpi_aggregates not available: {e}")
            has_aggregates = False

        if has_aggregates:
            rows = db.session.execute(
                sa.text("""
                    SELECT snapshot_date AS date, SUM(pending_count) AS pending
                    FROM va_daily_kpi_aggregates
                    WHERE site_id = ANY(:site_ids) AND snapshot_date >= :from_date
                    GROUP BY snapshot_date
                    ORDER BY snapshot_date
                """),
                {"site_ids": site_ids, "from_date": from_date},
            ).mappings().all()

            return {
                "data": [
                    {"date": str(r["date"]), "pending": r["pending"] or 0}
                    for r in rows
                ],
                "source": "aggregates",
            }

        # Live fallback (current snapshot only — no historical depth)
        current_pending = db.session.execute(
            sa.text("""
                SELECT COUNT(*) AS pending
                FROM va_submission_workflow w
                JOIN va_submissions s ON s.va_sid = w.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND w.workflow_state = 'ready_for_coding'
            """),
            {"site_ids": site_ids},
        ).scalar() or 0

        return {
            "data": [{"date": str(date.today()), "pending": current_pending}],
            "source": "live",
        }

    return jsonify(cached_kpi(f"backlog_trend:{days}", compute))
