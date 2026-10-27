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
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from flask import Blueprint, jsonify

from app import db
from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_coders import coders_covering_scope_sql
from app.routes.api.dm_kpi.dm_kpi_scope import cached_kpi, dm_scope
from app.services.duplicate_exclusion import not_confirmed_duplicate_sql
from app.services.odk_retirement_service import IN_ODK_BIND, in_odk_sql
from app.services.workflow.definition import (
    CODER_READY_POOL_STATES_SQL,
    NOT_DEMO_EVENT_SQL,
    PENDING_STATES_SQL,
)

bp = Blueprint("dm_kpi_language", __name__)
log = logging.getLogger(__name__)

# Retired submissions are not counted (docs/policy/odk-retired-submissions.md).
_IN_ODK_SQL = in_odk_sql("s")
# Confirmed-duplicate web cases leave every count (app/services/duplicate_exclusion.py).
_NOT_DUPLICATE_SQL = not_confirmed_duplicate_sql("s.va_sid")


def _language_table(scope, states_sql: str) -> list[dict]:
    """Per narration language: cases in *states_sql*, covering coders, 7-day rate.

    Languages match on ``lower(trim())`` as allocation does; a covering coder
    with no languages covers any (``coders_covering_scope_sql``). Cases with no
    language are not listed (they are the "missing language" blocker). One query
    for the cases and coders, one for the rate; counts only, never who the
    coders are.
    """
    pool = db.session.execute(
        sa.text(f"""
            WITH cov AS ({coders_covering_scope_sql()}),
            pool AS (
                SELECT lower(trim(s.va_narration_language)) AS lang_key,
                       MIN(trim(s.va_narration_language)) AS language,
                       COUNT(*) AS pending_count
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND w.workflow_state IN {states_sql}
                  AND trim(COALESCE(s.va_narration_language, '')) <> ''
                GROUP BY 1
            )
            SELECT p.lang_key, p.language, p.pending_count,
                   (SELECT COUNT(*) FROM cov
                    WHERE cardinality(cov.languages) = 0
                       OR p.lang_key = ANY(cov.languages)) AS coders_available
            FROM pool p
            ORDER BY p.pending_count DESC, p.language
        """),
        {**IN_ODK_BIND, **scope.params},
    ).mappings().all()

    # Mean daily coding rate per language, last 7 days; demo sessions dropped.
    rates = db.session.execute(
        sa.text(f"""
            SELECT lower(trim(s.va_narration_language)) AS lang_key,
                   COUNT(*)::FLOAT / 7.0 AS daily_rate
            FROM va_submission_workflow_events e
            JOIN va_submissions s ON s.va_sid = e.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
              AND e.transition_id IN ('coder_finalized', 'recode_finalized')
              AND e.event_created_at >= :cutoff
              AND {NOT_DEMO_EVENT_SQL}
              AND s.va_narration_language IS NOT NULL
            GROUP BY 1
        """),
        {**IN_ODK_BIND, **scope.params, "cutoff": datetime.now(timezone.utc) - timedelta(days=7)},
    ).mappings().all()
    rate_map = {r["lang_key"]: round(float(r["daily_rate"]), 1) for r in rates}

    table = []
    for r in pool:
        daily_rate = rate_map.get(r["lang_key"], 0)
        pending = r["pending_count"]
        if daily_rate > 0:
            predicted_days = round(pending / daily_rate, 1)
        else:
            predicted_days = "infinite" if pending > 0 else None  # JSON-safe sentinel
        table.append({
            "language": r["language"],
            "pending_count": pending,
            "coders_available": r["coders_available"],
            "gap": r["coders_available"] == 0,
            "daily_coding_rate": daily_rate,
            "predicted_days_to_clear": predicted_days,
        })
    return table


def compute_c15(scope, period=None, by: str | None = None) -> dict:
    """C-15 Language Gap Alert, with D-LC-03 as ``by="language"``.

    Cases in the ready pool (``ready_for_coding``) whose language has zero
    covering coders. Snapshot, so *period* is ignored. Always returns
    ``ready_pool`` and ``gap_cases``; ``by="language"`` adds ``languages``
    (every ready-pool language), ``gap_languages`` and ``bottleneck`` (the
    language with the most ready cases).
    """
    if by not in (None, "language"):
        raise ValueError(f"C-15 has no by={by!r}")
    if not scope:
        return {"ready_pool": 0, "gap_cases": 0, "languages": [], "gap_languages": [], "bottleneck": None}
    table = _language_table(scope, CODER_READY_POOL_STATES_SQL)
    gaps = [entry for entry in table if entry["gap"]]
    result = {
        "ready_pool": sum(entry["pending_count"] for entry in table),
        "gap_cases": sum(entry["pending_count"] for entry in gaps),
    }
    if by is None:
        return result
    return {
        **result,
        "by": "language",
        "languages": table,
        "gap_languages": gaps,
        "bottleneck": table[0] if table else None,
    }


def compute_c20(scope, period=None, by: str | None = None) -> dict:
    """C-20 Language with Maximum Pendency: the 6 pending states by language,
    with covering coders, 7-day rate and predicted days. ``bottleneck`` is the
    top row. Registered, not core; snapshot, so *period* is ignored."""
    if by not in (None, "language"):
        raise ValueError(f"C-20 has no by={by!r}")
    if not scope:
        return {"languages": [], "gap_languages": [], "bottleneck": None}
    table = _language_table(scope, PENDING_STATES_SQL)
    return {
        "languages": table,
        "gap_languages": [entry for entry in table if entry["gap"]],
        "bottleneck": table[0] if table else None,
    }


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

    def compute():
        # Overall distribution
        dist = db.session.execute(
            sa.text(f"""
                SELECT s.va_narration_language, COUNT(*) AS count
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND s.va_narration_language IS NOT NULL
                  AND s.va_narration_language != ''
                  AND (w.workflow_state IS NULL OR w.workflow_state != 'consent_refused')
                GROUP BY s.va_narration_language
                ORDER BY count DESC
            """),
            {**IN_ODK_BIND, **scope.params},
        ).mappings().all()

        # Monthly trend
        monthly = db.session.execute(
            sa.text(f"""
                SELECT
                    TO_CHAR(s.va_created_at, 'YYYY-MM') AS month,
                    s.va_narration_language,
                    COUNT(*) AS count
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND s.va_narration_language IS NOT NULL
                  AND s.va_narration_language != ''
                  AND (w.workflow_state IS NULL OR w.workflow_state != 'consent_refused')
                GROUP BY TO_CHAR(s.va_created_at, 'YYYY-MM'), s.va_narration_language
                ORDER BY month DESC, count DESC
            """),
            {**IN_ODK_BIND, **scope.params},
        ).mappings().all()

        return {
            "distribution": [
                {"language": r["va_narration_language"], "count": r["count"]}
                for r in dist
            ],
            "monthly": [
                {
                    "month": r["month"],
                    "language": r["va_narration_language"],
                    "count": r["count"],
                }
                for r in monthly
            ],
        }

    return jsonify(cached_kpi("language_distribution", compute))


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

    def compute():
        # Total CODING-POOL count
        total_pool = db.session.execute(
            sa.text(f"""
                SELECT COUNT(*) AS cnt
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND w.workflow_state NOT IN ('consent_refused', 'not_codeable_by_data_manager')
            """),
            {**IN_ODK_BIND, **scope.params},
        ).scalar() or 0

        # Missing (NULL or empty)
        missing = db.session.execute(
            sa.text(f"""
                SELECT COUNT(*) AS cnt
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND w.workflow_state NOT IN ('consent_refused', 'not_codeable_by_data_manager')
                  AND (s.va_narration_language IS NULL OR s.va_narration_language = '')
            """),
            {**IN_ODK_BIND, **scope.params},
        ).scalar() or 0

        # Unmapped (not in map_language_aliases)
        # Check if map_language_aliases table exists
        unmapped = 0
        try:
            unmapped = db.session.execute(
                sa.text(f"""
                    SELECT COUNT(*) AS cnt
                    FROM va_submissions s
                    JOIN va_forms f ON f.form_id = s.va_form_id
                    JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                    WHERE {scope.sql()}
                      AND {_IN_ODK_SQL}
                      AND {_NOT_DUPLICATE_SQL}
                      AND w.workflow_state NOT IN ('consent_refused', 'not_codeable_by_data_manager')
                      AND s.va_narration_language IS NOT NULL
                      AND s.va_narration_language != ''
                      AND s.va_narration_language NOT IN (
                          SELECT alias FROM map_language_aliases
                      )
                """),
                {**IN_ODK_BIND, **scope.params},
            ).scalar() or 0
        except Exception:
            log.warning("map_language_aliases table not found; skipping unmapped check")

        total_missing = missing + unmapped
        rate = round(total_missing / total_pool * 100, 1) if total_pool > 0 else 0.0

        return {
            "missing_count": missing,
            "unmapped_count": unmapped,
            "total_missing_unmapped": total_missing,
            "total_coding_pool": total_pool,
            "rate": rate,
        }

    return jsonify(cached_kpi("language_missing", compute))
