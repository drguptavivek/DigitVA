"""Add the polled per-user notification inbox.

Bead digitva-hdrv. ``map_user_notifications`` holds one row per nudge for one
user (ids and a fixed kind, no personal data), written in the transaction of the
event and purged after 30 days. Additive and reversible; starts empty.

Revision ID: h2n5q8t1v4w7
Revises: a8c4e2f6b9d1
Create Date: 2026-10-05
"""

import sqlalchemy as sa
from alembic import op

revision = "h2n5q8t1v4w7"
down_revision = "a8c4e2f6b9d1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "map_user_notifications",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("va_users.user_id"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=6), nullable=False),
        sa.Column("death_id", sa.Uuid(), nullable=True),
        sa.Column("draft_id", sa.Uuid(), nullable=True),
        sa.Column("va_sid", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_map_user_notifications_user_id_id", "map_user_notifications", ["user_id", "id"])
    op.create_index("ix_map_user_notifications_created_at", "map_user_notifications", ["created_at"])


def downgrade():
    op.drop_index("ix_map_user_notifications_created_at", table_name="map_user_notifications")
    op.drop_index("ix_map_user_notifications_user_id_id", table_name="map_user_notifications")
    op.drop_table("map_user_notifications")
