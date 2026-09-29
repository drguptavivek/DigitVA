"""Index va_death_register.va_sid for confirmed duplicates.

Every coding reader filters out submissions whose case is a confirmed
duplicate through a correlated NOT EXISTS on va_death_register.va_sid
(app/services/duplicate_exclusion.py). Only rows with status 'duplicate'
are ever matched, so a partial index keeps the lookup an index probe and
stays tiny. Additive; downgrade drops the index only.

Revision ID: f2a6d9c3e8b1
Revises: e5b2c8d4a1f7
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "f2a6d9c3e8b1"
down_revision = "e5b2c8d4a1f7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_va_death_register_duplicate_va_sid",
        "va_death_register",
        ["va_sid"],
        postgresql_where=sa.text("status = 'duplicate'"),
    )


def downgrade():
    op.drop_index("ix_va_death_register_duplicate_va_sid", table_name="va_death_register")
