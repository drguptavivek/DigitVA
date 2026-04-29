"""add site maintenance table

Revision ID: f8d9e0f1a2b3
Revises: f7c8d9e0f1a2
Create Date: 2026-04-29 13:25:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f8d9e0f1a2b3"
down_revision = "f7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "va_site_maintenance",
        sa.Column("maintenance_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cutoff_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("enabled_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["disabled_by_user_id"], ["va_users.user_id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["enabled_by_user_id"], ["va_users.user_id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("maintenance_id"),
    )
    op.create_index(
        "ix_va_site_maintenance_enabled",
        "va_site_maintenance",
        ["enabled"],
    )
    op.create_index(
        "ix_va_site_maintenance_cutoff_at",
        "va_site_maintenance",
        ["cutoff_at"],
    )


def downgrade():
    op.drop_index("ix_va_site_maintenance_cutoff_at", table_name="va_site_maintenance")
    op.drop_index("ix_va_site_maintenance_enabled", table_name="va_site_maintenance")
    op.drop_table("va_site_maintenance")
