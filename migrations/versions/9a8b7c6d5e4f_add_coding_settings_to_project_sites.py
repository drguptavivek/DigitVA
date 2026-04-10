"""add coding settings to va_project_sites

Adds coding_enabled, coding_start_date, coding_end_date, daily_coder_limit
to support per-site coding window and throughput configuration.

Revision ID: 9a8b7c6d5e4f
Revises: c8d9e0f1a2b3
Create Date: 2026-04-10

"""
from alembic import op
import sqlalchemy as sa

revision = '9a8b7c6d5e4f'
down_revision = 'c8d9e0f1a2b3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'va_project_sites',
        sa.Column('coding_enabled', sa.Boolean(), nullable=False, server_default=sa.text('true'))
    )
    op.add_column(
        'va_project_sites',
        sa.Column('coding_start_date', sa.Date(), nullable=True)
    )
    op.add_column(
        'va_project_sites',
        sa.Column('coding_end_date', sa.Date(), nullable=True)
    )
    op.add_column(
        'va_project_sites',
        sa.Column('daily_coder_limit', sa.Integer(), nullable=False, server_default=sa.text('100'))
    )


def downgrade():
    op.drop_column('va_project_sites', 'daily_coder_limit')
    op.drop_column('va_project_sites', 'coding_end_date')
    op.drop_column('va_project_sites', 'coding_start_date')
    op.drop_column('va_project_sites', 'coding_enabled')
