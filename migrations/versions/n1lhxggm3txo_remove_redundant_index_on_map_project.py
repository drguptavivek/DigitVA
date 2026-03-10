"""remove redundant index on map_project_site_odk id

Revision ID: n1lhxggm3txo
Revises: 1d95332b7d3c
Create Date: 2026-03-10T07:26:26.477245

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'n1lhxggm3txo'
down_revision = '1d95332b7d3c'
branch_labels = None
depends_on = None

def upgrade():
    op.drop_index('ix_map_project_site_odk_id', table_name='map_project_site_odk')

def downgrade():
    op.create_index('ix_map_project_site_odk_id', 'map_project_site_odk', ['id'], unique=False)
