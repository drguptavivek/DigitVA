"""Add passkey, TOTP, recovery-code and security-event tables.

digitva-sn1.1.2. Baseline: docs/policy/authentication-factors.md. Design
record .tasks/2026-09-28-passkey-login.md.

Purely additive: four new ``auth_*`` tables (credentials, TOTP enrolment,
recovery codes, security events) and one new column,
``va_users.auth_session_version``, used to invalidate sessions on a factor
or password reset. Nothing existing is read, rewritten or dropped, so the
upgrade is safe to run against a live database; the downgrade drops the new
tables and column, losing any enrolled factors and audit events.

Revision ID: c1d5e9a2f7b4
Revises: b8e2d4f6a1c3
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c1d5e9a2f7b4"
down_revision = "b8e2d4f6a1c3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "va_users",
        sa.Column(
            "auth_session_version",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.create_table(
        "auth_webauthn_credentials",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("credential_id", sa.LargeBinary(), nullable=False),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("backup_eligible", sa.Boolean(), nullable=True),
        sa.Column("backed_up", sa.Boolean(), nullable=True),
        sa.Column("transports", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_auth_webauthn_credentials"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["va_users.user_id"],
            name="fk_auth_webauthn_credentials_user_id_va_users",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "credential_id", name="auth_webauthn_credentials_credential_id_key"
        ),
    )
    op.create_index(
        "ix_auth_webauthn_credentials_user_id",
        "auth_webauthn_credentials",
        ["user_id"],
    )

    op.create_table(
        "auth_totp",
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("secret_encrypted", sa.Text(), nullable=False),
        sa.Column("last_used_step", sa.BigInteger(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name="pk_auth_totp"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["va_users.user_id"],
            name="fk_auth_totp_user_id_va_users",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "auth_recovery_codes",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_recovery_codes"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["va_users.user_id"],
            name="fk_auth_recovery_codes_user_id_va_users",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_auth_recovery_codes_user_id", "auth_recovery_codes", ["user_id"]
    )

    op.create_table(
        "auth_security_events",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("detail", postgresql.JSONB(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_auth_security_events"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["va_users.user_id"],
            name="fk_auth_security_events_user_id_va_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["va_users.user_id"],
            name="fk_auth_security_events_actor_user_id_va_users",
            ondelete="SET NULL",
        ),
    )
    op.create_index(
        "ix_auth_security_events_event_type", "auth_security_events", ["event_type"]
    )
    op.create_index(
        "ix_auth_security_events_occurred_at", "auth_security_events", ["occurred_at"]
    )


def downgrade():
    op.drop_index("ix_auth_security_events_occurred_at", table_name="auth_security_events")
    op.drop_index("ix_auth_security_events_event_type", table_name="auth_security_events")
    op.drop_table("auth_security_events")

    op.drop_index("ix_auth_recovery_codes_user_id", table_name="auth_recovery_codes")
    op.drop_table("auth_recovery_codes")

    op.drop_table("auth_totp")

    op.drop_index(
        "ix_auth_webauthn_credentials_user_id", table_name="auth_webauthn_credentials"
    )
    op.drop_table("auth_webauthn_credentials")

    op.drop_column("va_users", "auth_session_version")
