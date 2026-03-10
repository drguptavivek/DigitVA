"""add odk_label to mas_field_display_config

Revision ID: 1153a3e3a825
Revises: f4928a94d422
Create Date: 2026-03-10 17:05:12.347626

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '1153a3e3a825'
down_revision = 'f4928a94d422'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('mas_field_display_config', schema=None) as batch_op:
        batch_op.add_column(sa.Column('odk_label', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('mas_field_display_config', schema=None) as batch_op:
        batch_op.drop_column('odk_label')
