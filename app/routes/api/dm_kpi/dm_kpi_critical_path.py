"""DM KPI — Critical Path (D-WF-02, digitva-r5s0 step 2, group g).

Blueprint prefix: ``/api/v1/analytics/dm-kpi/critical-path``

KPI served (docs/policy/kpis.md, "Critical-path view (D-WF-02)"):
  D-WF-02  The median and p90 time in each stage, the dominant stage and the
           bottleneck against peers.

Sources:
  - va_submission_workflow_events: time in a stage is an event's
    ``event_created_at`` minus that of the event before it, when that earlier
    event entered the stage (``previous_state``), as ``state_velocity`` pairs
    them.
  - ``area_dashboard_service._medians``: the end segments, death to interview
    and interview to final cause.

Stages (``STAGES``) are the pending states (``PENDING_STATES``) plus the
upstream stage, split by the reason of the event that entered it: an ODK
change (``finalized_upstream_changed``) or the Collect correction
(``sent_back_for_revision``, CL-02). Retired, duplicate, demo and tester
events are left out; the window is the last *period* days on each event's
project clock (docs/policy/kpis.md, "Days follow the project clock").
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
from app.services.kpi.critical_path import (  # noqa: F401
    DEFAULT_PERIOD_DAYS,
    MAX_PERIOD_DAYS,
    compute_dwf02,
)

bp = Blueprint("dm_kpi_critical_path", __name__)
log = logging.getLogger(__name__)


@bp.get("/")
@role_required("data_manager", "admin")
def critical_path():
    """KPI: D-WF-02 critical path (``?days=``, 1 to 90, default 30)."""
    days = clamped_int_arg("days", DEFAULT_PERIOD_DAYS, MAX_PERIOD_DAYS)
    if days is None:
        return api_error("days must be a positive whole number.", "invalid_request", 400)
    scope = dm_scope()
    return jsonify(cached_kpi("critical_path", lambda: compute_dwf02(scope, days)))
