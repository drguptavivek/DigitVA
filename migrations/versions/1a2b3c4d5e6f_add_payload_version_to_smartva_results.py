"""Add payload-version linkage to SmartVA results.

Revision ID: 1a2b3c4d5e6f
Revises: 0d1e2f3a4b5c
Create Date: 2026-03-23 12:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "1a2b3c4d5e6f"
down_revision = "0d1e2f3a4b5c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_smartva_results",
        sa.Column("payload_version_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_va_smartva_results_payload_version_id",
        "va_smartva_results",
        ["payload_version_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_va_smartva_results_payload_version_id",
        "va_smartva_results",
        "va_submission_payload_versions",
        ["payload_version_id"],
        ["payload_version_id"],
        ondelete="SET NULL",
    )

    op.execute(
        """
        UPDATE va_smartva_results AS svr
        SET payload_version_id = s.active_payload_version_id
        FROM va_submissions AS s
        WHERE s.va_sid = svr.va_sid
          AND s.active_payload_version_id IS NOT NULL
          AND svr.payload_version_id IS NULL
        """
    )


def downgrade():
    op.drop_constraint(
        "fk_va_smartva_results_payload_version_id",
        "va_smartva_results",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_va_smartva_results_payload_version_id",
        table_name="va_smartva_results",
    )
    op.drop_column("va_smartva_results", "payload_version_id")
