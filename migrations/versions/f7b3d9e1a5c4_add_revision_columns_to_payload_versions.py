"""Record why and from which answers a payload version was made.

An interviewer's revision of a submitted interview (digitva-bhpl,
docs/policy/interview-revisions.md) is a new payload version carrying a fixed
``revision_reason_code`` and the ``answers_sha256`` of the exact answers text
the client sent. Both nullable: versions from ODK sync and earlier web
submissions have neither. Also indexes the draft by its submission id, which
a revision looks it up by. Additive and reversible.

Revision ID: f7b3d9e1a5c4
Revises: e6a2c9d4f1b7
Create Date: 2026-10-04
"""

import sqlalchemy as sa
from alembic import op

revision = "f7b3d9e1a5c4"
down_revision = "e6a2c9d4f1b7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("va_submission_payload_versions", sa.Column("revision_reason_code", sa.String(length=32), nullable=True))
    op.add_column("va_submission_payload_versions", sa.Column("answers_sha256", sa.String(length=64), nullable=True))
    op.create_index(
        "ix_va_web_intake_drafts_va_sid", "va_web_intake_drafts", ["va_sid"],
        postgresql_where=sa.text("va_sid IS NOT NULL"),
    )


def downgrade():
    op.drop_index("ix_va_web_intake_drafts_va_sid", table_name="va_web_intake_drafts")
    op.drop_column("va_submission_payload_versions", "answers_sha256")
    op.drop_column("va_submission_payload_versions", "revision_reason_code")
