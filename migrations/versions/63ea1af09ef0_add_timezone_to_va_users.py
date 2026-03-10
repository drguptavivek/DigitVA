"""add timezone to va_users

Revision ID: 63ea1af09ef0
Revises: n1lhxggm3txo
Create Date: 2026-03-10 08:03:04.590515

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '63ea1af09ef0'
down_revision = 'n1lhxggm3txo'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('va_users', sa.Column('timezone', sa.String(length=64), server_default='Asia/Kolkata', nullable=False))

def downgrade():
    op.drop_column('va_users', 'timezone')