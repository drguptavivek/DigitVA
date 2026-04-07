"""add project_target_completion_date to va_project_master

Enables C-18 burndown chart: admin-configurable target date for project completion.
Used to project coding progress and deadline tracking.

Revision ID: f9a0b1c2d3e4
Revises: d7e8f9a0b1c2
Create Date: 2026-04-07T00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'f9a0b1c2d3e4'
down_revision = 'd7e8f9a0b1c2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'va_project_master',
        sa.Column('project_target_completion_date', sa.Date(), nullable=True)
    )


def downgrade():
    op.drop_column('va_project_master', 'project_target_completion_date')
