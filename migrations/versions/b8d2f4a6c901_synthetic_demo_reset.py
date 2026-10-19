"""Opt-in synthetic demo reset and durable backup audit.

Revision ID: b8d2f4a6c901
Revises: a4c9e1f2b7d3
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b8d2f4a6c901"
down_revision = "a4c9e1f2b7d3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_project_master",
        sa.Column(
            "synthetic_demo_reset_enabled", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.create_check_constraint(
        op.f("ck_va_project_master_demo_modes_exclusive"),
        "va_project_master",
        "NOT (synthetic_demo_reset_enabled AND demo_training_enabled)",
    )
    op.create_table(
        "va_demo_reset_runs",
        sa.Column("reset_run_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(6),
            sa.ForeignKey("va_project_master.project_id"),
            nullable=False,
        ),
        sa.Column("scheduled_week", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("backup_id", sa.Uuid(), sa.ForeignKey("va_db_backups.backup_id")),
        sa.Column("backup_key", sa.Text()),
        sa.Column("backup_size_bytes", sa.BigInteger()),
        sa.Column("backup_sha256", sa.String(64)),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("counts", postgresql.JSONB(), nullable=False),
        sa.Column("error_code", sa.String(32)),
        sa.UniqueConstraint("project_id", "scheduled_week", name="uq_demo_reset_project_week"),
    )


def downgrade():
    op.drop_table("va_demo_reset_runs")
    op.drop_constraint(
        op.f("ck_va_project_master_demo_modes_exclusive"), "va_project_master", type_="check"
    )
    op.drop_column("va_project_master", "synthetic_demo_reset_enabled")
