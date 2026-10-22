"""Respondent (informant) DPDP consent tables.

Revision ID: e8c4f2a7b913
Revises: b9e4f2a7c1d3
Create Date: 2026-10-21

Additive and empty at upgrade: no project has consent settings, so every
existing project keeps today's behaviour (consent not required). The record
tables are append-only: a trigger refuses UPDATE. Downgrade drops the tables
and refuses while any consent record exists, since a record is the only
proof of what a respondent agreed to. Contract:
docs/policy/offline-api-contract.md section 5 (digitva-gb8w.3).
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e8c4f2a7b913"
down_revision = "b9e4f2a7c1d3"
branch_labels = None
depends_on = None

_JSONB = postgresql.JSONB(astext_type=sa.Text())
_APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION va_consent_refuse_update() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'consent records are append-only';
END;
$$ LANGUAGE plpgsql
"""
_APPEND_ONLY_TABLES = ("va_consent_records", "va_consent_record_purposes")


def upgrade():
    op.create_table(
        "mas_project_consent_settings",
        sa.Column("project_id", sa.String(6), nullable=False),
        sa.Column("consent_required", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("contacts", _JSONB, nullable=False),
        sa.Column("retention_period_days", sa.Integer(), nullable=True),
        sa.Column("expiry_action", sa.String(8), nullable=False),
        sa.Column("refusal_behaviour", sa.String(40), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("expiry_action IN ('erase', 'lock')",
                           name=op.f("ck_mas_project_consent_settings_expiry_action")),
        sa.CheckConstraint("refusal_behaviour IN ('interview_without_informant_data')",
                           name=op.f("ck_mas_project_consent_settings_refusal_behaviour")),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"],
                                name=op.f("fk_mas_project_consent_settings_project_id_va_project_master")),
        sa.ForeignKeyConstraint(["updated_by"], ["va_users.user_id"],
                                name=op.f("fk_mas_project_consent_settings_updated_by_va_users")),
        sa.PrimaryKeyConstraint("project_id", name=op.f("pk_mas_project_consent_settings")),
    )
    op.create_table(
        "mas_consent_notice_versions",
        sa.Column("notice_version_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(6), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("purposes", _JSONB, nullable=False),
        sa.Column("covered_fields", _JSONB, nullable=False),
        sa.Column("allowed_modes", _JSONB, nullable=False),
        sa.Column("witness_allowed", sa.Boolean(), nullable=False),
        sa.Column("contacts_snapshot", _JSONB, nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version >= 1", name=op.f("ck_mas_consent_notice_versions_version")),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"],
                                name=op.f("fk_mas_consent_notice_versions_project_id_va_project_master")),
        sa.ForeignKeyConstraint(["created_by"], ["va_users.user_id"],
                                name=op.f("fk_mas_consent_notice_versions_created_by_va_users")),
        sa.PrimaryKeyConstraint("notice_version_id", name=op.f("pk_mas_consent_notice_versions")),
        sa.UniqueConstraint("project_id", "version", "language",
                            name="uq_mas_consent_notice_versions_project_version_language"),
    )
    op.create_table(
        "va_consent_records",
        sa.Column("consent_id", sa.Uuid(), nullable=False),
        sa.Column("client_consent_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(6), nullable=False),
        sa.Column("death_id", sa.Uuid(), nullable=False),
        sa.Column("client_draft_id", sa.Uuid(), nullable=True),
        sa.Column("notice_version_id", sa.Uuid(), nullable=False),
        sa.Column("notice_language", sa.String(16), nullable=False),
        sa.Column("notice_sha256", sa.String(64), nullable=False),
        sa.Column("event", sa.String(10), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False),
        sa.Column("witness_present", sa.Boolean(), nullable=False),
        sa.Column("supersedes_consent_id", sa.Uuid(), nullable=True),
        sa.Column("recorded_by", sa.Uuid(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("channel", sa.String(8), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.CheckConstraint("event IN ('granted', 'refused', 'withdrawn')", name=op.f("ck_va_consent_records_event")),
        sa.CheckConstraint("mode IN ('spoken', 'tap', 'signed')", name=op.f("ck_va_consent_records_mode")),
        sa.CheckConstraint("channel IN ('web', 'device', 'bundle')", name=op.f("ck_va_consent_records_channel")),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"],
                                name=op.f("fk_va_consent_records_project_id_va_project_master")),
        sa.ForeignKeyConstraint(["death_id"], ["va_death_register.death_id"],
                                name=op.f("fk_va_consent_records_death_id_va_death_register")),
        sa.ForeignKeyConstraint(["notice_version_id"], ["mas_consent_notice_versions.notice_version_id"],
                                name=op.f("fk_va_consent_records_notice_version_id_mas_consent_notice_versions")),
        sa.ForeignKeyConstraint(["supersedes_consent_id"], ["va_consent_records.consent_id"],
                                name=op.f("fk_va_consent_records_supersedes_consent_id_va_consent_records")),
        sa.ForeignKeyConstraint(["recorded_by"], ["va_users.user_id"],
                                name=op.f("fk_va_consent_records_recorded_by_va_users")),
        sa.PrimaryKeyConstraint("consent_id", name=op.f("pk_va_consent_records")),
        sa.UniqueConstraint("client_consent_id", name="uq_va_consent_records_client_consent_id"),
    )
    op.create_index("ix_va_consent_records_death", "va_consent_records", ["death_id", "received_at"])
    op.create_index("ix_va_consent_records_client_draft", "va_consent_records", ["client_draft_id"])
    op.create_table(
        "va_consent_record_purposes",
        sa.Column("consent_id", sa.Uuid(), nullable=False),
        sa.Column("purpose_code", sa.String(64), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("granted", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["consent_id"], ["va_consent_records.consent_id"],
                                name=op.f("fk_va_consent_record_purposes_consent_id_va_consent_records")),
        sa.PrimaryKeyConstraint("consent_id", "purpose_code", name=op.f("pk_va_consent_record_purposes")),
    )
    op.create_table(
        "map_consent_audit",
        sa.Column("audit_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.String(6), nullable=False),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("actor_role", sa.String(30), nullable=False),
        sa.Column("notice_version_id", sa.Uuid(), nullable=True),
        sa.Column("details", _JSONB, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["va_project_master.project_id"],
                                name=op.f("fk_map_consent_audit_project_id_va_project_master")),
        sa.ForeignKeyConstraint(["actor_user_id"], ["va_users.user_id"],
                                name=op.f("fk_map_consent_audit_actor_user_id_va_users")),
        sa.PrimaryKeyConstraint("audit_id", name=op.f("pk_map_consent_audit")),
    )
    op.create_index("ix_map_consent_audit_project_created", "map_consent_audit", ["project_id", "created_at"])
    op.execute(_APPEND_ONLY_FUNCTION)
    for table in _APPEND_ONLY_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION va_consent_refuse_update()"
        )


def downgrade():
    rows = op.get_bind().execute(sa.text("SELECT count(*) FROM va_consent_records")).scalar()
    if rows:
        raise RuntimeError(
            f"va_consent_records holds {rows} consent record(s), the only record of what respondents "
            "agreed to; export them before downgrading."
        )
    op.drop_table("map_consent_audit")
    op.drop_table("va_consent_record_purposes")
    op.drop_table("va_consent_records")
    op.drop_table("mas_consent_notice_versions")
    op.drop_table("mas_project_consent_settings")
    op.execute("DROP FUNCTION IF EXISTS va_consent_refuse_update()")
