"""add project coding intake mode

Revision ID: e1f2a3b4c5d6
Revises: d9e1f2a3b4c5
Create Date: 2026-03-14 15:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e1f2a3b4c5d6"
down_revision = "d9e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_project_master",
        sa.Column(
            "coding_intake_mode",
            sa.String(length=32),
            nullable=False,
            server_default="random_form_allocation",
        ),
    )


def downgrade():
    op.drop_column("va_project_master", "coding_intake_mode")
