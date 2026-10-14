"""Record ODK attachments refused for size, and the refused count per sync run.

Revision ID: t3k8n1d6f2a9
Revises: q7w2e5r8t1y4
Create Date: 2026-10-14 09:00:00.000000

refused_reason and refused_size_bytes on va_submission_attachments hold the
refusal of an ODK file over its size cap (docs/policy/odk-attachment-intake-limits.md).
attachment_refused on va_sync_runs counts those per run. All three are nullable
and additive: no existing row or value changes. Downgrade drops them, and with
them any refusal record.
"""
import sqlalchemy as sa
from alembic import op

revision = "t3k8n1d6f2a9"
down_revision = "q7w2e5r8t1y4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_submission_attachments",
        sa.Column("refused_reason", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "va_submission_attachments",
        sa.Column("refused_size_bytes", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "va_sync_runs",
        sa.Column("attachment_refused", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_column("va_sync_runs", "attachment_refused")
    op.drop_column("va_submission_attachments", "refused_size_bytes")
    op.drop_column("va_submission_attachments", "refused_reason")
