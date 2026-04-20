"""make cod age band bounds non-null

Revision ID: ad0e1f2a3b4c
Revises: ac9d0e1f2a3b
Create Date: 2026-04-20T13:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "ad0e1f2a3b4c"
down_revision = "ac9d0e1f2a3b"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        UPDATE mas_cod_bucket_scheme_age_bands
        SET min_age_value = COALESCE(min_age_value, 0),
            min_age_unit = COALESCE(NULLIF(BTRIM(min_age_unit), ''), 'days'),
            max_age_value = COALESCE(max_age_value, 120),
            max_age_unit = COALESCE(NULLIF(BTRIM(max_age_unit), ''), 'years')
        """
    )
    op.alter_column(
        "mas_cod_bucket_scheme_age_bands",
        "min_age_value",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "mas_cod_bucket_scheme_age_bands",
        "min_age_unit",
        existing_type=sa.String(length=8),
        nullable=False,
    )
    op.alter_column(
        "mas_cod_bucket_scheme_age_bands",
        "max_age_value",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.alter_column(
        "mas_cod_bucket_scheme_age_bands",
        "max_age_unit",
        existing_type=sa.String(length=8),
        nullable=False,
    )


def downgrade():
    op.alter_column(
        "mas_cod_bucket_scheme_age_bands",
        "max_age_unit",
        existing_type=sa.String(length=8),
        nullable=True,
    )
    op.alter_column(
        "mas_cod_bucket_scheme_age_bands",
        "max_age_value",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.alter_column(
        "mas_cod_bucket_scheme_age_bands",
        "min_age_unit",
        existing_type=sa.String(length=8),
        nullable=True,
    )
    op.alter_column(
        "mas_cod_bucket_scheme_age_bands",
        "min_age_value",
        existing_type=sa.Integer(),
        nullable=True,
    )
