"""add va_submission_workflow_events table

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-03-22 12:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "va_submission_workflow_events",
        sa.Column("workflow_event_id", sa.Uuid(), nullable=False),
        sa.Column("va_sid", sa.String(length=64), nullable=False),
        sa.Column("transition_id", sa.String(length=64), nullable=False),
        sa.Column("previous_state", sa.String(length=64), nullable=True),
        sa.Column("current_state", sa.String(length=64), nullable=False),
        sa.Column("actor_kind", sa.String(length=32), nullable=True),
        sa.Column("actor_role", sa.String(length=32), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("transition_reason", sa.String(length=128), nullable=True),
        sa.Column("event_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["va_users.user_id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["va_sid"],
            ["va_submissions.va_sid"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workflow_event_id"),
    )
    op.create_index(
        "ix_va_submission_workflow_events_workflow_event_id",
        "va_submission_workflow_events",
        ["workflow_event_id"],
        unique=False,
    )
    op.create_index(
        "ix_va_submission_workflow_events_va_sid",
        "va_submission_workflow_events",
        ["va_sid"],
        unique=False,
    )
    op.create_index(
        "ix_va_submission_workflow_events_transition_id",
        "va_submission_workflow_events",
        ["transition_id"],
        unique=False,
    )
    op.create_index(
        "ix_va_submission_workflow_events_previous_state",
        "va_submission_workflow_events",
        ["previous_state"],
        unique=False,
    )
    op.create_index(
        "ix_va_submission_workflow_events_current_state",
        "va_submission_workflow_events",
        ["current_state"],
        unique=False,
    )
    op.create_index(
        "ix_va_submission_workflow_events_event_created_at",
        "va_submission_workflow_events",
        ["event_created_at"],
        unique=False,
    )
    op.create_index(
        "ix_va_submission_workflow_events_sid_created",
        "va_submission_workflow_events",
        ["va_sid", "event_created_at"],
        unique=False,
    )
    op.create_index(
        "ix_va_submission_workflow_events_transition_created",
        "va_submission_workflow_events",
        ["transition_id", "event_created_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(
        "ix_va_submission_workflow_events_transition_created",
        table_name="va_submission_workflow_events",
    )
    op.drop_index(
        "ix_va_submission_workflow_events_sid_created",
        table_name="va_submission_workflow_events",
    )
    op.drop_index(
        "ix_va_submission_workflow_events_event_created_at",
        table_name="va_submission_workflow_events",
    )
    op.drop_index(
        "ix_va_submission_workflow_events_current_state",
        table_name="va_submission_workflow_events",
    )
    op.drop_index(
        "ix_va_submission_workflow_events_previous_state",
        table_name="va_submission_workflow_events",
    )
    op.drop_index(
        "ix_va_submission_workflow_events_transition_id",
        table_name="va_submission_workflow_events",
    )
    op.drop_index(
        "ix_va_submission_workflow_events_va_sid",
        table_name="va_submission_workflow_events",
    )
    op.drop_index(
        "ix_va_submission_workflow_events_workflow_event_id",
        table_name="va_submission_workflow_events",
    )
    op.drop_table("va_submission_workflow_events")
