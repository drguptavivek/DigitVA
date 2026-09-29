"""Harden device sessions: retired refresh hashes, rotation time, outstanding
draft ids, and an index for the device second-factor lockout count.

Bead digitva-kmk.6 (.tasks/2026-09-30-android-collection-app.md, "API
contract"). ``auth_device_sessions`` gains ``retired_refresh_hashes`` (JSONB
list of the last few rotated-away refresh hashes, GIN ``jsonb_path_ops`` for
the ``@>`` reuse lookup), ``refreshed_at`` (last rotation, for the lost-response
grace window) and ``outstanding_client_draft_ids`` (JSONB, the app's unsent
draft uuids). ``auth_security_events`` gains a composite
``(user_id, event_type, occurred_at)`` index for the per-account failed
second-factor count. Additive; downgrade drops all of it.

Revision ID: e4b8d2f6a1c7
Revises: d7a3c9e1f5b2
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e4b8d2f6a1c7"
down_revision = "d7a3c9e1f5b2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "auth_device_sessions",
        sa.Column("retired_refresh_hashes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column("auth_device_sessions", sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "auth_device_sessions",
        sa.Column("outstanding_client_draft_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        "ix_auth_device_sessions_retired_refresh_hashes",
        "auth_device_sessions",
        ["retired_refresh_hashes"],
        postgresql_using="gin",
        postgresql_ops={"retired_refresh_hashes": "jsonb_path_ops"},
    )
    op.create_index(
        "ix_auth_security_events_user_type_time",
        "auth_security_events",
        ["user_id", "event_type", "occurred_at"],
    )


def downgrade():
    op.drop_index("ix_auth_security_events_user_type_time", table_name="auth_security_events")
    op.drop_index("ix_auth_device_sessions_retired_refresh_hashes", table_name="auth_device_sessions")
    op.drop_column("auth_device_sessions", "outstanding_client_draft_ids")
    op.drop_column("auth_device_sessions", "refreshed_at")
    op.drop_column("auth_device_sessions", "retired_refresh_hashes")
