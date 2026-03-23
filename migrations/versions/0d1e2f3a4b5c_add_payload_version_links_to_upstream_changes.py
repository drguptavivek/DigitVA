"""Add payload-version linkage columns to upstream-change records.

Revision ID: 0d1e2f3a4b5c
Revises: f0a1b2c3d4e5
Create Date: 2026-03-23 11:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0d1e2f3a4b5c"
down_revision = "f0a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_submission_upstream_changes",
        sa.Column("previous_payload_version_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "va_submission_upstream_changes",
        sa.Column("incoming_payload_version_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_va_submission_upstream_changes_previous_payload_version_id",
        "va_submission_upstream_changes",
        ["previous_payload_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_va_submission_upstream_changes_incoming_payload_version_id",
        "va_submission_upstream_changes",
        ["incoming_payload_version_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_upstream_changes_previous_payload_version_id",
        "va_submission_upstream_changes",
        "va_submission_payload_versions",
        ["previous_payload_version_id"],
        ["payload_version_id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_upstream_changes_incoming_payload_version_id",
        "va_submission_upstream_changes",
        "va_submission_payload_versions",
        ["incoming_payload_version_id"],
        ["payload_version_id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint(
        "fk_upstream_changes_incoming_payload_version_id",
        "va_submission_upstream_changes",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_upstream_changes_previous_payload_version_id",
        "va_submission_upstream_changes",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_va_submission_upstream_changes_incoming_payload_version_id",
        table_name="va_submission_upstream_changes",
    )
    op.drop_index(
        "ix_va_submission_upstream_changes_previous_payload_version_id",
        table_name="va_submission_upstream_changes",
    )
    op.drop_column("va_submission_upstream_changes", "incoming_payload_version_id")
    op.drop_column("va_submission_upstream_changes", "previous_payload_version_id")
