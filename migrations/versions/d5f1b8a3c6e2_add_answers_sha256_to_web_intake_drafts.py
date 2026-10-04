"""Store the answers hash of a device interview upload.

``answers_sha256`` is the SHA-256 of the exact answers JSON text the app
sent; a resend of the same ``client_draft_id`` is a duplicate only when the
hash is equal (digitva-2bxa, docs/policy/field-data-collection.md). Nullable:
web drafts and uploads stored before this have none.

Revision ID: d5f1b8a3c6e2
Revises: c4e8a1f7d2b3
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

revision = "d5f1b8a3c6e2"
down_revision = "c4e8a1f7d2b3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("va_web_intake_drafts", sa.Column("answers_sha256", sa.String(length=64), nullable=True))


def downgrade():
    op.drop_column("va_web_intake_drafts", "answers_sha256")
