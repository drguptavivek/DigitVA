"""add reviewer initial assessments

Revision ID: fe5f6a7b8c9d
Revises: fd4e5f6a7b8c
Create Date: 2026-05-04 06:40:00.000000

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "fe5f6a7b8c9d"
down_revision = "fd4e5f6a7b8c"
branch_labels = None
depends_on = None


def upgrade():
    status_enum = postgresql.ENUM(
        "active",
        "deactive",
        name="status_enum",
        create_type=False,
    )
    op.create_table(
        "va_reviewer_initial_assessments",
        sa.Column("va_riniassess_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("va_sid", sa.String(length=64), nullable=False),
        sa.Column("payload_version_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("va_riniassess_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("va_immediate_cod", sa.Text(), nullable=False),
        sa.Column("va_antecedent_cod", sa.Text(), nullable=False),
        sa.Column("va_other_conditions", sa.Text(), nullable=True),
        sa.Column("va_riniassess_status", status_enum, nullable=False),
        sa.Column("va_riniassess_createdat", sa.DateTime(), nullable=False),
        sa.Column("va_riniassess_updatedat", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["payload_version_id"],
            ["va_submission_payload_versions.payload_version_id"],
        ),
        sa.ForeignKeyConstraint(["va_riniassess_by"], ["va_users.user_id"]),
        sa.ForeignKeyConstraint(["va_sid"], ["va_submissions.va_sid"]),
        sa.PrimaryKeyConstraint("va_riniassess_id"),
    )
    op.create_index(
        op.f("ix_va_reviewer_initial_assessments_payload_version_id"),
        "va_reviewer_initial_assessments",
        ["payload_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_reviewer_initial_assessments_va_riniassess_by"),
        "va_reviewer_initial_assessments",
        ["va_riniassess_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_reviewer_initial_assessments_va_riniassess_createdat"),
        "va_reviewer_initial_assessments",
        ["va_riniassess_createdat"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_reviewer_initial_assessments_va_riniassess_id"),
        "va_reviewer_initial_assessments",
        ["va_riniassess_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_reviewer_initial_assessments_va_riniassess_status"),
        "va_reviewer_initial_assessments",
        ["va_riniassess_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_reviewer_initial_assessments_va_sid"),
        "va_reviewer_initial_assessments",
        ["va_sid"],
        unique=False,
    )
    op.add_column(
        "va_reviewer_final_assessments",
        sa.Column(
            "source_reviewer_initial_assessment_id",
            sa.Uuid(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(
        op.f(
            "ix_va_reviewer_final_assessments_source_reviewer_initial_assessment_id"
        ),
        "va_reviewer_final_assessments",
        ["source_reviewer_initial_assessment_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_reviewer_final_source_reviewer_initial",
        "va_reviewer_final_assessments",
        "va_reviewer_initial_assessments",
        ["source_reviewer_initial_assessment_id"],
        ["va_riniassess_id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        "fk_reviewer_final_source_reviewer_initial",
        "va_reviewer_final_assessments",
        type_="foreignkey",
    )
    op.drop_index(
        op.f(
            "ix_va_reviewer_final_assessments_source_reviewer_initial_assessment_id"
        ),
        table_name="va_reviewer_final_assessments",
    )
    op.drop_column(
        "va_reviewer_final_assessments",
        "source_reviewer_initial_assessment_id",
    )
    op.drop_index(
        op.f("ix_va_reviewer_initial_assessments_va_sid"),
        table_name="va_reviewer_initial_assessments",
    )
    op.drop_index(
        op.f("ix_va_reviewer_initial_assessments_va_riniassess_status"),
        table_name="va_reviewer_initial_assessments",
    )
    op.drop_index(
        op.f("ix_va_reviewer_initial_assessments_va_riniassess_id"),
        table_name="va_reviewer_initial_assessments",
    )
    op.drop_index(
        op.f("ix_va_reviewer_initial_assessments_va_riniassess_createdat"),
        table_name="va_reviewer_initial_assessments",
    )
    op.drop_index(
        op.f("ix_va_reviewer_initial_assessments_va_riniassess_by"),
        table_name="va_reviewer_initial_assessments",
    )
    op.drop_index(
        op.f("ix_va_reviewer_initial_assessments_payload_version_id"),
        table_name="va_reviewer_initial_assessments",
    )
    op.drop_table("va_reviewer_initial_assessments")
