"""allow decimal field display order

Revision ID: b6d9f3c4e1a2
Revises: a383b3c82328
Create Date: 2026-03-12 17:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b6d9f3c4e1a2'
down_revision = 'a383b3c82328'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('mas_field_display_config', schema=None) as batch_op:
        batch_op.alter_column(
            'display_order',
            existing_type=sa.Integer(),
            type_=sa.Numeric(10, 2),
            postgresql_using='display_order::numeric(10,2)',
            existing_nullable=False,
        )


def downgrade():
    with op.batch_alter_table('mas_field_display_config', schema=None) as batch_op:
        batch_op.alter_column(
            'display_order',
            existing_type=sa.Numeric(10, 2),
            type_=sa.Integer(),
            postgresql_using='round(display_order)::integer',
            existing_nullable=False,
        )
