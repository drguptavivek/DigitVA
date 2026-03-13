"""add social autopsy analysis tables

Revision ID: f1a2b3c4d5e6
Revises: e7f8a9b0c1d2
Create Date: 2026-03-13 13:25:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f1a2b3c4d5e6"
down_revision = "e7f8a9b0c1d2"
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
        "va_social_autopsy_analyses",
        sa.Column("va_saa_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("va_sid", sa.String(length=64), nullable=False),
        sa.Column("va_saa_by", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("va_saa_remark", sa.Text(), nullable=True),
        sa.Column("va_saa_status", status_enum, nullable=False),
        sa.Column("va_saa_createdat", sa.DateTime(), nullable=False),
        sa.Column("va_saa_updatedat", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["va_saa_by"], ["va_users.user_id"]),
        sa.ForeignKeyConstraint(["va_sid"], ["va_submissions.va_sid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("va_saa_id"),
        sa.UniqueConstraint("va_sid", "va_saa_by", name="uq_social_autopsy_analysis_sid_by"),
    )
    op.create_index(
        op.f("ix_va_social_autopsy_analyses_va_saa_id"),
        "va_social_autopsy_analyses",
        ["va_saa_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_social_autopsy_analyses_va_sid"),
        "va_social_autopsy_analyses",
        ["va_sid"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_social_autopsy_analyses_va_saa_by"),
        "va_social_autopsy_analyses",
        ["va_saa_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_social_autopsy_analyses_va_saa_status"),
        "va_social_autopsy_analyses",
        ["va_saa_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_social_autopsy_analyses_va_saa_createdat"),
        "va_social_autopsy_analyses",
        ["va_saa_createdat"],
        unique=False,
    )

    op.create_table(
        "va_social_autopsy_analysis_options",
        sa.Column("va_saa_option_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("va_saa_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("delay_level", sa.String(length=32), nullable=False),
        sa.Column("option_code", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["va_saa_id"],
            ["va_social_autopsy_analyses.va_saa_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("va_saa_option_id"),
        sa.UniqueConstraint(
            "va_saa_id",
            "delay_level",
            "option_code",
            name="uq_social_autopsy_analysis_option",
        ),
    )
    op.create_index(
        op.f("ix_va_social_autopsy_analysis_options_va_saa_option_id"),
        "va_social_autopsy_analysis_options",
        ["va_saa_option_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_social_autopsy_analysis_options_va_saa_id"),
        "va_social_autopsy_analysis_options",
        ["va_saa_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_va_social_autopsy_analysis_options_va_saa_id"), table_name="va_social_autopsy_analysis_options")
    op.drop_index(op.f("ix_va_social_autopsy_analysis_options_va_saa_option_id"), table_name="va_social_autopsy_analysis_options")
    op.drop_table("va_social_autopsy_analysis_options")

    op.drop_index(op.f("ix_va_social_autopsy_analyses_va_saa_createdat"), table_name="va_social_autopsy_analyses")
    op.drop_index(op.f("ix_va_social_autopsy_analyses_va_saa_status"), table_name="va_social_autopsy_analyses")
    op.drop_index(op.f("ix_va_social_autopsy_analyses_va_saa_by"), table_name="va_social_autopsy_analyses")
    op.drop_index(op.f("ix_va_social_autopsy_analyses_va_sid"), table_name="va_social_autopsy_analyses")
    op.drop_index(op.f("ix_va_social_autopsy_analyses_va_saa_id"), table_name="va_social_autopsy_analyses")
    op.drop_table("va_social_autopsy_analyses")
