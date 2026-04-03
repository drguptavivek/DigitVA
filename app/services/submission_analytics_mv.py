"""Helpers for the submission analytics materialized views.

Three focused MVs replace the former single wide MV:

  va_submission_analytics_core_mv   — identifiers, timestamps, workflow, sync
  va_submission_analytics_demographics_mv — sex, age band, boolean flags
  va_submission_cod_detail_mv       — COD ICD codes, SmartVA results
"""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.services.workflow.definition import (
    WORKFLOW_ATTACHMENT_SYNC_PENDING,
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_CONSENT_REFUSED,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
    WORKFLOW_SCREENING_PENDING,
    WORKFLOW_SMARTVA_PENDING,
)

CORE_MV_NAME = "va_submission_analytics_core_mv"
DEMOGRAPHICS_MV_NAME = "va_submission_analytics_demographics_mv"
COD_MV_NAME = "va_submission_cod_detail_mv"

# Legacy alias so existing imports don't break immediately.
MV_NAME = CORE_MV_NAME

_DAYS_PER_MONTH = "30.4375"
_DAYS_PER_YEAR = "365.25"


# ---------------------------------------------------------------------------
# MV 1: Core — identifiers, timestamps, workflow, sync
# ---------------------------------------------------------------------------

def build_submission_analytics_core_mv_sql(
    view_name: str = CORE_MV_NAME,
) -> str:
    """Return the CREATE MATERIALIZED VIEW statement for the core analytics MV."""
    return f"""
CREATE MATERIALIZED VIEW {view_name} AS
SELECT
    s.va_sid,
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
    (w.workflow_state = '{WORKFLOW_FINALIZED_UPSTREAM_CHANGED}') AS cod_pending_upstream_review
FROM va_submissions s
JOIN va_forms f ON f.form_id = s.va_form_id
LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
WITH DATA
"""


# ---------------------------------------------------------------------------
# MV 2: Demographics — sex, age band, boolean flags
# ---------------------------------------------------------------------------

def build_submission_analytics_demographics_mv_sql(
    view_name: str = DEMOGRAPHICS_MV_NAME,
) -> str:
    """Return the CREATE MATERIALIZED VIEW statement for the demographics MV."""
    return f"""
CREATE MATERIALIZED VIEW {view_name} AS
WITH base AS (
    SELECT
        s.va_sid,
        s.va_deceased_gender AS sex,
        s.va_deceased_age_normalized_days,
        s.va_deceased_age_normalized_years,
        s.va_deceased_age_source,
        LOWER(NULLIF(BTRIM(COALESCE(pv.payload_data ->> 'age_group', '')), '')) AS age_group_raw,
        CASE
            WHEN NULLIF(BTRIM(COALESCE(pv.payload_data ->> 'age_neonate_hours', '')), '') ~ '^(-?\\d+)(\\.\\d+)?$'
                THEN (pv.payload_data ->> 'age_neonate_hours')::numeric
            ELSE NULL
        END AS age_neonate_hours_num,
        CASE
            WHEN NULLIF(BTRIM(COALESCE(pv.payload_data ->> 'age_neonate_days', '')), '') ~ '^(-?\\d+)(\\.\\d+)?$'
                THEN (pv.payload_data ->> 'age_neonate_days')::numeric
            ELSE NULL
        END AS age_neonate_days_num,
        CASE
            WHEN NULLIF(BTRIM(COALESCE(pv.payload_data ->> 'ageInDays', '')), '') ~ '^(-?\\d+)(\\.\\d+)?$'
                THEN (pv.payload_data ->> 'ageInDays')::numeric
            ELSE NULL
        END AS age_in_days_num,
        CASE
            WHEN NULLIF(BTRIM(COALESCE(pv.payload_data ->> 'ageInMonths', '')), '') ~ '^(-?\\d+)(\\.\\d+)?$'
                THEN (pv.payload_data ->> 'ageInMonths')::numeric
            ELSE NULL
        END AS age_in_months_num,
        CASE
            WHEN NULLIF(BTRIM(COALESCE(pv.payload_data ->> 'ageInYears', '')), '') ~ '^(-?\\d+)(\\.\\d+)?$'
                THEN (pv.payload_data ->> 'ageInYears')::numeric
            ELSE NULL
        END AS age_in_years_num,
        CASE
            WHEN NULLIF(BTRIM(COALESCE(pv.payload_data ->> 'ageInYears2', '')), '') ~ '^(-?\\d+)(\\.\\d+)?$'
                THEN (pv.payload_data ->> 'ageInYears2')::numeric
            ELSE NULL
        END AS age_in_years2_num,
        CASE
            WHEN NULLIF(BTRIM(COALESCE(pv.payload_data ->> 'finalAgeInYears', '')), '') ~ '^(-?\\d+)(\\.\\d+)?$'
                THEN (pv.payload_data ->> 'finalAgeInYears')::numeric
            ELSE NULL
        END AS final_age_years_num,
        COALESCE(pv.payload_data ->> 'isNeonatal', '') IN ('1', '1.0', 'true', 'True') AS is_neonatal,
        COALESCE(pv.payload_data ->> 'isChild', '') IN ('1', '1.0', 'true', 'True') AS is_child,
        COALESCE(pv.payload_data ->> 'isAdult', '') IN ('1', '1.0', 'true', 'True') AS is_adult
    FROM va_submissions s
    LEFT JOIN va_submission_payload_versions pv
        ON pv.payload_version_id = s.active_payload_version_id
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
        a.va_sid,
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
        ) AS normalized_age_days
    FROM age_source a
)
SELECT
    an.va_sid,
    b.sex,
    CASE
        WHEN an.normalized_age_days IS NOT NULL AND an.normalized_age_days <= 28 THEN 'neonate'
        WHEN an.normalized_age_years IS NULL THEN 'unknown'
        WHEN an.normalized_age_years < 15 THEN 'child'
        WHEN an.normalized_age_years < 50 THEN '15_49y'
        WHEN an.normalized_age_years < 65 THEN '50_64y'
        ELSE '65_plus'
    END AS analytics_age_band,
    (smartva.va_smartva_id IS NOT NULL) AS has_smartva,
    (init_assess.va_iniassess_id IS NOT NULL) AS has_human_initial_cod,
    (
        reviewer_final.va_rfinassess_id IS NOT NULL
        OR coder_final.va_finassess_id IS NOT NULL
    ) AS has_human_final_cod
FROM age_normalized an
JOIN base b ON b.va_sid = an.va_sid
-- EXISTS-style checks: only need to know IF a row exists, not fetch details
LEFT JOIN (
    SELECT DISTINCT ON (va_sid)
        va_sid, va_iniassess_id
    FROM va_initial_assessments
    WHERE va_iniassess_status = 'active'
    ORDER BY va_sid, va_iniassess_createdat DESC, va_iniassess_id DESC
) AS init_assess ON init_assess.va_sid = an.va_sid
LEFT JOIN (
    SELECT DISTINCT ON (va_sid)
        va_sid, va_rfinassess_id
    FROM (
        SELECT
            rf.va_sid, rf.va_rfinassess_id, rf.va_rfinassess_createdat,
            0 AS priority
        FROM va_final_cod_authority a
        JOIN va_reviewer_final_assessments rf
            ON rf.va_rfinassess_id = a.authoritative_reviewer_final_assessment_id
        WHERE a.authoritative_reviewer_final_assessment_id IS NOT NULL
        UNION ALL
        SELECT
            rf.va_sid, rf.va_rfinassess_id, rf.va_rfinassess_createdat,
            1 AS priority
        FROM va_reviewer_final_assessments rf
        WHERE rf.va_rfinassess_status = 'active'
    ) x
    ORDER BY va_sid, priority, va_rfinassess_createdat DESC, va_rfinassess_id DESC
) AS reviewer_final ON reviewer_final.va_sid = an.va_sid
LEFT JOIN (
    SELECT DISTINCT ON (va_sid)
        va_sid, va_finassess_id
    FROM (
        SELECT
            f.va_sid, f.va_finassess_id, f.va_finassess_createdat,
            0 AS priority
        FROM va_final_cod_authority a
        JOIN va_final_assessments f
            ON f.va_finassess_id = a.authoritative_final_assessment_id
        WHERE a.authoritative_final_assessment_id IS NOT NULL
        UNION ALL
        SELECT
            f.va_sid, f.va_finassess_id, f.va_finassess_createdat,
            1 AS priority
        FROM va_final_assessments f
        WHERE f.va_finassess_status = 'active'
    ) x
    ORDER BY va_sid, priority, va_finassess_createdat DESC, va_finassess_id DESC
) AS coder_final ON coder_final.va_sid = an.va_sid
LEFT JOIN (
    SELECT DISTINCT ON (va_sid)
        va_sid, va_smartva_id
    FROM va_smartva_results
    WHERE va_smartva_status = 'active'
    ORDER BY va_sid, va_smartva_updatedat DESC, va_smartva_id DESC
) AS smartva ON smartva.va_sid = an.va_sid
WITH DATA
"""


# ---------------------------------------------------------------------------
# MV 3: COD detail — ICD codes, SmartVA results
# ---------------------------------------------------------------------------

def build_submission_cod_detail_mv_sql(
    view_name: str = COD_MV_NAME,
) -> str:
    """Return the CREATE MATERIALIZED VIEW statement for the COD detail MV."""
    return f"""
CREATE MATERIALIZED VIEW {view_name} AS
SELECT
    s.va_sid,
    substring(init_assess.va_immediate_cod from '^([A-Z][0-9][0-9A-Z](?:\\.[0-9A-Z]+)?)')
        AS initial_immediate_icd,
    COALESCE(reviewer_final.va_conclusive_cod, coder_final.va_conclusive_cod) AS final_cod_text,
    substring(
        COALESCE(reviewer_final.va_conclusive_cod, coder_final.va_conclusive_cod)
        from '^([A-Z][0-9][0-9A-Z](?:\\.[0-9A-Z]+)?)'
    ) AS final_icd,
    smartva.va_smartva_age AS smartva_age,
    smartva.va_smartva_gender AS smartva_gender,
    smartva.va_smartva_resultfor AS smartva_result_for,
    smartva.va_smartva_cause1 AS smartva_cause1,
    smartva.va_smartva_cause1icd AS smartva_cause1_icd,
    smartva.va_smartva_cause2 AS smartva_cause2,
    smartva.va_smartva_cause2icd AS smartva_cause2_icd,
    smartva.va_smartva_cause3 AS smartva_cause3,
    smartva.va_smartva_cause3icd AS smartva_cause3_icd
FROM va_submissions s
LEFT JOIN (
    SELECT DISTINCT ON (va_sid)
        va_sid, va_immediate_cod
    FROM va_initial_assessments
    WHERE va_iniassess_status = 'active'
    ORDER BY va_sid, va_iniassess_createdat DESC, va_iniassess_id DESC
) AS init_assess ON init_assess.va_sid = s.va_sid
LEFT JOIN (
    SELECT DISTINCT ON (va_sid)
        va_sid, va_conclusive_cod
    FROM (
        SELECT
            rf.va_sid, rf.va_conclusive_cod, rf.va_rfinassess_createdat,
            0 AS priority
        FROM va_final_cod_authority a
        JOIN va_reviewer_final_assessments rf
            ON rf.va_rfinassess_id = a.authoritative_reviewer_final_assessment_id
        WHERE a.authoritative_reviewer_final_assessment_id IS NOT NULL
        UNION ALL
        SELECT
            rf.va_sid, rf.va_conclusive_cod, rf.va_rfinassess_createdat,
            1 AS priority
        FROM va_reviewer_final_assessments rf
        WHERE rf.va_rfinassess_status = 'active'
    ) x
    ORDER BY va_sid, priority, va_rfinassess_createdat DESC
) AS reviewer_final ON reviewer_final.va_sid = s.va_sid
LEFT JOIN (
    SELECT DISTINCT ON (va_sid)
        va_sid, va_conclusive_cod
    FROM (
        SELECT
            f.va_sid, f.va_conclusive_cod, f.va_finassess_createdat,
            0 AS priority
        FROM va_final_cod_authority a
        JOIN va_final_assessments f
            ON f.va_finassess_id = a.authoritative_final_assessment_id
        WHERE a.authoritative_final_assessment_id IS NOT NULL
        UNION ALL
        SELECT
            f.va_sid, f.va_conclusive_cod, f.va_finassess_createdat,
            1 AS priority
        FROM va_final_assessments f
        WHERE f.va_finassess_status = 'active'
    ) x
    ORDER BY va_sid, priority, va_finassess_createdat DESC
) AS coder_final ON coder_final.va_sid = s.va_sid
LEFT JOIN (
    SELECT DISTINCT ON (va_sid)
        va_sid,
        va_smartva_age,
        va_smartva_gender,
        va_smartva_resultfor,
        va_smartva_cause1,
        va_smartva_cause1icd,
        va_smartva_cause2,
        va_smartva_cause2icd,
        va_smartva_cause3,
        va_smartva_cause3icd
    FROM va_smartva_results
    WHERE va_smartva_status = 'active'
    ORDER BY va_sid, va_smartva_updatedat DESC, va_smartva_id DESC
) AS smartva ON smartva.va_sid = s.va_sid
WITH DATA
"""


# ---------------------------------------------------------------------------
# Refresh helpers
# ---------------------------------------------------------------------------

def _build_refresh_sql(view_name: str, *, concurrently: bool = False) -> str:
    """Return the REFRESH MATERIALIZED VIEW statement for a given MV."""
    concurrent_clause = " CONCURRENTLY" if concurrently else ""
    return f"REFRESH MATERIALIZED VIEW{concurrent_clause} {view_name}"


def _refresh_one(view_name: str, *, concurrently: bool = False) -> None:
    """Refresh a single materialized view."""
    sql = sa.text(_build_refresh_sql(view_name, concurrently=concurrently))
    if concurrently:
        with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(sql)
        return
    db.session.execute(sql)
    db.session.commit()


def refresh_submission_analytics_mv(*, concurrently: bool = False) -> None:
    """Refresh all three submission analytics materialized views."""
    for name in (CORE_MV_NAME, DEMOGRAPHICS_MV_NAME, COD_MV_NAME):
        _refresh_one(name, concurrently=concurrently)


# Backwards-compatible aliases
build_refresh_submission_analytics_mv_sql = _build_refresh_sql


def build_submission_analytics_mv_sql(view_name: str = "va_submission_analytics_mv") -> str:
    """Legacy builder for the old single analytics MV.

    Kept only so that already-applied migrations (cc77dd88ee99 and earlier)
    remain importable.  Do NOT use in new code.
    """
    # The original migration already ran against the database; this function
    # only needs to return syntactically-valid SQL so that `flask db current`
    # can import the migration file without crashing.  The actual DDL is not
    # re-executed unless a downgrade crosses this revision.
    return f"CREATE MATERIALIZED VIEW {view_name} AS SELECT 1::int AS x WITH DATA"


# ---------------------------------------------------------------------------
# Filter helpers (used by analytics routes and data-management queries)
# ---------------------------------------------------------------------------

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
    core,
    demo,
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
    """Return MV filter conditions for the data-manager dashboard.

    ``core`` is the table reference for the core MV (has project_id,
    site_id, submission_date, workflow_state, odk_review_state, odk_sync_issue_code).
    ``demo`` is the table reference for the demographics MV (has sex,
    analytics_age_band, has_smartva).
    """
    conditions = [_mv_scope_filter(core, project_ids, project_site_pairs)]

    project_values = _csv_values(project)
    if project_values:
        conditions.append(core.c.project_id.in_(project_values))

    site_values = _csv_values(site)
    if site_values:
        conditions.append(core.c.site_id.in_(site_values))

    if date_from:
        conditions.append(core.c.submission_date >= date_from)
    if date_to:
        conditions.append(core.c.submission_date <= date_to)
    if odk_status == "hasIssues":
        conditions.append(core.c.odk_review_state == "hasIssues")
    elif odk_status == "approved":
        conditions.append(core.c.odk_review_state == "approved")
    elif odk_status == "no_review_state":
        conditions.append(core.c.odk_review_state.is_(None))
    if smartva == "available":
        conditions.append(demo.c.has_smartva.is_(True))
    elif smartva == "missing":
        conditions.append(demo.c.has_smartva.is_(False))
    if age_group:
        conditions.append(demo.c.analytics_age_band == age_group)
    if gender:
        conditions.append(demo.c.sex == gender)
    if odk_sync == "missing_in_odk":
        conditions.append(core.c.odk_sync_issue_code == "missing_in_odk")
    elif odk_sync == "in_sync":
        conditions.append(sa.or_(
            core.c.odk_sync_issue_code.is_(None),
            core.c.odk_sync_issue_code != "missing_in_odk",
        ))
    if workflow:
        if workflow == "pending_coding":
            conditions.append(core.c.workflow_state.in_([
                WORKFLOW_READY_FOR_CODING,
                WORKFLOW_CODING_IN_PROGRESS,
                WORKFLOW_CODER_STEP1_SAVED,
            ]))
        elif workflow == "coded":
            conditions.append(core.c.workflow_state.in_([
                WORKFLOW_CODER_FINALIZED,
                WORKFLOW_REVIEWER_ELIGIBLE,
                WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
                WORKFLOW_REVIEWER_FINALIZED,
            ]))
        else:
            conditions.append(core.c.workflow_state == workflow)
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
    """Return scoped KPI counts for the data-manager dashboard from the analytics MVs."""
    core = sa.table(
        CORE_MV_NAME,
        sa.column("va_sid"),
        sa.column("project_id"),
        sa.column("site_id"),
        sa.column("submission_date"),
        sa.column("workflow_state"),
        sa.column("odk_review_state"),
        sa.column("odk_sync_issue_code"),
    )
    demo = sa.table(
        DEMOGRAPHICS_MV_NAME,
        sa.column("va_sid"),
        sa.column("analytics_age_band"),
        sa.column("sex"),
        sa.column("has_smartva"),
    )

    conditions = build_dm_mv_filter_conditions(
        core,
        demo,
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

    joined = core.join(demo, core.c.va_sid == demo.c.va_sid)
    where = sa.and_(*conditions)

    total = db.session.scalar(
        sa.select(sa.func.count()).select_from(joined).where(where)
    ) or 0
    flagged = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(joined)
        .where(where)
        .where(
            core.c.workflow_state.in_(
                [WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER, WORKFLOW_NOT_CODEABLE_BY_CODER]
            )
        )
    ) or 0
    odk_issues = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(joined)
        .where(where)
        .where(core.c.odk_review_state == "hasIssues")
    ) or 0
    smartva_missing = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(joined)
        .where(where)
        .where(demo.c.has_smartva.is_(False))
    ) or 0
    revoked = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(joined)
        .where(where)
        .where(core.c.workflow_state == WORKFLOW_FINALIZED_UPSTREAM_CHANGED)
    ) or 0
    coded = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(joined)
        .where(where)
        .where(
            core.c.workflow_state.in_(
                [
                    WORKFLOW_CODER_FINALIZED,
                    WORKFLOW_REVIEWER_ELIGIBLE,
                    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
                    WORKFLOW_REVIEWER_FINALIZED,
                    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
                ]
            )
        )
    ) or 0
    pending = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(joined)
        .where(where)
        .where(core.c.workflow_state.in_([
            WORKFLOW_READY_FOR_CODING,
            WORKFLOW_CODING_IN_PROGRESS,
            WORKFLOW_CODER_STEP1_SAVED,
        ]))
    ) or 0

    consent_refused = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(joined)
        .where(where)
        .where(core.c.workflow_state == WORKFLOW_CONSENT_REFUSED)
    ) or 0

    # Per-state counts for the workflow flowchart — single GROUP BY query
    state_rows = db.session.execute(
        sa.select(core.c.workflow_state, sa.func.count().label("cnt"))
        .select_from(joined)
        .where(where)
        .group_by(core.c.workflow_state)
    ).all()
    workflow_counts = {row.workflow_state: row.cnt for row in state_rows}

    return {
        "total_submissions": total,
        "coded_submissions": coded,
        "pending_submissions": pending,
        "smartva_pending_submissions": workflow_counts.get(WORKFLOW_SMARTVA_PENDING, 0),
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

    core = sa.table(
        CORE_MV_NAME,
        sa.column("va_sid"),
        sa.column("project_id"),
        sa.column("site_id"),
        sa.column("submission_at"),
        sa.column("submission_date"),
        sa.column("workflow_state"),
        sa.column("odk_review_state"),
        sa.column("odk_sync_issue_code"),
    )
    demo = sa.table(
        DEMOGRAPHICS_MV_NAME,
        sa.column("va_sid"),
        sa.column("analytics_age_band"),
        sa.column("sex"),
        sa.column("has_smartva"),
    )

    user_tz = pytz.timezone(timezone_name or "Asia/Kolkata")
    now_local = datetime.now(user_tz)
    today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start_local = today_start_local - timedelta(days=today_start_local.weekday())
    today_start_utc = today_start_local.astimezone(pytz.UTC)
    week_start_utc = week_start_local.astimezone(pytz.UTC)

    conditions = build_dm_mv_filter_conditions(
        core,
        demo,
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

    joined = core.join(demo, core.c.va_sid == demo.c.va_sid)

    rows = db.session.execute(
        sa.select(
            core.c.project_id,
            core.c.site_id,
            sa.func.count().label("total_submissions"),
            sa.func.sum(
                sa.case((core.c.submission_at >= week_start_utc, 1), else_=0)
            ).label("this_week_submissions"),
            sa.func.sum(
                sa.case((core.c.submission_at >= today_start_utc, 1), else_=0)
            ).label("today_submissions"),
        )
        .select_from(joined)
        .where(sa.and_(*conditions))
        .group_by(core.c.project_id, core.c.site_id)
        .order_by(core.c.project_id, core.c.site_id)
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
