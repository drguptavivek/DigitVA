"""Death registration identifiers: per-project types, encrypted values, audit.

Policy: docs/policy/death-registration-identifiers.md (bead digitva-kzyp).
Values are never stored in plaintext: ``value_ciphertext`` and ``dek_wrapped``
are the envelope of ``app/utils/pii_crypto.py`` and ``value_blind_index`` is
the keyed HMAC used for duplicate checks and exact search.
"""
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB

from app import db

CHAR_TYPES = ("digits", "letters", "letters_digits", "letters_digits_hyphen_slash")
UNIQUENESS_SCOPES = ("none", "project")
IDENTIFIER_AUDIT_EVENTS = ("type_created", "type_updated", "export_with_identifiers")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MasDeathIdentifierType(db.Model):
    """One kind of official number a project collects (CRS, MCCD, ...)."""

    __tablename__ = "mas_death_identifier_type"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "code", name="uq_mas_death_identifier_type_project_code"),
        # The naming convention prefixes "ck_<table>_"; pass the discriminator.
        sa.CheckConstraint("uniqueness_scope IN ('none', 'project')", name="uniqueness_scope"),
        sa.CheckConstraint(
            "min_length >= 1 AND max_length <= 64 AND min_length <= max_length",
            name="length_range",
        ),
        sa.CheckConstraint(
            "char_type IS NULL OR char_type IN "
            "('digits', 'letters', 'letters_digits', 'letters_digits_hyphen_slash')",
            name="char_type",
        ),
    )

    identifier_type_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_project_master.project_id"), nullable=False, index=True
    )
    code: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    label: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    min_length: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False, default=1, server_default="1"
    )
    max_length: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False, default=64, server_default="64"
    )
    char_type: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    pattern: so.Mapped[str | None] = so.mapped_column(sa.String(200), nullable=True)
    example: so.Mapped[str | None] = so.mapped_column(sa.String(64), nullable=True)
    required_at_report: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    uniqueness_scope: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default="project", server_default="project"
    )
    sort_order: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False, default=0, server_default="0"
    )
    is_active: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class MapDeathIdentifier(db.Model):
    """One encrypted identifier value of one death (one per type per death)."""

    __tablename__ = "map_death_identifier"
    __table_args__ = (
        sa.UniqueConstraint(
            "death_id", "identifier_type_id", name="uq_map_death_identifier_death_type"
        ),
        # Duplicate check and exact search; deliberately not unique (a
        # duplicate number is a warning, decision 10).
        sa.Index("ix_map_death_identifier_type_bidx", "identifier_type_id", "value_blind_index"),
        # Lets the re-wrap job find rows still on an old key without a scan.
        sa.Index("ix_map_death_identifier_key", "key_id"),
    )

    death_identifier_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    death_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_death_register.death_id"), nullable=False
    )
    identifier_type_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_death_identifier_type.identifier_type_id"),
        nullable=False,
    )
    value_ciphertext: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    dek_wrapped: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    value_blind_index: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    key_id: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    entered_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    entered_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_by: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )
    updated_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class MapIdentifierAudit(db.Model):
    """Append-only configuration and export events. Never holds a value."""

    __tablename__ = "map_identifier_audit"
    __table_args__ = (
        sa.Index("ix_map_identifier_audit_project_created", "project_id", "created_at"),
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
    identifier_type_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), nullable=True
    )
    details: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False, default=dict)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
