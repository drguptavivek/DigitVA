"""Allocation kind: tell recode and demo allocations from new cases.

Revision ID: b8e4c1d7f3a2
Revises: a7d3f9c2e5b1
Create Date: 2026-11-06

Owner decision 2026-11-06: only new cases count toward the coder daily
allocation cap; recode, demo and practice allocations do not. Policy:
docs/policy/coding-workflow-state-machine.md ("Coder daily allocation limit").

Additive and nullable: NULL is a new case. Existing rows are not backfilled;
the cap counts one project-clock day, so older recode or demo rows only
matter on the day of the upgrade. Downgrade drops the column.
"""

import sqlalchemy as sa
from alembic import op

revision = "b8e4c1d7f3a2"
down_revision = "a7d3f9c2e5b1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_allocations",
        sa.Column("va_allocation_kind", sa.String(length=16), nullable=True),
    )


def downgrade():
    op.drop_column("va_allocations", "va_allocation_kind")
