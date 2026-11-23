"""Query and compute code for the DM KPI endpoints of ``app/routes/api/dm_kpi/dm_kpi_grid.py``.

Moved out of the route module unchanged (digitva-r8nh.16); the route parses
parameters, calls these functions and returns JSON.
"""


from __future__ import annotations

import logging
from datetime import UTC, timedelta

import sqlalchemy as sa

from app import db
from app.services.kpi.common import IN_ODK_SQL as _IN_ODK_SQL
from app.services.kpi.common import NOT_DUPLICATE_SQL as _NOT_DUPLICATE_SQL
from app.services.kpi.scope import (
    CLOCK_JOIN_SQL,
    NOT_DEMO_OUTPUT_SQL,
    DmScope,
    clock_day_sql,
    clock_tz_sql,
)
from app.services.odk_retirement_service import IN_ODK_BIND
from app.services.workflow.definition import (
    EVENT_CONSENT_REFUSED_SQL,
    EVENT_NOT_CODEABLE_SQL,
    PENDING_STATES,
)

log = logging.getLogger(__name__)

_FINALIZE_SQL = "e.transition_id IN ('coder_finalized', 'recode_finalized')"


def compute_c01(scope: DmScope, period: int = 8, by: str | None = None) -> dict:
    """C-01 rows for the last *period* project-clock days, newest first.

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
    today = scope.today()
    from_date = today - timedelta(days=period - 1)
    window_start = scope.day_floor(from_date)
    params = {
        **IN_ODK_BIND,
        **scope.params,
        "window_start": window_start,
        "window_start_naive": window_start.astimezone(UTC).replace(tzinfo=None),
    }

    # Total and New: va_created_at is naive UTC, compared raw (indexed) with
    # the naive floor and bucketed through timezone('UTC', ...). Days before
    # from_date (read when another project's zone sets the floor) are ignored.
    created = db.session.execute(
        sa.text(f"""
            WITH scoped AS (
                SELECT s.va_created_at, {clock_tz_sql()} AS timezone
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                {CLOCK_JOIN_SQL}
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
            )
            SELECT NULL::date AS d, COUNT(*) AS n FROM scoped
            UNION ALL
            SELECT DATE(timezone(timezone, timezone('UTC', va_created_at))), COUNT(*)
            FROM scoped
            WHERE va_created_at >= :window_start_naive
            GROUP BY 1
        """),
        params,
    ).all()
    total_now = next(n for d, n in created if d is None)
    new_by_day = {d: n for d, n in created if d is not None}

    events = db.session.execute(
        sa.text(f"""
            SELECT {clock_day_sql("e.event_created_at")} AS d,
                   COUNT(*) FILTER (WHERE {_FINALIZE_SQL} AND {NOT_DEMO_OUTPUT_SQL}) AS coded,
                   COUNT(*) FILTER (WHERE {EVENT_NOT_CODEABLE_SQL}) AS not_codeable,
                   COUNT(*) FILTER (WHERE {EVENT_CONSENT_REFUSED_SQL}) AS consent_refused
            FROM va_submission_workflow_events e
            JOIN va_submissions s ON s.va_sid = e.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            {CLOCK_JOIN_SQL}
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

    # Lazy: bucket_flow_by_day stays in the route module (tests/test_duplicate_exclusion_coverage.py
    # pins its path), and importing that module at load time re-enters this one.
    from app.routes.api.dm_kpi.dm_kpi_scope import bucket_flow_by_day

    flow = bucket_flow_by_day(scope, PENDING_STATES, from_date, today)
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
