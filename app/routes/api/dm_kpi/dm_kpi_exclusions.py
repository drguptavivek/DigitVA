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

import sqlalchemy as sa
from flask import Blueprint, jsonify, request

from app import db
from app.decorators import role_required
from app.services.duplicate_exclusion import not_confirmed_duplicate_sql
from app.services import not_analysable
from app.services.odk_retirement_service import IN_ODK_BIND, in_odk_sql
from app.services.workflow.definition import CODER_READY_POOL_STATES_SQL, PENDING_STATES_SQL
from app.routes.api.dm_kpi.dm_kpi_coders import (
    CODING_GRANT_CODES_SQL,
    CODING_GRANT_JOINS,
    coders_covering_scope_sql,
)
from app.routes.api.dm_kpi.dm_kpi_scope import cached_kpi, dm_scope
from app.routes.api.request_helpers import error as api_error
from app.services.workflow.revision_request_sql import (
    SENT_BACK_FOR_REVISION,
    odk_changed_sql,
    sent_back_sql,
)

bp = Blueprint("dm_kpi_exclusions", __name__)
log = logging.getLogger(__name__)

# Retired submissions are not counted (docs/policy/odk-retired-submissions.md).
_IN_ODK_SQL = in_odk_sql("s")
# Confirmed-duplicate web cases leave every count (app/services/duplicate_exclusion.py).
_NOT_DUPLICATE_SQL = not_confirmed_duplicate_sql("s.va_sid")


def _state_counts(scope) -> dict:
    """ALL-SYNCED and the state counts C-05 and C-06 share, in one scan."""
    return db.session.execute(
        sa.text(f"""
            SELECT
                COUNT(*) AS all_synced,
                COUNT(*) FILTER (WHERE w.workflow_state = 'consent_refused')
                    AS consent_refused,
                COUNT(*) FILTER (WHERE w.workflow_state = 'not_codeable_by_data_manager')
                    AS dm_not_codeable,
                COUNT(*) FILTER (WHERE w.workflow_state = 'not_codeable_by_coder')
                    AS coder_not_codeable,
                COUNT(*) FILTER (WHERE w.workflow_state NOT IN (
                    'consent_refused', 'not_codeable_by_data_manager'
                )) AS coding_pool
            FROM va_submissions s
            JOIN va_forms f ON f.form_id = s.va_form_id
            LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
        """),
        {**IN_ODK_BIND, **scope.params},
    ).mappings().first()


def _pct(n, d):
    return round(n / d * 100, 1) if d > 0 else 0.0


def compute_c05(scope, period=None, by: str | None = None, *, counts=None) -> dict:
    """C-05 % Not Codeable, with D-QG-01 to 05 folded in as views.

    ``by=None``: the overall count and rate over ALL-SYNCED, with the coder
    share (rate over the CODING-POOL, D-QG-01) and the DM share (D-QG-02) as
    ``coder`` and ``dm``. ``by="actor"`` (D-QG-03): active review rows by actor
    -- data manager, coder -- and workflow events ``screening_rejected``.
    ``by="reason"`` (D-QG-04/05): active review rows by reason, for the coder
    and the data manager. Cumulative, so *period* is ignored. *counts* lets a
    caller that already ran ``_state_counts`` share it.
    """
    if by not in (None, "actor", "reason"):
        raise ValueError(f"C-05 has no by={by!r}")
    if not scope:
        return {"all_synced": 0, "count": 0, "rate": 0.0, "coding_pool": 0,
                "coder": {"count": 0, "rate": 0.0}, "dm": {"count": 0, "rate": 0.0}}\
            if by is None else {"by": by, "rows": []}

    params = {**IN_ODK_BIND, **scope.params}
    if by == "actor":
        row = db.session.execute(
            sa.text(f"""
                SELECT
                    (SELECT COUNT(*) FROM va_data_manager_review dr
                     JOIN va_submissions s ON s.va_sid = dr.va_sid
                     JOIN va_forms f ON f.form_id = s.va_form_id
                     WHERE {scope.sql()} AND dr.va_dmreview_status = 'active'
                       AND {_IN_ODK_SQL}
                       AND {_NOT_DUPLICATE_SQL}
                    ) AS data_manager,
                    (SELECT COUNT(*) FROM va_coder_review cr
                     JOIN va_submissions s ON s.va_sid = cr.va_sid
                     JOIN va_forms f ON f.form_id = s.va_form_id
                     WHERE {scope.sql()} AND cr.va_creview_status = 'active'
                       AND {_IN_ODK_SQL}
                       AND {_NOT_DUPLICATE_SQL}
                    ) AS coder,
                    (SELECT COUNT(*) FROM va_submission_workflow_events e
                     JOIN va_submissions s ON s.va_sid = e.va_sid
                     JOIN va_forms f ON f.form_id = s.va_form_id
                     WHERE {scope.sql()}
                       AND {_IN_ODK_SQL}
                       AND {_NOT_DUPLICATE_SQL}
                       AND e.transition_id = 'screening_rejected') AS screening_rejected
            """),
            params,
        ).mappings().first()
        return {
            "by": "actor",
            "rows": [
                {"actor": actor, "count": row[actor] or 0}
                for actor in ("data_manager", "coder", "screening_rejected")
            ],
        }

    if by == "reason":
        rows = db.session.execute(
            sa.text(f"""
                SELECT 'coder' AS actor, cr.va_creview_reason AS reason, COUNT(*) AS count
                FROM va_coder_review cr
                JOIN va_submissions s ON s.va_sid = cr.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND cr.va_creview_status = 'active'
                GROUP BY cr.va_creview_reason
                UNION ALL
                SELECT 'data_manager', dr.va_dmreview_reason, COUNT(*)
                FROM va_data_manager_review dr
                JOIN va_submissions s ON s.va_sid = dr.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
                  AND dr.va_dmreview_status = 'active'
                GROUP BY dr.va_dmreview_reason
                ORDER BY count DESC
            """),
            params,
        ).mappings().all()
        return {
            "by": "reason",
            "rows": [{"actor": r["actor"], "reason": r["reason"], "count": r["count"]} for r in rows],
        }

    row = counts or _state_counts(scope)
    all_synced = row["all_synced"] or 0
    dm_nc = row["dm_not_codeable"] or 0
    coder_nc = row["coder_not_codeable"] or 0
    coding_pool = row["coding_pool"] or 0
    return {
        "all_synced": all_synced,
        "count": dm_nc + coder_nc,
        "rate": _pct(dm_nc + coder_nc, all_synced),
        "coding_pool": coding_pool,
        "coder": {"count": coder_nc, "rate": _pct(coder_nc, coding_pool)},
        "dm": {"count": dm_nc, "rate": _pct(dm_nc, all_synced)},
    }


def compute_c06(scope, period=None, by: str | None = None, *, counts=None) -> dict:
    """C-06 Not Analysable Rate: ``consent_refused`` over ALL-SYNCED, with
    ``by_reason`` (refused, respondent unavailable, partially completed) always
    present; ``by="reason"`` is the same split. Snapshot, so *period* is ignored.
    """
    if by not in (None, "reason"):
        raise ValueError(f"C-06 has no by={by!r}")
    if not scope:
        return {"all_synced": 0, "count": 0, "rate": 0.0, "by_reason": not_analysable.by_reason([])}
    row = counts or _state_counts(scope)
    reason_rows = db.session.execute(
        sa.text(f"""
            SELECT {not_analysable.REASON_SQL} AS reason, COUNT(*) AS cnt
            FROM va_submissions s
            JOIN va_forms f ON f.form_id = s.va_form_id
            JOIN va_submission_workflow w ON w.va_sid = s.va_sid
            {not_analysable.PAYLOAD_JOIN_SQL}
            WHERE {scope.sql()}
              AND w.workflow_state = 'consent_refused'
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
            GROUP BY 1
        """),
        {**IN_ODK_BIND, **scope.params},
    ).all()
    all_synced = row["all_synced"] or 0
    consent = row["consent_refused"] or 0
    return {
        "all_synced": all_synced,
        "count": consent,
        "rate": _pct(consent, all_synced),
        "by_reason": not_analysable.by_reason(reason_rows),
    }


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

    def compute():
        counts = _state_counts(scope)
        c05 = compute_c05(scope, counts=counts)
        c06 = compute_c06(scope, counts=counts)
        return {
            "all_synced": c05["all_synced"],
            "consent_refused": {"count": c06["count"], "rate": c06["rate"]},
            "not_analysable": {
                "count": c06["count"], "rate": c06["rate"], "by_reason": c06["by_reason"],
            },
            "not_codeable_overall": {"count": c05["count"], "rate": c05["rate"]},
            "coder_not_codeable": c05["coder"],
            "dm_not_codeable": c05["dm"],
            "coding_pool": c05["coding_pool"],
        }

    return jsonify(cached_kpi("exclusion_rates", compute))


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

    def compute():
        reasons = compute_c05(scope, None, "reason")["rows"]
        actors = compute_c05(scope, None, "actor")["rows"]
        return {
            "coder_reasons": [
                {"reason": r["reason"], "count": r["count"]} for r in reasons if r["actor"] == "coder"
            ],
            "dm_reasons": [
                {"reason": r["reason"], "count": r["count"]} for r in reasons if r["actor"] == "data_manager"
            ],
            "by_actor": {r["actor"]: r["count"] for r in actors},
        }

    return jsonify(cached_kpi("exclusion_breakdown", compute))


# C-23 blocker rows: key, label, DM action, fixed owner (docs/policy/kpis.md),
# and the per-case boolean they count (columns of the ``cases`` CTE below).
# Every row except the two upstream ones is limited to the 6 pending states.
_BLOCKERS = (
    ("screening_pending", "Awaiting DM screening", "Pass or reject screening",
     "data manager"),
    ("attachment_sync_pending", "Attachments not synced", "Trigger attachment sync",
     "data manager, or admin when the queue is down"),
    ("smartva_pending", "SmartVA not run", "Check SmartVA queue",
     "data manager, or admin when the queue is down"),
    ("finalized_upstream_changed", "Upstream change pending", "Accept or reject upstream change",
     "data manager"),
    (SENT_BACK_FOR_REVISION, "Sent back for revision",
     "Wait for the interviewer or cancel the request",
     "interviewer, through the in-charge"),
    ("missing_language", "Missing language", "Fix language mapping",
     "data manager"),
    ("language_gap", "Language gap", "Recruit or reassign coders",
     "coder supervisor or in-charge"),
    ("no_coder_at_unit", "No coder at unit", "Grant a coder who can code this unit",
     "coder supervisor or in-charge"),
    ("odk_has_issues", "ODK flagged", "Coordinate with field team",
     "field team, through the in-charge"),
)
_SOFT_GATE_OWNER = "data manager"
# Per-case booleans; ``w`` is the workflow row, ``s`` the submission, ``cu`` its unit.
_BLOCKER_CASE_SQL = {
    "screening_pending": "w.workflow_state = 'screening_pending'",
    "attachment_sync_pending": "w.workflow_state = 'attachment_sync_pending'",
    "smartva_pending": "w.workflow_state = 'smartva_pending'",
    "finalized_upstream_changed": odk_changed_sql("w"),
    SENT_BACK_FOR_REVISION: sent_back_sql("w"),
    "missing_language": (
        f"(w.workflow_state IN {PENDING_STATES_SQL} AND trim(COALESCE(s.va_narration_language, '')) = '')"
    ),
    # Ready pool, a language set, and no covering coder who matches it.
    "language_gap": (
        f"(w.workflow_state IN {CODER_READY_POOL_STATES_SQL}"
        " AND trim(COALESCE(s.va_narration_language, '')) <> ''"
        " AND NOT EXISTS (SELECT 1 FROM cov WHERE cardinality(cov.languages) = 0"
        " OR lower(trim(s.va_narration_language)) = ANY(cov.languages)))"
    ),
    # Pending, and no coder grant that codes reaches this case's own unit or pair.
    "no_coder_at_unit": (
        f"(w.workflow_state IN {PENDING_STATES_SQL} AND NOT EXISTS ("
        " SELECT 1 FROM va_user_access_grants g "
        f"{CODING_GRANT_JOINS}"
        " WHERE g.role = 'coder' AND g.grant_status = 'active'"
        " AND EXISTS (SELECT 1 FROM va_users gu WHERE gu.user_id = g.user_id"
        " AND gu.user_status = 'active')"
        f" AND {CODING_GRANT_CODES_SQL}"
        " AND (g.scope_type = 'project' AND g.project_id = f.project_id"
        " OR g.scope_type = 'project_site' AND gps.project_id = f.project_id"
        " AND gps.site_id = f.site_id"
        " OR g.scope_type = 'org_unit' AND gou.project_id = f.project_id"
        " AND cu.path IS NOT NULL AND cu.path <@ gou.path)))"
    ),
    "odk_has_issues": (
        f"(w.workflow_state IN {PENDING_STATES_SQL} AND s.va_odk_reviewstate = 'hasIssues')"
    ),
}
_SOFT_GATE_SQL = "w.workflow_state IN ('not_codeable_by_coder', 'not_codeable_by_data_manager')"


def compute_c23(scope, period=None, by: str | None = None) -> dict:
    """C-23 Blocked Forms: why cases cannot reach a coder, how old, who unblocks.

    One query. Every row is restricted to the 6 pending states except the two
    upstream rows (coded cases waiting on a DM). Each row has ``count``,
    ``age_p50_hours`` and ``age_max_hours`` (time in the current workflow
    state), a fixed ``owner``, and ``intake_source`` (``form_source`` odk/web).
    A case may sit in several rows; ``total_blocked`` counts it once. The
    soft-gate not-codeable cases (coder and DM) are a separate
    ``soft_gate_not_codeable`` count outside the total. ``by="unit"`` returns
    one row per routed unit (counts only, unrouted cases under a null unit).
    Snapshot, so *period* is ignored.
    """
    if by not in (None, "reason", "unit"):
        raise ValueError(f"C-23 has no by={by!r}")
    if not scope:
        return {"breakdown": [], "total_blocked": 0, "soft_gate_not_codeable": 0}

    flags = ",\n".join(f"({_BLOCKER_CASE_SQL[key]}) AS {key}" for key, *_ in _BLOCKERS)
    any_blocker = " OR ".join(key for key, *_ in _BLOCKERS)
    # Pending, upstream or soft-gate cases only: coded cases are never blocked.
    cases = f"""
        WITH cov AS ({coders_covering_scope_sql()}),
        cases AS (
            SELECT s.org_unit_id, f.form_source, {_SOFT_GATE_SQL} AS soft_gate,
                   EXTRACT(EPOCH FROM (timezone('UTC', now()) - w.workflow_updated_at)) / 3600.0
                       AS age_hours,
                   {flags}
            FROM va_submissions s
            JOIN va_forms f ON f.form_id = s.va_form_id
            JOIN va_submission_workflow w ON w.va_sid = s.va_sid
            LEFT JOIN mas_org_unit cu ON cu.org_unit_id = s.org_unit_id
            WHERE {scope.sql()}
              AND {_IN_ODK_SQL}
              AND {_NOT_DUPLICATE_SQL}
              AND (w.workflow_state IN {PENDING_STATES_SQL}
                   OR w.workflow_state = 'finalized_upstream_changed'
                   OR {_SOFT_GATE_SQL})
        )
    """
    params = {**IN_ODK_BIND, **scope.params}

    if by == "unit":
        counts = ",\n".join(f"COUNT(*) FILTER (WHERE c.{key}) AS {key}" for key, *_ in _BLOCKERS)
        any_c = " OR ".join(f"c.{key}" for key, *_ in _BLOCKERS)
        rows = db.session.execute(
            sa.text(cases + f"""
                SELECT c.org_unit_id, MIN(u.unit_name) AS unit_name,
                       COUNT(*) FILTER (WHERE {any_c}) AS total_blocked,
                       {counts}
                FROM cases c
                LEFT JOIN mas_org_unit u ON u.org_unit_id = c.org_unit_id
                GROUP BY c.org_unit_id
                HAVING COUNT(*) FILTER (WHERE {any_c}) > 0
                ORDER BY total_blocked DESC, unit_name
            """),
            params,
        ).mappings().all()
        return {
            "by": "unit",
            "rows": [
                {
                    "org_unit_id": str(r["org_unit_id"]) if r["org_unit_id"] else None,
                    "unit_name": r["unit_name"],
                    "total_blocked": r["total_blocked"],
                    "counts": {key: r[key] for key, *_ in _BLOCKERS},
                }
                for r in rows
            ],
        }

    aggregates = ",\n".join(
        f"""COUNT(*) FILTER (WHERE {key}) AS {key}_n,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY age_hours) FILTER (WHERE {key}) AS {key}_p50,
            MAX(age_hours) FILTER (WHERE {key}) AS {key}_max,
            COUNT(*) FILTER (WHERE {key} AND form_source = 'odk') AS {key}_odk,
            COUNT(*) FILTER (WHERE {key} AND form_source = 'web') AS {key}_web"""
        for key, *_ in _BLOCKERS
    )
    row = db.session.execute(
        sa.text(cases + f"""
            SELECT COUNT(*) FILTER (WHERE {any_blocker}) AS total_blocked,
                   COUNT(*) FILTER (WHERE soft_gate) AS soft_gate_not_codeable,
                   {aggregates}
            FROM cases
        """),
        params,
    ).mappings().first()

    def hours(value):
        return round(float(value), 1) if value is not None else None

    breakdown = [
        {
            "blockage_reason": key,
            "label": label,
            "count": row[f"{key}_n"],
            "dm_action": action,
            "owner": owner,
            "age_p50_hours": hours(row[f"{key}_p50"]),
            "age_max_hours": hours(row[f"{key}_max"]),
            "intake_source": {"odk": row[f"{key}_odk"], "web": row[f"{key}_web"]},
        }
        for key, label, action, owner in _BLOCKERS
        if row[f"{key}_n"] > 0
    ]
    return {
        "breakdown": breakdown,
        "total_blocked": row["total_blocked"] or 0,
        "soft_gate_not_codeable": row["soft_gate_not_codeable"] or 0,
        "soft_gate_owner": _SOFT_GATE_OWNER,
    }


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
      Same pattern as D-QG-07 but for va_social_autopsy_analyses and
      social_autopsy_enabled flag.
    """
    scope = dm_scope()
    if not scope:
        return jsonify({"nqa": {}, "social_autopsy": {}})

    def compute():
        result = {}

        for feature_flag, table_name, label in [
            ("narrative_qa_enabled", "va_narrative_assessments", "nqa"),
            ("social_autopsy_enabled", "va_social_autopsy_analyses", "social_autopsy"),
        ]:
            # Check if the project has this feature enabled
            status_col = f"va_{'nqa' if label == 'nqa' else 'saa'}_status"

            try:
                row = db.session.execute(
                    sa.text(f"""
                        WITH coded_in_enabled_projects AS (
                            SELECT s.va_sid
                            FROM va_submissions s
                            JOIN va_forms f ON f.form_id = s.va_form_id
                            JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                            JOIN va_project_master pm
                                ON pm.project_id = COALESCE(
                                    (SELECT ps.project_id FROM va_project_sites ps
                                     WHERE ps.site_id = f.site_id
                                       AND ps.project_site_status = 'active'
                                     LIMIT 1),
                                    f.project_id
                                )
                            WHERE {scope.sql()}
                              AND {_IN_ODK_SQL}
                              AND {_NOT_DUPLICATE_SQL}
                              AND w.workflow_state IN (
                                  'coder_finalized', 'reviewer_eligible',
                                  'reviewer_coding_in_progress',
                                  'reviewer_finalized', 'finalized_upstream_changed'
                              )
                              AND pm.{feature_flag} = true
                        ),
                        with_assessment AS (
                            SELECT c.va_sid
                            FROM coded_in_enabled_projects c
                            WHERE EXISTS (
                                SELECT 1 FROM {table_name} a
                                WHERE a.va_sid = c.va_sid
                                  AND a.{status_col} = 'active'
                            )
                        )
                        SELECT
                            (SELECT COUNT(*) FROM coded_in_enabled_projects) AS denominator,
                            (SELECT COUNT(*) FROM with_assessment) AS numerator
                    """),
                    {**IN_ODK_BIND, **scope.params},
                ).mappings().first()

                denom = row["denominator"] or 0 if row else 0
                numer = row["numerator"] or 0 if row else 0
                rate = round(numer / denom * 100, 1) if denom > 0 else 0.0

                result[label] = {
                    "numerator": numer,
                    "denominator": denom,
                    "rate": rate,
                    "enabled": True,
                }
            except Exception:
                result[label] = {"enabled": False, "rate": 0.0}

        return result

    return jsonify(cached_kpi("nqa_sa_rates", compute))


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

    def compute():
        row = db.session.execute(
            sa.text(f"""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE s.va_odk_reviewstate = 'hasIssues') AS has_issues
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE {scope.sql()}
                  AND {_IN_ODK_SQL}
                  AND {_NOT_DUPLICATE_SQL}
            """),
            {**IN_ODK_BIND, **scope.params},
        ).mappings().first()

        total = row["total"] or 0
        issues = row["has_issues"] or 0
        rate = round(issues / total * 100, 1) if total > 0 else 0.0

        return {"count": issues, "total": total, "rate": rate}

    return jsonify(cached_kpi("odk_issues", compute))
