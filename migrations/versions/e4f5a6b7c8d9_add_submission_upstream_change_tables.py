"""add submission upstream change tables

Revision ID: e4f5a6b7c8d9
Revises: d2f6a8b9c1e3
Create Date: 2026-03-20 18:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "e4f5a6b7c8d9"
down_revision = "d2f6a8b9c1e3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "va_submission_upstream_changes",
        sa.Column("upstream_change_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "va_sid",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("workflow_state_before", sa.String(length=64), nullable=False),
        sa.Column("previous_final_assessment_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("previous_va_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("incoming_va_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("detected_odk_updatedat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_status", sa.String(length=32), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("resolved_by_role", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["previous_final_assessment_id"],
            ["va_final_assessments.va_finassess_id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"],
            ["va_users.user_id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["va_sid"],
            ["va_submissions.va_sid"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("upstream_change_id"),
    )
    op.create_index(
        op.f("ix_va_submission_upstream_changes_created_at"),
        "va_submission_upstream_changes",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_upstream_changes_detected_odk_updatedat"),
        "va_submission_upstream_changes",
        ["detected_odk_updatedat"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_upstream_changes_resolution_status"),
        "va_submission_upstream_changes",
        ["resolution_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_upstream_changes_upstream_change_id"),
        "va_submission_upstream_changes",
        ["upstream_change_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_upstream_changes_va_sid"),
        "va_submission_upstream_changes",
        ["va_sid"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_upstream_changes_workflow_state_before"),
        "va_submission_upstream_changes",
        ["workflow_state_before"],
        unique=False,
    )
    op.create_index(
        "ix_va_submission_upstream_changes_sid_status_created",
        "va_submission_upstream_changes",
        ["va_sid", "resolution_status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ux_va_submission_upstream_changes_one_pending_per_sid",
        "va_submission_upstream_changes",
        ["va_sid"],
        unique=True,
        postgresql_where=sa.text("resolution_status = 'pending'"),
    )

    op.create_table(
        "va_submission_notifications",
        sa.Column("notification_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("va_sid", sa.String(length=64), nullable=False),
        sa.Column("upstream_change_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("audience_role", sa.String(length=32), nullable=False),
        sa.Column("notification_type", sa.String(length=64), nullable=False),
        sa.Column("notification_status", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["upstream_change_id"],
            ["va_submission_upstream_changes.upstream_change_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["va_sid"],
            ["va_submissions.va_sid"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("notification_id"),
    )
    op.create_index(
        op.f("ix_va_submission_notifications_audience_role"),
        "va_submission_notifications",
        ["audience_role"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_notifications_created_at"),
        "va_submission_notifications",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_notifications_notification_id"),
        "va_submission_notifications",
        ["notification_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_notifications_notification_status"),
        "va_submission_notifications",
        ["notification_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_notifications_notification_type"),
        "va_submission_notifications",
        ["notification_type"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_notifications_upstream_change_id"),
        "va_submission_notifications",
        ["upstream_change_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_va_submission_notifications_va_sid"),
        "va_submission_notifications",
        ["va_sid"],
        unique=False,
    )
    op.create_index(
        "ix_va_submission_notifications_pending_lookup",
        "va_submission_notifications",
        ["upstream_change_id", "notification_status", "audience_role", "notification_type"],
        unique=False,
    )
    op.create_index(
        "ux_va_submission_notifications_one_pending_per_audience",
        "va_submission_notifications",
        ["upstream_change_id", "audience_role", "notification_type"],
        unique=True,
        postgresql_where=sa.text("notification_status = 'pending'"),
    )


def downgrade():
    op.drop_index(
        "ux_va_submission_notifications_one_pending_per_audience",
        table_name="va_submission_notifications",
    )
    op.drop_index(
        "ix_va_submission_notifications_pending_lookup",
        table_name="va_submission_notifications",
    )
    op.drop_index(
        op.f("ix_va_submission_notifications_va_sid"),
        table_name="va_submission_notifications",
    )
    op.drop_index(
        op.f("ix_va_submission_notifications_upstream_change_id"),
        table_name="va_submission_notifications",
    )
    op.drop_index(
        op.f("ix_va_submission_notifications_notification_type"),
        table_name="va_submission_notifications",
    )
    op.drop_index(
        op.f("ix_va_submission_notifications_notification_status"),
        table_name="va_submission_notifications",
    )
    op.drop_index(
        op.f("ix_va_submission_notifications_notification_id"),
        table_name="va_submission_notifications",
    )
    op.drop_index(
        op.f("ix_va_submission_notifications_created_at"),
        table_name="va_submission_notifications",
    )
    op.drop_index(
        op.f("ix_va_submission_notifications_audience_role"),
        table_name="va_submission_notifications",
    )
    op.drop_table("va_submission_notifications")

    op.drop_index(
        "ux_va_submission_upstream_changes_one_pending_per_sid",
        table_name="va_submission_upstream_changes",
    )
    op.drop_index(
        "ix_va_submission_upstream_changes_sid_status_created",
        table_name="va_submission_upstream_changes",
    )
    op.drop_index(
        op.f("ix_va_submission_upstream_changes_workflow_state_before"),
        table_name="va_submission_upstream_changes",
    )
    op.drop_index(
        op.f("ix_va_submission_upstream_changes_va_sid"),
        table_name="va_submission_upstream_changes",
    )
    op.drop_index(
        op.f("ix_va_submission_upstream_changes_upstream_change_id"),
        table_name="va_submission_upstream_changes",
    )
    op.drop_index(
        op.f("ix_va_submission_upstream_changes_resolution_status"),
        table_name="va_submission_upstream_changes",
    )
    op.drop_index(
        op.f("ix_va_submission_upstream_changes_detected_odk_updatedat"),
        table_name="va_submission_upstream_changes",
    )
    op.drop_index(
        op.f("ix_va_submission_upstream_changes_created_at"),
        table_name="va_submission_upstream_changes",
    )
    op.drop_table("va_submission_upstream_changes")
