"""Respondent (informant) DPDP consent: project settings, notice versions,
append-only consent records.

Contract: docs/policy/offline-api-contract.md section 5; tables sketch:
docs/policy/offline-bundle-and-transfer.md 5.4. A consent record carries no
informant personal data: ids, the notice version and hash, the choices and
who recorded it. Records are never updated (a database trigger refuses it);
a correction is a new record naming ``supersedes_consent_id``.
"""
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB

from app import db

CONSENT_MODES = ("spoken", "tap", "signed")
CONSENT_EVENTS = ("granted", "refused", "withdrawn")
CONSENT_CHANNELS = ("web", "device", "bundle")
#: ``project``: a project's own notice (consent config, Project Setup);
#: ``standalone``: the text a Collect Plus phone used without a server showed,
#: stored from its push (offline-api-contract.md section 17). Never served.
NOTICE_SOURCES = ("project", "standalone")
EXPIRY_ACTIONS = ("erase", "lock")
#: Open enum (contract 13): new values are added, never changed.
REFUSAL_BEHAVIOURS = ("interview_without_informant_data",)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


class MasProjectConsentSettings(db.Model):
    """One project's consent settings (owner: configured at project level).
    No row means consent is not required: every project before this table."""

    __tablename__ = "mas_project_consent_settings"
    __table_args__ = (
        sa.CheckConstraint(f"expiry_action IN {_in(EXPIRY_ACTIONS)}", name="expiry_action"),
        sa.CheckConstraint(f"refusal_behaviour IN {_in(REFUSAL_BEHAVIOURS)}", name="refusal_behaviour"),
    )

    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_project_master.project_id"), primary_key=True
    )
    consent_required: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    #: The 5.2 ``contacts`` object; ``districts`` keyed by district org_unit_id.
    contacts: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False, default=dict)
    #: None: until the project ends.
    retention_period_days: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    expiry_action: so.Mapped[str] = so.mapped_column(sa.String(8), nullable=False, default="erase")
    refusal_behaviour: so.Mapped[str] = so.mapped_column(
        sa.String(40), nullable=False, default="interview_without_informant_data"
    )
    updated_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class MasConsentNoticeVersion(db.Model):
    """One notice text in one language. Never edited: a change is a new
    version. ``text_sha256`` is the lowercase hex SHA-256 of the UTF-8 bytes
    of ``text`` exactly as served. Retired versions stay for the records that
    name them. A ``standalone`` row is the text snapshot of a Collect Plus
    push (version 1, found again by its hash, never in the consent config)."""

    __tablename__ = "mas_consent_notice_versions"
    __table_args__ = (
        sa.Index("uq_mas_consent_notice_versions_project_notice", "project_id", "version", "language",
                 unique=True, postgresql_where=sa.text("source = 'project'")),
        sa.Index("uq_mas_consent_notice_versions_standalone_text", "project_id", "language", "text_sha256",
                 unique=True, postgresql_where=sa.text("source = 'standalone'")),
        sa.CheckConstraint("version >= 1", name="version"),
        sa.CheckConstraint(f"source IN {_in(NOTICE_SOURCES)}", name="source"),
    )

    notice_version_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_project_master.project_id"), nullable=False
    )
    version: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    language: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    text: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    text_sha256: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    #: ``[{code, label, required}]`` sorted by code.
    purposes: so.Mapped[list] = so.mapped_column(JSONB, nullable=False)
    covered_fields: so.Mapped[list] = so.mapped_column(JSONB, nullable=False)
    allowed_modes: so.Mapped[list] = so.mapped_column(JSONB, nullable=False)
    witness_allowed: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=True)
    #: The project's contacts when this version was created (what its text shows).
    contacts_snapshot: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False, default=dict)
    created_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    retired_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    #: Legal review: NULL is "Pending legal review"; an admin approves a
    #: version once. Usable for consent either way.
    approved_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    approved_by: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )
    source: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default="project", server_default="project"
    )
    #: A standalone row's bundled notice: the asset's version and content hash.
    bundle_version: so.Mapped[str | None] = so.mapped_column(sa.String(64), nullable=True)
    bundle_sha256: so.Mapped[str | None] = so.mapped_column(sa.String(64), nullable=True)


class VaConsentRecord(db.Model):
    """One consent event on a case, append-only. ``client_draft_id`` is the
    interview attempt it was taken for, NULL for a registration consent.
    ``content_sha256`` fingerprints the client's object (and case and
    recorder) so a resend of ``client_consent_id`` is told apart from reuse."""

    __tablename__ = "va_consent_records"
    __table_args__ = (
        sa.UniqueConstraint("client_consent_id", name="uq_va_consent_records_client_consent_id"),
        sa.Index("ix_va_consent_records_death", "death_id", "received_at"),
        sa.Index("ix_va_consent_records_client_draft", "client_draft_id"),
        sa.CheckConstraint(f"event IN {_in(CONSENT_EVENTS)}", name="event"),
        sa.CheckConstraint(f"mode IN {_in(CONSENT_MODES)}", name="mode"),
        sa.CheckConstraint(f"channel IN {_in(CONSENT_CHANNELS)}", name="channel"),
    )

    consent_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    client_consent_id: so.Mapped[uuid.UUID] = so.mapped_column(sa.Uuid(as_uuid=True), nullable=False)
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_project_master.project_id"), nullable=False
    )
    death_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_death_register.death_id"), nullable=False
    )
    client_draft_id: so.Mapped[uuid.UUID | None] = so.mapped_column(sa.Uuid(as_uuid=True), nullable=True)
    notice_version_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("mas_consent_notice_versions.notice_version_id"), nullable=False
    )
    notice_language: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    notice_sha256: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    event: so.Mapped[str] = so.mapped_column(sa.String(10), nullable=False)
    mode: so.Mapped[str] = so.mapped_column(sa.String(8), nullable=False)
    witness_present: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False)
    supersedes_consent_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_consent_records.consent_id"), nullable=True
    )
    recorded_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    #: The client's clock (RFC 3339 with offset as sent).
    recorded_at: so.Mapped[datetime] = so.mapped_column(sa.DateTime(timezone=True), nullable=False)
    received_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    channel: so.Mapped[str] = so.mapped_column(sa.String(8), nullable=False)
    content_sha256: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)

    purposes: so.Mapped[list["VaConsentRecordPurpose"]] = so.relationship(
        back_populates="record", lazy="selectin", order_by="VaConsentRecordPurpose.purpose_code"
    )


class VaConsentRecordPurpose(db.Model):
    """One purpose choice of a consent record (``required`` as the version said)."""

    __tablename__ = "va_consent_record_purposes"

    consent_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_consent_records.consent_id"), primary_key=True,
    )
    purpose_code: so.Mapped[str] = so.mapped_column(sa.String(64), primary_key=True)
    required: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False)
    granted: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False)

    record: so.Mapped[VaConsentRecord] = so.relationship(back_populates="purposes")


class MapConsentAudit(db.Model):
    """Append-only consent configuration events (settings saved, notice
    version created). ``details`` holds the changed settings, never a
    respondent's data."""

    __tablename__ = "map_consent_audit"
    __table_args__ = (
        sa.Index("ix_map_consent_audit_project_created", "project_id", "created_at"),
    )

    audit_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_project_master.project_id"), nullable=False
    )
    event: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    actor_user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    actor_role: so.Mapped[str] = so.mapped_column(sa.String(30), nullable=False)
    notice_version_id: so.Mapped[uuid.UUID | None] = so.mapped_column(sa.Uuid(as_uuid=True), nullable=True)
    details: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False, default=dict)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )


#: Append-only: UPDATE is refused on both record tables. DELETE stays
#: possible (the synthetic demo reset clears its own project's cases); the
#: app has no delete path.
APPEND_ONLY_FUNCTION = """
CREATE OR REPLACE FUNCTION va_consent_refuse_update() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'consent records are append-only';
END;
$$ LANGUAGE plpgsql
"""
APPEND_ONLY_TABLES = ("va_consent_records", "va_consent_record_purposes")


def append_only_trigger_sql(table: str) -> str:
    return (
        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE ON {table} "
        "FOR EACH ROW EXECUTE FUNCTION va_consent_refuse_update()"
    )


# create_all (the test schema) gets the same trigger as the migration.
sa.event.listen(VaConsentRecord.__table__, "after_create", sa.DDL(APPEND_ONLY_FUNCTION))
for _table in (VaConsentRecord.__table__, VaConsentRecordPurpose.__table__):
    sa.event.listen(_table, "after_create", sa.DDL(append_only_trigger_sql(_table.name)))
