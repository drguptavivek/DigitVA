"""add attachment progress tracking to va sync runs

Revision ID: c7d8e9f0a1b2
Revises: b2c4d6e8f0a1
Create Date: 2026-04-02 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c7d8e9f0a1b2"
down_revision = "b2c4d6e8f0a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("va_sync_runs", sa.Column("attachment_forms_total", sa.Integer(), nullable=True))
    op.add_column("va_sync_runs", sa.Column("attachment_forms_completed", sa.Integer(), nullable=True))
    op.add_column("va_sync_runs", sa.Column("attachment_downloaded", sa.Integer(), nullable=True))
    op.add_column("va_sync_runs", sa.Column("attachment_skipped", sa.Integer(), nullable=True))
    op.add_column("va_sync_runs", sa.Column("attachment_errors", sa.Integer(), nullable=True))
    op.add_column("va_sync_runs", sa.Column("smartva_records_generated", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("va_sync_runs", "smartva_records_generated")
    op.drop_column("va_sync_runs", "attachment_errors")
    op.drop_column("va_sync_runs", "attachment_skipped")
    op.drop_column("va_sync_runs", "attachment_downloaded")
    op.drop_column("va_sync_runs", "attachment_forms_completed")
    op.drop_column("va_sync_runs", "attachment_forms_total")
