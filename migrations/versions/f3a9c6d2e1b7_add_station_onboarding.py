"""Offline station onboarding: custodian, roster, issued station configs,
and an integer ``va_users.user_number``.

Revision ID: f3a9c6d2e1b7
Revises: e8c4f2a7b913
Create Date: 2026-10-21

Additive. The new tables start empty, so no station is onboarded and no
config is served until an admin or project data manager sets a custodian
and a roster and issues one. ``user_number`` is an identity column that
PostgreSQL fills for every existing user at upgrade: the offline station
carries user ids as integers (contract 4.1, desktop crate ``RosterMember``),
and ``va_users.user_id`` is a UUID. Downgrade drops the tables and the
column; it refuses while any config has been issued, since a station may
hold that config and a bundle may name it. Beads digitva-gb8w.4, .8.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "f3a9c6d2e1b7"
down_revision = "e8c4f2a7b913"
branch_labels = None
depends_on = None

_JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade():
    op.add_column(
        "va_users",
        sa.Column("user_number", sa.BigInteger(), sa.Identity(always=False), nullable=False),
    )
    op.create_unique_constraint("va_users_user_number_key", "va_users", ["user_number"])

    op.create_table(
        "auth_station_custodians",
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("designation", sa.String(32), nullable=False),
        sa.Column("phone", sa.String(10), nullable=True),
        sa.Column("email", sa.String(254), nullable=True),
        sa.Column("onboarded_on", sa.Date(), nullable=False),
        sa.Column("verified_by", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("phone IS NOT NULL OR email IS NOT NULL",
                           name=op.f("ck_auth_station_custodians_contact")),
        sa.ForeignKeyConstraint(["device_id"], ["auth_devices.device_id"],
                                name=op.f("fk_auth_station_custodians_device_id_auth_devices")),
        sa.ForeignKeyConstraint(["verified_by"], ["va_users.user_id"],
                                name=op.f("fk_auth_station_custodians_verified_by_va_users")),
        sa.PrimaryKeyConstraint("device_id", name=op.f("pk_auth_station_custodians")),
    )

    op.create_table(
        "auth_station_roster",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("designation", sa.String(32), nullable=False),
        sa.Column("roles", _JSONB, nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["auth_devices.device_id"],
                                name=op.f("fk_auth_station_roster_device_id_auth_devices")),
        sa.ForeignKeyConstraint(["user_id"], ["va_users.user_id"],
                                name=op.f("fk_auth_station_roster_user_id_va_users")),
        sa.ForeignKeyConstraint(["updated_by"], ["va_users.user_id"],
                                name=op.f("fk_auth_station_roster_updated_by_va_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_station_roster")),
        sa.UniqueConstraint("device_id", "user_id", name="uq_auth_station_roster_device_user"),
    )

    op.create_table(
        "auth_station_configs",
        sa.Column("config_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("issued_by", sa.Uuid(), nullable=False),
        sa.Column("signed_text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["device_id"], ["auth_devices.device_id"],
                                name=op.f("fk_auth_station_configs_device_id_auth_devices")),
        sa.ForeignKeyConstraint(["issued_by"], ["va_users.user_id"],
                                name=op.f("fk_auth_station_configs_issued_by_va_users")),
        sa.PrimaryKeyConstraint("config_id", name=op.f("pk_auth_station_configs")),
    )
    op.create_index("ix_auth_station_configs_device_issued", "auth_station_configs",
                    ["device_id", "issued_at"])


def downgrade():
    issued = op.get_bind().execute(sa.text("SELECT count(*) FROM auth_station_configs")).scalar()
    if issued:
        raise RuntimeError(
            f"auth_station_configs holds {issued} issued station config(s); a station may still "
            "use them. Back up and clear them deliberately before downgrading."
        )
    op.drop_index("ix_auth_station_configs_device_issued", table_name="auth_station_configs")
    op.drop_table("auth_station_configs")
    op.drop_table("auth_station_roster")
    op.drop_table("auth_station_custodians")
    op.drop_constraint("va_users_user_number_key", "va_users", type_="unique")
    op.drop_column("va_users", "user_number")
