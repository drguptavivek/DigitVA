"""cod detail mv: add final_icd11 for the COD bucket report

Adds final_icd11 (the ICD-11 stem of the final COD, first stem of a
post-coordinated value) to va_submission_cod_detail_mv, so the COD bucket
report can bucket ICD-11 deaths through a scheme's icd11 rows. final_icd
stays the ICD-10 code. Downgrade restores the view without the column.

Revision ID: e7b2c9d4a1f3
Revises: d1a6e3b7c2f4
Create Date: 2026-09-24 15:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e7b2c9d4a1f3"
down_revision = "d1a6e3b7c2f4"
branch_labels = None
depends_on = None


# Frozen output of build_submission_cod_detail_mv_sql(include_icd11=True) at the
# time of writing; migrations inline their SQL
# (tests/migrations/test_no_app_imports_in_migrations.py).
COD_DETAIL_MV_SQL_WITH_ICD11 = r"""
CREATE MATERIALIZED VIEW va_submission_cod_detail_mv AS
SELECT
    s.va_sid,
    substring(init_assess.va_immediate_cod from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)')
        AS initial_immediate_icd,
    COALESCE(reviewer_final.va_conclusive_cod, coder_final.va_conclusive_cod) AS final_cod_text,
    substring(
        COALESCE(reviewer_final.va_conclusive_cod, coder_final.va_conclusive_cod)
        from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)'
    ) AS final_icd,
    substring(
        upper(COALESCE(reviewer_final.va_conclusive_cod, coder_final.va_conclusive_cod))
        from '^([0-9A-Z][A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,2})?)'
    ) AS final_icd11,
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

# What e95dc3d7c4f2 built.
COD_DETAIL_MV_SQL_ICD10_ONLY = r"""
CREATE MATERIALIZED VIEW va_submission_cod_detail_mv AS
SELECT
    s.va_sid,
    substring(init_assess.va_immediate_cod from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)')
        AS initial_immediate_icd,
    COALESCE(reviewer_final.va_conclusive_cod, coder_final.va_conclusive_cod) AS final_cod_text,
    substring(
        COALESCE(reviewer_final.va_conclusive_cod, coder_final.va_conclusive_cod)
        from '^([A-Z][0-9][0-9A-Z](?:\.[0-9A-Z]+)?)'
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


def _rebuild(create_sql):
    op.execute(sa.text("DROP MATERIALIZED VIEW IF EXISTS va_submission_cod_detail_mv CASCADE"))
    op.execute(sa.text(create_sql))
    op.execute(
        sa.text(
            "CREATE UNIQUE INDEX ix_va_submission_cod_detail_mv_va_sid "
            "ON va_submission_cod_detail_mv (va_sid)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_cod_detail_mv_final_icd "
            "ON va_submission_cod_detail_mv (final_icd)"
        )
    )
    op.execute(
        sa.text(
            "CREATE INDEX ix_va_submission_cod_detail_mv_smartva_cause1_icd "
            "ON va_submission_cod_detail_mv (smartva_cause1_icd)"
        )
    )


def upgrade():
    _rebuild(COD_DETAIL_MV_SQL_WITH_ICD11)


def downgrade():
    _rebuild(COD_DETAIL_MV_SQL_ICD10_ONLY)
