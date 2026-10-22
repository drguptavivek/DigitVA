"""Device Ed25519 bundle-signing keys and the compromised-revocation flag.

Bead digitva-gb8w.5 (docs/policy/offline-bundle-and-transfer.md section 3.2).
``auth_devices`` gains ``signing_public_key`` (raw 32 bytes),
``signing_key_id`` (first 16 hex of its SHA-256, indexed),
``signing_key_set_at`` and ``revoked_compromised`` (not null, default false,
so existing rows read as an ordinary revoke). ``auth_device_signing_keys``
keeps every key a device has held, unique per (device, key id), so a bundle
signed before a re-key still verifies. Additive and empty at upgrade;
downgrade drops all of it (signing keys are lost; stations re-register).

Revision ID: b9e4f2a7c1d3
Revises: e5a2c7b9d3f1
Create Date: 2026-10-21
"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b9e4f2a7c1d3"
down_revision = "e5a2c7b9d3f1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "auth_devices",
        sa.Column("revoked_compromised", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("auth_devices", sa.Column("signing_public_key", sa.LargeBinary(), nullable=True))
    op.add_column("auth_devices", sa.Column("signing_key_id", sa.String(length=16), nullable=True))
    op.add_column("auth_devices", sa.Column("signing_key_set_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_auth_devices_signing_key_id", "auth_devices", ["signing_key_id"])
    op.create_table(
        "auth_device_signing_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("signing_public_key", sa.LargeBinary(), nullable=False),
        sa.Column("signing_key_id", sa.String(length=16), nullable=False),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["device_id"], ["auth_devices.device_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("device_id", "signing_key_id", name="uq_auth_device_signing_keys_device_key"),
    )


def downgrade():
    op.drop_table("auth_device_signing_keys")
    op.drop_index("ix_auth_devices_signing_key_id", table_name="auth_devices")
    op.drop_column("auth_devices", "signing_key_set_at")
    op.drop_column("auth_devices", "signing_key_id")
    op.drop_column("auth_devices", "signing_public_key")
    op.drop_column("auth_devices", "revoked_compromised")
