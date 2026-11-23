"""Query and compute code for the DM KPI endpoints of ``app/routes/api/dm_kpi/dm_kpi_burndown.py``.

Moved out of the route module unchanged (digitva-r8nh.16); the route parses
parameters, calls these functions and returns JSON.
"""


from __future__ import annotations

import logging
from datetime import timedelta

import sqlalchemy as sa

from app import db
from app.services.kpi.common import IN_ODK_SQL as _IN_ODK_SQL
from app.services.kpi.common import NOT_DUPLICATE_SQL as _NOT_DUPLICATE_SQL
from app.services.kpi.scope import (
    CLOCK_JOIN_SQL,
    NOT_DEMO_OUTPUT_SQL,
    DmScope,
    clock_day_sql,
    clock_params,
    in_last_days_sql,
)
from app.services.odk_retirement_service import IN_ODK_BIND
from app.services.workflow.definition import PENDING_STATES_SQL

#: The C-16 window: the last 7 days on each event's project clock, today included.
_LAST_7_DAYS_SQL = in_last_days_sql("e.event_created_at", "e.event_created_at >= :clock_floor")
log = logging.getLogger(__name__)


def compute_burndown(scope: DmScope):
    # --- C-16: Mean Daily Coding Rate (7d) ---
    last_7d = clock_params(7)

    total_coded_7d = _coded_last_7_days(scope)
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
              AND w.workflow_state IN {PENDING_STATES_SQL}
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
            {CLOCK_JOIN_SQL}
            LEFT JOIN va_users u ON u.user_id = e.actor_user_id
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
              AND e.transition_id IN ('coder_finalized', 'recode_finalized')
              AND {_LAST_7_DAYS_SQL}
              AND e.actor_user_id IS NOT NULL
              AND {NOT_DEMO_OUTPUT_SQL}
            GROUP BY e.actor_user_id, u.name
            ORDER BY coded_7d DESC
        """),
        {**IN_ODK_BIND, **scope.params, **last_7d},
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
            {CLOCK_JOIN_SQL}
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
              AND e.transition_id IN ('coder_finalized', 'recode_finalized')
              AND {_LAST_7_DAYS_SQL}
              AND s.va_narration_language IS NOT NULL
              AND {NOT_DEMO_OUTPUT_SQL}
            GROUP BY s.va_narration_language
            ORDER BY coded_7d DESC
        """),
        {**IN_ODK_BIND, **scope.params, **last_7d},
    ).mappings().all()

    # --- C-18: Burndown ---
    # Check if any project has a target completion date
    # Project metadata only: a unit grant's own project supplies its target.
    project_ids = scope.all_project_ids

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

        # First submission date, on the submission's project clock
        first_date = db.session.execute(
            sa.text(f"""
                SELECT MIN({clock_day_sql("timezone('UTC', s.va_created_at)")}) AS d
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                {CLOCK_JOIN_SQL}
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

            achieved = _achieved_line(scope, total_forms)

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


def _coded_last_7_days(scope: DmScope) -> int:
    """Live count of non-demo coder_finalized / recode_finalized events in the
    last 7 days on each event's project clock."""
    return db.session.execute(
        sa.text(f"""
            SELECT COUNT(*) AS cnt
            FROM va_submission_workflow_events e
            JOIN va_submissions s ON s.va_sid = e.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            {CLOCK_JOIN_SQL}
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
              AND e.transition_id IN ('coder_finalized', 'recode_finalized')
              AND {_LAST_7_DAYS_SQL}
              AND {NOT_DEMO_OUTPUT_SQL}
        """),
        {**IN_ODK_BIND, **scope.params, **clock_params(7)},
    ).scalar() or 0


def _achieved_line(scope: DmScope, total_forms: int) -> list[dict]:
    """C-18 achieved line: cumulative non-demo finalize events per project-clock day.

    One query over the whole scope; a day with no event has no point.
    """
    rows = db.session.execute(
        sa.text(f"""
            SELECT {clock_day_sql("e.event_created_at")} AS d, COUNT(*) AS cnt
            FROM va_submission_workflow_events e
            JOIN va_submissions s ON s.va_sid = e.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            {CLOCK_JOIN_SQL}
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
              AND e.transition_id IN ('coder_finalized', 'recode_finalized')
              AND {NOT_DEMO_OUTPUT_SQL}
            GROUP BY 1
            ORDER BY 1
        """),
        {**IN_ODK_BIND, **scope.params},
    ).all()

    achieved = []
    cumulative = 0
    for d, cnt in rows:
        cumulative += cnt
        achieved.append({
            "date": str(d),
            "cumulative_coded": cumulative,
            "remaining_achieved": max(total_forms - cumulative, 0),
        })
    return achieved
