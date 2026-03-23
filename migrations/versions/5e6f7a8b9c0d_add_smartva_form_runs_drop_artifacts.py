"""Add SmartVA form runs and drop run artifacts.

Revision ID: 5e6f7a8b9c0d
Revises: 4d5e6f7a8b9c
Create Date: 2026-03-23 21:25:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "5e6f7a8b9c0d"
down_revision = "4d5e6f7a8b9c"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "va_smartva_form_runs",
        sa.Column("form_run_id", sa.Uuid(), nullable=False),
        sa.Column("form_id", sa.String(length=12), nullable=False),
        sa.Column("project_id", sa.String(length=6), nullable=False),
        sa.Column("trigger_source", sa.String(length=32), nullable=False),
        sa.Column("pending_sid_count", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=True),
        sa.Column("disk_path", sa.String(length=255), nullable=True),
        sa.Column("run_started_at", sa.DateTime(), nullable=False),
        sa.Column("run_completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "outcome IN ('success', 'partial', 'failed')",
            name="ck_va_smartva_form_runs_outcome",
        ),
        sa.ForeignKeyConstraint(["form_id"], ["va_forms.form_id"]),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["va_research_projects.project_id"],
        ),
        sa.PrimaryKeyConstraint("form_run_id"),
    )
    op.create_index(
        "ix_va_smartva_form_runs_id",
        "va_smartva_form_runs",
        ["form_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_form_runs_form_id",
        "va_smartva_form_runs",
        ["form_id"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_form_runs_project_id",
        "va_smartva_form_runs",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_form_runs_trigger_source",
        "va_smartva_form_runs",
        ["trigger_source"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_form_runs_outcome",
        "va_smartva_form_runs",
        ["outcome"],
        unique=False,
    )
    op.create_index(
        "ix_va_smartva_form_runs_started_at",
        "va_smartva_form_runs",
        ["run_started_at"],
        unique=False,
    )

    op.add_column(
        "va_smartva_runs",
        sa.Column("form_run_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        "ix_va_smartva_runs_form_run_id",
        "va_smartva_runs",
        ["form_run_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_va_smartva_runs_form_run_id",
        "va_smartva_runs",
        "va_smartva_form_runs",
        ["form_run_id"],
        ["form_run_id"],
        ondelete="SET NULL",
    )

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


def downgrade():
    op.create_table(
        "va_smartva_run_artifacts",
        sa.Column("va_smartva_run_artifact_id", sa.Uuid(), nullable=False),
        sa.Column("va_smartva_run_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_kind", sa.String(length=32), nullable=False),
        sa.Column("artifact_filename", sa.String(length=255), nullable=True),
        sa.Column("artifact_mime_type", sa.String(length=128), nullable=True),
        sa.Column("artifact_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("artifact_metadata", sa.JSON(), nullable=True),
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

    op.drop_constraint(
        "fk_va_smartva_runs_form_run_id",
        "va_smartva_runs",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_va_smartva_runs_form_run_id",
        table_name="va_smartva_runs",
    )
    op.drop_column("va_smartva_runs", "form_run_id")

    op.drop_index(
        "ix_va_smartva_form_runs_started_at",
        table_name="va_smartva_form_runs",
    )
    op.drop_index(
        "ix_va_smartva_form_runs_outcome",
        table_name="va_smartva_form_runs",
    )
    op.drop_index(
        "ix_va_smartva_form_runs_trigger_source",
        table_name="va_smartva_form_runs",
    )
    op.drop_index(
        "ix_va_smartva_form_runs_project_id",
        table_name="va_smartva_form_runs",
    )
    op.drop_index(
        "ix_va_smartva_form_runs_form_id",
        table_name="va_smartva_form_runs",
    )
    op.drop_index(
        "ix_va_smartva_form_runs_id",
        table_name="va_smartva_form_runs",
    )
    op.drop_table("va_smartva_form_runs")
