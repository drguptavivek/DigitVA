"""add va_daily_kpi_aggregates table

Pre-computed daily KPI snapshot per (snapshot_date, site_id).
Stores counts, rates, and aggregates for all daily KPI columns.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-04-07T00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'd7e8f9a0b1c2'
down_revision = 'c6d7e8f9a0b1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'va_daily_kpi_aggregates',
        sa.Column('snapshot_date', sa.Date(), nullable=False),
        sa.Column('site_id', sa.String(4), sa.ForeignKey('va_site_master.site_id'), nullable=False),
        sa.Column('project_id', sa.String(6), nullable=False),  # owning project on this date (audit)
        sa.Column('total_submissions', sa.Integer(), nullable=True),
        sa.Column('new_from_odk', sa.Integer(), nullable=True),
        sa.Column('updated_from_odk', sa.Integer(), nullable=True),
        sa.Column('coded_count', sa.Integer(), nullable=True),
        sa.Column('pending_count', sa.Integer(), nullable=True),
        sa.Column('consent_refused_count', sa.Integer(), nullable=True),
        sa.Column('not_codeable_count', sa.Integer(), nullable=True),
        sa.Column('coding_duration_min', sa.Interval(), nullable=True),
        sa.Column('coding_duration_max', sa.Interval(), nullable=True),
        sa.Column('coding_duration_p50', sa.Interval(), nullable=True),
        sa.Column('coding_duration_p90', sa.Interval(), nullable=True),
        sa.Column('reviewer_finalized_count', sa.Integer(), nullable=True),
        sa.Column('upstream_changed_count', sa.Integer(), nullable=True),
        sa.Column('reopened_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('snapshot_date', 'site_id', name='pk_va_daily_kpi_aggregates'),
    )

    # Indexes for common queries
    op.create_index('ix_va_daily_kpi_aggregates_site', 'va_daily_kpi_aggregates', ['site_id'])
    op.create_index('ix_va_daily_kpi_aggregates_project', 'va_daily_kpi_aggregates', ['project_id'])


def downgrade():
    op.drop_index('ix_va_daily_kpi_aggregates_project', table_name='va_daily_kpi_aggregates')
    op.drop_index('ix_va_daily_kpi_aggregates_site', table_name='va_daily_kpi_aggregates')
    op.drop_table('va_daily_kpi_aggregates')
