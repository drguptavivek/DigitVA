"""DM KPI — Exclusions & Blocked Forms.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/exclusions``

KPIs served:
  C-05  % Not Codeable (Overall); D-QG-01..05 are its by=actor / by=reason views
  C-06  Not Analysable Rate
  C-23  Blocked Forms Alert (Composite)
  D-QG-06  ODK Has Issues Count
  D-QG-07  NQA Completion Rate
  D-QG-08  Social Autopsy Completion Rate

Sources:
  - va_submission_workflow (current states for rates)
  - va_coder_review (reason breakdowns)
  - va_data_manager_review (reason breakdowns)
  - va_reviewer_final_assessments (NQA/SA)
  - va_project_master (feature flags)

Submissions retired from ODK are excluded from every count, list,
grouping and average below (docs/policy/odk-retired-submissions.md).
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_scope import cached_kpi, dm_scope
from app.routes.api.request_helpers import error as api_error
from app.services.kpi.exclusions import (  # noqa: F401
    compute_c05,
    compute_c06,
    compute_c23,
    compute_exclusion_breakdown,
    compute_exclusion_rates,
    compute_nqa_sa_rates,
    compute_odk_issues,
)

bp = Blueprint("dm_kpi_exclusions", __name__)
log = logging.getLogger(__name__)


def _by_param(allowed):
    """The ``?by=`` value when allowed (or absent), else a 400 response."""
    by = request.args.get("by") or None
    if by in (None, *allowed):
        return by, None
    return by, api_error(f"Unsupported 'by'; use one of {', '.join(allowed)}.", status_code=400)


@bp.get("/rates")
@role_required("data_manager", "admin")
def exclusion_rates():
    """KPIs: C-05 (% Not Codeable), C-06 (Not Analysable Rate), with D-QG-01
    (coder share) and D-QG-02 (DM share) as ``coder_not_codeable`` /
    ``dm_not_codeable``. The legacy response shape, served from
    ``compute_c05`` / ``compute_c06``.

    C-05: COUNT of not_codeable_by_coder + not_codeable_by_data_manager over
      ALL-SYNCED. D-QG-01: coder share over the CODING-POOL. D-QG-02: DM share
      over ALL-SYNCED.
    C-06: COUNT of consent_refused over ALL-SYNCED, split in
      ``not_analysable.by_reason``; the ``consent_refused`` key is kept for
      existing readers.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({})

    return jsonify(cached_kpi("exclusion_rates", lambda: compute_exclusion_rates(scope)))


@bp.get("/not-codeable")
@role_required("data_manager", "admin")
def not_codeable():
    """KPI: C-05, ``?by=actor`` (D-QG-03) or ``?by=reason`` (D-QG-04/05)."""
    by, bad = _by_param(("actor", "reason"))
    if bad:
        return bad
    scope = dm_scope()
    return jsonify(cached_kpi("not_codeable", lambda: compute_c05(scope, None, by)))


@bp.get("/not-analysable")
@role_required("data_manager", "admin")
def not_analysable_rate():
    """KPI: C-06, with ``by_reason`` (``?by=reason`` is the same split)."""
    by, bad = _by_param(("reason",))
    if bad:
        return bad
    scope = dm_scope()
    return jsonify(cached_kpi("not_analysable", lambda: compute_c06(scope, None, by)))


@bp.get("/breakdown")
@role_required("data_manager", "admin")
def exclusion_breakdown():
    """KPIs: D-QG-04 (Coder Not-Codeable Reason Breakdown), D-QG-05 (DM
    Not-Codeable Reason Breakdown), D-QG-03 (Exclusions by Actor). The legacy
    response shape, a thin wrapper over ``compute_c05(by="reason" / "actor")``.

    D-QG-04: active ``va_coder_review`` rows by ``va_creview_reason``.
    D-QG-05: active ``va_data_manager_review`` rows by ``va_dmreview_reason``.
    D-QG-03: COUNT by actor (DM, coder, screening rejected). Cumulative.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({"coder_reasons": [], "dm_reasons": [], "by_actor": {}})

    return jsonify(cached_kpi("exclusion_breakdown", lambda: compute_exclusion_breakdown(scope)))


@bp.get("/blocked")
@role_required("data_manager", "admin")
def blocked_forms():
    """KPI: C-23 — Blocked Forms Alert (Composite); ``?by=unit`` for the unit slice.

    Pending cases that cannot reach a coder, plus the two upstream rows; one
    row per reason with count, age, fixed owner and intake source. See
    ``compute_c23`` and docs/policy/kpis.md.
    """
    by, bad = _by_param(("reason", "unit"))
    if bad:
        return bad
    scope = dm_scope()
    return jsonify(cached_kpi("blocked_forms", lambda: compute_c23(scope, None, by)))


@bp.get("/nqa-sa")
@role_required("data_manager", "admin")
def nqa_sa_rates():
    """KPIs: D-QG-07 (NQA Completion Rate), D-QG-08 (Social Autopsy Completion Rate).

    D-QG-07 — NQA Completion Rate:
      Numerator: COUNT of submissions with at least one active
                 va_narrative_assessments row.
      Denominator: COUNT of CODED submissions WHERE project
                   narrative_qa_enabled = true.
      Rate: N / D × 100.
      Inclusions: Only projects where narrative_qa_enabled = true.
      Exclusions: Projects where narrative_qa_enabled = false.
      Time frame: Cumulative.

    D-QG-08 — Social Autopsy Completion Rate:
      Same pattern as D-QG-07 but for va_social_autopsy_analyses, in
      projects with effective coder Social Autopsy
      (social_autopsy_collect_enabled and social_autopsy_enabled).
    """
    scope = dm_scope()
    if not scope:
        return jsonify({"nqa": {}, "social_autopsy": {}})

    return jsonify(cached_kpi("nqa_sa_rates", lambda: compute_nqa_sa_rates(scope)))


@bp.get("/odk-issues")
@role_required("data_manager", "admin")
def odk_issues():
    """KPI: D-QG-06 — ODK Has Issues Count.

    Numerator: COUNT WHERE va_odk_reviewstate = 'hasIssues'.
    Denominator: ALL-SYNCED.
    Time frame: Cumulative.
    Source: va_submissions JOIN va_forms.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({"count": 0, "total": 0, "rate": 0.0})

    return jsonify(cached_kpi("odk_issues", lambda: compute_odk_issues(scope)))
