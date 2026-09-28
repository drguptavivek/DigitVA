"""Add the per-unit VA question presets table.

Revision ID: b1f4d8a6c9e2
Revises: c1d5e9a2f7b4
Create Date: 2026-09-28 00:00:00.000000

Additive only: one new table, ``map_org_unit_va_presets``. A row sets
Id10002 (HIV/AIDS mortality) and/or Id10003 (malaria mortality) presets for
one organization unit's subtree; a unit with no row, or a null field, does
not set that preset -- it is inherited from the nearest ancestor that does
(resolution lives in application code, not in this schema). See
docs/policy/web-intake.md ("Area VA presets").
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b1f4d8a6c9e2"
down_revision = "c1d5e9a2f7b4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "map_org_unit_va_presets",
        sa.Column("org_unit_id", sa.Uuid(), nullable=False),
        sa.Column("hiv_mortality", sa.String(length=8), nullable=True),
        sa.Column("malaria_mortality", sa.String(length=8), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.PrimaryKeyConstraint("org_unit_id"),
        sa.ForeignKeyConstraint(
            ["org_unit_id"],
            ["mas_org_unit.org_unit_id"],
            name="fk_map_org_unit_va_presets_org_unit",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["va_users.user_id"],
            name="fk_map_org_unit_va_presets_updated_by",
        ),
        # op.create_table runs through the app's naming convention
        # (ck_%(table_name)s_%(constraint_name)s), which would double-prefix
        # an already-prefixed name -- pass only the discriminator, matching
        # the model (digitva-liu / fd232fab5987 is this exact mistake, fixed
        # elsewhere after the fact).
        sa.CheckConstraint("hiv_mortality IN ('high', 'low', 'veryl')", name="hiv_mortality"),
        sa.CheckConstraint("malaria_mortality IN ('high', 'low', 'veryl')", name="malaria_mortality"),
    )


def downgrade():
    op.drop_table("map_org_unit_va_presets")
