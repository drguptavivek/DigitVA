"""add_nqa_cannot_grade

Revision ID: add_nqa_cannot_grade
Revises: a1b3c5d7e9f0
Create Date: 2026-04-07 12:45:57.927342

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'add_nqa_cannot_grade'
down_revision = 'a1b3c5d7e9f0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_narrative_assessments",
        sa.Column("va_nqa_cannot_grade", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade():
    op.drop_column("va_narrative_assessments", "va_nqa_cannot_grade")
