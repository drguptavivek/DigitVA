"""Offline bundle (.dvb) ingests and the records they applied (bead
digitva-gb8w.2).

Policy: docs/policy/offline-bundle-and-transfer.md 3.3, 4, 5.6; contract
docs/policy/offline-api-contract.md 4.2. Neither table holds personal data:
ids, hashes, outcome and reason codes only. Rules live in
app/services/bundle_ingest_service.py.
"""
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB

from app import db

BUNDLE_CHANNELS = ("browser", "device")
BUNDLE_STATUSES = ("processing", "processed")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _in(values) -> str:
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


class VaBundleIngest(db.Model):
    """One ingested bundle: ``bundle_id`` is unique forever (replay, spec
    3.3). ``report`` is the per-record report of spec 5.6 (codes and client
    ids, never a value); ``receipt_text`` the signed two-line receipt, or
    NULL after a held coding result rewrote the report (the receipt route
    then signs the current report). A dry
    run (``/validate``) stores nothing, so every row is a real ingest."""

    __tablename__ = "va_bundle_ingests"
    __table_args__ = (
        sa.CheckConstraint(f"channel IN {_in(BUNDLE_CHANNELS)}", name="channel"),
        sa.CheckConstraint(f"status IN {_in(BUNDLE_STATUSES)}", name="status"),
        sa.Index("ix_va_bundle_ingests_device_received", "device_id", "received_at"),
        sa.Index("ix_va_bundle_ingests_device_seq", "device_id", "bundle_seq"),
    )

    bundle_id: so.Mapped[uuid.UUID] = so.mapped_column(sa.Uuid(as_uuid=True), primary_key=True)
    device_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("auth_devices.device_id"), nullable=False
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_project_master.project_id"), nullable=False
    )
    bundle_seq: so.Mapped[int] = so.mapped_column(sa.BigInteger, nullable=False)
    #: SHA-256 of manifest line 1; the manifest carries ``body_sha256``, so this
    #: names the exact bundle bytes for the replay check.
    manifest_sha256: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    station_config_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("auth_station_configs.config_id"), nullable=False
    )
    kem_key_id: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    uploader_user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    channel: so.Mapped[str] = so.mapped_column(sa.String(8), nullable=False)
    #: The manifest's claimed ``created_at`` (station clock).
    created_at: so.Mapped[datetime] = so.mapped_column(sa.DateTime(timezone=True), nullable=False)
    received_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    status: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    counts: so.Mapped[dict | None] = so.mapped_column(JSONB, nullable=True)
    report: so.Mapped[dict | None] = so.mapped_column(JSONB, nullable=True)
    receipt_text: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)


class MapBundleRecord(db.Model):
    """A bundle record the server applied (``accepted``, ``duplicate`` or
    ``superseded``), keyed by its client id: cross-bundle idempotency
    (same ``content_sha256``: duplicate, other: conflict) and the
    ``base_client_id`` stale check of a station correction (contract 4.2).
    ``content_sha256`` is over the decrypted record bytes, which carry the
    random client id, so it reveals nothing of the content."""

    __tablename__ = "map_bundle_records"
    __table_args__ = (
        sa.Index("ix_map_bundle_records_death_applied", "death_id", "applied_at"),
    )

    client_id: so.Mapped[uuid.UUID] = so.mapped_column(sa.Uuid(as_uuid=True), primary_key=True)
    bundle_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_bundle_ingests.bundle_id"), nullable=False, index=True
    )
    record_type: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    content_sha256: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    death_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_death_register.death_id"), nullable=True
    )
    applied_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )


PENDING_CODING_STATUSES = ("pending", "applied", "rejected")


class VaBundlePendingCoding(db.Model):
    """A bundle ``coding_result`` whose case was not ready (SmartVA or
    attachments pending) when it arrived, or an ICD-11 DORIS final the
    server reprocesses before saving: outcome ``pending`` (bundle spec 2.4
    Q5, 5.5). ``result`` holds the coding fields only (``kind``,
    ``initial`` / ``final`` / ``not_codeable``, ``coding_mode``, the draft
    and hash it codes), which are what the coding tables store anyway: no
    informant data, no ciphertext. ``bundle_ids`` lists every ingest whose
    report names it pending; the applier rewrites those reports (clearing
    their stored receipts) when it reaches ``applied`` or ``rejected``.
    ``code`` is the pending reason while pending, the refusal once
    rejected."""

    __tablename__ = "va_bundle_pending_coding"
    __table_args__ = (
        sa.CheckConstraint(f"status IN {_in(PENDING_CODING_STATUSES)}", name="status"),
        sa.Index("ix_va_bundle_pending_coding_status_created", "status", "created_at"),
    )

    client_id: so.Mapped[uuid.UUID] = so.mapped_column(sa.Uuid(as_uuid=True), primary_key=True)
    bundle_ids: so.Mapped[list[uuid.UUID]] = so.mapped_column(
        sa.ARRAY(sa.Uuid(as_uuid=True)), nullable=False
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_project_master.project_id"), nullable=False
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64), sa.ForeignKey("va_submissions.va_sid"), nullable=False, index=True
    )
    death_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_death_register.death_id"), nullable=True
    )
    actor_user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    #: SHA-256 of the decrypted record (as ``map_bundle_records.content_sha256``).
    content_sha256: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    result: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False)
    status: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False, default="pending")
    code: so.Mapped[str | None] = so.mapped_column(sa.String(64), nullable=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    resolved_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
