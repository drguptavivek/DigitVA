"""add form_type_id to map_project_site_odk

Revision ID: p3q7r9s1t2u5
Revises: n1lhxggm3txo
Create Date: 2026-03-11T00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'p3q7r9s1t2u5'
down_revision = '1153a3e3a825'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'map_project_site_odk',
        sa.Column(
            'form_type_id',
            sa.Uuid(as_uuid=True),
            sa.ForeignKey('mas_form_types.form_type_id'),
            nullable=True,
        )
    )


def downgrade():
    op.drop_column('map_project_site_odk', 'form_type_id')
