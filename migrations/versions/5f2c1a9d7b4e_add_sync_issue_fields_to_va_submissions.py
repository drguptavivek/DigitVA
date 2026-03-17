"""add sync issue fields to va_submissions

Revision ID: 5f2c1a9d7b4e
Revises: 1ff01015ccd4
Create Date: 2026-03-17 23:55:00.000000

"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5f2c1a9d7b4e"
down_revision = "1ff01015ccd4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("va_submissions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("va_sync_issue_code", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("va_sync_issue_detail", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("va_sync_issue_updated_at", sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f("ix_va_submissions_va_sync_issue_code"), ["va_sync_issue_code"], unique=False)
        batch_op.create_index(batch_op.f("ix_va_submissions_va_sync_issue_updated_at"), ["va_sync_issue_updated_at"], unique=False)


def downgrade():
    with op.batch_alter_table("va_submissions", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_va_submissions_va_sync_issue_updated_at"))
        batch_op.drop_index(batch_op.f("ix_va_submissions_va_sync_issue_code"))
        batch_op.drop_column("va_sync_issue_updated_at")
        batch_op.drop_column("va_sync_issue_detail")
        batch_op.drop_column("va_sync_issue_code")
