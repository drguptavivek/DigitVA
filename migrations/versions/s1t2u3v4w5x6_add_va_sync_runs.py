"""add va_sync_runs table

Revision ID: s1t2u3v4w5x6
Revises: c7f1d2e3a4b5
Create Date: 2026-03-12T00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 's1t2u3v4w5x6'
down_revision = 'c7f1d2e3a4b5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'va_sync_runs',
        sa.Column('sync_run_id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('triggered_by', sa.String(16), nullable=False),
        sa.Column(
            'triggered_user_id',
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey('va_users.user_id'),
            nullable=True,
            index=True,
        ),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('records_added', sa.Integer(), nullable=True),
        sa.Column('records_updated', sa.Integer(), nullable=True),
        sa.Column('records_skipped', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
    )


def downgrade():
    op.drop_table('va_sync_runs')
