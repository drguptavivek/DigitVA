"""Project coding scope: the level a death may be coded within.

Revision ID: f7b2d4e6a8c9
Revises: e2a5c8b1d7f3
Create Date: 2026-09-18 18:00:00.000000

Additive only. coding_scope_level_id is NULL for every existing project,
which means no unit-based coding scope and therefore no change to who may
code what. above_scope_coding_mode defaults to the conservative value,
'view_only', so enabling a scope level never silently widens access. Plan:
docs/planning/health-system-organization-model-plan.md (phase 4).
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f7b2d4e6a8c9"
down_revision = "e2a5c8b1d7f3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_project_master",
        sa.Column("coding_scope_level_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "va_project_master",
        sa.Column(
            "above_scope_coding_mode",
            sa.String(length=16),
            nullable=False,
            server_default="view_only",
        ),
    )
    op.create_foreign_key(
        "fk_va_project_master_coding_scope_level",
        "va_project_master",
        "mas_org_level",
        ["coding_scope_level_id"],
        ["org_level_id"],
    )
    op.create_check_constraint(
        "ck_va_project_master_above_scope_coding_mode",
        "va_project_master",
        "above_scope_coding_mode IN ('code_any', 'view_only')",
    )


def downgrade():
    for candidate in (
        "ck_va_project_master_above_scope_coding_mode",
        "ck_va_project_master_ck_va_project_master_above_scope_coding_mode",
    ):
        op.execute(
            f'ALTER TABLE va_project_master DROP CONSTRAINT IF EXISTS "{candidate}"'
        )
    op.drop_constraint(
        "fk_va_project_master_coding_scope_level", "va_project_master", type_="foreignkey"
    )
    op.drop_column("va_project_master", "above_scope_coding_mode")
    op.drop_column("va_project_master", "coding_scope_level_id")
