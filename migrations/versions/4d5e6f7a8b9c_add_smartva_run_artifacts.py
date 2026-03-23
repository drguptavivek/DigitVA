"""Add SmartVA run artifact storage.

Revision ID: 4d5e6f7a8b9c
Revises: 3c4d5e6f7a8b
Create Date: 2026-03-23 16:20:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "4d5e6f7a8b9c"
down_revision = "3c4d5e6f7a8b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "va_smartva_run_artifacts",
        sa.Column("va_smartva_run_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("va_smartva_run_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_kind", sa.String(length=32), nullable=False),
        sa.Column("artifact_filename", sa.String(length=255), nullable=True),
        sa.Column("artifact_mime_type", sa.String(length=128), nullable=True),
        sa.Column("artifact_bytes", sa.LargeBinary(), nullable=False),
        sa.Column(
            "artifact_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("artifact_created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["va_smartva_run_id"],
            ["va_smartva_runs.va_smartva_run_id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("va_smartva_run_artifact_id"),
    )
    op.create_index(
        "ix_va_smartva_run_artifacts_id",
        "va_smartva_run_artifacts",
        ["va_smartva_run_artifact_id"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_run_artifacts_run_id",
        "va_smartva_run_artifacts",
        ["va_smartva_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_run_artifacts_kind",
        "va_smartva_run_artifacts",
        ["artifact_kind"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_run_artifacts_created_at",
        "va_smartva_run_artifacts",
        ["artifact_created_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_va_smartva_run_artifacts_created_at",
        table_name="va_smartva_run_artifacts",
    )
    op.drop_index(
        "ix_va_smartva_run_artifacts_kind",
        table_name="va_smartva_run_artifacts",
    )
    op.drop_index(
        "ix_va_smartva_run_artifacts_run_id",
        table_name="va_smartva_run_artifacts",
    )
    op.drop_index(
        "ix_va_smartva_run_artifacts_id",
        table_name="va_smartva_run_artifacts",
    )
    op.drop_table("va_smartva_run_artifacts")
