"""increase_va_deceased_gender_length

Revision ID: 9ecc04221667
Revises: b3a1c2d4e5f6
Create Date: 2026-03-16 23:54:11.333023

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9ecc04221667'
down_revision = 'b3a1c2d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column(
        'va_submissions',
        'va_deceased_gender',
        existing_type=sa.String(8),
        type_=sa.String(20),
    )


def downgrade():
    op.alter_column(
        'va_submissions',
        'va_deceased_gender',
        existing_type=sa.String(20),
        type_=sa.String(8),
    )
