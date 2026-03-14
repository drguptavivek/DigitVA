"""add va submission workflow table

Revision ID: d9e1f2a3b4c5
Revises: c3d4e5f6a7b8
Create Date: 2026-03-14 14:40:00.000000
"""

from datetime import datetime, timezone
import uuid

from alembic import op
import sqlalchemy as sa


revision = "d9e1f2a3b4c5"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "va_submission_workflow",
        sa.Column("workflow_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("va_sid", sa.String(length=64), nullable=False),
        sa.Column("workflow_state", sa.String(length=64), nullable=False),
        sa.Column("workflow_reason", sa.String(length=128), nullable=True),
        sa.Column("workflow_updated_by_role", sa.String(length=32), nullable=True),
        sa.Column("workflow_updated_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("workflow_created_at", sa.DateTime(), nullable=False),
        sa.Column("workflow_updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["va_sid"], ["va_submissions.va_sid"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workflow_updated_by"], ["va_users.user_id"]),
        sa.PrimaryKeyConstraint("workflow_id"),
        sa.UniqueConstraint("va_sid", name="uq_va_submission_workflow_sid"),
    )
    op.create_index(
        op.f("ix_va_submission_workflow_workflow_id"),
        "va_submission_workflow",
        ["workflow_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_workflow_va_sid"),
        "va_submission_workflow",
        ["va_sid"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_workflow_workflow_state"),
        "va_submission_workflow",
        ["workflow_state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_workflow_workflow_created_at"),
        "va_submission_workflow",
        ["workflow_created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_workflow_workflow_updated_at"),
        "va_submission_workflow",
        ["workflow_updated_at"],
        unique=False,
    )

    bind = op.get_bind()
    submission_rows = bind.execute(sa.text("""
        SELECT s.va_sid,
               CASE
                   WHEN EXISTS (
                       SELECT 1
                       FROM va_final_assessments f
                       WHERE f.va_sid = s.va_sid
                         AND f.va_finassess_status = 'active'
                   ) THEN 'coder_finalized'
                   WHEN EXISTS (
                       SELECT 1
                       FROM va_coder_review cr
                       WHERE cr.va_sid = s.va_sid
                         AND cr.va_creview_status = 'active'
                   ) THEN 'not_codeable_by_coder'
                   WHEN EXISTS (
                       SELECT 1
                       FROM va_initial_assessments i
                       WHERE i.va_sid = s.va_sid
                         AND i.va_iniassess_status = 'active'
                   ) THEN 'coder_step1_saved'
                   WHEN EXISTS (
                       SELECT 1
                       FROM va_allocations a
                       WHERE a.va_sid = s.va_sid
                         AND a.va_allocation_for = 'coding'
                         AND a.va_allocation_status = 'active'
                   ) THEN 'coding_in_progress'
                   ELSE 'ready_for_coding'
               END AS workflow_state
        FROM va_submissions s
    """)).mappings().all()
    now = datetime.now(timezone.utc)
    if submission_rows:
        op.bulk_insert(
            sa.table(
                "va_submission_workflow",
                sa.column("workflow_id", sa.Uuid(as_uuid=True)),
                sa.column("va_sid", sa.String(length=64)),
                sa.column("workflow_state", sa.String(length=64)),
                sa.column("workflow_reason", sa.String(length=128)),
                sa.column("workflow_updated_by_role", sa.String(length=32)),
                sa.column("workflow_updated_by", sa.Uuid(as_uuid=True)),
                sa.column("workflow_created_at", sa.DateTime()),
                sa.column("workflow_updated_at", sa.DateTime()),
            ),
            [
                {
                    "workflow_id": uuid.uuid4(),
                    "va_sid": row["va_sid"],
                    "workflow_state": row["workflow_state"],
                    "workflow_reason": "legacy_backfill",
                    "workflow_updated_by_role": "vasystem",
                    "workflow_updated_by": None,
                    "workflow_created_at": now,
                    "workflow_updated_at": now,
                }
                for row in submission_rows
            ],
        )


def downgrade():
    op.drop_index(
        op.f("ix_va_submission_workflow_workflow_updated_at"),
        table_name="va_submission_workflow",
    )
    op.drop_index(
        op.f("ix_va_submission_workflow_workflow_created_at"),
        table_name="va_submission_workflow",
    )
    op.drop_index(
        op.f("ix_va_submission_workflow_workflow_state"),
        table_name="va_submission_workflow",
    )
    op.drop_index(
        op.f("ix_va_submission_workflow_va_sid"),
        table_name="va_submission_workflow",
    )
    op.drop_index(
        op.f("ix_va_submission_workflow_workflow_id"),
        table_name="va_submission_workflow",
    )
    op.drop_table("va_submission_workflow")
