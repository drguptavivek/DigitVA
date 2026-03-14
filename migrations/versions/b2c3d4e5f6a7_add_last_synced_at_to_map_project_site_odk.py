"""add_last_synced_at_to_map_project_site_odk

Revision ID: b2c3d4e5f6a7
Revises: 17daf4c488e7
Create Date: 2026-03-14 12:00:00.000000

Adds last_synced_at (TIMESTAMP WITH TIME ZONE, nullable) to map_project_site_odk.
Used by the incremental sync delta check to record when a form was last
successfully synced. NULL means never synced → always download on next run.

Idempotent: checks information_schema.columns before altering.
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2c3d4e5f6a7'
down_revision = '17daf4c488e7'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    exists = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'map_project_site_odk' "
        "  AND column_name = 'last_synced_at'"
    )).scalar()
    if not exists:
        with op.batch_alter_table('map_project_site_odk', schema=None) as batch_op:
            batch_op.add_column(
                sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True)
            )


def downgrade():
    conn = op.get_bind()
    exists = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'map_project_site_odk' "
        "  AND column_name = 'last_synced_at'"
    )).scalar()
    if exists:
        with op.batch_alter_table('map_project_site_odk', schema=None) as batch_op:
            batch_op.drop_column('last_synced_at')
