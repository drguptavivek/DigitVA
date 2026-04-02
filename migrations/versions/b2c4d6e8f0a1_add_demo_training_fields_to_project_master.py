"""add demo training fields to project master

Revision ID: b2c4d6e8f0a1
Revises: ab4d6f7c9e21
Create Date: 2026-04-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b2c4d6e8f0a1"
down_revision = "ab4d6f7c9e21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "va_project_master",
        sa.Column(
            "demo_training_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "va_project_master",
        sa.Column(
            "demo_retention_minutes",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("10"),
        ),
    )


def downgrade() -> None:
    op.drop_column("va_project_master", "demo_retention_minutes")
    op.drop_column("va_project_master", "demo_training_enabled")
