"""DM KPI — Burndown & Predictions.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/burndown``

KPIs served:
  C-16  Mean Daily Coding Rate
  C-17  Predicted Days to Clear Backlog
  C-18  Predicted vs Achieved (Burndown)

Sources:
  - va_daily_kpi_aggregates (time-series)
  - va_submission_workflow_events (live fallback)
  - va_project_master.project_target_completion_date

Design notes:
  C-18 requires project_target_completion_date to be set by admin.
  If not set, the endpoint returns burndown_available=false but still
  provides predicted_days and mean_daily_rate.

  The aggregates are site-keyed and cover the direct sites only. For a DM
  with unit-scope grants, the coded figures read from them (C-16 rate, C-18
  achieved line) add the unit part live, restricted to submissions outside
  the direct sites, so no submission is counted twice. Without aggregates
  the live queries cover the whole scope in one WHERE.

Submissions retired from ODK are excluded from every count, list,
grouping and average below (docs/policy/odk-retired-submissions.md).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.services.duplicate_exclusion import not_confirmed_duplicate_sql
from app.services.odk_retirement_service import IN_ODK_BIND, in_odk_sql
from app.routes.api.dm_kpi.dm_kpi_scope import (
    DmScope,
    cached_kpi,
    dm_project_site_pairs,
    dm_scope,
)

bp = Blueprint("dm_kpi_burndown", __name__)
log = logging.getLogger(__name__)

# Retired submissions are not counted (docs/policy/odk-retired-submissions.md).
_IN_ODK_SQL = in_odk_sql("s")
# Confirmed-duplicate web cases leave every count (app/services/duplicate_exclusion.py).
_NOT_DUPLICATE_SQL = not_confirmed_duplicate_sql("s.va_sid")


@bp.get("/")
@role_required("data_manager")
def burndown():
    """KPIs: C-16 (Mean Daily Coding Rate), C-17 (Predicted Days to Clear
    Backlog), C-18 (Predicted vs Achieved Burndown).

    C-16 — Mean Daily Coding Rate:
      Definition: Average number of submissions coded per day over
                  the trailing window.
      Formula: SUM of coded_count from va_daily_kpi_aggregates over
               window / COUNT of days in window.
      Also report:
        - Per coder: SUM of coder_finalized events / days grouped by
          va_finassess_by.
        - Per language: SUM of coder_finalized events / days grouped by
          va_narration_language.
      Scope: CODING-POOL.
      Time frames: 7d.
      Actionable: Tells DM "your team is averaging N forms/day" — compare
                  against inflow rate.

    C-17 — Predicted Days to Clear Backlog:
      Definition: Estimated days to code all currently uncoded forms.
      Formula: pending_count (C-04 numerator) / mean_daily_coding_rate (C-16).
      Scope: CODING-POOL.
      Time frame: Snapshot (recalculated daily).
      Also report: Per-language prediction.
      Edge case: If mean_daily_coding_rate = 0 (no coding in 7d), report
                 "inf" or "N/A".

    C-18 — Predicted vs Achieved (Burndown):
      Definition: Chart comparing projected completion trajectory vs
                  actual cumulative coding progress.
      Projected line: Straight line from (first_submission_date, total_forms)
                      to (target_date, 0). Daily point:
                      total − (days_elapsed × daily_target_rate).
      Achieved line: Cumulative count of CODED submissions over time
                     (from va_daily_kpi_aggregates cumulative coded_count).
      Requires: project_target_completion_date set by admin.
      Display: Line chart, two lines, X-axis = time, Y-axis = remaining.
      Actionable: If achieved line is above projected line, project is
                  behind schedule.
      Time frame: Daily series from project start to target date.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({
            "mean_daily_rate": 0,
            "predicted_days": None,
            "burndown_available": False,
            "achieved": [],
            "projected": [],
        })

    def compute():
        # --- C-16: Mean Daily Coding Rate (7d) ---
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

        # Try daily aggregates first
        agg_row = db.session.execute(
            sa.text("""
                SELECT
                    SUM(coded_count) AS total_coded,
                    COUNT(DISTINCT snapshot_date) AS days_with_data
                FROM va_daily_kpi_aggregates
                WHERE site_id = ANY(:aggregate_site_ids)
                  AND snapshot_date >= :from_date
            """),
            {
                "aggregate_site_ids": scope.aggregate_site_ids,
                "from_date": date.today() - timedelta(days=7),
            },
        ).mappings().first()

        has_aggregates = agg_row and (agg_row["days_with_data"] or 0) > 0

        if has_aggregates:
            total_coded_7d = agg_row["total_coded"] or 0
            days_with_data = agg_row["days_with_data"] or 1
            if scope.has_outside_aggregates:
                # The scope outside the aggregate sites, live.
                total_coded_7d += _coded_since(
                    scope.outside_aggregates_sql(), scope.params, seven_days_ago
                )
            mean_daily_rate = round(total_coded_7d / 7.0, 1)
        else:
            # Live fallback
            total_coded_7d = _coded_since(scope.sql(), scope.params, seven_days_ago)
            mean_daily_rate = round(total_coded_7d / 7.0, 1)

        # --- C-17: Pending count for prediction ---
        pending = db.session.execute(
            sa.text(f"""
                SELECT COUNT(*) AS cnt
                FROM va_submission_workflow w
                JOIN va_submissions s ON s.va_sid = w.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND w.workflow_state IN (
                      'ready_for_coding', 'coding_in_progress', 'coder_step1_saved',
                      'smartva_pending', 'screening_pending', 'attachment_sync_pending'
                  )
            """),
            {**IN_ODK_BIND, **scope.params},
        ).scalar() or 0

        predicted_days = None
        if mean_daily_rate > 0:
            predicted_days = round(pending / mean_daily_rate, 1)
        elif pending > 0:
            predicted_days = "infinite"  # Special string value for JSON serialization

        # Per-coder rate
        per_coder = db.session.execute(
            sa.text(f"""
                SELECT
                    e.actor_user_id AS coder_id,
                    u.name AS coder_name,
                    COUNT(*) AS coded_7d,
                    ROUND(COUNT(*)::NUMERIC / 7.0, 1) AS daily_rate
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                LEFT JOIN va_users u ON u.user_id = e.actor_user_id
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND e.transition_id IN ('coder_finalized', 'recode_finalized')
                  AND e.event_created_at >= :cutoff
                  AND e.actor_user_id IS NOT NULL
                GROUP BY e.actor_user_id, u.name
                ORDER BY coded_7d DESC
            """),
            {**IN_ODK_BIND, **scope.params, "cutoff": seven_days_ago},
        ).mappings().all()

        # Per-language rate
        per_language = db.session.execute(
            sa.text(f"""
                SELECT
                    s.va_narration_language AS language,
                    COUNT(*) AS coded_7d,
                    ROUND(COUNT(*)::NUMERIC / 7.0, 1) AS daily_rate
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND e.transition_id IN ('coder_finalized', 'recode_finalized')
                  AND e.event_created_at >= :cutoff
                  AND s.va_narration_language IS NOT NULL
                GROUP BY s.va_narration_language
                ORDER BY coded_7d DESC
            """),
            {**IN_ODK_BIND, **scope.params, "cutoff": seven_days_ago},
        ).mappings().all()

        # --- C-18: Burndown ---
        # Check if any project has a target completion date
        # Project metadata only: a unit grant's own project supplies its target.
        pairs = dm_project_site_pairs()
        project_ids = sorted(
            {pid for pid, _sid in pairs}
            | current_user.get_org_unit_projects("data_manager")
        )

        target_date = None
        if project_ids:
            try:
                target_date = db.session.execute(
                    sa.text("""
                        SELECT project_target_completion_date
                        FROM va_project_master
                        WHERE project_id = ANY(:project_ids)
                          AND project_target_completion_date IS NOT NULL
                        ORDER BY project_target_completion_date
                        LIMIT 1
                    """),
                    {"project_ids": project_ids},
                ).scalar()
            except Exception as e:
                # Column doesn't exist yet (migration not run)
                log.debug(f"project_target_completion_date not available: {e}")
                target_date = None

        burndown_available = target_date is not None
        achieved: list[dict] = []
        projected: list[dict] = []

        if burndown_available and target_date:
            # Total submissions in scope
            total_forms = db.session.execute(
                sa.text(f"""
                    SELECT COUNT(*) AS cnt
                    FROM va_submissions s
                    JOIN va_forms f ON f.form_id = s.va_form_id
                    WHERE {scope.sql()}
                      AND {_IN_ODK_SQL}
                      AND {_NOT_DUPLICATE_SQL}
                """),
                {**IN_ODK_BIND, **scope.params},
            ).scalar() or 0

            # First submission date
            first_date = db.session.execute(
                sa.text(f"""
                    SELECT MIN(DATE(va_created_at)) AS d
                    FROM va_submissions s
                    JOIN va_forms f ON f.form_id = s.va_form_id
                    WHERE {scope.sql()}
                      AND {_IN_ODK_SQL}
                      AND {_NOT_DUPLICATE_SQL}
                """),
                {**IN_ODK_BIND, **scope.params},
            ).scalar()

            if first_date and total_forms > 0:
                total_days = (target_date - first_date).days
                daily_target_rate = total_forms / max(total_days, 1)

                # Projected line
                current = first_date
                while current <= target_date:
                    days_elapsed = (current - first_date).days
                    remaining = max(total_forms - (days_elapsed * daily_target_rate), 0)
                    projected.append({
                        "date": str(current),
                        "remaining_projected": round(remaining),
                    })
                    current += timedelta(days=1)

                # Achieved line from aggregates
                if scope.has_outside_aggregates:
                    achieved = _achieved_with_units(scope, has_aggregates, total_forms)
                elif has_aggregates:
                    agg_rows = db.session.execute(
                        sa.text("""
                            SELECT
                                snapshot_date,
                                SUM(coded_count) OVER (
                                    ORDER BY snapshot_date
                                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                                ) AS cumulative_coded
                            FROM (
                                SELECT snapshot_date, SUM(coded_count) AS coded_count
                                FROM va_daily_kpi_aggregates
                                WHERE site_id = ANY(:aggregate_site_ids)
                                GROUP BY snapshot_date
                            ) sub
                            ORDER BY snapshot_date
                        """),
                        {"aggregate_site_ids": scope.aggregate_site_ids},
                    ).mappings().all()

                    for r in agg_rows:
                        remaining_achieved = max(total_forms - (r["cumulative_coded"] or 0), 0)
                        achieved.append({
                            "date": str(r["snapshot_date"]),
                            "cumulative_coded": r["cumulative_coded"] or 0,
                            "remaining_achieved": remaining_achieved,
                        })

        return {
            "c16_mean_daily_rate": mean_daily_rate,
            "c16_total_coded_7d": total_coded_7d,
            "c16_per_coder": [
                {
                    "coder_id": str(r["coder_id"]),
                    "coder_name": r["coder_name"],
                    "coded_7d": r["coded_7d"],
                    "daily_rate": float(r["daily_rate"]),
                }
                for r in per_coder
            ],
            "c16_per_language": [
                {
                    "language": r["language"],
                    "coded_7d": r["coded_7d"],
                    "daily_rate": float(r["daily_rate"]),
                }
                for r in per_language
            ],
            "c17_pending": pending,
            "c17_predicted_days": predicted_days,
            "c18_burndown_available": burndown_available,
            "c18_target_date": str(target_date) if target_date else None,
            "c18_achieved": achieved,
            "c18_projected": projected,
        }

    return jsonify(cached_kpi("burndown", compute))


def _coded_since(scope_sql: str, scope_params: dict, cutoff: datetime) -> int:
    """Live count of coder_finalized / recode_finalized events since *cutoff*."""
    return db.session.execute(
        sa.text(f"""
            SELECT COUNT(*) AS cnt
            FROM va_submission_workflow_events e
            JOIN va_submissions s ON s.va_sid = e.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE {scope_sql}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
              AND e.transition_id IN ('coder_finalized', 'recode_finalized')
              AND e.event_created_at >= :cutoff
        """),
        {**IN_ODK_BIND, **scope_params, "cutoff": cutoff},
    ).scalar() or 0


def _achieved_with_units(scope: DmScope, has_aggregates: bool, total_forms: int) -> list[dict]:
    """C-18 achieved line for a scope the aggregates do not wholly cover.

    Daily coded counts come from the aggregates for the aggregate sites (when
    they exist) plus live events for the rest of the scope (shared sites and
    the unit subtree outside those sites), or the whole scope when there are
    no aggregates. The two parts are disjoint, so the cumulative line counts
    each event once.
    """
    daily: dict[date, int] = {}
    if has_aggregates:
        rows = db.session.execute(
            sa.text("""
                SELECT snapshot_date AS d, SUM(coded_count) AS cnt
                FROM va_daily_kpi_aggregates
                WHERE site_id = ANY(:aggregate_site_ids)
                GROUP BY snapshot_date
            """),
            {"aggregate_site_ids": scope.aggregate_site_ids},
        ).mappings().all()
        for r in rows:
            daily[r["d"]] = daily.get(r["d"], 0) + (r["cnt"] or 0)

    live_sql = scope.outside_aggregates_sql() if has_aggregates else scope.sql()
    rows = db.session.execute(
        sa.text(f"""
            SELECT DATE(e.event_created_at) AS d, COUNT(*) AS cnt
            FROM va_submission_workflow_events e
            JOIN va_submissions s ON s.va_sid = e.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE {live_sql}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
              AND e.transition_id IN ('coder_finalized', 'recode_finalized')
            GROUP BY DATE(e.event_created_at)
        """),
        {**IN_ODK_BIND, **scope.params},
    ).mappings().all()
    for r in rows:
        daily[r["d"]] = daily.get(r["d"], 0) + r["cnt"]

    achieved = []
    cumulative = 0
    for d in sorted(daily):
        cumulative += daily[d]
        achieved.append({
            "date": str(d),
            "cumulative_coded": cumulative,
            "remaining_achieved": max(total_forms - cumulative, 0),
        })
    return achieved
