"""Enrolled collection devices, their interviewer sessions, and device upload ids.

Path B server side (bead digitva-kmk.1, .tasks/2026-09-30-android-collection-app.md):
``auth_device_enrolment_codes`` (hashed one-time codes an admin issues per
project), ``auth_devices`` (enrolled handsets, hashed device secret),
``auth_device_sessions`` (hashed access/refresh tokens per device and
interviewer, plus the device's outstanding-work report), and a nullable
``client_draft_id`` on ``va_web_intake_drafts``, unique where present, the
idempotency key of a device upload. Additive; downgrade drops all of it.

Revision ID: d7a3c9e1f5b2
Revises: c5e2b7a9d4f6
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "d7a3c9e1f5b2"
down_revision = "c5e2b7a9d4f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_device_enrolment_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(length=6), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"]),
        sa.ForeignKeyConstraint(["created_by"], ["va_users.user_id"]),
        sa.UniqueConstraint("code_hash"),
    )
    op.create_index(
        "ix_auth_device_enrolment_codes_project_id", "auth_device_enrolment_codes", ["project_id"]
    )

    op.create_table(
        "auth_devices",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(length=6), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("app_version", sa.String(length=32), nullable=True),
        sa.Column("secret_hash", sa.String(length=64), nullable=False),
        sa.Column("enrolled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enrolled_via", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("device_id"),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"]),
        sa.ForeignKeyConstraint(["enrolled_via"], ["auth_device_enrolment_codes.id"]),
        sa.ForeignKeyConstraint(["revoked_by"], ["va_users.user_id"]),
    )
    op.create_index("ix_auth_devices_project_id", "auth_devices", ["project_id"])

    op.create_table(
        "auth_device_sessions",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("access_hash", sa.String(length=64), nullable=False),
        sa.Column("access_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("refresh_hash", sa.String(length=64), nullable=False),
        sa.Column("refresh_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_session_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("previous_refresh_hash", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_reason", sa.String(length=32), nullable=True),
        sa.Column("outstanding_count", sa.Integer(), nullable=True),
        sa.Column("outstanding_unique_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("outstanding_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("session_id"),
        sa.ForeignKeyConstraint(["device_id"], ["auth_devices.device_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["va_users.user_id"]),
        sa.UniqueConstraint("access_hash"),
        sa.UniqueConstraint("refresh_hash"),
    )
    op.create_index("ix_auth_device_sessions_device_id", "auth_device_sessions", ["device_id"])
    op.create_index("ix_auth_device_sessions_user_id", "auth_device_sessions", ["user_id"])
    op.create_index(
        "ix_auth_device_sessions_previous_refresh_hash", "auth_device_sessions", ["previous_refresh_hash"]
    )

    op.add_column("va_web_intake_drafts", sa.Column("client_draft_id", sa.Uuid(), nullable=True))
    op.create_index(
        "uq_va_web_intake_drafts_client_draft_id",
        "va_web_intake_drafts",
        ["client_draft_id"],
        unique=True,
        postgresql_where=sa.text("client_draft_id IS NOT NULL"),
    )


def downgrade():
    op.drop_index("uq_va_web_intake_drafts_client_draft_id", table_name="va_web_intake_drafts")
    op.drop_column("va_web_intake_drafts", "client_draft_id")
    op.drop_table("auth_device_sessions")
    op.drop_table("auth_devices")
    op.drop_table("auth_device_enrolment_codes")
