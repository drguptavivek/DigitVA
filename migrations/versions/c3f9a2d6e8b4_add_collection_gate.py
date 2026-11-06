"""Data-collection gate: per project-site columns and a per-unit table.

Revision ID: c3f9a2d6e8b4
Revises: b8e4c1d7f3a2
Create Date: 2026-11-06

Policy: docs/policy/project-clock-and-gates.md ("Data-collection gate",
"Rollout"); bead digitva-jeyy. Additive: ``collection_enabled`` defaults to
true and the dates and daily limit are null, so every existing project-site
collects exactly as before. A unit with no ``map_org_unit_collection_gate``
row is not gated. The index serves the gate's daily count (a user's new
starts since project midnight). Downgrade drops all of it.
"""

import sqlalchemy as sa
from alembic import op

revision = "c3f9a2d6e8b4"
down_revision = "b8e4c1d7f3a2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_project_sites",
        sa.Column("collection_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column("va_project_sites", sa.Column("collection_start_date", sa.Date(), nullable=True))
    op.add_column("va_project_sites", sa.Column("collection_end_date", sa.Date(), nullable=True))
    op.add_column("va_project_sites", sa.Column("daily_interviewer_limit", sa.Integer(), nullable=True))
    op.create_table(
        "map_org_unit_collection_gate",
        sa.Column("org_unit_id", sa.Uuid(), nullable=False),
        sa.Column("collection_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("collection_start_date", sa.Date(), nullable=True),
        sa.Column("collection_end_date", sa.Date(), nullable=True),
        sa.Column("daily_interviewer_limit", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("org_unit_id"),
        sa.ForeignKeyConstraint(
            ["org_unit_id"],
            ["mas_org_unit.org_unit_id"],
            name="fk_map_org_unit_collection_gate_org_unit",
        ),
    )
    op.create_index(
        "ix_va_death_register_registered_by_created",
        "va_death_register",
        ["registered_by", "created_at"],
    )


def downgrade():
    op.drop_index("ix_va_death_register_registered_by_created", table_name="va_death_register")
    op.drop_table("map_org_unit_collection_gate")
    op.drop_column("va_project_sites", "daily_interviewer_limit")
    op.drop_column("va_project_sites", "collection_end_date")
    op.drop_column("va_project_sites", "collection_start_date")
    op.drop_column("va_project_sites", "collection_enabled")
