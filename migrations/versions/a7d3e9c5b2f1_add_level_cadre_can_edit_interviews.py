"""Add map_org_level_cadre.can_edit_interviews.

Revision ID: a7d3e9c5b2f1
Revises: f4c2a8e6b1d9
Create Date: 2026-11-23

Additive (digitva-6dh9, docs/policy/interview-revisions.md "Supervisor
correction"): an interview_supervisor whose cadre has this ticked on the level
x cadre grid at the grant unit's level may correct a submitted interview in
reach. Default false for every row, so nobody gains the power until an admin
or project PI ticks it. Downgrade drops the column: a setting, not data, and
the power simply ends.
"""

import sqlalchemy as sa
from alembic import op

revision = "a7d3e9c5b2f1"
down_revision = "f4c2a8e6b1d9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "map_org_level_cadre",
        sa.Column("can_edit_interviews", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column("map_org_level_cadre", "can_edit_interviews")
