"""Index map_training_participants.user_id.

Revision ID: c7f1d3a5e9b2
Revises: b4e8c2a6d0f3
Create Date: 2026-11-15

Additive: per-user lookups across sessions (access summary, training scope)
had only a partial index for pending onboarding.
"""

from alembic import op

revision = "c7f1d3a5e9b2"
down_revision = "b4e8c2a6d0f3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("ix_map_training_participants_user", "map_training_participants", ["user_id"])


def downgrade():
    op.drop_index("ix_map_training_participants_user", table_name="map_training_participants")
