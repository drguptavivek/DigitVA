"""Index va_web_intake_attachments(created_at) for the daily upload purge.

Revision ID: h5m2r8v4z1d9
Revises: g4k8p2t6x1b5
Create Date: 2026-10-06 22:00:00.000000

digitva-i9lb. The purge selects uploads older than 30 days, oldest first, in
bounded batches (``web_intake_attachment_service.purge_expired_uploads``); the
table's only other index is the unique storage name. Additive and reversible.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "h5m2r8v4z1d9"
down_revision = "g4k8p2t6x1b5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "ix_va_web_intake_attachments_created_at",
        "va_web_intake_attachments",
        ["created_at"],
    )


def downgrade():
    op.drop_index("ix_va_web_intake_attachments_created_at", table_name="va_web_intake_attachments")
