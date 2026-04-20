"""normalize builtin cod age band bounds

Revision ID: ac9d0e1f2a3b
Revises: ab8c9d0e1f2a
Create Date: 2026-04-20T06:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "ac9d0e1f2a3b"
down_revision = "ab8c9d0e1f2a"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        sa.text(
            """
            UPDATE mas_cod_bucket_scheme_age_bands age_band
            SET max_age_value = CASE age_band.age_scope
                    WHEN 'neonate' THEN 29
                    WHEN 'child_1_59m' THEN 60
                    ELSE age_band.max_age_value
                END,
                max_age_unit = CASE age_band.age_scope
                    WHEN 'neonate' THEN 'days'
                    WHEN 'child_1_59m' THEN 'months'
                    ELSE age_band.max_age_unit
                END
            FROM mas_cod_bucket_schemes scheme
            WHERE scheme.scheme_id = age_band.scheme_id
              AND scheme.scheme_code = 'SRS_INDIA'
              AND age_band.age_scope IN ('neonate', 'child_1_59m')
            """
        )
    )


def downgrade():
    op.execute(
        sa.text(
            """
            UPDATE mas_cod_bucket_scheme_age_bands age_band
            SET max_age_value = CASE age_band.age_scope
                    WHEN 'neonate' THEN 28
                    WHEN 'child_1_59m' THEN 59
                    ELSE age_band.max_age_value
                END,
                max_age_unit = CASE age_band.age_scope
                    WHEN 'neonate' THEN 'days'
                    WHEN 'child_1_59m' THEN 'months'
                    ELSE age_band.max_age_unit
                END
            FROM mas_cod_bucket_schemes scheme
            WHERE scheme.scheme_id = age_band.scheme_id
              AND scheme.scheme_code = 'SRS_INDIA'
              AND age_band.age_scope IN ('neonate', 'child_1_59m')
            """
        )
    )
