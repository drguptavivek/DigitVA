"""add reviewer pointer to final cod authority

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-03-23 15:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d5e6f7a8b9c0"
down_revision = "c4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_final_cod_authority",
        sa.Column(
            "authoritative_reviewer_final_assessment_id",
            sa.Uuid(),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_va_final_cod_authority_authoritative_reviewer_final",
        "va_final_cod_authority",
        "va_reviewer_final_assessments",
        ["authoritative_reviewer_final_assessment_id"],
        ["va_rfinassess_id"],
    )
    op.create_unique_constraint(
        "uq_va_final_cod_authority_authoritative_reviewer_final",
        "va_final_cod_authority",
        ["authoritative_reviewer_final_assessment_id"],
    )


def downgrade():
    op.drop_constraint(
        "uq_va_final_cod_authority_authoritative_reviewer_final",
        "va_final_cod_authority",
        type_="unique",
    )
    op.drop_constraint(
        "fk_va_final_cod_authority_authoritative_reviewer_final",
        "va_final_cod_authority",
        type_="foreignkey",
    )
    op.drop_column(
        "va_final_cod_authority",
        "authoritative_reviewer_final_assessment_id",
    )
