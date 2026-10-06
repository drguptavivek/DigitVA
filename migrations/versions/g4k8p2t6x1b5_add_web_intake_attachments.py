"""Add va_web_intake_attachments, the files uploaded for a draft before submit.

Revision ID: g4k8p2t6x1b5
Revises: g3k7n1s5v9y2
Create Date: 2026-10-06 21:00:00.000000

digitva-ej1. The web questionnaire uploads audio narration, images and files
while the interview is still a draft, before a submission id exists, so
``va_submission_attachments`` (keyed by submission) cannot hold them. One row
per (draft, client-generated attachment id): the primary key is the
idempotency key of the upload. Additive and reversible: a new table only; the
downgrade drops it (the stored objects stay in the attachment store, which
never deletes, see docs/policy/attachment-storage.md).
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "g4k8p2t6x1b5"
down_revision = "g3k7n1s5v9y2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "va_web_intake_attachments",
        sa.Column("draft_id", sa.Uuid(), nullable=False),
        sa.Column("client_attachment_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_name", sa.String(length=64), nullable=False),
        sa.Column("local_path", sa.String(length=512), nullable=True),
        sa.Column("store_state", sa.String(length=16), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("draft_id", "client_attachment_id"),
        sa.ForeignKeyConstraint(["draft_id"], ["va_web_intake_drafts.draft_id"]),
    )
    op.create_index(
        "uq_va_web_intake_attachments_storage_name",
        "va_web_intake_attachments",
        ["storage_name"],
        unique=True,
    )


def downgrade():
    op.drop_index("uq_va_web_intake_attachments_storage_name", table_name="va_web_intake_attachments")
    op.drop_table("va_web_intake_attachments")
