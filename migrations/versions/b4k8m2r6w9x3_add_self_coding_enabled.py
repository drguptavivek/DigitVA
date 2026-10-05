"""Add self_coding_enabled to va_project_master.

Revision ID: b4k8m2r6w9x3
Revises: h2n5q8t1v4w7
Create Date: 2026-10-05 12:00:00.000000

Per-project self-coding (digitva-xuxk, docs/policy/web-intake.md,
"Self-coding projects"): in such a project a coder also interviews. Off by
default, so every existing project behaves exactly as before.

Purely additive: one new NOT NULL column with a ``false`` server default, no
existing column touched, no data rewritten. The downgrade drops it.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b4k8m2r6w9x3"
down_revision = "h2n5q8t1v4w7"
branch_labels = None
depends_on = None

TABLE = "va_project_master"
COLUMN = "self_coding_enabled"


def upgrade():
    op.add_column(
        TABLE,
        sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    op.drop_column(TABLE, COLUMN)
