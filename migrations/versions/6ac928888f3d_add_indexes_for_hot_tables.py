"""add_indexes_for_hot_tables

Revision ID: 6ac928888f3d
Revises: e95dc3d7c4f2
Create Date: 2026-04-02 19:16:18.657540

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6ac928888f3d'
down_revision = 'e95dc3d7c4f2'
branch_labels = None
depends_on = None


def upgrade():
    # va_sync_runs: data-manager dashboard filters by triggered_by + orders by started_at DESC
    op.create_index(
        "ix_va_sync_runs_triggered_by_started_at",
        "va_sync_runs",
        ["triggered_by", sa.text("started_at DESC")],
    )

    # celery_periodictask: celery-beat polls for enabled tasks
    op.create_index(
        "ix_celery_periodictask_enabled",
        "celery_periodictask",
        ["enabled"],
    )


def downgrade():
    op.drop_index("ix_celery_periodictask_enabled", table_name="celery_periodictask")
    op.drop_index("ix_va_sync_runs_triggered_by_started_at", table_name="va_sync_runs")
