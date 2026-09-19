"""Add the per-unit coding gate table.

Revision ID: a40c38e73af4
Revises: f1c6a9d3e7b5
Create Date: 2026-09-18 00:00:00.000000

Additive only: one new table, ``map_org_unit_coding_gate``. A row narrows
coding for one organization unit's subtree; a unit with no row is not
gated (absence is not a closed unit). See
.tasks/org-per-unit-coding-gates.md and docs/policy/organization-model.md
("Coding scope") for the inheritance and precedence rules -- resolution and
enforcement live in application code, not in this schema.

This chains onto f1c6a9d3e7b5 (the collaborator_pii migration), not onto the
locally-present b8e3d1f7a2c4 head, which belongs to a different in-flight
change and must not be depended on here.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a40c38e73af4"
down_revision = "f1c6a9d3e7b5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "map_org_unit_coding_gate",
        sa.Column("org_unit_id", sa.Uuid(), nullable=False),
        sa.Column("coding_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("coding_start_date", sa.Date(), nullable=True),
        sa.Column("coding_end_date", sa.Date(), nullable=True),
        sa.Column("daily_coder_limit", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("org_unit_id"),
        sa.ForeignKeyConstraint(
            ["org_unit_id"],
            ["mas_org_unit.org_unit_id"],
            name="fk_map_org_unit_coding_gate_org_unit",
        ),
    )


def downgrade():
    op.drop_table("map_org_unit_coding_gate")
