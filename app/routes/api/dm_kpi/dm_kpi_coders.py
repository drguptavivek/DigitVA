"""DM KPI — Coder Stats.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/coders``

KPIs served:
  C-12  Coder Throughput
  C-21  Coder Utilization Rate
  C-24  Forms per Coder by Language (heatmap)
  D-LC-04  Coder Output by Language
  D-LC-06  Coder Roster
  D-QG-09  Coder-Reviewer Disagreement Rate

Sources:
  - va_final_assessments (coder output)
  - va_reviewer_final_assessments (reviewer output)
  - va_user_access_grants + va_users (coder pool)
  - va_allocations (utilization)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_scope import (
    cached_kpi,
    dm_project_site_pairs,
    dm_site_ids,
)

bp = Blueprint("dm_kpi_coders", __name__)
log = logging.getLogger(__name__)


@bp.get("/utilization")
@role_required("data_manager")
def coder_utilization():
    """KPI: C-21 — Coder Utilization Rate.

    Numerator: COUNT of coders with at least one active allocation
               (va_allocations where va_allocation_status = 'active').
    Denominator: COUNT of all active coders in DM's scope
                 (va_user_access_grants where role='coder', grant_status='active').
    Rate: N / D × 100.
    Time frame: Snapshot.
    Actionable: <70% → coders idle; >95% → coders saturated.
    """
    site_ids = dm_site_ids()
    pairs = dm_project_site_pairs()
    project_ids = sorted({pid for pid, _sid in pairs})

    if not project_ids:
        return jsonify({"active_count": 0, "total_coders": 0, "rate": 0.0})

    def compute():
        # Total active coders in DM's scope
        total_coders = db.session.execute(
            sa.text("""
                SELECT COUNT(DISTINCT g.user_id) AS cnt
                FROM va_user_access_grants g
                WHERE g.role = 'coder'
                  AND g.grant_status = 'active'
                  AND (
                      g.project_id = ANY(:project_ids)
                      OR g.project_id IS NULL
                  )
            """),
            {"project_ids": project_ids},
        ).scalar() or 0

        # Coders with active allocations in DM's scoped submissions
        active_coders = db.session.execute(
            sa.text("""
                SELECT COUNT(DISTINCT a.va_allocated_to) AS cnt
                FROM va_allocations a
                JOIN va_submissions s ON s.va_sid = a.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND a.va_allocation_status = 'active'
            """),
            {"site_ids": site_ids},
        ).scalar() or 0

        rate = round(active_coders / total_coders * 100, 1) if total_coders > 0 else 0.0

        return {
            "active_count": active_coders,
            "total_coders": total_coders,
            "rate": rate,
        }

    return jsonify(cached_kpi("coder_utilization", compute))


@bp.get("/output")
@role_required("data_manager")
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
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"heatmap": [], "per_coder": [], "total": 0})

    range_param = request.args.get("range", "cumulative")

    def compute():
        cutoff = None
        if range_param == "7d":
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        # Build WHERE clause for date range
        date_filter = ""
        params: dict = {"site_ids": site_ids}
        if cutoff:
            date_filter = "AND fa.va_finassess_createdat >= :cutoff"
            params["cutoff"] = cutoff

        # C-24 / D-LC-04: coder × language heatmap
        rows = db.session.execute(
            sa.text(f"""
                SELECT
                    fa.va_finassess_by,
                    u.user_name AS coder_name,
                    s.va_narration_language,
                    COUNT(*) AS count
                FROM va_final_assessments fa
                JOIN va_submissions s ON s.va_sid = fa.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                LEFT JOIN va_users u ON u.user_id = fa.va_finassess_by
                WHERE f.site_id = ANY(:site_ids)
                  AND fa.va_finassess_status = 'active'
                  {date_filter}
                GROUP BY fa.va_finassess_by, u.user_name, s.va_narration_language
                ORDER BY count DESC
            """),
            params,
        ).mappings().all()

        # C-12: per-coder throughput (total across languages)
        per_coder_map: dict[str, dict] = {}
        for r in rows:
            coder_id = str(r["va_finassess_by"])
            if coder_id not in per_coder_map:
                per_coder_map[coder_id] = {
                    "coder_id": coder_id,
                    "coder_name": r["coder_name"] or coder_id,
                    "total": 0,
                    "by_language": {},
                }
            per_coder_map[coder_id]["total"] += r["count"]
            lang = r["va_narration_language"] or "unknown"
            per_coder_map[coder_id]["by_language"][lang] = r["count"]

        total = sum(e["total"] for e in per_coder_map.values())

        return {
            "heatmap": [
                {
                    "coder_id": entry["coder_id"],
                    "coder_name": entry["coder_name"],
                    "language": lang,
                    "count": count,
                }
                for entry in per_coder_map.values()
                for lang, count in entry["by_language"].items()
            ],
            "per_coder": sorted(per_coder_map.values(), key=lambda x: x["total"], reverse=True),
            "total": total,
            "range": range_param,
        }

    return jsonify(cached_kpi(f"coder_output:{range_param}", compute))


@bp.get("/roster")
@role_required("data_manager")
def coder_roster():
    """KPI: D-LC-06 — Coder Roster.

    Definition: Per project, for each active coder: name, email,
                vacode_language list, total forms coded (cumulative),
                currently allocated count, active since date.
    Source: va_users JOIN va_user_access_grants JOIN va_final_assessments COUNT.
    Time frame: Cumulative.
    Note: Policy-only definition, exposed as data for the DM dashboard.
    """
    pairs = dm_project_site_pairs()
    project_ids = sorted({pid for pid, _sid in pairs})
    site_ids = dm_site_ids()

    if not project_ids:
        return jsonify({"coders": []})

    def compute():
        rows = db.session.execute(
            sa.text("""
                SELECT
                    u.user_id,
                    u.user_name,
                    u.user_email,
                    u.vacode_language,
                    g.project_id,
                    (
                        SELECT COUNT(*)
                        FROM va_final_assessments fa
                        JOIN va_submissions s2 ON s2.va_sid = fa.va_sid
                        JOIN va_forms f2 ON f2.form_id = s2.va_form_id
                        WHERE f2.site_id = ANY(:site_ids)
                          AND fa.va_finassess_by = u.user_id
                          AND fa.va_finassess_status = 'active'
                    ) AS total_coded,
                    (
                        SELECT COUNT(*)
                        FROM va_allocations a
                        WHERE a.va_allocated_to = u.user_id
                          AND a.va_allocation_status = 'active'
                    ) AS active_allocations,
                    MIN(g.created_at) AS active_since
                FROM va_users u
                JOIN va_user_access_grants g ON g.user_id = u.user_id
                WHERE g.role = 'coder'
                  AND g.grant_status = 'active'
                  AND (
                      g.project_id = ANY(:project_ids)
                      OR g.project_id IS NULL
                  )
                GROUP BY u.user_id, u.user_name, u.user_email, u.vacode_language, g.project_id
                ORDER BY u.user_name
            """),
            {"project_ids": project_ids, "site_ids": site_ids},
        ).mappings().all()

        return {
            "coders": [
                {
                    "user_id": str(r["user_id"]),
                    "name": r["user_name"],
                    "email": r["user_email"],
                    "languages": r["vacode_language"] or [],
                    "project_id": r["project_id"],
                    "total_coded": r["total_coded"] or 0,
                    "active_allocations": r["active_allocations"] or 0,
                    "active_since": r["active_since"].isoformat() if r["active_since"] else None,
                }
                for r in rows
            ]
        }

    return jsonify(cached_kpi("coder_roster", compute))


@bp.get("/disagreement")
@role_required("data_manager")
def coder_reviewer_disagreement():
    """KPI: D-QG-09 — Coder-Reviewer Disagreement Rate.

    Numerator: COUNT of submissions where va_reviewer_final_assessments
               exists AND va_final_assessments exists AND they have
               different va_conclusive_cod values.
    Denominator: COUNT of submissions with both coder final assessment
                 AND reviewer final assessment (active).
    Rate: N / D × 100.
    Source: va_final_assessments JOIN va_reviewer_final_assessments on va_sid.
    Time frame: Cumulative.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"total_reviewed": 0, "disagreements": 0, "rate": 0.0})

    def compute():
        row = db.session.execute(
            sa.text("""
                SELECT
                    COUNT(*) AS total_reviewed,
                    COUNT(*) FILTER (
                        WHERE fa.va_conclusive_cod IS DISTINCT FROM rf.va_conclusive_cod
                    ) AS disagreements
                FROM va_final_assessments fa
                JOIN va_reviewer_final_assessments rf ON rf.va_sid = fa.va_sid
                JOIN va_submissions s ON s.va_sid = fa.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND fa.va_finassess_status = 'active'
                  AND rf.va_rfinassess_status = 'active'
            """),
            {"site_ids": site_ids},
        ).mappings().first()

        total = row["total_reviewed"] or 0 if row else 0
        disagreements = row["disagreements"] or 0 if row else 0
        rate = round(disagreements / total * 100, 1) if total > 0 else 0.0

        return {
            "total_reviewed": total,
            "disagreements": disagreements,
            "rate": rate,
        }

    return jsonify(cached_kpi("coder_reviewer_disagreement", compute))
