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
  pairs OR unit subtree, one WHERE), so a submission is counted once. Each
  submission and event falls on its own project's day (docs/policy/kpis.md,
  "Days follow the project clock"), every day of the window has a row, and
  the newest row is the latest project today in scope (``DmScope.today``).
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify

from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_scope import (
    cached_kpi,
    dm_scope,
)
from app.routes.api.request_helpers import clamped_int_arg
from app.routes.api.request_helpers import error as api_error
from app.services.kpi.grid import (  # noqa: F401
    compute_c01,
)

bp = Blueprint("dm_kpi_grid", __name__)
log = logging.getLogger(__name__)


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
