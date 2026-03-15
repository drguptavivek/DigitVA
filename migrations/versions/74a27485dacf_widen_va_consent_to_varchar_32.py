"""Widen va_consent to varchar 32

Revision ID: 74a27485dacf
Revises: c9d0e1f2a3b4
Create Date: 2026-03-15 13:21:06.368398

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '74a27485dacf'
down_revision = 'c9d0e1f2a3b4'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('va_submissions', schema=None) as batch_op:
        batch_op.alter_column('va_consent',
               existing_type=sa.VARCHAR(length=4),
               type_=sa.String(length=32),
               existing_nullable=False)


def downgrade():
    with op.batch_alter_table('va_submissions', schema=None) as batch_op:
        batch_op.alter_column('va_consent',
               existing_type=sa.String(length=32),
               type_=sa.VARCHAR(length=4),
               existing_nullable=False)
