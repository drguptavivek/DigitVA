"""DM KPI — Daily Operations Grid.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/grid``

KPIs served:
  C-01  Daily Operations Grid

Sources:
  - va_daily_kpi_aggregates (primary, pre-computed)
  - va_submissions + va_submission_workflow_events (live fallback)

  Submissions retired from ODK are excluded (docs/policy/odk-retired-submissions.md).

Design notes:
  The grid reads from ``va_daily_kpi_aggregates`` which is keyed by
  ``(snapshot_date, site_id)`` and counts every project's forms at the site,
  so only ``DmScope.aggregate_site_ids`` (sites whose every project is in the
  DM's pairs) are read from it (digitva-lh1h).

  Dates filled live use the whole scope (direct pairs OR unit subtree) in one
  WHERE; dates served from the aggregates add the rest of the scope live
  (shared sites and the unit subtree outside the aggregate sites), so no
  submission is counted twice.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import sqlalchemy as sa
from flask import Blueprint, jsonify, request

from app import db
from app.decorators import role_required
from app.services.duplicate_exclusion import not_confirmed_duplicate_sql
from app.services.odk_retirement_service import IN_ODK_BIND, in_odk_sql
from app.routes.api.dm_kpi.dm_kpi_scope import DmScope, cached_kpi, dm_scope

bp = Blueprint("dm_kpi_grid", __name__)
log = logging.getLogger(__name__)

# Retired submissions are not counted (docs/policy/odk-retired-submissions.md).
_IN_ODK_SQL = in_odk_sql("s")
# Confirmed-duplicate web cases leave every count (app/services/duplicate_exclusion.py).
_NOT_DUPLICATE_SQL = not_confirmed_duplicate_sql("s.va_sid")


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
    scope = dm_scope()
    if not scope:
        return jsonify({"data": [], "source": "none"})

    days = min(int(request.args.get("days", 8)), 90)

    def compute():
        # Aggregates are site-keyed, so only the aggregate-safe direct sites
        # are read. An empty IN () would abort the transaction, hence the guard.
        has_aggregates = False
        if scope.aggregate_site_ids:
            try:
                has_aggregates = bool(db.session.scalar(
                    sa.select(sa.func.count()).select_from(
                        sa.text("va_daily_kpi_aggregates")
                    ).where(
                        sa.text("site_id IN :sites"),
                    ).params(sites=tuple(scope.aggregate_site_ids))
                ))
            except Exception as e:
                # Table doesn't exist yet (migration not run) — fall back to live
                log.debug(f"va_daily_kpi_aggregates not available: {e}")
                has_aggregates = False

        if has_aggregates:
            return _grid_from_aggregates_with_live_fill(scope, days)
        return _grid_from_live(scope, days)

    return jsonify(cached_kpi("grid", compute))


# ---------------------------------------------------------------------------
# Live per-day counts shared by both grid paths
# ---------------------------------------------------------------------------

def _live_daily_counts(scope_sql: str, scope_params: dict, from_date: date) -> dict[str, dict[str, int]]:
    """Per-day live counts since *from_date* under *scope_sql*.

    Returns ``{"new": {...}, "coded": {...}, "not_codeable": {...},
    "consent_refused": {...}}``, each mapping ISO date -> count.
    """
    params = {**IN_ODK_BIND, **scope_params, "from_date": from_date}
    event_counts = {
        "coded": "e.transition_id IN ('coder_finalized', 'recode_finalized')",
        "not_codeable": "e.transition_id IN ('coder_not_codeable', 'data_manager_not_codeable')",
        "consent_refused": "e.current_state = 'consent_refused'",
    }
    counts: dict[str, dict[str, int]] = {}

    new_rows = db.session.execute(
        sa.text(f"""
            SELECT DATE(s.va_created_at) AS d, COUNT(*) AS cnt
            FROM va_submissions s
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE {scope_sql}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
              AND DATE(s.va_created_at) >= :from_date
            GROUP BY DATE(s.va_created_at)
        """),
        params,
    ).mappings().all()
    counts["new"] = {str(r["d"]): r["cnt"] for r in new_rows}

    for key, condition in event_counts.items():
        rows = db.session.execute(
            sa.text(f"""
                SELECT DATE(e.event_created_at) AS d, COUNT(*) AS cnt
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE {scope_sql}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND {condition}
                  AND DATE(e.event_created_at) >= :from_date
                GROUP BY DATE(e.event_created_at)
            """),
            params,
        ).mappings().all()
        counts[key] = {str(r["d"]): r["cnt"] for r in rows}
    return counts


def _live_pending(scope: DmScope) -> int:
    """Current coding-pool pending count for the whole scope."""
    return db.session.execute(
        sa.text(f"""
            SELECT COUNT(*) AS pending
            FROM va_submission_workflow w
            JOIN va_submissions s ON s.va_sid = w.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
              AND w.workflow_state IN (
                  'ready_for_coding', 'coding_in_progress', 'coder_step1_saved'
              )
        """),
        {**IN_ODK_BIND, **scope.params},
    ).scalar() or 0


# ---------------------------------------------------------------------------
# Grid from pre-computed aggregates — with live fill for missing/today dates
# ---------------------------------------------------------------------------

def _grid_from_aggregates_with_live_fill(scope: DmScope, days: int) -> dict:
    """Read daily grid from va_daily_kpi_aggregates, filling gaps with live data.

    Aggregate rows are written once daily for *yesterday*. This means:
    - Today's row is always missing or stale.
    - Days where no task ran are also missing.
    Use live workflow-event counts for any date not covered by the aggregates.

    Live-filled dates count the whole scope. Aggregate dates cover the
    aggregate sites only, so the rest of the scope is added live (event and
    new-submission counts; that part has no pending history).
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
            WHERE site_id = ANY(:aggregate_site_ids)
              AND snapshot_date >= :from_date
            GROUP BY snapshot_date
            ORDER BY snapshot_date DESC
        """),
        {"aggregate_site_ids": scope.aggregate_site_ids, "from_date": from_date},
    ).mappings().all()

    agg_map = {str(r["date"]): dict(r) for r in agg_rows}

    # Identify dates that need live fill: always today + any gap in the window
    all_dates = [(today - timedelta(days=i)) for i in range(days)]
    missing_dates = [d for d in all_dates if str(d) not in agg_map]

    live_map: dict[str, dict] = {}
    if missing_dates:
        live = _live_daily_counts(scope.sql(), scope.params, min(missing_dates))
        pending_now = _live_pending(scope)

        for d in missing_dates:
            ds = str(d)
            live_map[ds] = {
                "date": ds,
                "total": live["new"].get(ds, 0),
                "new_from_odk": live["new"].get(ds, 0),
                "updated_from_odk": 0,
                "coded": live["coded"].get(ds, 0),
                "pending": pending_now if d == today else 0,
                "consent_refused": live["consent_refused"].get(ds, 0),
                "not_codeable": live["not_codeable"].get(ds, 0),
                "_source": "live",
            }

    # The rest of the scope on the dates served from the aggregates.
    covered = [d for d in all_dates if str(d) in agg_map]
    unit_live = None
    if scope.has_outside_aggregates and covered:
        unit_live = _live_daily_counts(
            scope.outside_aggregates_sql(), scope.params, min(covered)
        )

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
            if unit_live is not None:
                unit_new = unit_live["new"].get(ds, 0)
                row["total"] = (row.get("total") or 0) + unit_new
                row["new_from_odk"] = (row.get("new_from_odk") or 0) + unit_new
                for key in ("coded", "consent_refused", "not_codeable"):
                    row[key] = (row.get(key) or 0) + unit_live[key].get(ds, 0)
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

def _grid_from_live(scope: DmScope, days: int) -> dict:
    """Compute daily grid live from va_submissions + workflow events.

    One WHERE over the whole scope (direct pairs OR unit subtree).
    """
    from_date = date.today() - timedelta(days=days - 1)
    live = _live_daily_counts(scope.sql(), scope.params, from_date)

    # Total per day: cumulative count as of each day is complex live, so
    # daily new counts are returned as a simpler proxy.
    total_map = live["new"]
    coded_map = live["coded"]
    not_codeable_map = live["not_codeable"]
    consent_map = live["consent_refused"]

    # Pending snapshot (current state, attributed to today as proxy)
    pending_count = _live_pending(scope)

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
