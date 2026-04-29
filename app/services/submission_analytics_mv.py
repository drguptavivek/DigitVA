"""Helpers for the submission analytics materialized views.

Three focused MVs replace the former single wide MV:

  va_submission_analytics_core_mv   — identifiers, timestamps, workflow, sync
  va_submission_analytics_demographics_mv — sex, age band, boolean flags
  va_submission_cod_detail_mv       — COD ICD codes, SmartVA results
  va_submission_cod_snapshot_mv     — active COD/export snapshot
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
COD_SNAPSHOT_MV_NAME = "va_submission_cod_snapshot_mv"

# Legacy alias so existing imports don't break immediately.
MV_NAME = CORE_MV_NAME

_DAYS_PER_MONTH = "30.4375"
_DAYS_PER_YEAR = "365.25"
_WHO_2022_SCHEME_CODE = "WHO_2022_VA"


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
    COALESCE(ps.project_id, f.project_id) AS project_id,
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
LEFT JOIN va_project_sites ps
    ON ps.site_id = f.site_id AND ps.project_site_status = 'active'
LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
WITH DATA
"""


# ---------------------------------------------------------------------------
# MV 2: Demographics — sex, age band, boolean flags
# ---------------------------------------------------------------------------

def build_submission_analytics_demographics_mv_sql(
    view_name: str = DEMOGRAPHICS_MV_NAME,
) -> str:
    """Return the CREATE MATERIALIZED VIEW statement for the demographics MV.

    Age band is derived entirely from the pre-computed columns on va_submissions
    (va_deceased_age_normalized_days, va_deceased_age_normalized_years) — no join
    to va_submission_payload_versions is needed.  The old 3-CTE JSONB extraction
    path was redundant for 99.7% of rows once those columns were backfilled by
    migration d2f6a8b9c1e3.
    """
    return f"""
CREATE MATERIALIZED VIEW {view_name} AS
SELECT
    s.va_sid,
    s.va_narration_language,
    s.va_deceased_gender AS sex,
    s.va_deceased_age_normalized_days AS analytics_age_normalized_days,
    CASE
        WHEN s.va_deceased_age_normalized_days IS NOT NULL
             AND s.va_deceased_age_normalized_days <= 28 THEN 'neonate'
        WHEN s.va_deceased_age_normalized_years IS NULL  THEN 'unknown'
        WHEN s.va_deceased_age_normalized_years < 15     THEN 'child'
        WHEN s.va_deceased_age_normalized_years < 50     THEN '15_49y'
        WHEN s.va_deceased_age_normalized_years < 65     THEN '50_64y'
        ELSE '65_plus'
    END AS analytics_age_band,
    (smartva.va_smartva_id IS NOT NULL)        AS has_smartva,
    (init_assess.va_iniassess_id IS NOT NULL)  AS has_human_initial_cod,
    (
        reviewer_final.va_rfinassess_id IS NOT NULL
        OR coder_final.va_finassess_id IS NOT NULL
    ) AS has_human_final_cod
FROM va_submissions s
LEFT JOIN (
    SELECT DISTINCT ON (va_sid)
        va_sid, va_iniassess_id
    FROM va_initial_assessments
    WHERE va_iniassess_status = 'active'
    ORDER BY va_sid, va_iniassess_createdat DESC, va_iniassess_id DESC
) AS init_assess ON init_assess.va_sid = s.va_sid
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
) AS reviewer_final ON reviewer_final.va_sid = s.va_sid
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
) AS coder_final ON coder_final.va_sid = s.va_sid
LEFT JOIN (
    SELECT DISTINCT ON (va_sid)
        va_sid, va_smartva_id
    FROM va_smartva_results
    WHERE va_smartva_status = 'active'
    ORDER BY va_sid, va_smartva_updatedat DESC, va_smartva_id DESC
) AS smartva ON smartva.va_sid = s.va_sid
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
# MV 4: COD snapshot — active export/reporting snapshot
# ---------------------------------------------------------------------------

def build_submission_cod_snapshot_mv_sql(
    view_name: str = COD_SNAPSHOT_MV_NAME,
) -> str:
    """Return the CREATE MATERIALIZED VIEW statement for the COD snapshot MV."""
    return f"""
CREATE MATERIALIZED VIEW {view_name} AS
WITH active_payload AS (
    SELECT
        s.va_sid,
        s.active_payload_version_id,
        p.payload_data
    FROM va_submissions s
    LEFT JOIN va_submission_payload_versions p
        ON p.payload_version_id = s.active_payload_version_id
),
latest_initial AS (
    SELECT DISTINCT ON (va_sid)
        va_sid,
        va_iniassess_id,
        va_iniassess_by,
        va_immediate_cod,
        va_antecedent_cod,
        va_other_conditions,
        va_iniassess_createdat,
        va_iniassess_updatedat
    FROM va_initial_assessments
    WHERE va_iniassess_status = 'active'
    ORDER BY va_sid, va_iniassess_createdat DESC, va_iniassess_id DESC
),
latest_coder_final AS (
    SELECT DISTINCT ON (va_sid)
        va_sid,
        va_finassess_id,
        payload_version_id,
        va_finassess_by,
        va_conclusive_cod,
        va_finassess_remark,
        va_finassess_createdat,
        va_finassess_updatedat
    FROM va_final_assessments
    WHERE va_finassess_status = 'active'
    ORDER BY va_sid, va_finassess_createdat DESC, va_finassess_id DESC
),
latest_reviewer_final AS (
    SELECT DISTINCT ON (va_sid)
        va_sid,
        va_rfinassess_id,
        payload_version_id,
        va_rfinassess_by,
        va_conclusive_cod,
        va_rfinassess_remark,
        va_rfinassess_createdat,
        va_rfinassess_updatedat
    FROM va_reviewer_final_assessments
    WHERE va_rfinassess_status = 'active'
    ORDER BY va_sid, va_rfinassess_createdat DESC, va_rfinassess_id DESC
),
authoritative_coder AS (
    SELECT
        a.va_sid,
        f.va_finassess_id,
        f.payload_version_id,
        f.va_finassess_by,
        f.va_conclusive_cod,
        f.va_finassess_remark,
        f.va_finassess_createdat,
        f.va_finassess_updatedat
    FROM va_final_cod_authority a
    JOIN va_final_assessments f
        ON f.va_finassess_id = a.authoritative_final_assessment_id
),
authoritative_reviewer AS (
    SELECT
        a.va_sid,
        rf.va_rfinassess_id,
        rf.payload_version_id,
        rf.va_rfinassess_by,
        rf.va_conclusive_cod,
        rf.va_rfinassess_remark,
        rf.va_rfinassess_createdat,
        rf.va_rfinassess_updatedat
    FROM va_final_cod_authority a
    JOIN va_reviewer_final_assessments rf
        ON rf.va_rfinassess_id = a.authoritative_reviewer_final_assessment_id
),
latest_smartva AS (
    SELECT DISTINCT ON (va_sid)
        va_sid,
        payload_version_id,
        va_smartva_resultfor,
        va_smartva_age,
        va_smartva_gender,
        va_smartva_cause1,
        va_smartva_cause1icd,
        va_smartva_cause2,
        va_smartva_cause2icd,
        va_smartva_cause3,
        va_smartva_cause3icd,
        va_smartva_likelihood1,
        va_smartva_likelihood2,
        va_smartva_likelihood3,
        va_smartva_keysymptom1,
        va_smartva_keysymptom2,
        va_smartva_keysymptom3,
        va_smartva_allsymptoms,
        va_smartva_outcome,
        va_smartva_failure_stage,
        va_smartva_failure_detail,
        va_smartva_addedat,
        va_smartva_updatedat
    FROM va_smartva_results
    WHERE va_smartva_status = 'active'
    ORDER BY va_sid, va_smartva_updatedat DESC, va_smartva_id DESC
),
latest_nqa AS (
    SELECT DISTINCT ON (n.va_sid)
        n.va_sid,
        n.va_nqa_id,
        n.va_nqa_by,
        n.va_nqa_length,
        n.va_nqa_pos_symptoms,
        n.va_nqa_neg_symptoms,
        n.va_nqa_chronology,
        n.va_nqa_doc_review,
        n.va_nqa_comorbidity,
        n.va_nqa_score,
        n.va_nqa_cannot_grade,
        n.va_nqa_createdat,
        n.va_nqa_updatedat
    FROM va_narrative_assessments n
    JOIN active_payload ap
        ON ap.va_sid = n.va_sid
       AND ap.active_payload_version_id IS NOT DISTINCT FROM n.payload_version_id
    WHERE n.va_nqa_status = 'active'
    ORDER BY n.va_sid, n.va_nqa_createdat DESC, n.va_nqa_id DESC
),
social_autopsy_options AS (
    SELECT
        va_saa_id,
        string_agg(delay_level || '::' || option_code, ';' ORDER BY delay_level, option_code)
            AS option_pairs
    FROM va_social_autopsy_analysis_options
    GROUP BY va_saa_id
),
latest_social_autopsy AS (
    SELECT DISTINCT ON (saa.va_sid)
        saa.va_sid,
        saa.va_saa_id,
        saa.va_saa_by,
        saa.va_saa_remark,
        saa.va_saa_createdat,
        saa.va_saa_updatedat,
        sao.option_pairs
    FROM va_social_autopsy_analyses saa
    JOIN active_payload ap
        ON ap.va_sid = saa.va_sid
       AND ap.active_payload_version_id IS NOT DISTINCT FROM saa.payload_version_id
    LEFT JOIN social_autopsy_options sao
        ON sao.va_saa_id = saa.va_saa_id
    WHERE saa.va_saa_status = 'active'
    ORDER BY saa.va_sid, saa.va_saa_createdat DESC, saa.va_saa_id DESC
),
active_coding_allocation AS (
    SELECT DISTINCT ON (va_sid)
        va_sid,
        va_allocated_to,
        va_allocation_createdat,
        va_allocation_updatedat
    FROM va_allocations
    WHERE va_allocation_status = 'active'
      AND va_allocation_for = 'coding'
    ORDER BY va_sid, va_allocation_updatedat DESC, va_allocation_id DESC
),
active_reviewer_allocation AS (
    SELECT DISTINCT ON (va_sid)
        va_sid,
        va_allocated_to,
        va_allocation_createdat,
        va_allocation_updatedat
    FROM va_allocations
    WHERE va_allocation_status = 'active'
      AND va_allocation_for = 'reviewing'
    ORDER BY va_sid, va_allocation_updatedat DESC, va_allocation_id DESC
),
legacy_reporting_alias AS (
    SELECT
        upper(legacy_code) AS legacy_code,
        upper(reporting_code) AS reporting_code
    FROM map_icd10_legacy_reporting_aliases
),
who_2022_buckets AS (
    SELECT DISTINCT ON (upper(map.icd_code))
        upper(map.icd_code) AS icd_code,
        parent.node_label AS bucket_section,
        leaf.node_label AS bucket_label
    FROM mas_cod_bucket_schemes scheme
    JOIN map_icd_cod_buckets map
        ON map.scheme_id = scheme.scheme_id
       AND map.is_active IS TRUE
       AND map.age_scope IS NULL
    JOIN mas_cod_bucket_nodes leaf
        ON leaf.node_id = map.node_id
       AND leaf.is_active IS TRUE
    LEFT JOIN mas_cod_bucket_nodes parent
        ON parent.node_id = leaf.parent_node_id
       AND parent.is_active IS TRUE
    WHERE scheme.scheme_code = '{_WHO_2022_SCHEME_CODE}'
      AND scheme.is_active IS TRUE
    ORDER BY
        upper(map.icd_code),
        COALESCE(parent.sort_order, 0),
        leaf.sort_order,
        map.created_at,
        map.mapping_id
),
coder_actor AS (
    SELECT
        s.va_sid,
        COALESCE(cf.va_finassess_by, ini.va_iniassess_by, nqa.va_nqa_by, saa.va_saa_by, ca.va_allocated_to) AS user_id
    FROM va_submissions s
    LEFT JOIN latest_coder_final cf ON cf.va_sid = s.va_sid
    LEFT JOIN latest_initial ini ON ini.va_sid = s.va_sid
    LEFT JOIN latest_nqa nqa ON nqa.va_sid = s.va_sid
    LEFT JOIN latest_social_autopsy saa ON saa.va_sid = s.va_sid
    LEFT JOIN active_coding_allocation ca ON ca.va_sid = s.va_sid
)
SELECT
    s.va_sid,
    f.project_id,
    f.site_id,
    s.va_form_id AS form_id,
    s.active_payload_version_id,
    s.va_submission_date AS submission_at,
    DATE(s.va_submission_date) AS submission_date,
    w.workflow_state,
    s.va_narration_language AS narration_language,
    s.va_deceased_gender AS sex,
    s.va_deceased_age AS age_raw,
    s.va_deceased_age_normalized_days AS age_normalized_days,
    s.va_deceased_age_normalized_years AS age_normalized_years,
    s.va_deceased_age_source AS age_source,
    COALESCE(
        ap.payload_data ->> 'Id10476',
        ap.payload_data ->> 'narration',
        ap.payload_data ->> 'Narrative Text'
    ) AS narrative_text,
    ca.user_id AS coder_user_id,
    coder_user.name AS coder_name,
    ini.va_iniassess_id AS coder_step1_assessment_id,
    ini.va_iniassess_by AS coder_step1_by,
    ini.va_immediate_cod AS coder_step1_immediate_cod,
    ini.va_antecedent_cod AS coder_step1_antecedent_cod,
    ini.va_other_conditions AS coder_step1_other_conditions,
    ini.va_iniassess_createdat AS coder_step1_saved_at,
    ini.va_iniassess_updatedat AS coder_step1_updated_at,
    cf.va_finassess_id AS coder_final_assessment_id,
    cf.va_finassess_by AS coder_final_by,
    cf.va_conclusive_cod AS coder_final_cod_text,
    substring(cf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\\.[0-9A-Z]+)?)') AS coder_final_icd,
    cf.va_finassess_remark AS coder_final_remark,
    cf.va_finassess_createdat AS coder_final_saved_at,
    cf.va_finassess_updatedat AS coder_final_updated_at,
    reviewer_user.user_id AS reviewer_user_id,
    reviewer_user.name AS reviewer_name,
    rf.va_rfinassess_id AS reviewer_final_assessment_id,
    rf.va_rfinassess_by AS reviewer_final_by,
    rf.va_conclusive_cod AS reviewer_final_cod_text,
    substring(rf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\\.[0-9A-Z]+)?)') AS reviewer_final_icd,
    rf.va_rfinassess_remark AS reviewer_final_remark,
    rf.va_rfinassess_createdat AS reviewer_final_saved_at,
    rf.va_rfinassess_updatedat AS reviewer_final_updated_at,
    CASE
        WHEN ar.va_sid IS NOT NULL THEN 'reviewer'
        WHEN ac.va_sid IS NOT NULL THEN 'coder'
        WHEN rf.va_rfinassess_id IS NOT NULL THEN 'reviewer'
        WHEN cf.va_finassess_id IS NOT NULL THEN 'coder'
        ELSE NULL
    END AS authoritative_source,
    CASE
        WHEN ar.va_sid IS NOT NULL THEN ar.va_conclusive_cod
        WHEN ac.va_sid IS NOT NULL THEN ac.va_conclusive_cod
        WHEN rf.va_rfinassess_id IS NOT NULL THEN rf.va_conclusive_cod
        WHEN cf.va_finassess_id IS NOT NULL THEN cf.va_conclusive_cod
        ELSE NULL
    END AS authoritative_cod_text,
    substring(
        CASE
            WHEN ar.va_sid IS NOT NULL THEN ar.va_conclusive_cod
            WHEN ac.va_sid IS NOT NULL THEN ac.va_conclusive_cod
            WHEN rf.va_rfinassess_id IS NOT NULL THEN rf.va_conclusive_cod
            WHEN cf.va_finassess_id IS NOT NULL THEN cf.va_conclusive_cod
            ELSE NULL
        END
        from '^([A-Z][0-9][0-9A-Z](?:\\.[0-9A-Z]+)?)'
    ) AS authoritative_icd,
    CASE
        WHEN ar.va_sid IS NOT NULL THEN ar.va_rfinassess_createdat
        WHEN ac.va_sid IS NOT NULL THEN ac.va_finassess_createdat
        WHEN rf.va_rfinassess_id IS NOT NULL THEN rf.va_rfinassess_createdat
        WHEN cf.va_finassess_id IS NOT NULL THEN cf.va_finassess_createdat
        ELSE NULL
    END AS authoritative_saved_at,
    CASE
        WHEN ar.va_sid IS NOT NULL THEN ar.va_rfinassess_createdat
        WHEN ac.va_sid IS NOT NULL THEN ac.va_finassess_createdat
        WHEN rf.va_rfinassess_id IS NOT NULL THEN rf.va_rfinassess_createdat
        WHEN cf.va_finassess_id IS NOT NULL THEN cf.va_finassess_createdat
        ELSE NULL
    END AS coded_at_authoritative,
    ls.va_smartva_resultfor AS smartva_result_for,
    ls.va_smartva_age AS smartva_age,
    ls.va_smartva_gender AS smartva_gender,
    ls.va_smartva_cause1 AS smartva_cause1,
    upper(ls.va_smartva_cause1icd) AS smartva_cause1_icd,
    ls.va_smartva_cause2 AS smartva_cause2,
    upper(ls.va_smartva_cause2icd) AS smartva_cause2_icd,
    ls.va_smartva_cause3 AS smartva_cause3,
    upper(ls.va_smartva_cause3icd) AS smartva_cause3_icd,
    ls.va_smartva_likelihood1 AS smartva_likelihood1,
    ls.va_smartva_likelihood2 AS smartva_likelihood2,
    ls.va_smartva_likelihood3 AS smartva_likelihood3,
    ls.va_smartva_keysymptom1 AS smartva_keysymptom1,
    ls.va_smartva_keysymptom2 AS smartva_keysymptom2,
    ls.va_smartva_keysymptom3 AS smartva_keysymptom3,
    ls.va_smartva_allsymptoms AS smartva_all_symptoms,
    ls.va_smartva_outcome AS smartva_outcome,
    ls.va_smartva_failure_stage AS smartva_failure_stage,
    ls.va_smartva_failure_detail AS smartva_failure_detail,
    ls.va_smartva_addedat AS smartva_saved_at,
    ls.va_smartva_updatedat AS smartva_updated_at,
    nqa.va_nqa_by AS nqa_user_id,
    nqa_user.name AS nqa_name,
    nqa.va_nqa_length AS nqa_length,
    nqa.va_nqa_pos_symptoms AS nqa_pos_symptoms,
    nqa.va_nqa_neg_symptoms AS nqa_neg_symptoms,
    nqa.va_nqa_chronology AS nqa_chronology,
    nqa.va_nqa_doc_review AS nqa_doc_review,
    nqa.va_nqa_comorbidity AS nqa_comorbidity,
    nqa.va_nqa_score AS nqa_score,
    nqa.va_nqa_cannot_grade AS nqa_cannot_grade,
    CASE
        WHEN nqa.va_nqa_cannot_grade IS TRUE THEN 'Cannot Grade'
        WHEN nqa.va_nqa_score >= 7 THEN 'Good'
        WHEN nqa.va_nqa_score >= 5 THEN 'Fair'
        WHEN nqa.va_nqa_score IS NOT NULL THEN 'Poor'
        ELSE NULL
    END AS nqa_rating,
    nqa.va_nqa_createdat AS nqa_saved_at,
    nqa.va_nqa_updatedat AS nqa_updated_at,
    saa.va_saa_by AS social_autopsy_user_id,
    saa_user.name AS social_autopsy_name,
    saa.va_saa_remark AS social_autopsy_remark,
    saa.option_pairs AS social_autopsy_option_pairs,
    saa.va_saa_createdat AS social_autopsy_saved_at,
    saa.va_saa_updatedat AS social_autopsy_updated_at,
    coding_alloc.va_allocated_to AS active_coder_assigned_user_id,
    coding_alloc_user.name AS active_coder_assigned_name,
    reviewing_alloc.va_allocated_to AS active_reviewer_assigned_user_id,
    reviewing_alloc_user.name AS active_reviewer_assigned_name,
    coder_bucket.bucket_section AS coder_final_who_bucket_section,
    coder_bucket.bucket_label AS coder_final_who_bucket,
    reviewer_bucket.bucket_section AS reviewer_final_who_bucket_section,
    reviewer_bucket.bucket_label AS reviewer_final_who_bucket,
    auth_bucket.bucket_section AS authoritative_who_bucket_section,
    auth_bucket.bucket_label AS authoritative_who_bucket,
    smartva1_bucket.bucket_section AS smartva_cause1_who_bucket_section,
    smartva1_bucket.bucket_label AS smartva_cause1_who_bucket,
    smartva2_bucket.bucket_section AS smartva_cause2_who_bucket_section,
    smartva2_bucket.bucket_label AS smartva_cause2_who_bucket,
    smartva3_bucket.bucket_section AS smartva_cause3_who_bucket_section,
    smartva3_bucket.bucket_label AS smartva_cause3_who_bucket
FROM va_submissions s
JOIN va_forms f ON f.form_id = s.va_form_id
LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
LEFT JOIN active_payload ap ON ap.va_sid = s.va_sid
LEFT JOIN latest_initial ini ON ini.va_sid = s.va_sid
LEFT JOIN latest_coder_final cf ON cf.va_sid = s.va_sid
LEFT JOIN latest_reviewer_final rf ON rf.va_sid = s.va_sid
LEFT JOIN authoritative_coder ac ON ac.va_sid = s.va_sid
LEFT JOIN authoritative_reviewer ar ON ar.va_sid = s.va_sid
LEFT JOIN latest_smartva ls ON ls.va_sid = s.va_sid
LEFT JOIN latest_nqa nqa ON nqa.va_sid = s.va_sid
LEFT JOIN latest_social_autopsy saa ON saa.va_sid = s.va_sid
LEFT JOIN active_coding_allocation coding_alloc ON coding_alloc.va_sid = s.va_sid
LEFT JOIN active_reviewer_allocation reviewing_alloc ON reviewing_alloc.va_sid = s.va_sid
LEFT JOIN coder_actor ca ON ca.va_sid = s.va_sid
LEFT JOIN va_users coder_user ON coder_user.user_id = ca.user_id
LEFT JOIN va_users reviewer_user ON reviewer_user.user_id = rf.va_rfinassess_by
LEFT JOIN va_users nqa_user ON nqa_user.user_id = nqa.va_nqa_by
LEFT JOIN va_users saa_user ON saa_user.user_id = saa.va_saa_by
LEFT JOIN va_users coding_alloc_user ON coding_alloc_user.user_id = coding_alloc.va_allocated_to
LEFT JOIN va_users reviewing_alloc_user ON reviewing_alloc_user.user_id = reviewing_alloc.va_allocated_to
LEFT JOIN legacy_reporting_alias coder_icd_alias
    ON coder_icd_alias.legacy_code = substring(cf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\\.[0-9A-Z]+)?)')
LEFT JOIN legacy_reporting_alias reviewer_icd_alias
    ON reviewer_icd_alias.legacy_code = substring(rf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\\.[0-9A-Z]+)?)')
LEFT JOIN legacy_reporting_alias auth_icd_alias
    ON auth_icd_alias.legacy_code = substring(
        CASE
            WHEN ar.va_sid IS NOT NULL THEN ar.va_conclusive_cod
            WHEN ac.va_sid IS NOT NULL THEN ac.va_conclusive_cod
            WHEN rf.va_rfinassess_id IS NOT NULL THEN rf.va_conclusive_cod
            WHEN cf.va_finassess_id IS NOT NULL THEN cf.va_conclusive_cod
            ELSE NULL
        END
        from '^([A-Z][0-9][0-9A-Z](?:\\.[0-9A-Z]+)?)'
    )
LEFT JOIN legacy_reporting_alias smartva1_icd_alias
    ON smartva1_icd_alias.legacy_code = upper(ls.va_smartva_cause1icd)
LEFT JOIN legacy_reporting_alias smartva2_icd_alias
    ON smartva2_icd_alias.legacy_code = upper(ls.va_smartva_cause2icd)
LEFT JOIN legacy_reporting_alias smartva3_icd_alias
    ON smartva3_icd_alias.legacy_code = upper(ls.va_smartva_cause3icd)
LEFT JOIN who_2022_buckets coder_bucket
    ON coder_bucket.icd_code = COALESCE(
        coder_icd_alias.reporting_code,
        substring(cf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\\.[0-9A-Z]+)?)')
    )
LEFT JOIN who_2022_buckets reviewer_bucket
    ON reviewer_bucket.icd_code = COALESCE(
        reviewer_icd_alias.reporting_code,
        substring(rf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\\.[0-9A-Z]+)?)')
    )
LEFT JOIN who_2022_buckets auth_bucket
    ON auth_bucket.icd_code = COALESCE(
        auth_icd_alias.reporting_code,
        substring(
            CASE
                WHEN ar.va_sid IS NOT NULL THEN ar.va_conclusive_cod
                WHEN ac.va_sid IS NOT NULL THEN ac.va_conclusive_cod
                WHEN rf.va_rfinassess_id IS NOT NULL THEN rf.va_conclusive_cod
                WHEN cf.va_finassess_id IS NOT NULL THEN cf.va_conclusive_cod
                ELSE NULL
            END
            from '^([A-Z][0-9][0-9A-Z](?:\\.[0-9A-Z]+)?)'
        )
    )
LEFT JOIN who_2022_buckets smartva1_bucket
    ON smartva1_bucket.icd_code = COALESCE(smartva1_icd_alias.reporting_code, upper(ls.va_smartva_cause1icd))
LEFT JOIN who_2022_buckets smartva2_bucket
    ON smartva2_bucket.icd_code = COALESCE(smartva2_icd_alias.reporting_code, upper(ls.va_smartva_cause2icd))
LEFT JOIN who_2022_buckets smartva3_bucket
    ON smartva3_bucket.icd_code = COALESCE(smartva3_icd_alias.reporting_code, upper(ls.va_smartva_cause3icd))
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
    exists = db.session.execute(
        sa.text("SELECT to_regclass(:view_name)"),
        {"view_name": view_name},
    ).scalar_one()
    if not exists:
        return
    sql = sa.text(_build_refresh_sql(view_name, concurrently=concurrently))
    if concurrently:
        with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            conn.execute(sql)
        return
    db.session.execute(sql)
    db.session.commit()


def refresh_submission_analytics_mv(*, concurrently: bool = False) -> None:
    """Refresh all analytics/reporting materialized views."""
    for name in (CORE_MV_NAME, DEMOGRAPHICS_MV_NAME, COD_MV_NAME, COD_SNAPSHOT_MV_NAME):
        _refresh_one(name, concurrently=concurrently)


def ensure_submission_cod_snapshot_mv() -> None:
    """Create the COD snapshot MV on demand if it does not yet exist.

    This keeps the export endpoint operational on environments where the code
    has been deployed before the migration has been applied. Once created,
    normal refresh flows maintain the MV contents.
    """
    exists = db.session.execute(
        sa.text("SELECT to_regclass(:view_name)"),
        {"view_name": COD_SNAPSHOT_MV_NAME},
    ).scalar_one()
    if exists:
        return

    db.session.execute(sa.text(build_submission_cod_snapshot_mv_sql()))
    db.session.execute(
        sa.text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_va_submission_cod_snapshot_mv_va_sid "
            f"ON {COD_SNAPSHOT_MV_NAME} (va_sid)"
        )
    )
    db.session.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_va_submission_cod_snapshot_mv_project_site "
            f"ON {COD_SNAPSHOT_MV_NAME} (project_id, site_id)"
        )
    )
    db.session.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_va_submission_cod_snapshot_mv_workflow_state "
            f"ON {COD_SNAPSHOT_MV_NAME} (workflow_state)"
        )
    )
    db.session.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_va_submission_cod_snapshot_mv_authoritative_icd "
            f"ON {COD_SNAPSHOT_MV_NAME} (authoritative_icd)"
        )
    )
    db.session.commit()


# Backwards-compatible aliases
build_refresh_submission_analytics_mv_sql = _build_refresh_sql


def build_submission_analytics_mv_sql(view_name: str = "va_submission_analytics_mv") -> str:
    """Legacy builder for the old single analytics MV.

    Kept so the pre-split migration chain can still run on a fresh database.
    Do NOT use in new code.
    """
    return f"""
CREATE MATERIALIZED VIEW {view_name} AS
SELECT
    s.va_sid,
    DATE(s.va_submission_date) AS submission_date,
    f.project_id,
    f.site_id,
    w.workflow_state,
    s.va_odk_reviewstate AS odk_review_state,
    s.va_deceased_gender AS sex,
    s.va_deceased_age_normalized_days AS analytics_age_normalized_days,
    CASE
        WHEN s.va_deceased_age IS NULL THEN 'unknown'
        WHEN s.va_deceased_age < 15 THEN 'child'
        WHEN s.va_deceased_age < 50 THEN '15_49y'
        WHEN s.va_deceased_age < 65 THEN '50_64y'
        ELSE '65_plus'
    END AS analytics_age_band,
    NULL::text AS final_icd,
    (w.workflow_state = 'finalized_upstream_changed') AS cod_pending_upstream_review
FROM va_submissions s
JOIN va_forms f ON f.form_id = s.va_form_id
LEFT JOIN va_submission_workflow w ON w.va_sid = s.va_sid
WITH DATA
"""


# ---------------------------------------------------------------------------
# Filter helpers (used by analytics routes and data-management queries)
# ---------------------------------------------------------------------------

def _expand_project_ids_to_active_pairs(project_ids: list[str]) -> set[tuple[str, str]]:
    """Expand project-level grants to the currently active (project_id, site_id) pairs.

    A project-level DM grant covers all sites in that project, but only those
    whose ``va_project_sites.project_site_status`` is currently active.  This
    ensures that sites removed from a project are excluded from all scoped
    queries without requiring changes to ``va_forms.project_id``.
    """
    if not project_ids:
        return set()
    from app.models import VaProjectSites, VaStatuses
    rows = db.session.execute(
        sa.select(VaProjectSites.project_id, VaProjectSites.site_id).where(
            VaProjectSites.project_id.in_(project_ids),
            VaProjectSites.project_site_status == VaStatuses.active,
        )
    ).all()
    return {(row.project_id, row.site_id) for row in rows}


def _mv_scope_filter(mv, project_ids: list[str], project_site_pairs):
    """Return a WHERE clause scoped to the given project/project-site grants.

    Project-level grants are expanded to their currently active
    (project_id, site_id) pairs so that sites removed from a project are
    not included.
    """
    all_pairs: set[tuple[str, str]] = set(project_site_pairs)
    all_pairs |= _expand_project_ids_to_active_pairs(project_ids)

    if not all_pairs:
        return sa.false()

    return sa.tuple_(mv.c.project_id, mv.c.site_id).in_(list(all_pairs))


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

    # Count submissions whose active SmartVA result has outcome='failed'.
    # These are distinct from "missing" (no result) — they ran but produced no COD.
    from app.models import VaSmartvaResults
    smartva_failed = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(
            joined.join(
                VaSmartvaResults,
                sa.and_(
                    VaSmartvaResults.va_sid == core.c.va_sid,
                    VaSmartvaResults.va_smartva_status == "active",
                    VaSmartvaResults.va_smartva_outcome == VaSmartvaResults.OUTCOME_FAILED,
                ),
            )
        )
        .where(where)
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
        "smartva_failed_submissions": smartva_failed,
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
