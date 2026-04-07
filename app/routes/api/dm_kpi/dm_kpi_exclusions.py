"""DM KPI — Exclusions & Blocked Forms.

Blueprint prefix: ``/api/v1/analytics/dm-kpi/exclusions``

KPIs served:
  C-05  % Not Codeable (Overall)
  C-06  Consent Refusal Rate
  C-23  Blocked Forms Alert (Composite)
  D-QG-01  Coder Not-Codeable Count & Rate
  D-QG-02  DM Not-Codeable Count & Rate
  D-QG-03  Exclusions by Actor
  D-QG-04  Coder Not-Codeable Reason Breakdown
  D-QG-05  DM Not-Codeable Reason Breakdown
  D-QG-06  ODK Has Issues Count
  D-QG-07  NQA Completion Rate
  D-QG-08  Social Autopsy Completion Rate

Sources:
  - va_submission_workflow (current states for rates)
  - va_coder_review (reason breakdowns)
  - va_data_manager_review (reason breakdowns)
  - va_reviewer_final_assessments (NQA/SA)
  - va_project_master (feature flags)
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.routes.api.dm_kpi.dm_kpi_scope import cached_kpi, dm_site_ids

bp = Blueprint("dm_kpi_exclusions", __name__)
log = logging.getLogger(__name__)


@bp.get("/rates")
@role_required("data_manager")
def exclusion_rates():
    """KPIs: C-05 (% Not Codeable Overall), C-06 (Consent Refusal Rate),
    D-QG-01 (Coder Not-Codeable Rate), D-QG-02 (DM Not-Codeable Rate).

    C-05 — % Not Codeable (Overall):
      Numerator: COUNT WHERE workflow_state IN ('not_codeable_by_coder',
                 'not_codeable_by_data_manager').
      Denominator: COUNT of ALL-SYNCED.
      Rate: N / D × 100.
      Scope: ALL-SYNCED.
      Time frames: Snapshot.

    C-06 — Consent Refusal Rate:
      Numerator: COUNT WHERE workflow_state = 'consent_refused'.
      Denominator: COUNT of ALL-SYNCED.
      Rate: N / D × 100.
      Time frames: Snapshot.

    D-QG-01 — Coder Not-Codeable Rate:
      Numerator: COUNT WHERE workflow_state = 'not_codeable_by_coder'.
      Denominator: COUNT of CODING-POOL.
      Rate: N / D × 100.

    D-QG-02 — DM Not-Codeable Rate:
      Numerator: COUNT WHERE workflow_state = 'not_codeable_by_data_manager'.
      Denominator: COUNT of ALL-SYNCED.
      Rate: N / D × 100.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({})

    def compute():
        row = db.session.execute(
            sa.text("""
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
                WHERE f.site_id = ANY(:site_ids)
            """),
            {"site_ids": site_ids},
        ).mappings().first()

        all_synced = row["all_synced"] or 0
        consent = row["consent_refused"] or 0
        dm_nc = row["dm_not_codeable"] or 0
        coder_nc = row["coder_not_codeable"] or 0
        coding_pool = row["coding_pool"] or 0

        def pct(n, d):
            return round(n / d * 100, 1) if d > 0 else 0.0

        return {
            "all_synced": all_synced,
            "consent_refused": {"count": consent, "rate": pct(consent, all_synced)},
            "not_codeable_overall": {
                "count": dm_nc + coder_nc,
                "rate": pct(dm_nc + coder_nc, all_synced),
            },
            "coder_not_codeable": {
                "count": coder_nc,
                "rate": pct(coder_nc, coding_pool),
            },
            "dm_not_codeable": {
                "count": dm_nc,
                "rate": pct(dm_nc, all_synced),
            },
            "coding_pool": coding_pool,
        }

    return jsonify(cached_kpi("exclusion_rates", compute))


@bp.get("/breakdown")
@role_required("data_manager")
def exclusion_breakdown():
    """KPIs: D-QG-04 (Coder Not-Codeable Reason Breakdown),
    D-QG-05 (DM Not-Codeable Reason Breakdown), D-QG-03 (Exclusions by Actor).

    D-QG-04 — Coder Not-Codeable Reason Breakdown:
      Numerator: COUNT grouped by va_creview_reason.
      Values: narration_language, narration_doesnt_match, no_info, others.
      Where: va_creview_status = 'active'.
      Time frame: Cumulative.

    D-QG-05 — DM Not-Codeable Reason Breakdown:
      Numerator: COUNT grouped by va_dmreview_reason.
      Values: submission_incomplete, source_data_mismatch,
              duplicate_submission, language_unreadable, others.
      Where: va_dmreview_status = 'active'.
      Time frame: Cumulative.

    D-QG-03 — Exclusions by Actor:
      COUNT grouped by actor type (DM, Coder, Reviewer rejection,
      Screening rejected).
      Time frame: Cumulative.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"coder_reasons": [], "dm_reasons": [], "by_actor": {}})

    def compute():
        # Coder reason breakdown
        coder_reasons = db.session.execute(
            sa.text("""
                SELECT cr.va_creview_reason, COUNT(*) AS count
                FROM va_coder_review cr
                JOIN va_submissions s ON s.va_sid = cr.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND cr.va_creview_status = 'active'
                GROUP BY cr.va_creview_reason
                ORDER BY count DESC
            """),
            {"site_ids": site_ids},
        ).mappings().all()

        # DM reason breakdown
        dm_reasons = db.session.execute(
            sa.text("""
                SELECT dr.va_dmreview_reason, COUNT(*) AS count
                FROM va_data_manager_review dr
                JOIN va_submissions s ON s.va_sid = dr.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND dr.va_dmreview_status = 'active'
                GROUP BY dr.va_dmreview_reason
                ORDER BY count DESC
            """),
            {"site_ids": site_ids},
        ).mappings().all()

        # D-QG-03: Exclusions by actor
        dm_count = db.session.execute(
            sa.text("""
                SELECT COUNT(*) AS cnt FROM va_data_manager_review dr
                JOIN va_submissions s ON s.va_sid = dr.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids) AND dr.va_dmreview_status = 'active'
            """),
            {"site_ids": site_ids},
        ).scalar() or 0

        coder_count = db.session.execute(
            sa.text("""
                SELECT COUNT(*) AS cnt FROM va_coder_review cr
                JOIN va_submissions s ON s.va_sid = cr.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids) AND cr.va_creview_status = 'active'
            """),
            {"site_ids": site_ids},
        ).scalar() or 0

        screening_rejected = db.session.execute(
            sa.text("""
                SELECT COUNT(*) AS cnt
                FROM va_submission_workflow_events e
                JOIN va_submissions s ON s.va_sid = e.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND e.transition_id = 'screening_rejected'
            """),
            {"site_ids": site_ids},
        ).scalar() or 0

        return {
            "coder_reasons": [
                {"reason": r["va_creview_reason"], "count": r["count"]}
                for r in coder_reasons
            ],
            "dm_reasons": [
                {"reason": r["va_dmreview_reason"], "count": r["count"]}
                for r in dm_reasons
            ],
            "by_actor": {
                "data_manager": dm_count,
                "coder": coder_count,
                "screening_rejected": screening_rejected,
            },
        }

    return jsonify(cached_kpi("exclusion_breakdown", compute))


@bp.get("/blocked")
@role_required("data_manager")
def blocked_forms():
    """KPI: C-23 — Blocked Forms Alert (Composite).

    Definition: COUNT and breakdown of all submissions in CODING-POOL that
    cannot be routed to a coder right now, grouped by blockage reason.

    Breakdown (each condition checked independently):
      - screening_pending       → DM: pass or reject screening
      - attachment_sync_pending → DM: trigger attachment sync
      - smartva_pending         → DM: check SmartVA queue
      - finalized_upstream_changed → DM: accept or reject upstream change
      - missing_language        → DM: fix language mapping
      - odk_has_issues          → DM: coordinate with field team

    Scope: CODING-POOL (excludes consent_refused).
    Time frame: Snapshot.
    Actionable: DM's "to-do list" — each blockage has a clear action.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"breakdown": [], "total_blocked": 0})

    def compute():
        breakdown = []

        # Define blockage categories with their queries
        categories = [
            ("screening_pending", "Awaiting DM screening", "Pass or reject screening"),
            ("attachment_sync_pending", "Attachments not synced", "Trigger attachment sync"),
            ("smartva_pending", "SmartVA not run", "Check SmartVA queue"),
            ("finalized_upstream_changed", "Upstream change pending", "Accept or reject upstream change"),
        ]

        for state, label, action in categories:
            count = db.session.execute(
                sa.text(f"""
                    SELECT COUNT(*) AS cnt
                    FROM va_submission_workflow w
                    JOIN va_submissions s ON s.va_sid = w.va_sid
                    JOIN va_forms f ON f.form_id = s.va_form_id
                    WHERE f.site_id = ANY(:site_ids)
                      AND w.workflow_state = '{state}'
                """),
                {"site_ids": site_ids},
            ).scalar() or 0
            if count > 0:
                breakdown.append({
                    "blockage_reason": state,
                    "label": label,
                    "count": count,
                    "dm_action": action,
                })

        # Missing language
        missing_lang = db.session.execute(
            sa.text("""
                SELECT COUNT(*) AS cnt
                FROM va_submission_workflow w
                JOIN va_submissions s ON s.va_sid = w.va_sid
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
                  AND w.workflow_state IN ('ready_for_coding', 'coding_in_progress', 'coder_step1_saved')
                  AND (s.va_narration_language IS NULL OR s.va_narration_language = '')
            """),
            {"site_ids": site_ids},
        ).scalar() or 0
        if missing_lang > 0:
            breakdown.append({
                "blockage_reason": "missing_language",
                "label": "Missing language",
                "count": missing_lang,
                "dm_action": "Fix language mapping",
            })

        # ODK has issues
        odk_issues = db.session.execute(
            sa.text("""
                SELECT COUNT(*) AS cnt
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                WHERE f.site_id = ANY(:site_ids)
                  AND w.workflow_state NOT IN ('consent_refused', 'not_codeable_by_data_manager')
                  AND s.va_odk_reviewstate = 'hasIssues'
            """),
            {"site_ids": site_ids},
        ).scalar() or 0
        if odk_issues > 0:
            breakdown.append({
                "blockage_reason": "odk_has_issues",
                "label": "ODK flagged",
                "count": odk_issues,
                "dm_action": "Coordinate with field team",
            })

        # Total unique blocked (deduplicated)
        total_blocked = db.session.execute(
            sa.text("""
                SELECT COUNT(DISTINCT s.va_sid) AS cnt
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                JOIN va_submission_workflow w ON w.va_sid = s.va_sid
                WHERE f.site_id = ANY(:site_ids)
                  AND w.workflow_state NOT IN (
                      'consent_refused', 'not_codeable_by_data_manager',
                      'not_codeable_by_coder'
                  )
                  AND (
                      w.workflow_state IN (
                          'screening_pending', 'attachment_sync_pending',
                          'smartva_pending', 'finalized_upstream_changed'
                      )
                      OR (s.va_narration_language IS NULL OR s.va_narration_language = '')
                      OR s.va_odk_reviewstate = 'hasIssues'
                  )
            """),
            {"site_ids": site_ids},
        ).scalar() or 0

        return {
            "breakdown": breakdown,
            "total_blocked": total_blocked,
        }

    return jsonify(cached_kpi("blocked_forms", compute))


@bp.get("/nqa-sa")
@role_required("data_manager")
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
    site_ids = dm_site_ids()
    if not site_ids:
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
                            WHERE f.site_id = ANY(:site_ids)
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
                    {"site_ids": site_ids},
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
@role_required("data_manager")
def odk_issues():
    """KPI: D-QG-06 — ODK Has Issues Count.

    Numerator: COUNT WHERE va_odk_reviewstate = 'hasIssues'.
    Denominator: ALL-SYNCED.
    Time frame: Cumulative.
    Source: va_submissions JOIN va_forms.
    """
    site_ids = dm_site_ids()
    if not site_ids:
        return jsonify({"count": 0, "total": 0, "rate": 0.0})

    def compute():
        row = db.session.execute(
            sa.text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE s.va_odk_reviewstate = 'hasIssues') AS has_issues
                FROM va_submissions s
                JOIN va_forms f ON f.form_id = s.va_form_id
                WHERE f.site_id = ANY(:site_ids)
            """),
            {"site_ids": site_ids},
        ).mappings().first()

        total = row["total"] or 0
        issues = row["has_issues"] or 0
        rate = round(issues / total * 100, 1) if total > 0 else 0.0

        return {"count": issues, "total": total, "rate": rate}

    return jsonify(cached_kpi("odk_issues", compute))
