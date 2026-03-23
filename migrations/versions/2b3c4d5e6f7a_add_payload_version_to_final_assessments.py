"""Add payload-version linkage to final assessment artifacts.

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6f
Create Date: 2026-03-23 13:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "2b3c4d5e6f7a"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_final_assessments",
        sa.Column("payload_version_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_va_final_assessments_payload_version_id",
        "va_final_assessments",
        ["payload_version_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_va_final_assessments_payload_version_id",
        "va_final_assessments",
        "va_submission_payload_versions",
        ["payload_version_id"],
        ["payload_version_id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "va_reviewer_final_assessments",
        sa.Column("payload_version_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_va_reviewer_final_assessments_payload_version_id",
        "va_reviewer_final_assessments",
        ["payload_version_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_va_reviewer_final_assessments_payload_version_id",
        "va_reviewer_final_assessments",
        "va_submission_payload_versions",
        ["payload_version_id"],
        ["payload_version_id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        UPDATE va_final_assessments AS fa
        SET payload_version_id = s.active_payload_version_id
        FROM va_submissions AS s
        WHERE s.va_sid = fa.va_sid
          AND s.active_payload_version_id IS NOT NULL
          AND fa.payload_version_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE va_reviewer_final_assessments AS rfa
        SET payload_version_id = s.active_payload_version_id
        FROM va_submissions AS s
        WHERE s.va_sid = rfa.va_sid
          AND s.active_payload_version_id IS NOT NULL
          AND rfa.payload_version_id IS NULL
        """
    )


def downgrade():
    op.drop_constraint(
        "fk_va_reviewer_final_assessments_payload_version_id",
        "va_reviewer_final_assessments",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_va_reviewer_final_assessments_payload_version_id",
        table_name="va_reviewer_final_assessments",
    )
    op.drop_column("va_reviewer_final_assessments", "payload_version_id")

    op.drop_constraint(
        "fk_va_final_assessments_payload_version_id",
        "va_final_assessments",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_va_final_assessments_payload_version_id",
        table_name="va_final_assessments",
    )
    op.drop_column("va_final_assessments", "payload_version_id")
