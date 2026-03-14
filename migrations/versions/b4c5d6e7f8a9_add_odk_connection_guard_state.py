"""add odk connection guard state

Revision ID: b4c5d6e7f8a9
Revises: a1b2c3d4e5f6
Create Date: 2026-03-14 20:25:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b4c5d6e7f8a9"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "mas_odk_connections",
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "mas_odk_connections",
        sa.Column(
            "consecutive_failure_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "mas_odk_connections",
        sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "mas_odk_connections",
        sa.Column("last_failure_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "mas_odk_connections",
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "mas_odk_connections",
        sa.Column("last_request_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.alter_column(
        "mas_odk_connections",
        "consecutive_failure_count",
        server_default=None,
    )


def downgrade():
    op.drop_column("mas_odk_connections", "last_request_started_at")
    op.drop_column("mas_odk_connections", "last_success_at")
    op.drop_column("mas_odk_connections", "last_failure_message")
    op.drop_column("mas_odk_connections", "last_failure_at")
    op.drop_column("mas_odk_connections", "consecutive_failure_count")
    op.drop_column("mas_odk_connections", "cooldown_until")
