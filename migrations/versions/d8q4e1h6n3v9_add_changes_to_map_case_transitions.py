"""Add map_case_transitions.changes.

Revision ID: d8q4e1h6n3v9
Revises: c7p3d9k2m5t8
Create Date: 2026-10-06 14:00:00.000000

``changes`` (digitva-uq6v): the previous and new value of each case detail a
correction or an interview's identity copy changed, as
``{field: {"old": ..., "new": ...}}``. Personal data, so it is kept out of
``reason`` and never logged. Null on every other audit row and on rows
written before this migration.

Purely additive: one nullable column, no default, no data rewritten. The
downgrade drops it (the values are lost; the field names stay in ``reason``).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d8q4e1h6n3v9"
down_revision = "c7p3d9k2m5t8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "map_case_transitions",
        sa.Column("changes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade():
    op.drop_column("map_case_transitions", "changes")
