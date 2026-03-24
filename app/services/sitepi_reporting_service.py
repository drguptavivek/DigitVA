"""Site PI reporting helpers."""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import VaAccessRoles, VaAccessScopeTypes, VaStatuses
from app.services.workflow.definition import (
    TRANSITION_ADMIN_OVERRIDE_TO_RECODE,
    TRANSITION_CODER_FINALIZED,
    TRANSITION_RECODE_FINALIZED,
    TRANSITION_RECODE_STARTED,
    TRANSITION_REVIEWER_CODING_STARTED,
    TRANSITION_REVIEWER_FINALIZED,
    TRANSITION_UPSTREAM_CHANGE_ACCEPTED,
    TRANSITION_UPSTREAM_CHANGE_DETECTED,
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
    WORKFLOW_SCREENING_PENDING,
    WORKFLOW_SMARTVA_PENDING,
)


_PENDING_STATES = (
    WORKFLOW_SCREENING_PENDING,
    WORKFLOW_SMARTVA_PENDING,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_CODER_STEP1_SAVED,
)


def get_sitepi_dashboard_data(site_id: str) -> dict:
    """Return workflow-aware reporting for a Site PI site."""
    kpi_sql = sa.text(
        f"""
        WITH site_submissions AS (
            SELECT
                s.va_sid,
                COALESCE(w.workflow_state, :default_ready_state) AS workflow_state
            FROM va_submissions s
            JOIN va_forms f ON f.form_id = s.va_form_id
            LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
            WHERE f.site_id = :site_id
        ),
        authority AS (
            SELECT
                ss.va_sid,
                CASE
                    WHEN a.authoritative_reviewer_final_assessment_id IS NOT NULL THEN 'reviewer'
                    WHEN a.authoritative_final_assessment_id IS NOT NULL THEN 'coder'
                    ELSE 'none'
                END AS authority_source
            FROM site_submissions ss
            LEFT JOIN va_final_cod_authority a ON a.va_sid = ss.va_sid
        ),
        event_totals AS (
            SELECT
                COUNT(*) FILTER (WHERE e.transition_id = :transition_admin_override) AS admin_reset_events,
                COUNT(*) FILTER (WHERE e.transition_id = :transition_upstream_detected) AS upstream_change_events,
                COUNT(*) FILTER (WHERE e.transition_id = :transition_upstream_accepted) AS upstream_change_accept_events,
                COUNT(*) FILTER (WHERE e.transition_id = :transition_recode_started) AS recode_started_events,
                COUNT(*) FILTER (WHERE e.transition_id = :transition_recode_finalized) AS recode_finalized_events,
                COUNT(*) FILTER (WHERE e.transition_id = :transition_reviewer_started) AS reviewer_started_events,
                COUNT(*) FILTER (WHERE e.transition_id = :transition_reviewer_finalized) AS reviewer_finalized_events
            FROM va_submission_workflow_events e
            JOIN site_submissions ss ON ss.va_sid = e.va_sid
        )
        SELECT
            COUNT(*) AS total_submissions,
            COUNT(*) FILTER (
                WHERE authority.authority_source IN ('coder', 'reviewer')
            ) AS total_authoritative_coded,
            COUNT(*) FILTER (
                WHERE ss.workflow_state = :workflow_reviewer_eligible
            ) AS reviewer_eligible_submissions,
            COUNT(*) FILTER (
                WHERE ss.workflow_state = :workflow_reviewer_finalized
            ) AS reviewer_finalized_submissions,
            COUNT(*) FILTER (
                WHERE ss.workflow_state = :workflow_upstream_changed
            ) AS upstream_changed_submissions,
            COUNT(*) FILTER (
                WHERE ss.workflow_state IN (:workflow_not_codeable_coder, :workflow_not_codeable_dm)
            ) AS total_not_codeable,
            COUNT(*) FILTER (
                WHERE ss.workflow_state IN :pending_states
            ) AS pending_or_active_submissions,
            COUNT(*) FILTER (
                WHERE ss.workflow_state IN (:workflow_reviewer_eligible, :workflow_reviewer_finalized)
            ) AS post_coder_complete_submissions,
            COUNT(*) FILTER (
                WHERE authority.authority_source = 'coder'
            ) AS coder_authority_submissions,
            COUNT(*) FILTER (
                WHERE authority.authority_source = 'reviewer'
            ) AS reviewer_authority_submissions,
            MAX(event_totals.admin_reset_events) AS admin_reset_events,
            MAX(event_totals.upstream_change_events) AS upstream_change_events,
            MAX(event_totals.upstream_change_accept_events) AS upstream_change_accept_events,
            MAX(event_totals.recode_started_events) AS recode_started_events,
            MAX(event_totals.recode_finalized_events) AS recode_finalized_events,
            MAX(event_totals.reviewer_started_events) AS reviewer_started_events,
            MAX(event_totals.reviewer_finalized_events) AS reviewer_finalized_events
        FROM site_submissions ss
        JOIN authority ON authority.va_sid = ss.va_sid
        CROSS JOIN event_totals
        """
    ).bindparams(sa.bindparam("pending_states", expanding=True))

    kpi_row = db.session.execute(
        kpi_sql,
        {
            "site_id": site_id,
            "default_ready_state": WORKFLOW_READY_FOR_CODING,
            "workflow_reviewer_eligible": WORKFLOW_REVIEWER_ELIGIBLE,
            "workflow_reviewer_finalized": WORKFLOW_REVIEWER_FINALIZED,
            "workflow_upstream_changed": WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
            "workflow_not_codeable_coder": WORKFLOW_NOT_CODEABLE_BY_CODER,
            "workflow_not_codeable_dm": WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
            "pending_states": list(_PENDING_STATES),
            "transition_admin_override": TRANSITION_ADMIN_OVERRIDE_TO_RECODE,
            "transition_upstream_detected": TRANSITION_UPSTREAM_CHANGE_DETECTED,
            "transition_upstream_accepted": TRANSITION_UPSTREAM_CHANGE_ACCEPTED,
            "transition_recode_started": TRANSITION_RECODE_STARTED,
            "transition_recode_finalized": TRANSITION_RECODE_FINALIZED,
            "transition_reviewer_started": TRANSITION_REVIEWER_CODING_STARTED,
            "transition_reviewer_finalized": TRANSITION_REVIEWER_FINALIZED,
        },
    ).mappings().one()

    coder_kpi_sql = sa.text(
        """
        WITH site_forms AS (
            SELECT form_id
            FROM va_forms
            WHERE site_id = :site_id
        ),
        site_project_sites AS (
            SELECT ps.project_site_id
            FROM va_project_sites ps
            WHERE ps.site_id = :site_id
              AND ps.project_site_status = :active_status
        )
        SELECT
            u.name AS coder_name,
            u.pw_reset_t_and_c AS onboarded,
            COALESCE(work.total_done, 0) AS total_done,
            COALESCE(review.total_errors, 0) AS total_errors
        FROM va_users u
        JOIN va_user_access_grants g
          ON g.user_id = u.user_id
         AND g.role = :coder_role
         AND g.scope_type = :project_site_scope
         AND g.grant_status = :active_status
         AND g.project_site_id IN (SELECT project_site_id FROM site_project_sites)
        LEFT JOIN (
            SELECT
                fa.va_finassess_by AS user_id,
                COUNT(*) AS total_done
            FROM va_final_assessments fa
            JOIN va_submissions s ON s.va_sid = fa.va_sid
            WHERE fa.va_finassess_status = :active_status
              AND s.va_form_id IN (SELECT form_id FROM site_forms)
            GROUP BY fa.va_finassess_by
        ) work ON work.user_id = u.user_id
        LEFT JOIN (
            SELECT
                cr.va_creview_by AS user_id,
                COUNT(*) AS total_errors
            FROM va_coder_review cr
            JOIN va_submissions s ON s.va_sid = cr.va_sid
            WHERE cr.va_creview_status = :active_status
              AND s.va_form_id IN (SELECT form_id FROM site_forms)
            GROUP BY cr.va_creview_by
        ) review ON review.user_id = u.user_id
        ORDER BY coder_name
        """
    )

    coder_rows = db.session.execute(
        coder_kpi_sql,
        {
            "site_id": site_id,
            "active_status": VaStatuses.active.value,
            "coder_role": VaAccessRoles.coder.value,
            "project_site_scope": VaAccessScopeTypes.project_site.value,
        },
    ).mappings().all()

    submission_rows_sql = sa.text(
        """
        WITH site_submissions AS (
            SELECT
                s.va_sid,
                COALESCE(w.workflow_state, :default_ready_state) AS workflow_state
            FROM va_submissions s
            JOIN va_forms f ON f.form_id = s.va_form_id
            LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
            WHERE f.site_id = :site_id
        ),
        authority AS (
            SELECT
                ss.va_sid,
                CASE
                    WHEN a.authoritative_reviewer_final_assessment_id IS NOT NULL THEN 'reviewer'
                    WHEN a.authoritative_final_assessment_id IS NOT NULL THEN 'coder'
                    ELSE 'none'
                END AS authority_source
            FROM site_submissions ss
            LEFT JOIN va_final_cod_authority a ON a.va_sid = ss.va_sid
        ),
        event_counts AS (
            SELECT
                e.va_sid,
                COUNT(*) FILTER (WHERE e.transition_id = :transition_coder_finalized) AS coder_finalized_count,
                COUNT(*) FILTER (WHERE e.transition_id = :transition_admin_override) AS admin_reset_count,
                COUNT(*) FILTER (WHERE e.transition_id = :transition_upstream_detected) AS upstream_change_count,
                COUNT(*) FILTER (WHERE e.transition_id = :transition_upstream_accepted) AS upstream_accept_count,
                COUNT(*) FILTER (WHERE e.transition_id = :transition_recode_started) AS recode_started_count,
                COUNT(*) FILTER (WHERE e.transition_id = :transition_recode_finalized) AS recode_finalized_count,
                COUNT(*) FILTER (WHERE e.transition_id = :transition_reviewer_started) AS reviewer_started_count,
                COUNT(*) FILTER (WHERE e.transition_id = :transition_reviewer_finalized) AS reviewer_finalized_count,
                MAX(e.event_created_at) AS last_workflow_event_at
            FROM va_submission_workflow_events e
            JOIN site_submissions ss ON ss.va_sid = e.va_sid
            GROUP BY e.va_sid
        )
        SELECT
            ss.va_sid,
            ss.workflow_state,
            authority.authority_source,
            COALESCE(ec.coder_finalized_count, 0) AS coder_finalized_count,
            COALESCE(ec.admin_reset_count, 0) AS admin_reset_count,
            COALESCE(ec.upstream_change_count, 0) AS upstream_change_count,
            COALESCE(ec.upstream_accept_count, 0) AS upstream_accept_count,
            COALESCE(ec.recode_started_count, 0) AS recode_started_count,
            COALESCE(ec.recode_finalized_count, 0) AS recode_finalized_count,
            COALESCE(ec.reviewer_started_count, 0) AS reviewer_started_count,
            COALESCE(ec.reviewer_finalized_count, 0) AS reviewer_finalized_count,
            ec.last_workflow_event_at
        FROM site_submissions ss
        JOIN authority ON authority.va_sid = ss.va_sid
        LEFT JOIN event_counts ec ON ec.va_sid = ss.va_sid
        ORDER BY ec.last_workflow_event_at DESC NULLS LAST, ss.va_sid
        """
    )
    submission_rows = db.session.execute(
        submission_rows_sql,
        {
            "site_id": site_id,
            "default_ready_state": WORKFLOW_READY_FOR_CODING,
            "transition_coder_finalized": TRANSITION_CODER_FINALIZED,
            "transition_admin_override": TRANSITION_ADMIN_OVERRIDE_TO_RECODE,
            "transition_upstream_detected": TRANSITION_UPSTREAM_CHANGE_DETECTED,
            "transition_upstream_accepted": TRANSITION_UPSTREAM_CHANGE_ACCEPTED,
            "transition_recode_started": TRANSITION_RECODE_STARTED,
            "transition_recode_finalized": TRANSITION_RECODE_FINALIZED,
            "transition_reviewer_started": TRANSITION_REVIEWER_CODING_STARTED,
            "transition_reviewer_finalized": TRANSITION_REVIEWER_FINALIZED,
        },
    ).mappings().all()

    return {
        "total_submissions": kpi_row["total_submissions"] or 0,
        "total_coded": kpi_row["total_authoritative_coded"] or 0,
        "total_not_codeable": kpi_row["total_not_codeable"] or 0,
        "current_state_kpis": {
            "pending_or_active": kpi_row["pending_or_active_submissions"] or 0,
            "reviewer_eligible": kpi_row["reviewer_eligible_submissions"] or 0,
            "reviewer_finalized": kpi_row["reviewer_finalized_submissions"] or 0,
            "post_coder_complete": kpi_row["post_coder_complete_submissions"] or 0,
            "upstream_changed": kpi_row["upstream_changed_submissions"] or 0,
        },
        "authority_kpis": {
            "coder_authority": kpi_row["coder_authority_submissions"] or 0,
            "reviewer_authority": kpi_row["reviewer_authority_submissions"] or 0,
        },
        "cycle_kpis": {
            "admin_resets": kpi_row["admin_reset_events"] or 0,
            "upstream_changes": kpi_row["upstream_change_events"] or 0,
            "upstream_accepts": kpi_row["upstream_change_accept_events"] or 0,
            "recode_started": kpi_row["recode_started_events"] or 0,
            "recode_finalized": kpi_row["recode_finalized_events"] or 0,
            "reviewer_started": kpi_row["reviewer_started_events"] or 0,
            "reviewer_finalized": kpi_row["reviewer_finalized_events"] or 0,
        },
        "coder_kpis": list(coder_rows),
        "submission_rows": list(submission_rows),
    }
