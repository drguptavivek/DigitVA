"""add age days to demographics mv

Revision ID: ab8c9d0e1f2a
Revises: aa7b8c9d0e1f
Create Date: 2026-04-20T01:10:00.000000

"""

import sqlalchemy as sa
from alembic import op

from app.services.analytics.submission_mv import (
    DEMOGRAPHICS_MV_NAME,
    build_submission_analytics_demographics_mv_sql,
)


revision = "ab8c9d0e1f2a"
down_revision = "aa7b8c9d0e1f"
branch_labels = None
depends_on = None

_INDEX = "ix_va_submission_analytics_demographics_mv_va_sid"
_OLD_DEMOGRAPHICS_MV_SQL = f"""
CREATE MATERIALIZED VIEW {DEMOGRAPHICS_MV_NAME} AS
SELECT
    s.va_sid,
    s.va_narration_language,
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


def upgrade():
    op.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {DEMOGRAPHICS_MV_NAME} CASCADE"))
    op.execute(sa.text(build_submission_analytics_demographics_mv_sql()))
    op.execute(
        sa.text(
            f"CREATE UNIQUE INDEX {_INDEX} ON {DEMOGRAPHICS_MV_NAME} (va_sid)"
        )
    )


def downgrade():
    op.execute(sa.text(f"DROP MATERIALIZED VIEW IF EXISTS {DEMOGRAPHICS_MV_NAME} CASCADE"))
    op.execute(sa.text(_OLD_DEMOGRAPHICS_MV_SQL))
    op.execute(
        sa.text(
            f"CREATE UNIQUE INDEX {_INDEX} ON {DEMOGRAPHICS_MV_NAME} (va_sid)"
        )
    )
