"""increase_va_deceased_gender_to_20

Revision ID: 1ff01015ccd4
Revises: 9ecc04221667
Create Date: 2026-03-16 23:57:46.736497

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '1ff01015ccd4'
down_revision = '9ecc04221667'
branch_labels = None
depends_on = None


def upgrade():
    # Already applied directly, kept for migration history
    op.alter_column(
        'va_submissions',
        'va_deceased_gender',
        existing_type=sa.String(16),
        type_=sa.String(20),
    )


def downgrade():
    op.alter_column(
        'va_submissions',
        'va_deceased_gender',
        existing_type=sa.String(20),
        type_=sa.String(16),
    )
