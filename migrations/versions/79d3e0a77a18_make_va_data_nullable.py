"""make_va_data_nullable

Revision ID: 79d3e0a77a18
Revises: 6ac928888f3d
Create Date: 2026-04-03 04:05:03.062870

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '79d3e0a77a18'
down_revision = '6ac928888f3d'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        "va_submissions",
        "va_data",
        existing_type=sa.dialects.postgresql.JSONB,
        nullable=True,
    )


def downgrade():
    op.alter_column(
        "va_submissions",
        "va_data",
        existing_type=sa.dialects.postgresql.JSONB,
        nullable=False,
    )
