"""Index for the worklist's "Recent" order (newest reported first).

Revision ID: a4c9e1f2b7d3
Revises: t3k8n1d6f2a9
Create Date: 2026-10-14 09:00:00.000000

digitva-83bz (VA Interview table). Policy: docs/policy/web-intake.md, "The
list". Additive and reversible: one index on ``va_death_register`` that serves
``GET /api/v1/intake/cases?sort=reported`` (ORDER BY created_at DESC, death_id
DESC, keyset-paged). Downgrade drops only the index.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "a4c9e1f2b7d3"
down_revision = "t3k8n1d6f2a9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_va_death_register_created", "va_death_register", ["created_at", "death_id"])


def downgrade():
    op.drop_index("ix_va_death_register_created", table_name="va_death_register")
