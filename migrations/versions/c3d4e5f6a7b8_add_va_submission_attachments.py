"""add_va_submission_attachments

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-14 14:00:00.000000

Adds va_submission_attachments table for ETag-based per-submission
attachment caching. One row per (va_sid, filename). Enables Phase 2
incremental sync: only download attachments that have changed since last sync.

Idempotent: checks information_schema.tables before creating.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c3d4e5f6a7b8'
down_revision = 'b2c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    exists = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' "
        "  AND table_name = 'va_submission_attachments'"
    )).scalar()
    if not exists:
        op.create_table(
            'va_submission_attachments',
            sa.Column('va_sid', sa.String(64), sa.ForeignKey('va_submissions.va_sid'),
                      primary_key=True, nullable=False),
            sa.Column('filename', sa.String(255), primary_key=True, nullable=False),
            sa.Column('local_path', sa.String(512), nullable=True),
            sa.Column('mime_type', sa.String(64), nullable=True),
            sa.Column('etag', sa.String(128), nullable=True),
            sa.Column('exists_on_odk', sa.Boolean(), nullable=False,
                      server_default=sa.text('true')),
            sa.Column('last_downloaded_at', sa.DateTime(timezone=True), nullable=True),
        )


def downgrade():
    conn = op.get_bind()
    exists = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables "
        "WHERE table_schema = 'public' "
        "  AND table_name = 'va_submission_attachments'"
    )).scalar()
    if exists:
        op.drop_table('va_submission_attachments')
