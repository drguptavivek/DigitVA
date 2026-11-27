"""Add ``auth_icd11_api_clients``: tokens for the ICD-11 client API.

Additive (docs/policy/icd11-client-api.md, digitva-ddpf). A token is stored as
its SHA-256 digest only. No backfill. Downgrade drops only this table, which
loses the issued tokens (every one stops working) and their last-used times;
the issue and revoke audit rows in ``auth_security_events`` stay.

Revision ID: a4d7e2c9b1f6
Revises: a40477e55b72
Create Date: 2026-11-27
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a4d7e2c9b1f6"
down_revision = "a40477e55b72"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_icd11_api_clients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("key_id", sa.String(length=16), nullable=False),
        sa.Column("token_sha256", sa.String(length=64), nullable=False),
        sa.Column("scopes", postgresql.ARRAY(sa.String(length=32)), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Uuid(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["va_users.user_id"]),
        sa.ForeignKeyConstraint(["revoked_by"], ["va_users.user_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_id"),
        sa.UniqueConstraint("token_sha256"),
    )
    op.create_index(
        "ix_auth_icd11_api_clients_created_at", "auth_icd11_api_clients", ["created_at"]
    )


def downgrade():
    op.drop_index("ix_auth_icd11_api_clients_created_at", table_name="auth_icd11_api_clients")
    op.drop_table("auth_icd11_api_clients")
