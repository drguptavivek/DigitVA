"""add storage_name to va_submission_attachments

Revision ID: cc557953614c
Revises: 080779a13b9f
Create Date: 2026-04-04 07:15:36.468061

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'cc557953614c'
down_revision = '080779a13b9f'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('va_submission_attachments',
        sa.Column('storage_name', sa.String(64), nullable=True))
    op.create_index(
        'ix_va_submission_attachments_storage_name',
        'va_submission_attachments',
        ['storage_name'],
        unique=True,
        postgresql_where=sa.text('storage_name IS NOT NULL')
    )


def downgrade():
    op.drop_index('ix_va_submission_attachments_storage_name', table_name='va_submission_attachments')
    op.drop_column('va_submission_attachments', 'storage_name')
