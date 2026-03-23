"""add reviewer final assessment artifact table

Revision ID: c4d5e6f7a8b9
Revises: b8c9d0e1f2a3
Create Date: 2026-03-23 14:45:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c4d5e6f7a8b9"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade():
    status_enum = postgresql.ENUM(
        "pending",
        "active",
        "deactive",
        name="status_enum",
        create_type=False,
    )
    op.create_table(
        "va_reviewer_final_assessments",
        sa.Column("va_rfinassess_id", sa.Uuid(), nullable=False),
        sa.Column("va_sid", sa.String(length=64), nullable=False),
        sa.Column("va_rfinassess_by", sa.Uuid(), nullable=False),
        sa.Column("va_conclusive_cod", sa.Text(), nullable=False),
        sa.Column("va_rfinassess_remark", sa.Text(), nullable=True),
        sa.Column(
            "supersedes_coder_final_assessment_id",
            sa.Uuid(),
            nullable=True,
        ),
        sa.Column("va_rfinassess_status", status_enum, nullable=False),
        sa.Column("va_rfinassess_createdat", sa.DateTime(), nullable=False),
        sa.Column("va_rfinassess_updatedat", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["va_sid"], ["va_submissions.va_sid"]),
        sa.ForeignKeyConstraint(["va_rfinassess_by"], ["va_users.user_id"]),
        sa.ForeignKeyConstraint(
            ["supersedes_coder_final_assessment_id"],
            ["va_final_assessments.va_finassess_id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("va_rfinassess_id"),
    )
    op.create_index(
        "ix_va_reviewer_final_assessments_va_rfinassess_id",
        "va_reviewer_final_assessments",
        ["va_rfinassess_id"],
        unique=False,
    )
    op.create_index(
        "ix_va_reviewer_final_assessments_va_sid",
        "va_reviewer_final_assessments",
        ["va_sid"],
        unique=False,
    )
    op.create_index(
        "ix_va_reviewer_final_assessments_va_rfinassess_by",
        "va_reviewer_final_assessments",
        ["va_rfinassess_by"],
        unique=False,
    )
    op.create_index(
        "ix_va_reviewer_final_assessments_va_rfinassess_status",
        "va_reviewer_final_assessments",
        ["va_rfinassess_status"],
        unique=False,
    )
    op.create_index(
        "ix_va_reviewer_final_assessments_va_rfinassess_createdat",
        "va_reviewer_final_assessments",
        ["va_rfinassess_createdat"],
        unique=False,
    )
    op.create_index(
        "ix_va_reviewer_final_assessments_supersedes_coder_final_id",
        "va_reviewer_final_assessments",
        ["supersedes_coder_final_assessment_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_va_reviewer_final_assessments_supersedes_coder_final_id",
        table_name="va_reviewer_final_assessments",
    )
    op.drop_index(
        "ix_va_reviewer_final_assessments_va_rfinassess_createdat",
        table_name="va_reviewer_final_assessments",
    )
    op.drop_index(
        "ix_va_reviewer_final_assessments_va_rfinassess_status",
        table_name="va_reviewer_final_assessments",
    )
    op.drop_index(
        "ix_va_reviewer_final_assessments_va_rfinassess_by",
        table_name="va_reviewer_final_assessments",
    )
    op.drop_index(
        "ix_va_reviewer_final_assessments_va_sid",
        table_name="va_reviewer_final_assessments",
    )
    op.drop_index(
        "ix_va_reviewer_final_assessments_va_rfinassess_id",
        table_name="va_reviewer_final_assessments",
    )
    op.drop_table("va_reviewer_final_assessments")
