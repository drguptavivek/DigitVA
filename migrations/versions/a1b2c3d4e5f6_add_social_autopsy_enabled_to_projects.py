"""add social autopsy enabled flag to projects

Revision ID: aa12bb34cc56
Revises: c7d8e9f0a1b2
Create Date: 2026-04-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "aa12bb34cc56"
down_revision = "c7d8e9f0a1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "va_project_master",
        sa.Column(
            "social_autopsy_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="true",
        ),
    )


def downgrade() -> None:
    op.drop_column("va_project_master", "social_autopsy_enabled")
