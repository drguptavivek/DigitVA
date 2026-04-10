"""DM KPI — Daily Operations Grid.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/grid``

KPIs served:
  C-01  Daily Operations Grid

Sources:
  - va_daily_kpi_aggregates (primary, pre-computed)
  - va_submissions + va_submission_workflow_events (live fallback)

Design notes:
  The grid reads from ``va_daily_kpi_aggregates`` which is keyed by
  ``(snapshot_date, site_id)``.  ``project_id`` is a data column (audit).
  DM scoping resolves site_ids from current ``va_project_sites`` active
  membership, so a DM sees all rows for their currently-owned sites
  regardless of which project owned those sites historically.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_scope import cached_kpi, dm_site_ids

bp = Blueprint("dm_kpi_grid", __name__)
log = logging.getLogger(__name__)


@bp.get("/")
@role_required("data_manager")
def daily_grid():
    """KPI: C-01 — Daily Operations Grid.

    A 7-column table, last N rows (default 8: today + 7 prior days),
    slicable by project and site.

    Columns:
      - Total:         COUNT of ALL-SYNCED submissions as of end of that day
      - New from ODK:  COUNT of submissions created that day
      - Updated in ODK: COUNT of submissions updated that day
      - Coded:         COUNT of coder_finalized / recode_finalized events that day
      - Pending:       COUNT in ready_for_coding + coding_in_progress +
                       coder_step1_saved as of end of that day
      - Consent Refused: COUNT of consent_refused events that day
      - Not Codeable:  COUNT of not_codeable events (coder + DM) that day

    Denominator scope: ALL-SYNCED for Total/Consent/NotCodeable;
                       CODING-POOL for Pending.
    Time frames: Grid shows last N calendar days.
    Sources: va_daily_kpi_aggregates (primary); live fallback from
             va_submissions + va_submission_workflow_events.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"data": [], "source": "none"})

    days = min(int(request.args.get("days", 8)), 90)

    def compute():
        # Check if va_daily_kpi_aggregates has any rows for these sites
        has_aggregates = False
        try:
            has_aggregates = bool(db.session.scalar(
                sa.select(sa.func.count()).select_from(
                    sa.text("va_daily_kpi_aggregates")
                ).where(
                    sa.text("site_id IN :sites"),
                ).params(sites=tuple(site_ids))
            ))
        except Exception as e:
            # Table doesn't exist yet (migration not run) — fall back to live
            log.debug(f"va_daily_kpi_aggregates not available: {e}")
            has_aggregates = False

        if has_aggregates:
            return _grid_from_aggregates_with_live_fill(site_ids, days)
        return _grid_from_live(site_ids, days)

    return jsonify(cached_kpi("grid", compute))


# ---------------------------------------------------------------------------
# Grid from pre-computed aggregates — with live fill for missing/today dates
# ---------------------------------------------------------------------------

def _grid_from_aggregates_with_live_fill(site_ids: list[str], days: int) -> dict:
    """Read daily grid from va_daily_kpi_aggregates, filling gaps with live data.

    Aggregate rows are written once daily for *yesterday*. This means:
    - Today's row is always missing or stale.
    - Days where no task ran are also missing.
    Use live workflow-event counts for any date not covered by the aggregates.
    """
    today = date.today()
    from_date = today - timedelta(days=days - 1)

    # Load what the aggregates have
    agg_rows = db.session.execute(
        sa.text("""
            SELECT
                snapshot_date                  AS date,
                SUM(total_submissions)         AS total,
                SUM(new_from_odk)              AS new_from_odk,
                SUM(updated_from_odk)          AS updated_from_odk,
                SUM(coded_count)               AS coded,
                SUM(pending_count)             AS pending,
                SUM(consent_refused_count)     AS consent_refused,
                SUM(not_codeable_count)        AS not_codeable
            FROM va_daily_kpi_aggregates
            WHERE site_id = ANY(:site_ids)
              AND snapshot_date >= :from_date
            GROUP BY snapshot_date
            ORDER BY snapshot_date DESC
        """),
        {"site_ids": site_ids, "from_date": from_date},
    ).mappings().all()

    agg_map = {str(r["date"]): dict(r) for r in agg_rows}

    # Identify dates that need live fill: always today + any gap in the window
    all_dates = [(today - timedelta(days=i)) for i in range(days)]
    missing_dates = [d for d in all_dates if str(d) not in agg_map]

    live_map: dict[str, dict] = {}
    if missing_dates:
        min_missing = min(missing_dates)

        # Coded per day from live events
        coded_rows = db.session.execute(
            sa.text("""
                SELECT DATE(e.event_created_at) AS d, COUNT(*) AS coded
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND e.transition_id IN ('coder_finalized', 'recode_finalized')
                  AND DATE(e.event_created_at) >= :from_date
                GROUP BY DATE(e.event_created_at)
            """),
            {"site_ids": site_ids, "from_date": min_missing},
        ).mappings().all()
        coded_by_date = {str(r["d"]): r["coded"] for r in coded_rows}

        # New submissions per day
        new_rows = db.session.execute(
            sa.text("""
                SELECT DATE(s.va_created_at) AS d, COUNT(*) AS cnt
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND DATE(s.va_created_at) >= :from_date
                GROUP BY DATE(s.va_created_at)
            """),
            {"site_ids": site_ids, "from_date": min_missing},
        ).mappings().all()
        new_by_date = {str(r["d"]): r["cnt"] for r in new_rows}

        # Not-codeable per day
        nc_rows = db.session.execute(
            sa.text("""
                SELECT DATE(e.event_created_at) AS d, COUNT(*) AS cnt
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND e.transition_id IN ('coder_not_codeable', 'data_manager_not_codeable')
                  AND DATE(e.event_created_at) >= :from_date
                GROUP BY DATE(e.event_created_at)
            """),
            {"site_ids": site_ids, "from_date": min_missing},
        ).mappings().all()
        nc_by_date = {str(r["d"]): r["cnt"] for r in nc_rows}

        # Consent refused per day
        cr_rows = db.session.execute(
            sa.text("""
                SELECT DATE(e.event_created_at) AS d, COUNT(*) AS cnt
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND e.current_state = 'consent_refused'
                  AND DATE(e.event_created_at) >= :from_date
                GROUP BY DATE(e.event_created_at)
            """),
            {"site_ids": site_ids, "from_date": min_missing},
        ).mappings().all()
        cr_by_date = {str(r["d"]): r["cnt"] for r in cr_rows}

        # Current pending snapshot (attributed to today only)
        pending_now = db.session.execute(
            sa.text("""
                SELECT COUNT(*) AS pending
                FROM va_submission_workflow w
                JOIN va_submissions s ON s.va_sid = w.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND w.workflow_state IN (
                      'ready_for_coding', 'coding_in_progress', 'coder_step1_saved'
                  )
            """),
            {"site_ids": site_ids},
        ).scalar() or 0

        for d in missing_dates:
            ds = str(d)
            live_map[ds] = {
                "date": ds,
                "total": new_by_date.get(ds, 0),
                "new_from_odk": new_by_date.get(ds, 0),
                "updated_from_odk": 0,
                "coded": coded_by_date.get(ds, 0),
                "pending": pending_now if d == today else 0,
                "consent_refused": cr_by_date.get(ds, 0),
                "not_codeable": nc_by_date.get(ds, 0),
                "_source": "live",
            }

    # Merge: live overrides agg for missing dates; agg wins for older covered dates
    # But today always uses live even if an (stale) agg row exists
    result = []
    for d in all_dates:
        ds = str(d)
        if d == today and ds in live_map:
            row = live_map[ds]
        elif ds in agg_map:
            row = dict(agg_map[ds])
            row["date"] = ds
        elif ds in live_map:
            row = live_map[ds]
        else:
            continue
        result.append({
            "date": row["date"],
            "total": row.get("total") or 0,
            "new_from_odk": row.get("new_from_odk") or 0,
            "updated_from_odk": row.get("updated_from_odk") or 0,
            "coded": row.get("coded") or 0,
            "pending": row.get("pending") or 0,
            "consent_refused": row.get("consent_refused") or 0,
            "not_codeable": row.get("not_codeable") or 0,
        })

    return {"data": result, "source": "aggregates+live"}


# ---------------------------------------------------------------------------
# Live fallback (when no aggregates exist yet)
# ---------------------------------------------------------------------------

def _grid_from_live(site_ids: list[str], days: int) -> dict:
    """Compute daily grid live from va_submissions + workflow events."""
    from app.services.workflow.definition import (
        TRANSITION_CODER_FINALIZED,
        TRANSITION_CODER_NOT_CODEABLE,
        TRANSITION_DM_NOT_CODEABLE,
        TRANSITION_RECODE_FINALIZED,
        WORKFLOW_CODER_STEP1_SAVED,
        WORKFLOW_CODING_IN_PROGRESS,
        WORKFLOW_READY_FOR_CODING,
    )

    from_date = date.today() - timedelta(days=days - 1)

    # Build a CTE with one row per submission, scoped to DM sites
    scoped = sa.text("""
        SELECT s.va_sid, f.site_id,
               DATE(s.va_created_at) AS created_date,
               w.workflow_state
        FROM va_submissions s
        JOIN va_forms f ON f.form_id = s.va_form_id
        LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
        WHERE f.site_id = ANY(:site_ids)
    """)

    # Total per day (cumulative count as of each day is complex live,
    # so we return daily new counts as a simpler proxy)
    totals = db.session.execute(
        sa.text("""
            SELECT DATE(s.va_created_at) AS date, COUNT(*) AS total
            FROM va_submissions s
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = ANY(:site_ids)
              AND DATE(s.va_created_at) >= :from_date
            GROUP BY DATE(s.va_created_at)
        """),
        {"site_ids": site_ids, "from_date": from_date},
    ).mappings().all()

    total_map = {str(r["date"]): r["total"] for r in totals}

    # Coded per day
    coded = db.session.execute(
        sa.text("""
            SELECT DATE(e.event_created_at) AS date, COUNT(*) AS coded
            FROM va_submission_workflow_events e
            JOIN va_submissions s ON s.va_sid = e.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = ANY(:site_ids)
              AND e.transition_id IN ('coder_finalized', 'recode_finalized')
              AND DATE(e.event_created_at) >= :from_date
            GROUP BY DATE(e.event_created_at)
        """),
        {"site_ids": site_ids, "from_date": from_date},
    ).mappings().all()

    coded_map = {str(r["date"]): r["coded"] for r in coded}

    # Not-codeable per day
    not_codeable = db.session.execute(
        sa.text("""
            SELECT DATE(e.event_created_at) AS date, COUNT(*) AS not_codeable
            FROM va_submission_workflow_events e
            JOIN va_submissions s ON s.va_sid = e.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = ANY(:site_ids)
              AND e.transition_id IN ('coder_not_codeable', 'data_manager_not_codeable')
              AND DATE(e.event_created_at) >= :from_date
            GROUP BY DATE(e.event_created_at)
        """),
        {"site_ids": site_ids, "from_date": from_date},
    ).mappings().all()

    not_codeable_map = {str(r["date"]): r["not_codeable"] for r in not_codeable}

    # Consent refused per day
    consent = db.session.execute(
        sa.text("""
            SELECT DATE(e.event_created_at) AS date, COUNT(*) AS consent_refused
            FROM va_submission_workflow_events e
            JOIN va_submissions s ON s.va_sid = e.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = ANY(:site_ids)
              AND e.current_state = 'consent_refused'
              AND DATE(e.event_created_at) >= :from_date
            GROUP BY DATE(e.event_created_at)
        """),
        {"site_ids": site_ids, "from_date": from_date},
    ).mappings().all()

    consent_map = {str(r["date"]): r["consent_refused"] for r in consent}

    # Pending snapshot (current state, attributed to today as proxy)
    pending_count = db.session.execute(
        sa.text("""
            SELECT COUNT(*) AS pending
            FROM va_submission_workflow w
            JOIN va_submissions s ON s.va_sid = w.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE f.site_id = ANY(:site_ids)
              AND w.workflow_state IN (
                  'ready_for_coding', 'coding_in_progress', 'coder_step1_saved'
              )
        """),
        {"site_ids": site_ids},
    ).scalar() or 0

    # Merge all dates
    all_dates = sorted(
        set(total_map) | set(coded_map) | set(not_codeable_map) | set(consent_map),
        reverse=True,
    )

    return {
        "data": [
            {
                "date": d,
                "total": total_map.get(d, 0),
                "new_from_odk": total_map.get(d, 0),
                "updated_from_odk": 0,
                "coded": coded_map.get(d, 0),
                "pending": pending_count if i == 0 else 0,  # only today
                "consent_refused": consent_map.get(d, 0),
                "not_codeable": not_codeable_map.get(d, 0),
            }
            for i, d in enumerate(all_dates)
        ],
        "source": "live",
    }
