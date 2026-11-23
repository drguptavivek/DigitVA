"""DM KPI — Coder Stats.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/coders``

KPIs served:
  C-12  Coder Throughput
  C-21  Coder Utilization Rate (D-LC-02 as by=language)
  C-24  Forms per Coder by Language (heatmap)
  D-LC-04  Coder Output by Language
  D-LC-06  Coder Roster
  D-QG-09  Coder-Reviewer Disagreement Rate

Sources:
  - va_final_assessments (coder output)
  - va_reviewer_final_assessments (reviewer output)
  - va_user_access_grants + va_users (coder pool)
  - va_allocations (utilization)

Submissions retired from ODK are excluded from every count, list,
grouping and average below (docs/policy/odk-retired-submissions.md).
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_scope import (
    cached_kpi,
    dm_scope,
)
from app.routes.api.request_helpers import error as api_error
from app.services.kpi.coders import (  # noqa: F401
    compute_c21,
    compute_coder_output,
    compute_coder_roster,
)

bp = Blueprint("dm_kpi_coders", __name__)
log = logging.getLogger(__name__)


@bp.get("/utilization")
@role_required("data_manager", "admin")
def coder_utilization():
    """KPI: C-21 — Coder Utilization Rate (D-LC-02 as ``?by=language``).

    Numerator: COUNT of coders with at least one active allocation
               (va_allocations where va_allocation_status = 'active').
    Denominator: COUNT of coders who can code at least one case in the DM's
                 subtree (coders_covering_scope_sql; owner decision 2026-10-27).
    Rate: N / D × 100.
    Time frame: Snapshot.
    Actionable: <70% → coders idle; >95% → coders saturated.
    """
    by = request.args.get("by") or None
    if by not in (None, "language"):
        return api_error("Unsupported 'by'; use 'language'.", status_code=400)
    scope = dm_scope()
    if not scope:
        return jsonify({"active_count": 0, "total_coders": 0, "rate": 0.0})
    return jsonify(cached_kpi("coder_utilization", lambda: compute_c21(scope, None, by)))


@bp.get("/output")
@role_required("data_manager", "admin")
def coder_output():
    """KPIs: C-12 (Coder Throughput), C-24 (Forms per Coder by Language),
    D-LC-04 (Coder Output by Language).

    C-12 — Coder Throughput:
      Numerator: COUNT of workflow events with transition_id IN
                 ('coder_finalized', 'recode_finalized') in window.
      Also report: Per-coder breakdown.
      Scope: CODING-POOL.
      Time frames: 7d, cumulative.

    C-24 — Forms per Coder by Language:
      Numerator: COUNT of va_final_assessments (active) GROUP BY
                 (va_finassess_by, va_narration_language).
      Denominator scope: CODED.
      Time frames: 7d, cumulative.
      Display: Heatmap table (coder × language matrix).

    D-LC-04 — Coder Output by Language:
      Same data as C-24, sliceable by coder, language, project, site.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({"heatmap": [], "per_coder": [], "total": 0})

    range_param = request.args.get("range", "cumulative")

    return jsonify(cached_kpi(f"coder_output:{range_param}", lambda: compute_coder_output(scope, range_param)))


@bp.get("/roster")
@role_required("data_manager", "admin")
def coder_roster():
    """KPI: D-LC-06 — Coder Roster.

    Definition: Per project, for each active coder: name, email,
                vacode_language list, total forms coded (cumulative),
                currently allocated count, active since date.
    Source: va_users JOIN va_user_access_grants JOIN va_final_assessments COUNT.
    Time frame: Cumulative.
    Note: Policy-only definition, exposed as data for the DM dashboard.
    """
    # Coders are listed only when their grant sits inside the DM's own scope
    # (owner decision 2026-10-03, digitva-4b3e): a site DM sees its own
    # pairs' coders, a unit DM its subtree's. Counts use the same scope.
    scope = dm_scope()

    if not scope:
        return jsonify({"coders": []})

    return jsonify(cached_kpi("coder_roster", lambda: compute_coder_roster(scope)))


@bp.get("/disagreement")
@role_required("data_manager", "admin")
def coder_reviewer_disagreement():
    """KPI: D-QG-09, kept at its old path; the WHO 2026 bucket comparison.

    Returns ``compute_dqg09`` (``reviewed``, ``disagreements``, ``rate`` as a
    fraction). Nothing in the dashboard reads this path.
    """
    from app.services.kpi.outcomes import compute_dqg09

    return jsonify(cached_kpi("outcomes:D-QG-09", lambda: compute_dqg09(dm_scope())))
