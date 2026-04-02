"""Add payload-version linkage to reviewer review artifacts.

Revision ID: ab4d6f7c9e21
Revises: 9c6d4b2a1f0e
Create Date: 2026-04-02 05:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "ab4d6f7c9e21"
down_revision = "9c6d4b2a1f0e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "va_reviewer_review",
        sa.Column("payload_version_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_va_reviewer_review_payload_version_id",
        "va_reviewer_review",
        ["payload_version_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_va_reviewer_review_payload_version_id",
        "va_reviewer_review",
        "va_submission_payload_versions",
        ["payload_version_id"],
        ["payload_version_id"],
        ondelete="SET NULL",
    )
    op.execute(
        """
        UPDATE va_reviewer_review AS rr
        SET payload_version_id = s.active_payload_version_id
        FROM va_submissions AS s
        WHERE s.va_sid = rr.va_sid
          AND s.active_payload_version_id IS NOT NULL
          AND rr.payload_version_id IS NULL
        """
    )
    op.create_index(
        "ix_va_reviewer_review_active_sid_by_unique",
        "va_reviewer_review",
        ["va_sid", "va_rreview_by"],
        unique=True,
        postgresql_where=sa.text("va_rreview_status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_va_reviewer_review_active_sid_by_unique",
        table_name="va_reviewer_review",
    )
    op.drop_constraint(
        "fk_va_reviewer_review_payload_version_id",
        "va_reviewer_review",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_va_reviewer_review_payload_version_id",
        table_name="va_reviewer_review",
    )
    op.drop_column("va_reviewer_review", "payload_version_id")
