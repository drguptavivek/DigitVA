"""Add the sign-in QR token table and ``auth_devices.enrolled_via_sign_in_token``.

Additive (docs/policy/mobile-sign-in.md section 8, digitva-3g19). The token is
stored as a SHA-256 digest only. Downgrade drops the column and the table,
which loses the sign-in QR history (the audit rows in ``auth_security_events``
stay).

Revision ID: f3c8a1d5b7e2
Revises: e7b2c4d8f1a3
Create Date: 2026-10-23
"""
import sqlalchemy as sa
from alembic import op

revision = "f3c8a1d5b7e2"
down_revision = "e7b2c4d8f1a3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_sign_in_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("issued_by", sa.Uuid(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("redeemed_device_id", sa.Uuid(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expiry_noted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_session_version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["va_users.user_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issued_by"], ["va_users.user_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["redeemed_device_id"], ["auth_devices.device_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(
        "ix_auth_sign_in_tokens_pending_user", "auth_sign_in_tokens", ["user_id"], unique=True,
        postgresql_where=sa.text("redeemed_at IS NULL AND revoked_at IS NULL"),
    )
    op.add_column("auth_devices", sa.Column("enrolled_via_sign_in_token", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_auth_devices_enrolled_via_sign_in_token", "auth_devices", "auth_sign_in_tokens",
        ["enrolled_via_sign_in_token"], ["id"],
    )


def downgrade():
    op.drop_constraint("fk_auth_devices_enrolled_via_sign_in_token", "auth_devices", type_="foreignkey")
    op.drop_column("auth_devices", "enrolled_via_sign_in_token")
    op.drop_index("ix_auth_sign_in_tokens_pending_user", table_name="auth_sign_in_tokens")
    op.drop_table("auth_sign_in_tokens")
