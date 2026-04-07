"""DM KPI — Language Gap & Distribution.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/language``

KPIs served:
  C-15  Language Gap Alert
  C-20  Language with Maximum Pendency
  D-LC-01  Submission Language Distribution
  D-LC-03  Language Gap Analysis
  D-LC-07  Forms with Missing/Unmapped Language

Sources:
  - va_submissions JOIN va_forms JOIN va_submission_workflow
  - va_user_access_grants JOIN va_users (unnest vacode_language)
  - map_language_aliases (for unmapped detection)
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_scope import cached_kpi, dm_site_ids, dm_project_site_pairs

bp = Blueprint("dm_kpi_language", __name__)
log = logging.getLogger(__name__)


# States that count as "pending" (waiting for or in coding)
_PENDING_STATES = (
    "ready_for_coding",
    "coding_in_progress",
    "coder_step1_saved",
)


@bp.get("/gap")
@role_required("data_manager")
def language_gap():
    """KPIs: C-15 (Language Gap Alert), C-20 (Language with Maximum Pendency),
    D-LC-03 (Language Gap Analysis).

    Numerator: COUNT of submissions WHERE workflow_state IN
      ('ready_for_coding', 'coding_in_progress', 'coder_step1_saved') AND
      va_narration_language has zero active coders with that language in their
      vacode_language array.
    Denominator scope: CODING-POOL (excludes consent_refused,
      not_codeable_by_data_manager).
    Time frame: Snapshot.
    Sources: va_submissions, va_forms, va_submission_workflow,
             va_user_access_grants, va_users.vacode_language.

    Returns: Per-language table with pending count, coders available,
    gap flag (bool), predicted days to clear.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"languages": [], "gap_languages": [], "bottleneck": None})

    def compute():
        # Step 1: Pending submissions grouped by language
        pending_by_lang = db.session.execute(
            sa.text("""
                SELECT s.va_narration_language, COUNT(*) AS pending_count
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                WHERE f.site_id = ANY(:site_ids)
                  AND w.workflow_state IN ('ready_for_coding', 'coding_in_progress', 'coder_step1_saved')
                  AND s.va_narration_language IS NOT NULL
                  AND s.va_narration_language != ''
                GROUP BY s.va_narration_language
                ORDER BY pending_count DESC
            """),
            {"site_ids": site_ids},
        ).mappings().all()

        # Step 2: Coders per language (DM-scoped)
        # Resolve project_ids from DM's site_ids
        pairs = dm_project_site_pairs()
        project_ids = sorted({pid for pid, _sid in pairs})

        coders_by_lang = db.session.execute(
            sa.text("""
                SELECT UNNEST(u.vacode_language) AS lang, COUNT(DISTINCT u.user_id) AS coder_count
                FROM va_users u
                JOIN va_user_access_grants g ON g.user_id = u.user_id
                WHERE g.role = 'coder'
                  AND g.grant_status = 'active'
                  AND g.project_id = ANY(:project_ids)
                GROUP BY lang
            """),
            {"project_ids": project_ids},
        ).mappings().all()

        coder_map = {r["lang"]: r["coder_count"] for r in coders_by_lang}

        # Step 3: Mean daily coding rate per language (last 7d)
        # (simplified: count coder_finalized events per language in last 7 days)
        from datetime import datetime, timedelta, timezone
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)

        daily_rate_by_lang = db.session.execute(
            sa.text("""
                SELECT s.va_narration_language,
                       COUNT(*)::FLOAT / 7.0 AS daily_rate
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND e.transition_id IN ('coder_finalized', 'recode_finalized')
                  AND e.event_created_at >= :cutoff
                  AND s.va_narration_language IS NOT NULL
                GROUP BY s.va_narration_language
            """),
            {"site_ids": site_ids, "cutoff": seven_days_ago},
        ).mappings().all()

        rate_map = {r["va_narration_language"]: round(float(r["daily_rate"]), 1) for r in daily_rate_by_lang}

        # Step 4: Assemble
        languages = []
        gap_languages = []
        for r in pending_by_lang:
            lang = r["va_narration_language"]
            pending = r["pending_count"]
            coders = coder_map.get(lang, 0)
            is_gap = coders == 0
            daily_rate = rate_map.get(lang, 0)

            predicted_days = None
            if daily_rate > 0:
                predicted_days = round(pending / daily_rate, 1)
            elif pending > 0:
                predicted_days = float("inf")

            entry = {
                "language": lang,
                "pending_count": pending,
                "coders_available": coders,
                "gap": is_gap,
                "daily_coding_rate": daily_rate,
                "predicted_days_to_clear": predicted_days,
            }
            languages.append(entry)
            if is_gap:
                gap_languages.append(entry)

        # C-20: bottleneck = language with max pendency
        bottleneck = languages[0] if languages else None

        return {
            "languages": languages,
            "gap_languages": gap_languages,
            "bottleneck": bottleneck,
        }

    return jsonify(cached_kpi("language_gap", compute))


@bp.get("/distribution")
@role_required("data_manager")
def language_distribution():
    """KPI: D-LC-01 — Submission Language Distribution.

    Numerator: COUNT grouped by va_narration_language.
    Denominator scope: CONSENT-VALID (excludes consent_refused).
    Where: va_narration_language IS NOT NULL.
    Time frame: Cumulative.
    Also reports: Trend over time (monthly).
    Source: va_submissions JOIN va_forms.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"distribution": [], "monthly": []})

    def compute():
        # Overall distribution
        dist = db.session.execute(
            sa.text("""
                SELECT s.va_narration_language, COUNT(*) AS count
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                WHERE f.site_id = ANY(:site_ids)
                  AND s.va_narration_language IS NOT NULL
                  AND s.va_narration_language != ''
                  AND (w.workflow_state IS NULL OR w.workflow_state != 'consent_refused')
                GROUP BY s.va_narration_language
                ORDER BY count DESC
            """),
            {"site_ids": site_ids},
        ).mappings().all()

        # Monthly trend
        monthly = db.session.execute(
            sa.text("""
                SELECT
                    TO_CHAR(s.va_created_at, 'YYYY-MM') AS month,
                    s.va_narration_language,
                    COUNT(*) AS count
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                WHERE f.site_id = ANY(:site_ids)
                  AND s.va_narration_language IS NOT NULL
                  AND s.va_narration_language != ''
                  AND (w.workflow_state IS NULL OR w.workflow_state != 'consent_refused')
                GROUP BY TO_CHAR(s.va_created_at, 'YYYY-MM'), s.va_narration_language
                ORDER BY month DESC, count DESC
            """),
            {"site_ids": site_ids},
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
@role_required("data_manager")
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
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"missing_count": 0, "unmapped_count": 0, "total_coding_pool": 0, "rate": 0.0})

    def compute():
        # Total CODING-POOL count
        total_pool = db.session.execute(
            sa.text("""
                SELECT COUNT(*) AS cnt
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                WHERE f.site_id = ANY(:site_ids)
                  AND w.workflow_state NOT IN ('consent_refused', 'not_codeable_by_data_manager')
            """),
            {"site_ids": site_ids},
        ).scalar() or 0

        # Missing (NULL or empty)
        missing = db.session.execute(
            sa.text("""
                SELECT COUNT(*) AS cnt
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                WHERE f.site_id = ANY(:site_ids)
                  AND w.workflow_state NOT IN ('consent_refused', 'not_codeable_by_data_manager')
                  AND (s.va_narration_language IS NULL OR s.va_narration_language = '')
            """),
            {"site_ids": site_ids},
        ).scalar() or 0

        # Unmapped (not in map_language_aliases)
        # Check if map_language_aliases table exists
        unmapped = 0
        try:
            unmapped = db.session.execute(
                sa.text("""
                    SELECT COUNT(*) AS cnt
                    FROM va_submissions s
                    JOIN va_forms f ON f.form_id = s.va_form_id
                    JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                    WHERE f.site_id = ANY(:site_ids)
                      AND w.workflow_state NOT IN ('consent_refused', 'not_codeable_by_data_manager')
                      AND s.va_narration_language IS NOT NULL
                      AND s.va_narration_language != ''
                      AND s.va_narration_language NOT IN (
                          SELECT alias FROM map_language_aliases
                      )
                """),
                {"site_ids": site_ids},
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
