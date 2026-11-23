"""DM KPI — Outcome, Equity and Coverage (digitva-r5s0 step 2, groups f and g).

Blueprint prefix: ``/api/v1/analytics/dm-kpi/outcomes``

KPIs served (docs/policy/kpis.md):
  O-UNK    Unknown Cause Share (``by=icd``: the ICD codes inside the section)
  D-QG-09  Coder-Reviewer Disagreement Rate, at the WHO 2026 bucket
  EQ-01    Female Share Against Peers
  EQ-02    Female-Male Final Cause Gap (plus the register half)
  AD-FCOD  Final Cause Coverage
  AD-COV   Reported-Death Interview Coverage (death-register projects only)

Sources:
  - va_submission_cod_snapshot_mv (WHO 2026 buckets of each final)
  - va_final_cod_authority (``area_dashboard_service._has_final_cod``)
  - va_death_register (``area_dashboard_service._case_count_columns``)

Every count is scoped by ``DmScope.sql()``, with retired submissions and
confirmed duplicates excluded; training is excluded when the scope is
resolved (``dm_scope`` drops the training project's grants). A rate is None
when its denominator is under ``PERCENT_MIN_WHOLE``. "Authoritative final"
means an authority row naming a final (``_has_final_cod``), never the
snapshot MV's latest-active fallback, so O-UNK's base is a subset of the
``_has_final_cod`` cases (AD-FCOD also drops the not-codeable states).

Peers (EQ-01 and the D-WF-02 bottleneck): the children of the viewer's grant
roots, never a unit above the grant (``peer_units_sql``).
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_scope import cached_kpi, dm_scope
from app.routes.api.request_helpers import error as api_error
from app.services.kpi.outcomes import (  # noqa: F401
    compute_adcov,
    compute_adfcod,
    compute_dqg09,
    compute_eq01,
    compute_eq02,
    compute_ounk,
)

bp = Blueprint("dm_kpi_outcomes", __name__)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Routes (thin wrappers; each KPI is its compute function)
# ---------------------------------------------------------------------------

def _serve(kpi_id: str, compute_fn):
    scope = dm_scope()
    by = request.args.get("by") or None
    try:
        return jsonify(cached_kpi(f"outcomes:{kpi_id}", lambda: compute_fn(scope, None, by)))
    except ValueError:
        return api_error(f"Unsupported 'by' for {kpi_id}.", "invalid_request", 400)


@bp.get("/unknown-cause")
@role_required("data_manager", "admin")
def unknown_cause():
    """KPI: O-UNK (``?by=icd`` for the codes inside the section)."""
    return _serve("O-UNK", compute_ounk)


@bp.get("/disagreement")
@role_required("data_manager", "admin")
def disagreement():
    """KPI: D-QG-09 at the WHO 2026 bucket."""
    return _serve("D-QG-09", compute_dqg09)


@bp.get("/female-share")
@role_required("data_manager", "admin")
def female_share():
    """KPI: EQ-01, per peer unit."""
    return _serve("EQ-01", compute_eq01)


@bp.get("/female-final-gap")
@role_required("data_manager", "admin")
def female_final_gap():
    """KPI: EQ-02."""
    return _serve("EQ-02", compute_eq02)


@bp.get("/final-cause-coverage")
@role_required("data_manager", "admin")
def final_cause_coverage():
    """KPI: AD-FCOD (``?by=sex``)."""
    return _serve("AD-FCOD", compute_adfcod)


@bp.get("/register-coverage")
@role_required("data_manager", "admin")
def register_coverage():
    """KPI: AD-COV; ``applicable: false`` outside death-register projects."""
    return _serve("AD-COV", compute_adcov)
