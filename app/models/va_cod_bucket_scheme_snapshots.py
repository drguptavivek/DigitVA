import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB

from app import db


class VaCodBucketSchemeSnapshot(db.Model):
    """A whole-scheme JSON export taken right before a destructive reset.

    "Reset from source" (``reset_cod_bucket_scheme_age_band_to_source``)
    rebuilds a COD bucket scheme's nodes and mappings from its workbook,
    which destroys anything not in that workbook: admin edits, ICD-11 rows,
    manual overrides. This table is the safety net -- every reset snapshots
    the whole scheme via ``export_cod_bucket_scheme_json`` first, in the same
    transaction, and the reset is refused if the snapshot fails. Restore is
    the existing ``import_cod_bucket_scheme_json`` (there is no restore
    endpoint here; an admin downloads the JSON and re-imports it).

    ``scheme_code`` duplicates ``scheme_id``'s FK target so a snapshot stays
    findable (and downloadable) even after the scheme it was taken from is
    deleted -- the FK alone would go to NULL. ``payload`` is always the
    *entire* scheme regardless of ``reason``/``age_scope`` (an age-band-only
    snapshot could not restore a whole-scheme reset), so `age_scope` is
    metadata about what triggered the snapshot, not what it covers.

    No retention/prune job yet -- add one if this table grows large enough
    to matter (see docs/policy/icd11-cod-bucket-schemes.md).
    """

    __tablename__ = "va_cod_bucket_scheme_snapshots"
    __table_args__ = (
        sa.CheckConstraint(
            "reason IN ('reset_scheme', 'reset_age_band', 'cli_import')",
            name="reason",
        ),
        sa.Index(
            "ix_va_cod_bucket_scheme_snapshots_scheme_code_created_at",
            "scheme_code",
            sa.text("created_at DESC"),
        ),
    )

    REASON_RESET_SCHEME = "reset_scheme"
    REASON_RESET_AGE_BAND = "reset_age_band"
    REASON_CLI_IMPORT = "cli_import"
    REASONS = (REASON_RESET_SCHEME, REASON_RESET_AGE_BAND, REASON_CLI_IMPORT)

    snapshot_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        default=uuid.uuid4,
        server_default=sa.text("gen_random_uuid()"),
        primary_key=True,
    )
    scheme_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_cod_bucket_schemes.scheme_id", ondelete="SET NULL"),
        nullable=True,
    )
    scheme_code: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    reason: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    age_scope: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    payload: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False)
    created_by_user_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey(
            "va_users.user_id",
            name="fk_va_cod_bucket_scheme_snapshots_created_by_user_id",
        ),
        nullable=True,
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    def __repr__(self) -> str:
        return (
            f"<VaCodBucketSchemeSnapshot {self.snapshot_id} "
            f"scheme_code={self.scheme_code} reason={self.reason}>"
        )
