"""add va_narration_language to demographics MV

Adds va_narration_language column to va_submission_analytics_demographics_mv
to support D-LC-01 (submission language distribution) and D-LC-03 (language gap analysis).

Revision ID: f0a1b2c3d4e5
Revises: f9a0b1c2d3e4
Create Date: 2026-04-07T00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from app.services.submission_analytics_mv import build_submission_analytics_demographics_mv_sql

revision = 'f0a1b2c3d4e5'
down_revision = 'f9a0b1c2d3e4'
branch_labels = None
depends_on = None


def upgrade():
    # Drop and recreate the demographics MV with the new column
    op.execute("DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_demographics_mv")
    op.execute(build_submission_analytics_demographics_mv_sql())


def downgrade():
    # Recreate the old version without va_narration_language
    old_sql = """
CREATE MATERIALIZED VIEW va_submission_analytics_demographics_mv AS
SELECT
    s.va_sid,
    s.va_deceased_gender AS sex,
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
    op.execute("DROP MATERIALIZED VIEW IF EXISTS va_submission_analytics_demographics_mv")
    op.execute(old_sql)
