"""DM KPI — Daily Operations Grid.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/grid``

KPIs served:
  C-01  Daily Operations Grid

Sources (live, digitva-0hul; ``va_daily_kpi_aggregates`` is not read):
  - va_submissions (Total, New)
  - va_submission_workflow_events (Coded, Not analysable, Not Codeable)
  - ``bucket_flow_by_day`` (Pending, end of each day, replayed from events)

  Submissions retired from ODK are excluded (docs/policy/odk-retired-submissions.md).

Design notes:
  Every row comes from the same three queries over the whole scope (direct
  pairs OR unit subtree, one WHERE), so a submission is counted once. Days
  are the viewer's (``DmScope.tz``), every day of the window has a row, and
  today is today in that timezone.
"""

from __future__ import annotations

import logging
from datetime import timedelta

import sqlalchemy as sa
from flask import Blueprint, jsonify

from app import db
from app.decorators import role_required
from app.routes.api.request_helpers import clamped_int_arg, error as api_error
from app.services.duplicate_exclusion import not_confirmed_duplicate_sql
from app.services.odk_retirement_service import IN_ODK_BIND, in_odk_sql
from app.services.workflow.definition import (
    EVENT_CONSENT_REFUSED_SQL,
    EVENT_NOT_CODEABLE_SQL,
    PENDING_STATES,
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

bp = Blueprint("dm_kpi_grid", __name__)
log = logging.getLogger(__name__)

# Retired submissions are not counted (docs/policy/odk-retired-submissions.md).
_IN_ODK_SQL = in_odk_sql("s")
# Confirmed-duplicate web cases leave every count (app/services/duplicate_exclusion.py).
_NOT_DUPLICATE_SQL = not_confirmed_duplicate_sql("s.va_sid")

_FINALIZE_SQL = "e.transition_id IN ('coder_finalized', 'recode_finalized')"


@bp.get("/")
@role_required("data_manager", "admin")
def daily_grid():
    """KPI: C-01 — Daily Operations Grid (thin wrapper over ``compute_c01``)."""
    scope = dm_scope()
    if not scope:
        return jsonify({"data": [], "source": "none"})

    days = clamped_int_arg("days", 8, 90)
    if days is None:
        return api_error("days must be a positive whole number.", "invalid_request", 400)

    return jsonify(cached_kpi("grid", lambda: compute_c01(scope, days)))


def compute_c01(scope: DmScope, period: int = 8, by: str | None = None) -> dict:
    """C-01 rows for the last *period* days in the viewer's timezone, newest first.

    Columns (docs/policy/kpis.md, C-01):
      - total:           submissions created up to the end of the day (cumulative)
      - new_from_odk:    submissions created that day (ODK and web intake)
      - updated_from_odk: 0; the per-scope source is not defined yet
      - coded:           non-demo coder_finalized / recode_finalized events that day
      - pending:         the 6 pending states at the end of the day
      - consent_refused: events into consent_refused that day
      - not_codeable:    coder / data-manager not-codeable events that day

    Three queries whatever *period* is. Raises ``ValueError`` for an
    unsupported *by* (only the whole scope is implemented).
    """
    if by is not None:
        raise ValueError(f"C-01 does not support by={by!r}")
    tz = scope.tz
    today = local_today(tz)
    from_date = today - timedelta(days=period - 1)
    window_start = local_day_start(from_date, tz)
    params = {**IN_ODK_BIND, **scope.params, "tz": tz, "window_start": window_start}

    # Total and New: va_created_at is naive UTC, hence timezone('UTC', ...).
    created = db.session.execute(
        sa.text(f"""
            WITH scoped AS (
                SELECT s.va_created_at
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
            )
            SELECT NULL::date AS d, COUNT(*) AS n FROM scoped
            UNION ALL
            SELECT DATE(timezone(:tz, timezone('UTC', va_created_at))), COUNT(*)
            FROM scoped
            WHERE timezone('UTC', va_created_at) >= :window_start
            GROUP BY 1
        """),
        params,
    ).all()
    total_now = next(n for d, n in created if d is None)
    new_by_day = {d: n for d, n in created if d is not None}

    events = db.session.execute(
        sa.text(f"""
            SELECT DATE(timezone(:tz, e.event_created_at)) AS d,
                   COUNT(*) FILTER (WHERE {_FINALIZE_SQL} AND {NOT_DEMO_OUTPUT_SQL}) AS coded,
                   COUNT(*) FILTER (WHERE {EVENT_NOT_CODEABLE_SQL}) AS not_codeable,
                   COUNT(*) FILTER (WHERE {EVENT_CONSENT_REFUSED_SQL}) AS consent_refused
            FROM va_submission_workflow_events e
            JOIN va_submissions s ON s.va_sid = e.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
              AND e.event_created_at >= :window_start
              AND ({_FINALIZE_SQL} OR {EVENT_NOT_CODEABLE_SQL} OR {EVENT_CONSENT_REFUSED_SQL})
            GROUP BY 1
        """),
        params,
    ).mappings().all()
    events_by_day = {r["d"]: r for r in events}

    flow = bucket_flow_by_day(scope.sql(), scope.params, PENDING_STATES, from_date, today, tz)
    pending_by_day = {row["date"]: row["end_of_day"] for row in flow}

    rows = []
    total = total_now
    day = today
    while day >= from_date:
        ev = events_by_day.get(day)
        new = new_by_day.get(day, 0)
        rows.append({
            "date": day.isoformat(),
            "total": total,
            "new_from_odk": new,
            "updated_from_odk": 0,
            "coded": ev["coded"] if ev else 0,
            "pending": pending_by_day[day.isoformat()],
            "consent_refused": ev["consent_refused"] if ev else 0,
            "not_codeable": ev["not_codeable"] if ev else 0,
        })
        total -= new
        day -= timedelta(days=1)
    return {"data": rows, "source": "live"}
