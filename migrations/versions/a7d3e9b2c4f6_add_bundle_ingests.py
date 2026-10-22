"""Offline bundle ingests and the records they applied.

Revision ID: a7d3e9b2c4f6
Revises: f3a9c6d2e1b7
Create Date: 2026-10-21

Additive: two empty tables. ``va_bundle_ingests`` holds one row per
ingested ``.dvb`` bundle (``bundle_id`` unique forever, the replay guard of
docs/policy/offline-bundle-and-transfer.md 3.3) with its per-record report
and signed receipt; ``map_bundle_records`` one row per applied record, keyed
by client id (cross-bundle idempotency and the station correction stale
check, offline-api-contract.md 4.2). Neither holds personal data. Downgrade
drops both and refuses while any ingest is recorded: a station deletes its
records on a receipt, so the rows are the only trace of what arrived.
Bead digitva-gb8w.2.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a7d3e9b2c4f6"
down_revision = "f3a9c6d2e1b7"
branch_labels = None
depends_on = None

_JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade():
    op.create_table(
        "va_bundle_ingests",
        sa.Column("bundle_id", sa.Uuid(), nullable=False),
        sa.Column("device_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(6), nullable=False),
        sa.Column("bundle_seq", sa.BigInteger(), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("station_config_id", sa.Uuid(), nullable=False),
        sa.Column("kem_key_id", sa.String(16), nullable=False),
        sa.Column("uploader_user_id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("counts", _JSONB, nullable=True),
        sa.Column("report", _JSONB, nullable=True),
        sa.Column("receipt_text", sa.Text(), nullable=True),
        sa.CheckConstraint("channel IN ('browser', 'device')", name=op.f("ck_va_bundle_ingests_channel")),
        sa.CheckConstraint("status IN ('processing', 'processed')", name=op.f("ck_va_bundle_ingests_status")),
        sa.ForeignKeyConstraint(["device_id"], ["auth_devices.device_id"],
                                name=op.f("fk_va_bundle_ingests_device_id_auth_devices")),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"],
                                name=op.f("fk_va_bundle_ingests_project_id_va_project_master")),
        sa.ForeignKeyConstraint(["station_config_id"], ["auth_station_configs.config_id"],
                                name=op.f("fk_va_bundle_ingests_station_config_id_auth_station_configs")),
        sa.ForeignKeyConstraint(["uploader_user_id"], ["va_users.user_id"],
                                name=op.f("fk_va_bundle_ingests_uploader_user_id_va_users")),
        sa.PrimaryKeyConstraint("bundle_id", name=op.f("pk_va_bundle_ingests")),
    )
    op.create_index("ix_va_bundle_ingests_device_received", "va_bundle_ingests", ["device_id", "received_at"])
    op.create_index("ix_va_bundle_ingests_device_seq", "va_bundle_ingests", ["device_id", "bundle_seq"])

    op.create_table(
        "map_bundle_records",
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("bundle_id", sa.Uuid(), nullable=False),
        sa.Column("record_type", sa.String(32), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("death_id", sa.Uuid(), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["bundle_id"], ["va_bundle_ingests.bundle_id"],
                                name=op.f("fk_map_bundle_records_bundle_id_va_bundle_ingests")),
        sa.ForeignKeyConstraint(["death_id"], ["va_death_register.death_id"],
                                name=op.f("fk_map_bundle_records_death_id_va_death_register")),
        sa.PrimaryKeyConstraint("client_id", name=op.f("pk_map_bundle_records")),
    )
    op.create_index(op.f("ix_map_bundle_records_bundle_id"), "map_bundle_records", ["bundle_id"])
    op.create_index("ix_map_bundle_records_death_applied", "map_bundle_records", ["death_id", "applied_at"])


def downgrade():
    ingested = op.get_bind().execute(sa.text("SELECT count(*) FROM va_bundle_ingests")).scalar()
    if ingested:
        raise RuntimeError(
            f"va_bundle_ingests holds {ingested} ingested bundle(s), the only record of what stations "
            "sent. Back up and clear them deliberately before downgrading."
        )
    op.drop_index("ix_map_bundle_records_death_applied", table_name="map_bundle_records")
    op.drop_index(op.f("ix_map_bundle_records_bundle_id"), table_name="map_bundle_records")
    op.drop_table("map_bundle_records")
    op.drop_index("ix_va_bundle_ingests_device_seq", table_name="va_bundle_ingests")
    op.drop_index("ix_va_bundle_ingests_device_received", table_name="va_bundle_ingests")
    op.drop_table("va_bundle_ingests")
