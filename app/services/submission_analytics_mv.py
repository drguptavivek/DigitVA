"""Helpers for the submission analytics materialized view."""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_CONSENT_REFUSED,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
    WORKFLOW_SCREENING_PENDING,
)


MV_NAME = "va_submission_analytics_mv"
_DAYS_PER_MONTH = "30.4375"
_DAYS_PER_YEAR = "365.25"


def build_submission_analytics_mv_sql(view_name: str = MV_NAME) -> str:
    """Return the CREATE MATERIALIZED VIEW statement for submission analytics."""
    return f"""
CREATE MATERIALIZED VIEW {view_name} AS
WITH base AS (
    SELECT
        s.va_sid,
        s.va_form_id AS form_id,
        f.project_id,
        f.site_id,
        s.va_submission_date AS submission_at,
        DATE(s.va_submission_date) AS submission_date,
        DATE_TRUNC('week', s.va_submission_date)::date AS submission_week_start,
        DATE_TRUNC('month', s.va_submission_date)::date AS submission_month_start,
        w.workflow_state,
        s.va_odk_reviewstate AS odk_review_state,
        s.va_sync_issue_code AS odk_sync_issue_code,
        (s.va_sync_issue_code IS NOT NULL) AS has_sync_issue,
        s.va_deceased_gender AS sex,
        s.va_deceased_age_normalized_days,
        s.va_deceased_age_normalized_years,
        s.va_deceased_age_source,
        LOWER(NULLIF(BTRIM(COALESCE(s.va_data ->> 'age_group', '')), '')) AS age_group_raw,
        CASE
            WHEN NULLIF(BTRIM(COALESCE(s.va_data ->> 'age_neonate_hours', '')), '') ~ '^-?\\d+(\\.\\d+)?$'
                THEN (s.va_data ->> 'age_neonate_hours')::numeric
            ELSE NULL
        END AS age_neonate_hours_num,
        CASE
            WHEN NULLIF(BTRIM(COALESCE(s.va_data ->> 'age_neonate_days', '')), '') ~ '^-?\\d+(\\.\\d+)?$'
                THEN (s.va_data ->> 'age_neonate_days')::numeric
            ELSE NULL
        END AS age_neonate_days_num,
        CASE
            WHEN NULLIF(BTRIM(COALESCE(s.va_data ->> 'ageInDays', '')), '') ~ '^-?\\d+(\\.\\d+)?$'
                THEN (s.va_data ->> 'ageInDays')::numeric
            ELSE NULL
        END AS age_in_days_num,
        CASE
            WHEN NULLIF(BTRIM(COALESCE(s.va_data ->> 'ageInMonths', '')), '') ~ '^-?\\d+(\\.\\d+)?$'
                THEN (s.va_data ->> 'ageInMonths')::numeric
            ELSE NULL
        END AS age_in_months_num,
        CASE
            WHEN NULLIF(BTRIM(COALESCE(s.va_data ->> 'ageInYears', '')), '') ~ '^-?\\d+(\\.\\d+)?$'
                THEN (s.va_data ->> 'ageInYears')::numeric
            ELSE NULL
        END AS age_in_years_num,
        CASE
            WHEN NULLIF(BTRIM(COALESCE(s.va_data ->> 'ageInYears2', '')), '') ~ '^-?\\d+(\\.\\d+)?$'
                THEN (s.va_data ->> 'ageInYears2')::numeric
            ELSE NULL
        END AS age_in_years2_num,
        CASE
            WHEN NULLIF(BTRIM(COALESCE(s.va_data ->> 'finalAgeInYears', '')), '') ~ '^-?\\d+(\\.\\d+)?$'
                THEN (s.va_data ->> 'finalAgeInYears')::numeric
            ELSE NULL
        END AS final_age_years_num,
        COALESCE(s.va_data ->> 'isNeonatal', '') IN ('1', '1.0', 'true', 'True') AS is_neonatal,
        COALESCE(s.va_data ->> 'isChild', '') IN ('1', '1.0', 'true', 'True') AS is_child,
        COALESCE(s.va_data ->> 'isAdult', '') IN ('1', '1.0', 'true', 'True') AS is_adult
    FROM va_submissions s
    JOIN va_forms f ON f.form_id = s.va_form_id
    LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
),
age_source AS (
    SELECT
        b.*,
        COALESCE(
            b.va_deceased_age_source,
            CASE
                WHEN b.age_neonate_hours_num IS NOT NULL THEN 'age_neonate_hours'
                WHEN b.age_neonate_days_num IS NOT NULL THEN 'age_neonate_days'
                WHEN b.is_neonatal AND b.age_in_days_num IS NOT NULL THEN 'ageInDays'
                WHEN b.is_child AND b.age_in_days_num IS NOT NULL THEN 'ageInDays'
                WHEN b.is_child AND b.age_in_months_num IS NOT NULL THEN 'ageInMonths'
                WHEN b.is_child AND b.age_in_years_num IS NOT NULL THEN 'ageInYears'
                WHEN b.is_child AND b.age_in_years2_num IS NOT NULL THEN 'ageInYears2'
                WHEN b.is_child AND b.final_age_years_num IS NOT NULL THEN 'finalAgeInYears'
                WHEN b.is_adult AND b.age_in_years_num IS NOT NULL THEN 'ageInYears'
                WHEN b.is_adult AND b.age_in_years2_num IS NOT NULL THEN 'ageInYears2'
                WHEN b.is_adult AND b.final_age_years_num IS NOT NULL THEN 'finalAgeInYears'
                WHEN b.age_in_years_num IS NOT NULL THEN 'ageInYears'
                WHEN b.age_in_days_num IS NOT NULL THEN 'ageInDays'
                WHEN b.age_in_months_num IS NOT NULL THEN 'ageInMonths'
                WHEN b.age_in_years2_num IS NOT NULL THEN 'ageInYears2'
                WHEN b.final_age_years_num IS NOT NULL THEN 'finalAgeInYears'
                ELSE NULL
            END
        ) AS normalized_age_source
    FROM base b
),
age_normalized AS (
    SELECT
        a.*,
        CASE
            WHEN a.normalized_age_source = 'age_neonate_hours' THEN a.age_neonate_hours_num
            ELSE NULL
        END AS normalized_age_hours,
        COALESCE(
            a.va_deceased_age_normalized_days,
            CASE
                WHEN a.normalized_age_source = 'age_neonate_hours' THEN 0::numeric
                WHEN a.normalized_age_source = 'age_neonate_days' THEN a.age_neonate_days_num
                WHEN a.normalized_age_source = 'ageInDays' THEN a.age_in_days_num
                WHEN a.normalized_age_source = 'ageInMonths' THEN a.age_in_months_num * {_DAYS_PER_MONTH}
                WHEN a.normalized_age_source = 'ageInYears' THEN a.age_in_years_num * {_DAYS_PER_YEAR}
                WHEN a.normalized_age_source = 'ageInYears2' THEN a.age_in_years2_num * {_DAYS_PER_YEAR}
                WHEN a.normalized_age_source = 'finalAgeInYears' THEN a.final_age_years_num * {_DAYS_PER_YEAR}
                ELSE NULL
            END
        ) AS normalized_age_days,
        CASE
            WHEN a.normalized_age_source = 'age_neonate_hours' THEN 0::numeric
            WHEN a.normalized_age_source = 'age_neonate_days' THEN COALESCE(
                a.va_deceased_age_normalized_days,
                a.age_neonate_days_num
            ) / {_DAYS_PER_MONTH}
            WHEN a.normalized_age_source = 'ageInDays' THEN COALESCE(
                a.va_deceased_age_normalized_days,
                a.age_in_days_num
            ) / {_DAYS_PER_MONTH}
            WHEN a.normalized_age_source = 'ageInMonths' THEN COALESCE(
                a.va_deceased_age_normalized_days / {_DAYS_PER_MONTH},
                a.age_in_months_num
            )
            WHEN a.normalized_age_source IN ('ageInYears', 'ageInYears2', 'finalAgeInYears')
                THEN COALESCE(
                    a.va_deceased_age_normalized_years,
                    CASE
                        WHEN a.normalized_age_source = 'ageInYears' THEN a.age_in_years_num
                        WHEN a.normalized_age_source = 'ageInYears2' THEN a.age_in_years2_num
                        WHEN a.normalized_age_source = 'finalAgeInYears' THEN a.final_age_years_num
                        ELSE NULL
                    END
                ) * 12
            ELSE NULL
        END AS normalized_age_months,
        COALESCE(
            a.va_deceased_age_normalized_years,
            CASE
                WHEN a.normalized_age_source = 'age_neonate_hours' THEN 0::numeric
                WHEN a.normalized_age_source = 'age_neonate_days' THEN a.age_neonate_days_num / {_DAYS_PER_YEAR}
                WHEN a.normalized_age_source = 'ageInDays' THEN a.age_in_days_num / {_DAYS_PER_YEAR}
                WHEN a.normalized_age_source = 'ageInMonths' THEN a.age_in_months_num / 12
                WHEN a.normalized_age_source = 'ageInYears' THEN a.age_in_years_num
                WHEN a.normalized_age_source = 'ageInYears2' THEN a.age_in_years2_num
                WHEN a.normalized_age_source = 'finalAgeInYears' THEN a.final_age_years_num
                ELSE NULL
            END
        ) AS normalized_age_years,
        CASE
            WHEN a.normalized_age_source = 'age_neonate_hours' THEN 'hours'
            WHEN a.normalized_age_source IN ('age_neonate_days', 'ageInDays') THEN 'days'
            WHEN a.normalized_age_source = 'ageInMonths' THEN 'months'
            WHEN a.normalized_age_source IN ('ageInYears', 'ageInYears2', 'finalAgeInYears') THEN 'years'
            ELSE 'unknown'
        END AS age_precision
    FROM age_source a
)
SELECT
    an.va_sid,
    an.form_id,
    an.project_id,
    an.site_id,
    an.submission_at,
    an.submission_date,
    an.submission_week_start,
    an.submission_month_start,
    an.workflow_state,
    an.odk_review_state,
    an.odk_sync_issue_code,
    an.has_sync_issue,
    an.sex,
    an.normalized_age_hours,
    an.normalized_age_days,
    an.normalized_age_months,
    an.normalized_age_years,
    an.normalized_age_source,
    an.age_precision,
    CASE
        WHEN an.normalized_age_days IS NOT NULL AND an.normalized_age_days <= 28 THEN 'neonate'
        WHEN an.normalized_age_years IS NULL THEN 'unknown'
        WHEN an.normalized_age_years < 15 THEN 'child'
        WHEN an.normalized_age_years < 50 THEN '15_49y'
        WHEN an.normalized_age_years < 65 THEN '50_64y'
        ELSE '65_plus'
    END AS analytics_age_band,
    (init_assess.va_iniassess_id IS NOT NULL) AS has_human_initial_cod,
    init_assess.va_immediate_cod AS initial_immediate_cod_text,
    substring(init_assess.va_immediate_cod from '^([A-Z][0-9][0-9A-Z](?:\\.[0-9A-Z]+)?)') AS initial_immediate_icd,
    init_assess.va_antecedent_cod AS initial_antecedent_cod_text,
    substring(init_assess.va_antecedent_cod from '^([A-Z][0-9][0-9A-Z](?:\\.[0-9A-Z]+)?)') AS initial_antecedent_icd,
    (
        reviewer_final.va_rfinassess_id IS NOT NULL
        OR coder_final.va_finassess_id IS NOT NULL
    ) AS has_human_final_cod,
    COALESCE(reviewer_final.va_conclusive_cod, coder_final.va_conclusive_cod) AS final_cod_text,
    substring(
        COALESCE(reviewer_final.va_conclusive_cod, coder_final.va_conclusive_cod)
        from '^([A-Z][0-9][0-9A-Z](?:\\.[0-9A-Z]+)?)'
    ) AS final_icd,
    COALESCE(
        reviewer_final.authority_source_role,
        coder_final.authority_source_role,
        'latest_active_fallback'
    ) AS final_cod_authority_source,
    (smartva.va_smartva_id IS NOT NULL) AS has_smartva,
    smartva.va_smartva_age AS smartva_age,
    smartva.va_smartva_gender AS smartva_gender,
    smartva.va_smartva_resultfor AS smartva_result_for,
    smartva.va_smartva_cause1 AS smartva_cause1,
    smartva.va_smartva_cause1icd AS smartva_cause1_icd,
    smartva.va_smartva_cause2 AS smartva_cause2,
    smartva.va_smartva_cause2icd AS smartva_cause2_icd,
    smartva.va_smartva_cause3 AS smartva_cause3,
    smartva.va_smartva_cause3icd AS smartva_cause3_icd,
    (an.workflow_state = '{WORKFLOW_FINALIZED_UPSTREAM_CHANGED}') AS cod_pending_upstream_review
FROM age_normalized an
LEFT JOIN LATERAL (
    SELECT
        i.va_iniassess_id,
        i.va_immediate_cod,
        i.va_antecedent_cod
    FROM va_initial_assessments i
    WHERE
        i.va_sid = an.va_sid
        AND i.va_iniassess_status = 'active'
    ORDER BY i.va_iniassess_createdat DESC, i.va_iniassess_id DESC
    LIMIT 1
) AS init_assess ON TRUE
LEFT JOIN LATERAL (
    SELECT
        rf.va_rfinassess_id,
        rf.va_conclusive_cod,
        COALESCE(a.authority_source_role, 'reviewer_latest_active_fallback') AS authority_source_role
    FROM va_reviewer_final_assessments rf
    LEFT JOIN va_final_cod_authority a
        ON a.authoritative_reviewer_final_assessment_id = rf.va_rfinassess_id
    WHERE rf.va_rfinassess_id = (
        COALESCE(
            (
                SELECT a2.authoritative_reviewer_final_assessment_id
                FROM va_final_cod_authority a2
                WHERE
                    a2.va_sid = an.va_sid
                    AND a2.authoritative_reviewer_final_assessment_id IS NOT NULL
                LIMIT 1
            ),
            (
                SELECT rf2.va_rfinassess_id
                FROM va_reviewer_final_assessments rf2
                WHERE
                    rf2.va_sid = an.va_sid
                    AND rf2.va_rfinassess_status = 'active'
                ORDER BY rf2.va_rfinassess_createdat DESC, rf2.va_rfinassess_id DESC
                LIMIT 1
            )
        )
    )
) AS reviewer_final ON TRUE
LEFT JOIN LATERAL (
    SELECT
        f.va_finassess_id,
        f.va_conclusive_cod,
        COALESCE(a.authority_source_role, 'latest_active_fallback') AS authority_source_role
    FROM va_final_assessments f
    LEFT JOIN va_final_cod_authority a
        ON a.authoritative_final_assessment_id = f.va_finassess_id
    WHERE f.va_finassess_id = (
        COALESCE(
            (
                SELECT a2.authoritative_final_assessment_id
                FROM va_final_cod_authority a2
                WHERE
                    a2.va_sid = an.va_sid
                    AND a2.authoritative_final_assessment_id IS NOT NULL
                LIMIT 1
            ),
            (
                SELECT f2.va_finassess_id
                FROM va_final_assessments f2
                WHERE
                    f2.va_sid = an.va_sid
                    AND f2.va_finassess_status = 'active'
                ORDER BY f2.va_finassess_createdat DESC, f2.va_finassess_id DESC
                LIMIT 1
            )
        )
    )
) AS coder_final ON TRUE
LEFT JOIN LATERAL (
    SELECT
        sv.va_smartva_id,
        sv.va_smartva_age,
        sv.va_smartva_gender,
        sv.va_smartva_resultfor,
        sv.va_smartva_cause1,
        sv.va_smartva_cause1icd,
        sv.va_smartva_cause2,
        sv.va_smartva_cause2icd,
        sv.va_smartva_cause3,
        sv.va_smartva_cause3icd
    FROM va_smartva_results sv
    WHERE
        sv.va_sid = an.va_sid
        AND sv.va_smartva_status = 'active'
    ORDER BY sv.va_smartva_updatedat DESC, sv.va_smartva_id DESC
    LIMIT 1
) AS smartva ON TRUE
WITH DATA
"""


def build_refresh_submission_analytics_mv_sql(
    *,
    view_name: str = MV_NAME,
    concurrently: bool = False,
) -> str:
    """Return the REFRESH MATERIALIZED VIEW statement."""
    concurrent_clause = " CONCURRENTLY" if concurrently else ""
    return f"REFRESH MATERIALIZED VIEW{concurrent_clause} {view_name}"


def _mv_scope_filter(mv, project_ids: list[str], project_site_pairs):
    """Return a WHERE clause scoped to the given project/project-site grants."""
    project_clause = sa.false()
    if project_ids:
        project_clause = mv.c.project_id.in_(project_ids)

    site_clause = sa.false()
    if project_site_pairs:
        site_clause = sa.tuple_(mv.c.project_id, mv.c.site_id).in_(
            list(project_site_pairs)
        )

    return sa.or_(project_clause, site_clause)


def _csv_values(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [value.strip() for value in raw.split(",") if value.strip()]


def build_dm_mv_filter_conditions(
    mv,
    *,
    project_ids: list[str],
    project_site_pairs,
    project: str = "",
    site: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    odk_status: str = "",
    smartva: str = "",
    age_group: str = "",
    gender: str = "",
    odk_sync: str = "",
    workflow: str = "",
):
    """Return MV filter conditions for the data-manager dashboard."""
    conditions = [_mv_scope_filter(mv, project_ids, project_site_pairs)]

    project_values = _csv_values(project)
    if project_values:
        conditions.append(mv.c.project_id.in_(project_values))

    site_values = _csv_values(site)
    if site_values:
        conditions.append(mv.c.site_id.in_(site_values))

    if date_from:
        conditions.append(mv.c.submission_date >= date_from)
    if date_to:
        conditions.append(mv.c.submission_date <= date_to)

    if odk_status == "hasIssues":
        conditions.append(mv.c.odk_review_state == "hasIssues")
    elif odk_status == "approved":
        conditions.append(mv.c.odk_review_state == "approved")
    elif odk_status == "no_review_state":
        conditions.append(mv.c.odk_review_state.is_(None))

    if smartva == "available":
        conditions.append(mv.c.has_smartva.is_(True))
    elif smartva == "missing":
        conditions.append(mv.c.has_smartva.is_(False))

    if age_group:
        conditions.append(mv.c.analytics_age_band == age_group)
    if gender:
        conditions.append(mv.c.sex == gender)

    if odk_sync == "missing_in_odk":
        conditions.append(mv.c.odk_sync_issue_code == "missing_in_odk")
    elif odk_sync == "in_sync":
        conditions.append(sa.or_(
            mv.c.odk_sync_issue_code.is_(None),
            mv.c.odk_sync_issue_code != "missing_in_odk",
        ))

    if workflow:
        if workflow == "pending_coding":
            conditions.append(mv.c.workflow_state.in_([
                WORKFLOW_SCREENING_PENDING,
                WORKFLOW_READY_FOR_CODING,
                WORKFLOW_CODING_IN_PROGRESS,
                WORKFLOW_CODER_STEP1_SAVED,
            ]))
        else:
            conditions.append(mv.c.workflow_state == workflow)

    return conditions


def get_dm_kpi_from_mv(
    project_ids: list[str],
    project_site_pairs,
    *,
    project: str = "",
    site: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    odk_status: str = "",
    smartva: str = "",
    age_group: str = "",
    gender: str = "",
    odk_sync: str = "",
    workflow: str = "",
) -> dict:
    """Return scoped KPI counts for the data-manager dashboard from the analytics MV."""
    mv = sa.table(
        MV_NAME,
        sa.column("project_id"),
        sa.column("site_id"),
        sa.column("submission_date"),
        sa.column("workflow_state"),
        sa.column("odk_review_state"),
        sa.column("has_smartva"),
        sa.column("analytics_age_band"),
        sa.column("sex"),
        sa.column("odk_sync_issue_code"),
    )
    conditions = build_dm_mv_filter_conditions(
        mv,
        project_ids=project_ids,
        project_site_pairs=project_site_pairs,
        project=project,
        site=site,
        date_from=date_from,
        date_to=date_to,
        odk_status=odk_status,
        smartva=smartva,
        age_group=age_group,
        gender=gender,
        odk_sync=odk_sync,
        workflow=workflow,
    )

    total = db.session.scalar(
        sa.select(sa.func.count()).select_from(mv).where(sa.and_(*conditions))
    ) or 0
    flagged = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(mv)
        .where(sa.and_(*conditions))
        .where(
            mv.c.workflow_state.in_(
                [WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER, WORKFLOW_NOT_CODEABLE_BY_CODER]
            )
        )
    ) or 0
    odk_issues = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(mv)
        .where(sa.and_(*conditions))
        .where(mv.c.odk_review_state == "hasIssues")
    ) or 0
    smartva_missing = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(mv)
        .where(sa.and_(*conditions))
        .where(mv.c.has_smartva.is_(False))
    ) or 0
    revoked = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(mv)
        .where(sa.and_(*conditions))
        .where(mv.c.workflow_state == WORKFLOW_FINALIZED_UPSTREAM_CHANGED)
    ) or 0
    coded = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(mv)
        .where(sa.and_(*conditions))
        .where(
            mv.c.workflow_state.in_(
                [
                    WORKFLOW_CODER_FINALIZED,
                    WORKFLOW_REVIEWER_ELIGIBLE,
                    WORKFLOW_REVIEWER_FINALIZED,
                    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
                ]
            )
        )
    ) or 0
    pending = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(mv)
        .where(sa.and_(*conditions))
        .where(mv.c.workflow_state.in_([
            WORKFLOW_SCREENING_PENDING,
            WORKFLOW_READY_FOR_CODING,
            WORKFLOW_CODING_IN_PROGRESS,
            WORKFLOW_CODER_STEP1_SAVED,
        ]))
    ) or 0

    consent_refused = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(mv)
        .where(sa.and_(*conditions))
        .where(mv.c.workflow_state == WORKFLOW_CONSENT_REFUSED)
    ) or 0

    # Per-state counts for the workflow flowchart — single GROUP BY query
    state_rows = db.session.execute(
        sa.select(mv.c.workflow_state, sa.func.count().label("cnt"))
        .select_from(mv)
        .where(sa.and_(*conditions))
        .group_by(mv.c.workflow_state)
    ).all()
    workflow_counts = {row.workflow_state: row.cnt for row in state_rows}

    return {
        "total_submissions": total,
        "coded_submissions": coded,
        "pending_submissions": pending,
        "flagged_submissions": flagged,
        "odk_has_issues_submissions": odk_issues,
        "smartva_missing_submissions": smartva_missing,
        "revoked_submissions": revoked,
        "consent_refused_submissions": consent_refused,
        "workflow_counts": workflow_counts,
    }


def get_dm_project_site_stats_from_mv(
    *,
    project_ids: list[str],
    project_site_pairs,
    timezone_name: str,
    project: str = "",
    site: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    odk_status: str = "",
    smartva: str = "",
    age_group: str = "",
    gender: str = "",
    odk_sync: str = "",
    workflow: str = "",
) -> list[dict]:
    """Return project/site submission stats for the data-manager dashboard."""
    import pytz
    from datetime import datetime, timedelta

    mv = sa.table(
        MV_NAME,
        sa.column("project_id"),
        sa.column("site_id"),
        sa.column("submission_at"),
        sa.column("submission_date"),
        sa.column("workflow_state"),
        sa.column("odk_review_state"),
        sa.column("has_smartva"),
        sa.column("analytics_age_band"),
        sa.column("sex"),
        sa.column("odk_sync_issue_code"),
    )

    user_tz = pytz.timezone(timezone_name or "Asia/Kolkata")
    now_local = datetime.now(user_tz)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start_local = today_start_local - timedelta(days=today_start_local.weekday())
    today_start_utc = today_start_local.astimezone(pytz.UTC)
    week_start_utc = week_start_local.astimezone(pytz.UTC)

    conditions = build_dm_mv_filter_conditions(
        mv,
        project_ids=project_ids,
        project_site_pairs=project_site_pairs,
        project=project,
        site=site,
        date_from=date_from,
        date_to=date_to,
        odk_status=odk_status,
        smartva=smartva,
        age_group=age_group,
        gender=gender,
        odk_sync=odk_sync,
        workflow=workflow,
    )

    rows = db.session.execute(
        sa.select(
            mv.c.project_id,
            mv.c.site_id,
            sa.func.count().label("total_submissions"),
            sa.func.sum(
                sa.case((mv.c.submission_at >= week_start_utc, 1), else_=0)
            ).label("this_week_submissions"),
            sa.func.sum(
                sa.case((mv.c.submission_at >= today_start_utc, 1), else_=0)
            ).label("today_submissions"),
        )
        .select_from(mv)
        .where(sa.and_(*conditions))
        .group_by(mv.c.project_id, mv.c.site_id)
        .order_by(mv.c.project_id, mv.c.site_id)
    ).mappings().all()

    return [
        {
            "project_id": row["project_id"],
            "site_id": row["site_id"],
            "total_submissions": row["total_submissions"] or 0,
            "this_week_submissions": row["this_week_submissions"] or 0,
            "today_submissions": row["today_submissions"] or 0,
        }
        for row in rows
    ]


def refresh_submission_analytics_mv(*, concurrently: bool = False) -> None:
    """Refresh the submission analytics materialized view."""
    sql = sa.text(
        build_refresh_submission_analytics_mv_sql(
            concurrently=concurrently,
        )
    )
    if concurrently:
        with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(sql)
        return

    db.session.execute(sql)
    db.session.commit()
