"""Device offline cases: idempotency keys for deaths registered and contact
attempts logged offline, and pending registrations in the outstanding report.

Bead digitva-kmk.4 (.tasks/2026-09-30-android-collection-app.md, "API
contract"). ``va_death_register`` gains ``client_death_id`` and
``map_case_contact_attempts`` gains ``client_attempt_id``: the app's UUIDs, so a
resend returns the first result instead of registering or logging twice;
each unique where not null. ``auth_device_sessions`` gains
``outstanding_client_death_ids`` (JSONB, registrations still on the phone).
Additive; downgrade drops all of it.

Revision ID: f2c6a8d4b1e9
Revises: e4b8d2f6a1c7
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "f2c6a8d4b1e9"
down_revision = "e4b8d2f6a1c7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("va_death_register", sa.Column("client_death_id", sa.Uuid(), nullable=True))
    op.create_index(
        "uq_va_death_register_client_death_id",
        "va_death_register",
        ["client_death_id"],
        unique=True,
        postgresql_where=sa.text("client_death_id IS NOT NULL"),
    )
    op.add_column("map_case_contact_attempts", sa.Column("client_attempt_id", sa.Uuid(), nullable=True))
    op.create_index(
        "uq_map_case_contact_attempts_client_attempt_id",
        "map_case_contact_attempts",
        ["client_attempt_id"],
        unique=True,
        postgresql_where=sa.text("client_attempt_id IS NOT NULL"),
    )
    op.add_column(
        "auth_device_sessions",
        sa.Column("outstanding_client_death_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade():
    op.drop_column("auth_device_sessions", "outstanding_client_death_ids")
    op.drop_index("uq_map_case_contact_attempts_client_attempt_id", table_name="map_case_contact_attempts")
    op.drop_column("map_case_contact_attempts", "client_attempt_id")
    op.drop_index("uq_va_death_register_client_death_id", table_name="va_death_register")
    op.drop_column("va_death_register", "client_death_id")
