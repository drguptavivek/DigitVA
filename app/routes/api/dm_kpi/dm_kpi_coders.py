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
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from flask import Blueprint, jsonify, request

from app import db
from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_scope import (
    GRANT_PROJECT_JOINS,
    GRANT_PROJECT_SQL,
    DmScope,
    cached_kpi,
    dm_scope,
)
from app.routes.api.request_helpers import error as api_error
from app.services.duplicate_exclusion import not_confirmed_duplicate_sql
from app.services.odk_retirement_service import IN_ODK_BIND, in_odk_sql

bp = Blueprint("dm_kpi_coders", __name__)
log = logging.getLogger(__name__)

# Retired submissions are not counted (docs/policy/odk-retired-submissions.md).
_IN_ODK_SQL = in_odk_sql("s")
# Confirmed-duplicate web cases leave every count (app/services/duplicate_exclusion.py).
_NOT_DUPLICATE_SQL = not_confirmed_duplicate_sql("s.va_sid")
_IN_ODK_SQL_S2 = in_odk_sql("s2")
_NOT_DUPLICATE_SQL_S2 = not_confirmed_duplicate_sql("s2.va_sid")


# A coder grant ``g`` with its project, unit and the project's coding scope
# level resolved (aliases gps, gou, gpm, gsl, gul). Only grants on active
# projects count, as authz's grant relation does.
CODING_GRANT_JOINS = f"""
    {GRANT_PROJECT_JOINS}
    JOIN va_project_master gpm
      ON gpm.project_id = {GRANT_PROJECT_SQL} AND gpm.project_status = 'active'
    LEFT JOIN mas_org_level gsl ON gsl.org_level_id = gpm.coding_scope_level_id
    LEFT JOIN mas_org_level gul ON gul.org_level_id = gou.org_level_id
"""
# The coding scope rule (authz ``ResolvedGrants.codes``): with a scope level
# set, a project or pair grant (above any level) codes only under
# ``code_any``; a unit grant codes at or below the level, or under ``code_any``.
CODING_GRANT_CODES_SQL = (
    "(gsl.org_level_id IS NULL OR gpm.above_scope_coding_mode = 'code_any'"
    " OR (g.scope_type = 'org_unit' AND gul.depth >= gsl.depth))"
)


def coders_covering_scope_sql() -> str:
    """SELECT of the coders who can code at least one case in the DM's subtree
    (coder availability, docs/policy/kpis.md and access-control-model.md).

    One row per coder: ``user_id`` and ``languages``, their ``vacode_language``
    lower-cased and trimmed; an empty array means the coder covers any language
    (as allocation does). Deactivated users are skipped, as they cannot sign in.
    A grant counts when it codes (``CODING_GRANT_CODES_SQL``)
    and is a project grant on a project of the scope, a pair grant on a pair of
    the scope (or, for a unit DM, on a pair holding a case of its subtree), or a
    unit grant that is an ancestor or descendant of a DM unit or sits in a
    project the DM holds by pair. Binds ``DmScope.params`` only. Names no one by
    itself: callers aggregate. The named roster (D-LC-06) keeps
    ``grant_in_scope_sql`` and its stricter rule.

    ponytail: the pair-grant probe for a unit DM ignores retired and duplicate
    cases; an existence test only, not a count.
    """
    unit_projects = (
        "SELECT cov_u.project_id FROM mas_org_unit cov_u"
        " WHERE cov_u.org_unit_id = ANY(CAST(:unit_ids AS uuid[]))"
    )
    return f"""
        SELECT u.user_id,
               ARRAY(SELECT lower(trim(l)) FROM unnest(u.vacode_language) l
                     WHERE trim(l) <> '') AS languages
        FROM va_users u
        WHERE u.user_status = 'active'
          AND u.user_id IN (
            SELECT g.user_id
            FROM va_user_access_grants g
            {CODING_GRANT_JOINS}
            WHERE g.role = 'coder'
              AND g.grant_status = 'active'
              AND {CODING_GRANT_CODES_SQL}
              AND (
                (g.scope_type = 'project'
                 AND (g.project_id = ANY(CAST(:pair_project_ids AS text[]))
                      OR g.project_id IN ({unit_projects})))
                OR (g.scope_type = 'project_site' AND gps.project_site_id IS NOT NULL
                    AND ((gps.project_id, gps.site_id) IN (SELECT * FROM unnest(
                              CAST(:pair_project_ids AS text[]),
                              CAST(:pair_site_ids AS text[])))
                         OR EXISTS (
                              SELECT 1 FROM va_submissions cov_s
                              JOIN va_forms cov_f ON cov_f.form_id = cov_s.va_form_id
                              WHERE cov_f.project_id = gps.project_id
                                AND cov_f.site_id = gps.site_id
                                AND cov_s.org_unit_id IN ({DmScope.subtree_sql()}))))
                OR (g.scope_type = 'org_unit' AND gou.org_unit_id IS NOT NULL
                    AND (gou.project_id = ANY(CAST(:pair_project_ids AS text[]))
                         OR EXISTS (
                              SELECT 1 FROM mas_org_unit cov_a
                              WHERE cov_a.org_unit_id = ANY(CAST(:unit_ids AS uuid[]))
                                AND cov_a.project_id = gou.project_id
                                AND (gou.path <@ cov_a.path OR gou.path @> cov_a.path))))
              )
        )
    """


def compute_c21(scope: DmScope, period=None, by: str | None = None) -> dict:
    """C-21 Coder Utilization, with D-LC-02 (coder language pool) as ``by="language"``.

    Numerator: covering coders with an active allocation on a case of the
    scope. Denominator: covering coders (``coders_covering_scope_sql``).
    Snapshot, so *period* is ignored. ``by="language"`` adds ``rows``: per
    language the coders who cover it (explicit plus any-language coders) and how
    many of them are active; counts only, names stay in D-LC-06.
    """
    if by not in (None, "language"):
        raise ValueError(f"C-21 has no by={by!r}")
    if not scope:
        result = {"active_count": 0, "total_coders": 0, "rate": 0.0}
        return {**result, "by": by, "rows": []} if by else result

    cte = f"""
        WITH cov AS ({coders_covering_scope_sql()}),
        busy AS (
            SELECT DISTINCT a.va_allocated_to AS user_id
            FROM va_allocations a
            JOIN va_submissions s ON s.va_sid = a.va_sid
            JOIN va_forms f ON f.form_id = s.va_form_id
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
              AND a.va_allocation_status = 'active'
              AND a.va_allocated_to IN (SELECT user_id FROM cov)
        )
    """
    params = {**IN_ODK_BIND, **scope.params}
    row = db.session.execute(
        sa.text(cte + """
            SELECT (SELECT COUNT(*) FROM cov) AS total,
                   (SELECT COUNT(*) FROM busy) AS active
        """),
        params,
    ).mappings().first()
    total, active = row["total"] or 0, row["active"] or 0
    result = {
        "active_count": active,
        "total_coders": total,
        "rate": round(active / total * 100, 1) if total > 0 else 0.0,
    }
    if by is None:
        return result

    rows = db.session.execute(
        sa.text(cte + """
            , langs AS (SELECT DISTINCT unnest(languages) AS lang FROM cov)
            SELECT l.lang AS language,
                   COUNT(c.user_id) AS coders,
                   COUNT(c.user_id) FILTER (WHERE c.user_id IN (SELECT user_id FROM busy))
                       AS active_coders
            FROM langs l
            JOIN cov c ON cardinality(c.languages) = 0 OR l.lang = ANY(c.languages)
            GROUP BY l.lang
            ORDER BY coders DESC, l.lang
        """),
        params,
    ).mappings().all()
    return {
        **result,
        "by": "language",
        "rows": [
            {"language": r["language"], "coders": r["coders"], "active_coders": r["active_coders"]}
            for r in rows
        ],
    }


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

    def compute():
        cutoff = None
        if range_param == "7d":
            cutoff = datetime.now(timezone.utc) - timedelta(days=7)

        # Build WHERE clause for date range
        date_filter = ""
        params: dict = {**IN_ODK_BIND, **scope.params}
        if cutoff:
            date_filter = "AND fa.va_finassess_createdat >= :cutoff"
            params["cutoff"] = cutoff

        # C-24 / D-LC-04: coder × language heatmap
        rows = db.session.execute(
            sa.text(f"""
                SELECT
                    fa.va_finassess_by,
                    u.name AS coder_name,
                    s.va_narration_language,
                    COUNT(*) AS count
                FROM va_final_assessments fa
                JOIN va_submissions s ON s.va_sid = fa.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                LEFT JOIN va_users u ON u.user_id = fa.va_finassess_by
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND fa.va_finassess_status = 'active'
                  {date_filter}
                GROUP BY fa.va_finassess_by, u.name, s.va_narration_language
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

    def compute():
        rows = db.session.execute(
            sa.text(f"""
                WITH roster AS (
                    SELECT
                        g.user_id,
                        {GRANT_PROJECT_SQL} AS project_id,
                        MIN(g.grant_created_at) AS active_since
                    FROM va_user_access_grants g
                    {GRANT_PROJECT_JOINS}
                    WHERE g.role = 'coder'
                      AND g.grant_status = 'active'
                      AND {scope.grant_in_scope_sql("g")}
                    GROUP BY g.user_id, {GRANT_PROJECT_SQL}
                )
                SELECT
                    u.user_id,
                    u.name,
                    u.email,
                    u.vacode_language,
                    r.project_id,
                    (
                        SELECT COUNT(*)
                        FROM va_final_assessments fa
                        JOIN va_submissions s2 ON s2.va_sid = fa.va_sid
                        JOIN va_forms f2 ON f2.form_id = s2.va_form_id
                        WHERE {scope.sql("f2", "s2")}
                          AND {_IN_ODK_SQL_S2}
                          AND {_NOT_DUPLICATE_SQL_S2}
                          AND fa.va_finassess_by = u.user_id
                          AND fa.va_finassess_status = 'active'
                    ) AS total_coded,
                    (
                        SELECT COUNT(*)
                        FROM va_allocations a
                        JOIN va_submissions s3 ON s3.va_sid = a.va_sid
                        JOIN va_forms f3 ON f3.form_id = s3.va_form_id
                        WHERE a.va_allocated_to = u.user_id
                          AND a.va_allocation_status = 'active'
                          AND f3.project_id = r.project_id
                          AND {scope.sql("f3", "s3")}
                    ) AS active_allocations,
                    r.active_since
                FROM roster r
                JOIN va_users u ON u.user_id = r.user_id
                ORDER BY u.name
            """),
            {**IN_ODK_BIND, **scope.params},
        ).mappings().all()

        return {
            "coders": [
                {
                    "user_id": str(r["user_id"]),
                    "name": r["name"],
                    "email": r["email"],
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
@role_required("data_manager", "admin")
def coder_reviewer_disagreement():
    """KPI: D-QG-09, kept at its old path; the WHO 2026 bucket comparison.

    Returns ``compute_dqg09`` (``reviewed``, ``disagreements``, ``rate`` as a
    fraction). Nothing in the dashboard reads this path.
    """
    from app.routes.api.dm_kpi.dm_kpi_outcomes import compute_dqg09

    return jsonify(cached_kpi("outcomes:D-QG-09", lambda: compute_dqg09(dm_scope())))
