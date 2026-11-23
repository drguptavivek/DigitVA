"""DM KPI — Language Gap & Distribution.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/language``

KPIs served:
  C-15  Language Gap Alert (ready pool; D-LC-03 as by=language)
  C-20  Language with Maximum Pendency (6 pending states)
  D-LC-01  Submission Language Distribution
  D-LC-07  Forms with Missing/Unmapped Language

Sources:
  - va_submissions JOIN va_forms JOIN va_submission_workflow
  - va_users.vacode_language via coders_covering_scope_sql (dm_kpi_coders)
  - map_language_aliases (for unmapped detection)

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
from app.services.kpi.language import (  # noqa: F401
    compute_c15,
    compute_c20,
    compute_language_distribution,
    compute_language_missing,
)

bp = Blueprint("dm_kpi_language", __name__)
log = logging.getLogger(__name__)


@bp.get("/gap")
@role_required("data_manager", "admin")
def language_gap():
    """KPI: C-15 (Language Gap Alert), D-LC-03 (Language Gap Analysis) as the
    per-language table. The ready pool only (``ready_for_coding``); C-20 moved
    to ``/pendency``.

    Numerator: COUNT of submissions in the ready pool whose language has no
      covering coder (``lower(trim())`` match; a coder with no languages covers
      any; coders who can code a case in the DM's subtree).
    Time frame: Snapshot.
    Returns: ``ready_pool``, ``gap_cases`` and per-language ``languages``
    (pending_count = ready cases, coders_available, gap flag, daily rate,
    predicted days), ``gap_languages``, ``bottleneck``.
    """
    return jsonify(cached_kpi("language_gap", lambda: compute_c15(dm_scope(), None, "language")))


@bp.get("/pendency")
@role_required("data_manager", "admin")
def language_pendency():
    """KPI: C-20 — Language with Maximum Pendency (6 pending states)."""
    return jsonify(cached_kpi("language_pendency", lambda: compute_c20(dm_scope(), None, "language")))


@bp.get("/distribution")
@role_required("data_manager", "admin")
def language_distribution():
    """KPI: D-LC-01 — Submission Language Distribution.

    Numerator: COUNT grouped by va_narration_language.
    Denominator scope: CONSENT-VALID (excludes consent_refused).
    Where: va_narration_language IS NOT NULL.
    Time frame: Cumulative.
    Also reports: Trend over time (monthly).
    Source: va_submissions JOIN va_forms.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({"distribution": [], "monthly": []})

    return jsonify(cached_kpi("language_distribution", lambda: compute_language_distribution(scope)))


@bp.get("/missing")
@role_required("data_manager", "admin")
def language_missing():
    """KPI: D-LC-07 — Forms with Missing/Unmapped Language.

    Numerator: COUNT WHERE va_narration_language IS NULL OR = ''
               OR NOT IN (SELECT alias FROM map_language_aliases).
    Denominator: COUNT of CODING-POOL.
    Rate: N / D × 100.
    Denominator scope: CODING-POOL (excludes consent_refused,
      not_codeable_by_data_manager).
    Time frame: Snapshot.
    Source: va_submissions JOIN va_forms.
    Actionable: These forms cannot be language-matched to coders.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({"missing_count": 0, "unmapped_count": 0, "total_coding_pool": 0, "rate": 0.0})

    return jsonify(cached_kpi("language_missing", lambda: compute_language_missing(scope)))
