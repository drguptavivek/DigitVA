"""DM KPI — Sync Health.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/sync``

KPIs served:
  C-02  Last Sync Run Status
  C-03  Sync Error Rate
  C-13  Sync Latency (ODK → App) — P50/P90/P99
  C-14  Attachment Health
  D-SH-01  Attachment Download Completeness
  D-SH-04  SmartVA Failure Rate

Sources:
  - va_sync_runs (system-level, no DM scoping for C-02/C-03)
  - va_submissions JOIN va_forms (C-13, scoped by site_id)
  - va_submission_attachments JOIN va_submissions JOIN va_forms (C-14)

Design notes:
  va_sync_runs has no per-site breakdown, so C-02 and C-03 are
  system-level.  C-13 (sync latency) is DM-scoped via site attribution.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_scope import cached_kpi, dm_site_ids

bp = Blueprint("dm_kpi_sync", __name__)
log = logging.getLogger(__name__)


@bp.get("/status")
@role_required("data_manager")
def sync_status():
    """KPIs: C-02 (Last Sync Run Status) + C-03 (Sync Error Rate).

    C-02 — Last Sync Run Status:
      Definition: status, started_at, finished_at from most recent
                  va_sync_runs row.
      Source: va_sync_runs ORDER BY started_at DESC LIMIT 1.
      Time frame: Snapshot.
      Scope: System-level (no DM scoping — va_sync_runs is not per-site).

    C-03 — Sync Error Rate:
      Numerator: COUNT of va_sync_runs where status IN ('error', 'partial')
                 and started_at ≥ window_start.
      Denominator: COUNT of all va_sync_runs where started_at ≥ window_start.
      Rate: N / D × 100.
      Time frames: 7d, cumulative.
    """
    def compute():
        # C-02: latest sync run
        latest = db.session.execute(
            sa.text("""
                SELECT status, started_at, finished_at,
                       records_added, records_updated, records_skipped
                FROM va_sync_runs
                ORDER BY started_at DESC
                LIMIT 1
            """)
        ).mappings().first()

        latest_data = None
        if latest:
            latest_data = {
                "status": latest["status"],
                "started_at": latest["started_at"].isoformat() if latest["started_at"] else None,
                "finished_at": latest["finished_at"].isoformat() if latest["finished_at"] else None,
                "records_added": latest["records_added"],
                "records_updated": latest["records_updated"],
                "records_skipped": latest["records_skipped"],
            }

        # C-03: sync error rate for 7d and cumulative
        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)

        rate_7d = db.session.execute(
            sa.text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status IN ('error', 'partial')) AS errors
                FROM va_sync_runs
                WHERE started_at >= :cutoff
            """),
            {"cutoff": seven_days_ago},
        ).mappings().first()

        rate_cumulative = db.session.execute(
            sa.text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE status IN ('error', 'partial')) AS errors
                FROM va_sync_runs
            """)
        ).mappings().first()

        def _pct(total, errors):
            t = total or 0
            e = errors or 0
            return round(e / t * 100, 1) if t > 0 else 0.0

        return {
            "latest_run": latest_data,
            "error_rate_7d": _pct(rate_7d["total"], rate_7d["errors"]),
            "error_rate_cumulative": _pct(rate_cumulative["total"], rate_cumulative["errors"]),
            "runs_7d": {
                "total": rate_7d["total"] or 0,
                "errors": rate_7d["errors"] or 0,
            },
            "runs_cumulative": {
                "total": rate_cumulative["total"] or 0,
                "errors": rate_cumulative["errors"] or 0,
            },
        }

    return jsonify(cached_kpi("sync_status", compute))


@bp.get("/latency")
@role_required("data_manager")
def sync_latency():
    """KPI: C-13 — Sync Latency (ODK → App).

    Definition: For submissions synced in window: time between ODK
                submission timestamp and local DB insert.
    Formula: va_created_at − va_submission_date per submission.
    Aggregates: P50, P90, P99.
    Denominator scope: ALL-SYNCED (DM-scoped via site_id).
    Time frames: Today, 7d.
    Source: va_submissions JOIN va_forms scoped by site_id.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"p50": None, "p90": None, "p99": None, "count": 0})

    range_param = request.args.get("range", "7d")

    def compute():
        if range_param == "today":
            cutoff = datetime.now(timezone.utc).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        else:
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        row = db.session.execute(
            sa.text("""
                SELECT
                    COUNT(*) AS cnt,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY
                        EXTRACT(EPOCH FROM (s.va_created_at - s.va_submission_date))
                    ) AS p50,
                    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY
                        EXTRACT(EPOCH FROM (s.va_created_at - s.va_submission_date))
                    ) AS p90,
                    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY
                        EXTRACT(EPOCH FROM (s.va_created_at - s.va_submission_date))
                    ) AS p99
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND s.va_created_at >= :cutoff
                  AND s.va_submission_date IS NOT NULL
            """),
            {"site_ids": site_ids, "cutoff": cutoff},
        ).mappings().first()

        def _fmt(val):
            if val is None:
                return None
            return round(val, 1)

        return {
            "count": row["cnt"] or 0,
            "p50_seconds": _fmt(row["p50"]),
            "p90_seconds": _fmt(row["p90"]),
            "p99_seconds": _fmt(row["p99"]),
            "range": range_param,
        }

    return jsonify(cached_kpi(f"sync_latency:{range_param}", compute))


@bp.get("/attachment-health")
@role_required("data_manager")
def attachment_health():
    """KPIs: C-14 (Attachment Health) + D-SH-01 (Attachment Download Completeness).

    C-14 — Attachment Health:
      Numerator: COUNT of submissions past SmartVA gate where attachment
                 count = 0.
      Denominator: COUNT of submissions past SmartVA gate.
      Rate: N / D × 100.
      Source: va_submission_attachments JOIN va_submissions JOIN va_forms.
      Time frame: Snapshot.

    D-SH-01 — Attachment Download Completeness:
      Numerator: va_sync_runs.attachment_downloaded from latest run.
      Denominator: attachment_downloaded + attachment_skipped +
                   attachment_errors from same run.
      Rate: N / D × 100.
      Time frame: Snapshot.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"c14": {}, "d_sh_01": {}})

    def compute():
        # C-14: attachment health for DM-scoped submissions
        # Submissions past SmartVA gate: workflow_state NOT IN
        #   (screening_pending, attachment_sync_pending, smartva_pending)
        c14 = db.session.execute(
            sa.text("""
                WITH past_smartva AS (
                    SELECT s.va_sid
                    FROM va_submissions s
                    JOIN va_forms f ON f.form_id = s.va_form_id
                    LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                    WHERE f.site_id = ANY(:site_ids)
                      AND w.workflow_state IS NOT NULL
                      AND w.workflow_state NOT IN (
                          'screening_pending', 'attachment_sync_pending', 'smartva_pending'
                      )
                ),
                with_attachments AS (
                    SELECT ps.va_sid, COUNT(a.va_attachment_id) AS att_count
                    FROM past_smartva ps
                    LEFT JOIN va_submission_attachments a ON a.va_sid = ps.va_sid
                    GROUP BY ps.va_sid
                )
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE att_count = 0) AS missing
                FROM with_attachments
            """),
            {"site_ids": site_ids},
        ).mappings().first()

        total_c14 = c14["total"] or 0
        missing_c14 = c14["missing"] or 0
        c14_rate = round(missing_c14 / total_c14 * 100, 1) if total_c14 > 0 else 0.0

        # D-SH-01: attachment download completeness from latest sync run
        dsh01 = db.session.execute(
            sa.text("""
                SELECT
                    attachment_downloaded,
                    attachment_forms_total,
                    attachment_forms_completed
                FROM va_sync_runs
                ORDER BY started_at DESC
                LIMIT 1
            """)
        ).mappings().first()

        dsh01_data = None
        if dsh01:
            dl = dsh01["attachment_downloaded"] or 0
            total_att = dsh01["attachment_forms_total"] or 0
            dsh01_data = {
                "downloaded": dl,
                "total": total_att,
                "rate": round(dl / total_att * 100, 1) if total_att > 0 else None,
            }

        return {
            "c14": {
                "total_past_smartva": total_c14,
                "missing_attachments": missing_c14,
                "rate": c14_rate,
            },
            "d_sh_01": dsh01_data,
        }

    return jsonify(cached_kpi("attachment_health", compute))


@bp.get("/smartva-failure-rate")
@role_required("data_manager")
def smartva_failure_rate():
    """KPI: D-SH-04 — SmartVA Failure Rate.

    Numerator: COUNT of va_smartva_runs where va_smartva_outcome = 'failed'
               in window.
    Denominator: COUNT of all va_smartva_runs in window.
    Rate: N / D × 100.
    Time frames: 7d, cumulative.
    Source: va_smartva_runs.
    """
    def compute():
        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)

        rate_7d = db.session.execute(
            sa.text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE va_smartva_outcome = 'failed') AS failed
                FROM va_smartva_runs
                WHERE va_smartva_run_started_at >= :cutoff
            """),
            {"cutoff": seven_days_ago},
        ).mappings().first()

        rate_cum = db.session.execute(
            sa.text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE va_smartva_outcome = 'failed') AS failed
                FROM va_smartva_runs
            """)
        ).mappings().first()

        def _pct(t, f):
            return round(f / t * 100, 1) if t > 0 else 0.0

        return {
            "rate_7d": _pct(rate_7d["total"], rate_7d["failed"]),
            "rate_cumulative": _pct(rate_cum["total"], rate_cum["failed"]),
            "runs_7d": {"total": rate_7d["total"] or 0, "failed": rate_7d["failed"] or 0},
            "runs_cumulative": {"total": rate_cum["total"] or 0, "failed": rate_cum["failed"] or 0},
        }

    return jsonify(cached_kpi("smartva_failure_rate", compute))
