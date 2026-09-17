"""add health-system organization master tables

Revision ID: c8d2e4f6a1b3
Revises: b7c41e0d95af
Create Date: 2026-09-17 12:00:00.000000

Additive only: five new tables and the ltree extension. Plan:
docs/planning/health-system-organization-model-plan.md (phase 1).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c8d2e4f6a1b3"
down_revision = "b7c41e0d95af"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS ltree")

    op.create_table(
        "mas_org_level",
        sa.Column("org_level_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(length=6), nullable=False),
        sa.Column("level_code", sa.String(length=32), nullable=False),
        sa.Column("level_name", sa.String(length=128), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("is_optional", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("org_level_id"),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"]),
        sa.UniqueConstraint("project_id", "level_code", name="uq_mas_org_level_project_code"),
        sa.UniqueConstraint("project_id", "depth", name="uq_mas_org_level_project_depth"),
        sa.CheckConstraint("depth >= 1", name="ck_mas_org_level_depth_positive"),
    )
    op.create_index("ix_mas_org_level_project_id", "mas_org_level", ["project_id"])

    op.create_table(
        "mas_org_unit",
        sa.Column("org_unit_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(length=6), nullable=False),
        sa.Column("org_level_id", sa.Uuid(), nullable=False),
        sa.Column("parent_org_unit_id", sa.Uuid(), nullable=True),
        sa.Column("unit_code", sa.String(length=32), nullable=False),
        sa.Column("unit_name", sa.Text(), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),  # altered to LTREE below
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("google_maps_url", sa.Text(), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("org_unit_id"),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"]),
        sa.ForeignKeyConstraint(["org_level_id"], ["mas_org_level.org_level_id"]),
        sa.ForeignKeyConstraint(["parent_org_unit_id"], ["mas_org_unit.org_unit_id"]),
        sa.UniqueConstraint("project_id", "unit_code", name="uq_mas_org_unit_project_code"),
    )
    op.execute("ALTER TABLE mas_org_unit ALTER COLUMN path TYPE ltree USING path::ltree")
    op.create_index("ix_mas_org_unit_project_id", "mas_org_unit", ["project_id"])
    op.create_index("ix_mas_org_unit_org_level_id", "mas_org_unit", ["org_level_id"])
    op.create_index("ix_mas_org_unit_parent", "mas_org_unit", ["parent_org_unit_id"])
    op.create_index("ix_mas_org_unit_path", "mas_org_unit", ["path"], postgresql_using="gist")

    op.create_table(
        "mas_cadre",
        sa.Column("cadre_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(length=6), nullable=False),
        sa.Column("cadre_code", sa.String(length=32), nullable=False),
        sa.Column("cadre_name", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("cadre_id"),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"]),
        sa.UniqueConstraint("project_id", "cadre_code", name="uq_mas_cadre_project_code"),
    )
    op.create_index("ix_mas_cadre_project_id", "mas_cadre", ["project_id"])

    op.create_table(
        "map_org_level_cadre",
        sa.Column("level_cadre_id", sa.Uuid(), nullable=False),
        sa.Column("org_level_id", sa.Uuid(), nullable=False),
        sa.Column("cadre_id", sa.Uuid(), nullable=False),
        sa.Column("can_fill_va_form", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("can_code_va_form", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("level_cadre_id"),
        sa.ForeignKeyConstraint(["org_level_id"], ["mas_org_level.org_level_id"]),
        sa.ForeignKeyConstraint(["cadre_id"], ["mas_cadre.cadre_id"]),
        sa.UniqueConstraint("org_level_id", "cadre_id", name="uq_map_org_level_cadre"),
    )
    op.create_index("ix_map_org_level_cadre_org_level_id", "map_org_level_cadre", ["org_level_id"])
    op.create_index("ix_map_org_level_cadre_cadre_id", "map_org_level_cadre", ["cadre_id"])

    op.create_table(
        "mas_org_unit_worker",
        sa.Column("worker_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(length=6), nullable=False),
        sa.Column("org_unit_id", sa.Uuid(), nullable=False),
        sa.Column("cadre_id", sa.Uuid(), nullable=False),
        sa.Column("worker_code", sa.String(length=32), nullable=False),
        sa.Column("worker_name", sa.Text(), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.PrimaryKeyConstraint("worker_id"),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"]),
        sa.ForeignKeyConstraint(["org_unit_id"], ["mas_org_unit.org_unit_id"]),
        sa.ForeignKeyConstraint(["cadre_id"], ["mas_cadre.cadre_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["va_users.user_id"]),
        sa.UniqueConstraint("project_id", "worker_code", name="uq_mas_org_unit_worker_project_code"),
    )
    op.create_index("ix_mas_org_unit_worker_project_id", "mas_org_unit_worker", ["project_id"])
    op.create_index("ix_mas_org_unit_worker_unit", "mas_org_unit_worker", ["org_unit_id"])
    op.create_index("ix_mas_org_unit_worker_cadre_id", "mas_org_unit_worker", ["cadre_id"])
    op.create_index("ix_mas_org_unit_worker_user_id", "mas_org_unit_worker", ["user_id"])


def downgrade():
    op.drop_table("mas_org_unit_worker")
    op.drop_table("map_org_level_cadre")
    op.drop_table("mas_cadre")
    op.drop_table("mas_org_unit")
    op.drop_table("mas_org_level")
    # The ltree extension is left installed: dropping it could break other
    # objects created after this migration.
