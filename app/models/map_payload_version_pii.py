"""Sealed personal data of one payload version (PII slice 1b).

Policy: docs/policy/pii-encryption-at-rest.md, "Payload design". One row per
``va_submission_payload_versions`` row: the sealed-set fields of that version
moved out of ``payload_data``, sealed under one data key per record
(``app/utils/pii_crypto.seal_record``). Written and read only through
``app/services/payload_pii_accessor.py``; written only with
``PAYLOAD_PII_SPLIT_ENABLED`` on or by ``flask pii split-payloads`` (part II-A).
"""
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB

from app import db

TABLE_NAME = "map_payload_version_pii"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MapPayloadVersionPii(db.Model):
    """``sealed`` is ``{field_id: "v1:aes256gcm:..."}`` (field presence stays
    queryable as ``sealed ? 'field'``); ``pii_digest`` is the keyed digest the
    version fingerprint is built from, so a comparison never decrypts;
    ``sealed_ids`` the sealed set it was computed under;
    ``review_flags`` are field ids the national-ID sweep flagged (ids only)."""

    __tablename__ = TABLE_NAME
    __table_args__ = (
        # Lets the re-wrap job find rows still on an old key without a scan.
        sa.Index("ix_map_payload_version_pii_key", "key_id"),
        # Exact ABHA search and duplicate hints; most rows carry no ABHA.
        sa.Index(
            "ix_map_payload_version_pii_abha_number_bidx",
            "abha_number_bidx",
            postgresql_where=sa.text("abha_number_bidx IS NOT NULL"),
        ),
        sa.Index(
            "ix_map_payload_version_pii_abha_address_bidx",
            "abha_address_bidx",
            postgresql_where=sa.text("abha_address_bidx IS NOT NULL"),
        ),
    )

    payload_version_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_submission_payload_versions.payload_version_id"),
        primary_key=True,
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64), sa.ForeignKey("va_submissions.va_sid"), nullable=False, index=True
    )
    sealed: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False, default=dict)
    dek_wrapped: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    key_id: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    pii_digest: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    # The sealed set (sorted field ids) pii_digest was computed under. Every
    # comparison against this row splits on it, not on today's registry: an
    # is_pii toggle after the split must not read as a change, and absent
    # versus null digests alike only for keys in this set.
    sealed_ids: so.Mapped[list] = so.mapped_column(JSONB, nullable=False)
    abha_number_bidx: so.Mapped[str | None] = so.mapped_column(sa.String(128), nullable=True)
    abha_address_bidx: so.Mapped[str | None] = so.mapped_column(sa.String(128), nullable=True)
    # pii_crypto.blind_key_id() of the key the digest and both indexes were
    # computed with, so a blind-key rotation can tell old rows from new.
    blind_key_id: so.Mapped[str] = so.mapped_column(sa.String(8), nullable=False)
    review_flags: so.Mapped[list] = so.mapped_column(
        JSONB, nullable=False, default=list, server_default=sa.text("'[]'::jsonb")
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
