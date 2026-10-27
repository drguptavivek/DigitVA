"""DM KPI — Sync Health.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/sync``

KPIs served:
  C-03  Sync Error Rate (C-02 last run status merged)
  C-13  Sync Latency (ODK → App) — P50/P90/P99
  C-14  Attachment Health
  D-SH-01  Attachment Download Completeness
  D-SH-04  SmartVA Failure Rate

Sources:
  - va_sync_runs (system-level, no DM scoping for C-02/C-03)
  - va_submissions JOIN va_forms (C-13, scoped by site_id)
  - va_submission_attachments JOIN va_submissions JOIN va_forms (C-14)

Design notes:
  va_sync_runs and va_smartva_runs have no per-site breakdown, so C-02,
  C-03, D-SH-01 and D-SH-04 are system-level. They are served only to a
  data manager with a project or pair grant (or project_pi on a tree
  project, or admin: authz ``Lens.DM_DIRECT``, digitva-38lp); a unit-only
  data manager or In-charge sees sync runs only for forms a direct grant
  covers, so gets 403 on /status and /smartva-failure-rate and no D-SH-01.
  C-13 (sync latency) is DM-scoped via site attribution.

Retired-from-ODK submissions (docs/policy/odk-retired-submissions.md),
per KPI:
  C-13, C-14  counted over submissions — retired rows are excluded, C-13
              because its denominator is ALL-SYNCED and C-14 because a
              retired submission's attachments are archival, not a gap the
              DM can act on.
  C-02, C-03, D-SH-01  counted over va_sync_runs rows, not submissions —
              unaffected.
  D-SH-04     counted over va_smartva_runs rows, not submissions —
              unaffected.
  D-SH-03 (the "missing in ODK" count itself) is served from the analytics
  MV, not here, and deliberately keeps counting retired submissions.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from flask import Blueprint, jsonify, request

from app import db
from app.decorators import role_required
from app.routes.api.request_helpers import error as api_error
from app.services.duplicate_exclusion import not_confirmed_duplicate_sql
from app.services.odk_retirement_service import IN_ODK_BIND, in_odk_sql
from app.routes.api.dm_kpi.dm_kpi_scope import cached_kpi, dm_scope

bp = Blueprint("dm_kpi_sync", __name__)
log = logging.getLogger(__name__)

# Retired submissions are not counted (docs/policy/odk-retired-submissions.md).
_IN_ODK_SQL = in_odk_sql("s")
# Confirmed-duplicate web cases leave every count (app/services/duplicate_exclusion.py).
_NOT_DUPLICATE_SQL = not_confirmed_duplicate_sql("s.va_sid")


def _system_level_refused():
    return api_error("System-level sync figures need a project or site grant.", status_code=403)


def compute_c03(scope, period=None, by: str | None = None) -> dict:
    """C-03 Sync Error Rate, with C-02 (last run status) merged in.

    Error or partial runs over all ``va_sync_runs`` started in the window, as a
    rate. *period* is ``"7d"`` (the default) or ``"cumulative"``; the headline
    ``rate`` / ``runs`` / ``errors`` follow it and both windows are returned
    (``error_rate_7d``, ``runs_7d``, ``error_rate_cumulative``,
    ``runs_cumulative``). ``latest_run`` / ``last_status`` are the most recent
    run (C-02). System level: ``va_sync_runs`` has no per-site rows, so *scope*
    is not used to filter; the caller refuses a DM without a direct grant.
    """
    if by is not None:
        raise ValueError(f"C-03 has no by={by!r}")
    if period not in (None, "7d", "cumulative"):
        raise ValueError(f"C-03 has no period {period!r}")
    window = period or "7d"

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

    counts = db.session.execute(
        sa.text("""
            SELECT
                COUNT(*) FILTER (WHERE started_at >= :cutoff) AS runs_7d,
                COUNT(*) FILTER (WHERE started_at >= :cutoff
                                   AND status IN ('error', 'partial')) AS errors_7d,
                COUNT(*) AS runs_all,
                COUNT(*) FILTER (WHERE status IN ('error', 'partial')) AS errors_all
            FROM va_sync_runs
        """),
        {"cutoff": datetime.now(timezone.utc) - timedelta(days=7)},
    ).mappings().first()

    def pct(total, errors):
        return round(errors / total * 100, 1) if total > 0 else 0.0

    runs_7d, errors_7d = counts["runs_7d"] or 0, counts["errors_7d"] or 0
    runs_all, errors_all = counts["runs_all"] or 0, counts["errors_all"] or 0
    runs, errors = (runs_7d, errors_7d) if window == "7d" else (runs_all, errors_all)
    return {
        "period": window,
        "rate": pct(runs, errors),
        "runs": runs,
        "errors": errors,
        "last_status": latest_data["status"] if latest_data else None,
        "latest_run": latest_data,
        "error_rate_7d": pct(runs_7d, errors_7d),
        "error_rate_cumulative": pct(runs_all, errors_all),
        "runs_7d": {"total": runs_7d, "errors": errors_7d},
        "runs_cumulative": {"total": runs_all, "errors": errors_all},
    }


@bp.get("/status")
@role_required("data_manager", "admin")
def sync_status():
    """System-level, so direct grants only (module docstring, digitva-38lp).

    KPI: C-03 (Sync Error Rate) with C-02 (Last Sync Run Status) merged in; a
    thin wrapper over ``compute_c03``. ``?period=7d|cumulative`` picks the
    headline ``rate``; both windows and ``latest_run`` are always returned.

    C-03: error or partial runs / all runs started in the window × 100.
    C-02: status, started_at, finished_at of the most recent run.
    """
    scope = dm_scope()
    if not scope.direct:
        return _system_level_refused()
    period = request.args.get("period") or None
    if period not in (None, "7d", "cumulative"):
        return api_error("Unsupported 'period'; use '7d' or 'cumulative'.", status_code=400)
    return jsonify(cached_kpi("sync_status", lambda: compute_c03(scope, period)))


@bp.get("/latency")
@role_required("data_manager", "admin")
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
    scope = dm_scope()
    if not scope:
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
            sa.text(f"""
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
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND s.va_created_at >= :cutoff
                  AND s.va_submission_date IS NOT NULL
            """),
            {**IN_ODK_BIND, **scope.params, "cutoff": cutoff},
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
@role_required("data_manager", "admin")
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
    scope = dm_scope()
    if not scope:
        return jsonify({"c14": {}, "d_sh_01": {}})

    def compute():
        # C-14: attachment health for DM-scoped submissions
        # Submissions past SmartVA gate: workflow_state NOT IN
        #   (screening_pending, attachment_sync_pending, smartva_pending)
        c14 = db.session.execute(
            sa.text(f"""
                WITH past_smartva AS (
                    SELECT s.va_sid
                    FROM va_submissions s
                    JOIN va_forms f ON f.form_id = s.va_form_id
                    LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                    WHERE {scope.sql()}
                      AND {_IN_ODK_SQL}
                      AND {_NOT_DUPLICATE_SQL}
                      AND w.workflow_state IS NOT NULL
                      AND w.workflow_state NOT IN (
                          'screening_pending', 'attachment_sync_pending', 'smartva_pending'
                      )
                ),
                with_attachments AS (
                    SELECT ps.va_sid, COUNT(a.filename) AS att_count
                    FROM past_smartva ps
                    LEFT JOIN va_submission_attachments a ON a.va_sid = ps.va_sid
                    GROUP BY ps.va_sid
                )
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE att_count = 0) AS missing
                FROM with_attachments
            """),
            {**IN_ODK_BIND, **scope.params},
        ).mappings().first()

        total_c14 = c14["total"] or 0
        missing_c14 = c14["missing"] or 0
        c14_rate = round(missing_c14 / total_c14 * 100, 1) if total_c14 > 0 else 0.0

        # D-SH-01: attachment download completeness from latest sync run;
        # system-level, so direct grants only (digitva-38lp).
        dsh01 = scope.direct and db.session.execute(
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
@role_required("data_manager", "admin")
def smartva_failure_rate():
    """KPI: D-SH-04 — SmartVA Failure Rate.

    Numerator: COUNT of va_smartva_runs where va_smartva_outcome = 'failed'
               in window.
    Denominator: COUNT of all va_smartva_runs in window.
    Rate: N / D × 100.
    Time frames: 7d, cumulative.
    Source: va_smartva_runs. System-level, so direct grants only (digitva-38lp).
    """
    if not dm_scope().direct:
        return _system_level_refused()

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
