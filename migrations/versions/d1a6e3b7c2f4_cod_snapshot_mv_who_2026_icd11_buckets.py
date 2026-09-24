"""cod snapshot mv: bucket in WHO_2022_VA_2026, ICD-11 deaths included

Rebuilds va_submission_cod_snapshot_mv so each COD is bucketed in
WHO_2022_VA_2026 through the rows of its own classification (ICD-10 or
ICD-11, decided by the code's shape), with a provenance column per bucket.
Owner decisions 6 and 7 of docs/policy/icd10-to-icd11-transition.md.
Downgrade restores the WHO_2022_VA ICD-10-only view.

Revision ID: d1a6e3b7c2f4
Revises: fad35e5c4b79
Create Date: 2026-09-24 12:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "d1a6e3b7c2f4"
down_revision = "fad35e5c4b79"
branch_labels = None
depends_on = None


# Frozen output of build_submission_cod_snapshot_mv_sql(icd11_buckets=True) at
# the time of writing; migrations inline their SQL
# (tests/migrations/test_no_app_imports_in_migrations.py).
SNAPSHOT_MV_SQL_WHO_2026 = r"""
CREATE MATERIALIZED VIEW va_submission_cod_snapshot_mv AS
WITH RECURSIVE active_payload AS (
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
bucket_rows AS (
    SELECT DISTINCT ON (map.icd_classification, upper(map.icd_code))
        map.icd_classification,
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
    WHERE scheme.scheme_code = 'WHO_2022_VA_2026'
      AND scheme.is_active IS TRUE
    ORDER BY
        map.icd_classification,
        upper(map.icd_code),
        COALESCE(parent.sort_order, 0),
        leaf.sort_order,
        map.created_at,
        map.mapping_id
),
icd10_buckets AS (
    SELECT icd_code, bucket_section, bucket_label
    FROM bucket_rows
    WHERE icd_classification = 'icd10'
),
icd11_mapped AS (
    SELECT icd_code, bucket_section, bucket_label
    FROM bucket_rows
    WHERE icd_classification = 'icd11'
),
-- Catalogue codes with no row of their own, walked up the parent chain
-- (block and chapter nodes have no code) until a mapped ancestor is reached.
-- The depth cap stops a parent cycle in bad catalogue data; MMS is ~8 deep.
icd11_ancestors AS (
    SELECT
        upper(c.code) AS start_code,
        upper(c.code) AS code,
        c.parent_linearization_uri,
        0 AS depth
    FROM mas_icd11_mms c
    WHERE c.release = '2026-01'
      AND c.code IS NOT NULL
      AND upper(c.code) NOT IN (SELECT icd_code FROM icd11_mapped)
    UNION ALL
    SELECT
        a.start_code,
        upper(p.code),
        p.parent_linearization_uri,
        a.depth + 1
    FROM icd11_ancestors a
    JOIN mas_icd11_mms p
        ON p.release = '2026-01'
       AND p.linearization_uri = a.parent_linearization_uri
    WHERE (a.code IS NULL OR a.code NOT IN (SELECT icd_code FROM icd11_mapped))
      AND a.depth < 20
),
icd11_buckets AS (
    SELECT icd_code, bucket_section, bucket_label
    FROM icd11_mapped
    UNION ALL
    (
        SELECT DISTINCT ON (a.start_code)
            a.start_code AS icd_code,
            m.bucket_section,
            m.bucket_label
        FROM icd11_ancestors a
        JOIN icd11_mapped m ON m.icd_code = a.code
        ORDER BY a.start_code, a.depth, m.bucket_label
    )
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
    ap.payload_data ->> 'unique_id' AS unique_id,
    ap.payload_data ->> 'survey_block' AS survey_block,
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
    substring(cf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)') AS coder_final_icd,
    cf.va_finassess_remark AS coder_final_remark,
    cf.va_finassess_createdat AS coder_final_saved_at,
    cf.va_finassess_updatedat AS coder_final_updated_at,
    reviewer_user.user_id AS reviewer_user_id,
    reviewer_user.name AS reviewer_name,
    rf.va_rfinassess_id AS reviewer_final_assessment_id,
    rf.va_rfinassess_by AS reviewer_final_by,
    rf.va_conclusive_cod AS reviewer_final_cod_text,
    substring(rf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)') AS reviewer_final_icd,
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
        from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)'
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
    ap.payload_data ->> 'sa01' AS sa01,
    ap.payload_data ->> 'sa06' AS sa06,
    ap.payload_data ->> 'sa06_a' AS sa06_a,
    ap.payload_data ->> 'sa02' AS sa02,
    ap.payload_data ->> 'sa03' AS sa03,
    ap.payload_data ->> 'sa04' AS sa04,
    ap.payload_data ->> 'sa05' AS sa05,
    ap.payload_data ->> 'sa05_a' AS sa05_a,
    ap.payload_data ->> 'sa07' AS sa07,
    ap.payload_data ->> 'sa07_a' AS sa07_a,
    ap.payload_data ->> 'sa09' AS sa09,
    ap.payload_data ->> 'sa10' AS sa10,
    ap.payload_data ->> 'sa11' AS sa11,
    ap.payload_data ->> 'sa12' AS sa12,
    ap.payload_data ->> 'sa08' AS sa08,
    ap.payload_data ->> 'sa13' AS sa13,
    ap.payload_data ->> 'sa_tu13' AS sa_tu13,
    ap.payload_data ->> 'sa14' AS sa14,
    ap.payload_data ->> 'sa_tu14' AS sa_tu14,
    ap.payload_data ->> 'sa15' AS sa15,
    ap.payload_data ->> 'sa_tu15' AS sa_tu15,
    ap.payload_data ->> 'sa16' AS sa16,
    ap.payload_data ->> 'sa_tu16' AS sa_tu16,
    ap.payload_data ->> 'sa17' AS sa17,
    ap.payload_data ->> 'sa_tu17' AS sa_tu17,
    ap.payload_data ->> 'sa18' AS sa18,
    ap.payload_data ->> 'sa_tu18' AS sa_tu18,
    ap.payload_data ->> 'sa19' AS sa19,
    ap.payload_data ->> 'sa_tu19' AS sa_tu19,
    coding_alloc.va_allocated_to AS active_coder_assigned_user_id,
    coding_alloc_user.name AS active_coder_assigned_name,
    reviewing_alloc.va_allocated_to AS active_reviewer_assigned_user_id,
    reviewing_alloc_user.name AS active_reviewer_assigned_name,
    COALESCE(coder_bucket.bucket_section, coder_bucket11.bucket_section) AS coder_final_who_bucket_section,
    COALESCE(coder_bucket.bucket_label, coder_bucket11.bucket_label) AS coder_final_who_bucket,
    CASE
        WHEN NULLIF(btrim(cf.va_conclusive_cod), '') IS NULL THEN NULL
        WHEN coder_bucket.icd_code IS NOT NULL THEN 'icd10'
        WHEN coder_bucket11.icd_code IS NOT NULL THEN 'icd11_native'
        ELSE 'unmapped'
    END AS coder_final_who_bucket_provenance,
    COALESCE(reviewer_bucket.bucket_section, reviewer_bucket11.bucket_section) AS reviewer_final_who_bucket_section,
    COALESCE(reviewer_bucket.bucket_label, reviewer_bucket11.bucket_label) AS reviewer_final_who_bucket,
    CASE
        WHEN NULLIF(btrim(rf.va_conclusive_cod), '') IS NULL THEN NULL
        WHEN reviewer_bucket.icd_code IS NOT NULL THEN 'icd10'
        WHEN reviewer_bucket11.icd_code IS NOT NULL THEN 'icd11_native'
        ELSE 'unmapped'
    END AS reviewer_final_who_bucket_provenance,
    COALESCE(auth_bucket.bucket_section, auth_bucket11.bucket_section) AS authoritative_who_bucket_section,
    COALESCE(auth_bucket.bucket_label, auth_bucket11.bucket_label) AS authoritative_who_bucket,
    CASE
        WHEN NULLIF(btrim(auth_cod.cod_text), '') IS NULL THEN NULL
        WHEN auth_bucket.icd_code IS NOT NULL THEN 'icd10'
        WHEN auth_bucket11.icd_code IS NOT NULL THEN 'icd11_native'
        ELSE 'unmapped'
    END AS authoritative_who_bucket_provenance,
    smartva1_bucket.bucket_section AS smartva_cause1_who_bucket_section,
    smartva1_bucket.bucket_label AS smartva_cause1_who_bucket,
    CASE
        WHEN NULLIF(btrim(ls.va_smartva_cause1icd), '') IS NULL THEN NULL
        WHEN smartva1_bucket.icd_code IS NOT NULL THEN 'icd10'
        ELSE 'unmapped'
    END AS smartva_cause1_who_bucket_provenance,
    smartva2_bucket.bucket_section AS smartva_cause2_who_bucket_section,
    smartva2_bucket.bucket_label AS smartva_cause2_who_bucket,
    CASE
        WHEN NULLIF(btrim(ls.va_smartva_cause2icd), '') IS NULL THEN NULL
        WHEN smartva2_bucket.icd_code IS NOT NULL THEN 'icd10'
        ELSE 'unmapped'
    END AS smartva_cause2_who_bucket_provenance,
    smartva3_bucket.bucket_section AS smartva_cause3_who_bucket_section,
    smartva3_bucket.bucket_label AS smartva_cause3_who_bucket,
    CASE
        WHEN NULLIF(btrim(ls.va_smartva_cause3icd), '') IS NULL THEN NULL
        WHEN smartva3_bucket.icd_code IS NOT NULL THEN 'icd10'
        ELSE 'unmapped'
    END AS smartva_cause3_who_bucket_provenance
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
CROSS JOIN LATERAL (
    SELECT CASE
            WHEN ar.va_sid IS NOT NULL THEN ar.va_conclusive_cod
            WHEN ac.va_sid IS NOT NULL THEN ac.va_conclusive_cod
            WHEN rf.va_rfinassess_id IS NOT NULL THEN rf.va_conclusive_cod
            WHEN cf.va_finassess_id IS NOT NULL THEN cf.va_conclusive_cod
            ELSE NULL
        END AS cod_text
) auth_cod
LEFT JOIN legacy_reporting_alias coder_icd_alias
    ON coder_icd_alias.legacy_code = substring(cf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)')
LEFT JOIN icd10_buckets coder_bucket
    ON coder_bucket.icd_code = COALESCE(coder_icd_alias.reporting_code, substring(cf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)'))
LEFT JOIN icd11_buckets coder_bucket11
    ON coder_bucket11.icd_code = substring(upper(cf.va_conclusive_cod) from '^([0-9A-Z][A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,2})?)')
LEFT JOIN legacy_reporting_alias reviewer_icd_alias
    ON reviewer_icd_alias.legacy_code = substring(rf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)')
LEFT JOIN icd10_buckets reviewer_bucket
    ON reviewer_bucket.icd_code = COALESCE(reviewer_icd_alias.reporting_code, substring(rf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)'))
LEFT JOIN icd11_buckets reviewer_bucket11
    ON reviewer_bucket11.icd_code = substring(upper(rf.va_conclusive_cod) from '^([0-9A-Z][A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,2})?)')
LEFT JOIN legacy_reporting_alias auth_icd_alias
    ON auth_icd_alias.legacy_code = substring(auth_cod.cod_text from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)')
LEFT JOIN icd10_buckets auth_bucket
    ON auth_bucket.icd_code = COALESCE(auth_icd_alias.reporting_code, substring(auth_cod.cod_text from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)'))
LEFT JOIN icd11_buckets auth_bucket11
    ON auth_bucket11.icd_code = substring(upper(auth_cod.cod_text) from '^([0-9A-Z][A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,2})?)')
LEFT JOIN legacy_reporting_alias smartva1_icd_alias
    ON smartva1_icd_alias.legacy_code = upper(ls.va_smartva_cause1icd)
LEFT JOIN icd10_buckets smartva1_bucket
    ON smartva1_bucket.icd_code = COALESCE(smartva1_icd_alias.reporting_code, upper(ls.va_smartva_cause1icd))
LEFT JOIN legacy_reporting_alias smartva2_icd_alias
    ON smartva2_icd_alias.legacy_code = upper(ls.va_smartva_cause2icd)
LEFT JOIN icd10_buckets smartva2_bucket
    ON smartva2_bucket.icd_code = COALESCE(smartva2_icd_alias.reporting_code, upper(ls.va_smartva_cause2icd))
LEFT JOIN legacy_reporting_alias smartva3_icd_alias
    ON smartva3_icd_alias.legacy_code = upper(ls.va_smartva_cause3icd)
LEFT JOIN icd10_buckets smartva3_bucket
    ON smartva3_bucket.icd_code = COALESCE(smartva3_icd_alias.reporting_code, upper(ls.va_smartva_cause3icd))
WITH DATA
"""

# What fc3d4e5f6a7b built: WHO_2022_VA, ICD-10 only.
SNAPSHOT_MV_SQL_WHO_2022 = r"""
CREATE MATERIALIZED VIEW va_submission_cod_snapshot_mv AS
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
    WHERE scheme.scheme_code = 'WHO_2022_VA'
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
    ap.payload_data ->> 'unique_id' AS unique_id,
    ap.payload_data ->> 'survey_block' AS survey_block,
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
    substring(cf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)') AS coder_final_icd,
    cf.va_finassess_remark AS coder_final_remark,
    cf.va_finassess_createdat AS coder_final_saved_at,
    cf.va_finassess_updatedat AS coder_final_updated_at,
    reviewer_user.user_id AS reviewer_user_id,
    reviewer_user.name AS reviewer_name,
    rf.va_rfinassess_id AS reviewer_final_assessment_id,
    rf.va_rfinassess_by AS reviewer_final_by,
    rf.va_conclusive_cod AS reviewer_final_cod_text,
    substring(rf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)') AS reviewer_final_icd,
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
        from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)'
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
    ap.payload_data ->> 'sa01' AS sa01,
    ap.payload_data ->> 'sa06' AS sa06,
    ap.payload_data ->> 'sa06_a' AS sa06_a,
    ap.payload_data ->> 'sa02' AS sa02,
    ap.payload_data ->> 'sa03' AS sa03,
    ap.payload_data ->> 'sa04' AS sa04,
    ap.payload_data ->> 'sa05' AS sa05,
    ap.payload_data ->> 'sa05_a' AS sa05_a,
    ap.payload_data ->> 'sa07' AS sa07,
    ap.payload_data ->> 'sa07_a' AS sa07_a,
    ap.payload_data ->> 'sa09' AS sa09,
    ap.payload_data ->> 'sa10' AS sa10,
    ap.payload_data ->> 'sa11' AS sa11,
    ap.payload_data ->> 'sa12' AS sa12,
    ap.payload_data ->> 'sa08' AS sa08,
    ap.payload_data ->> 'sa13' AS sa13,
    ap.payload_data ->> 'sa_tu13' AS sa_tu13,
    ap.payload_data ->> 'sa14' AS sa14,
    ap.payload_data ->> 'sa_tu14' AS sa_tu14,
    ap.payload_data ->> 'sa15' AS sa15,
    ap.payload_data ->> 'sa_tu15' AS sa_tu15,
    ap.payload_data ->> 'sa16' AS sa16,
    ap.payload_data ->> 'sa_tu16' AS sa_tu16,
    ap.payload_data ->> 'sa17' AS sa17,
    ap.payload_data ->> 'sa_tu17' AS sa_tu17,
    ap.payload_data ->> 'sa18' AS sa18,
    ap.payload_data ->> 'sa_tu18' AS sa_tu18,
    ap.payload_data ->> 'sa19' AS sa19,
    ap.payload_data ->> 'sa_tu19' AS sa_tu19,
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
    ON coder_icd_alias.legacy_code = substring(cf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)')
LEFT JOIN legacy_reporting_alias reviewer_icd_alias
    ON reviewer_icd_alias.legacy_code = substring(rf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)')
LEFT JOIN legacy_reporting_alias auth_icd_alias
    ON auth_icd_alias.legacy_code = substring(
        CASE
            WHEN ar.va_sid IS NOT NULL THEN ar.va_conclusive_cod
            WHEN ac.va_sid IS NOT NULL THEN ac.va_conclusive_cod
            WHEN rf.va_rfinassess_id IS NOT NULL THEN rf.va_conclusive_cod
            WHEN cf.va_finassess_id IS NOT NULL THEN cf.va_conclusive_cod
            ELSE NULL
        END
        from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)'
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
        substring(cf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)')
    )
LEFT JOIN who_2022_buckets reviewer_bucket
    ON reviewer_bucket.icd_code = COALESCE(
        reviewer_icd_alias.reporting_code,
        substring(rf.va_conclusive_cod from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)')
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
            from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)'
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


def _rebuild(create_sql):
    op.execute(
        sa.text("DROP MATERIALIZED VIEW IF EXISTS va_submission_cod_snapshot_mv CASCADE")
    )
    op.execute(sa.text(create_sql))
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX ix_va_submission_cod_snapshot_mv_va_sid "
            "ON va_submission_cod_snapshot_mv (va_sid)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_cod_snapshot_mv_project_site "
            "ON va_submission_cod_snapshot_mv (project_id, site_id)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_cod_snapshot_mv_workflow_state "
            "ON va_submission_cod_snapshot_mv (workflow_state)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_cod_snapshot_mv_authoritative_icd "
            "ON va_submission_cod_snapshot_mv (authoritative_icd)"
        )
    )


def upgrade():
    _rebuild(SNAPSHOT_MV_SQL_WHO_2026)


def downgrade():
    _rebuild(SNAPSHOT_MV_SQL_WHO_2022)
