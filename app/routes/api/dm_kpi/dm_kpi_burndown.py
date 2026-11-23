"""DM KPI — Burndown & Predictions.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/burndown``

KPIs served:
  C-16  Mean Daily Coding Rate
  C-17  Predicted Days to Clear Backlog
  C-18  Predicted vs Achieved (Burndown)

Sources (live, digitva-0hul; ``va_daily_kpi_aggregates`` is not read):
  - va_submission_workflow_events (non-demo finalize events)
  - va_project_master.project_target_completion_date

Design notes:
  C-18 requires project_target_completion_date to be set by admin.
  If not set, the endpoint returns burndown_available=false but still
  provides predicted_days and mean_daily_rate.

  Every query covers the whole scope (direct pairs OR unit subtree) in one
  WHERE, so no submission is counted twice. Coded counts drop demo events
  (``NOT_DEMO_OUTPUT_SQL``); the achieved line's days are the viewer's.

Submissions retired from ODK are excluded from every count, list,
grouping and average below (docs/policy/odk-retired-submissions.md).
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify

from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_scope import (
    cached_kpi,
    dm_scope,
)
from app.services.kpi.burndown import (  # noqa: F401
    compute_burndown,
)

bp = Blueprint("dm_kpi_burndown", __name__)
log = logging.getLogger(__name__)


@bp.get("/")
@role_required("data_manager", "admin")
def burndown():
    """KPIs: C-16 (Mean Daily Coding Rate), C-17 (Predicted Days to Clear
    Backlog), C-18 (Predicted vs Achieved Burndown).

    C-16 — Mean Daily Coding Rate:
      Definition: Average number of submissions coded per day over
                  the trailing window.
      Formula: non-demo coder_finalized / recode_finalized events in the
               last 7 days / 7.
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
      Achieved line: Cumulative non-demo finalize events per viewer day,
                     live from workflow events.
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

    return jsonify(cached_kpi("burndown", lambda: compute_burndown(scope)))
