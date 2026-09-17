import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from datetime import datetime, timezone


class VaSubmissionAttachments(db.Model):
    """ETag cache and file state for ODK submission attachments.

    Stores one row per (submission, attachment filename) pair.
    Used to implement conditional GET (If-None-Match) so unchanged
    attachments are not re-downloaded on incremental syncs.

    The ``source_*`` / ``derivative_*`` / ``local_fallback_state`` columns carry
    the readiness state the attachment service needs once presence stops being a
    filesystem question (Phase 2 of ``docs/planning/s3-attachment-plan.md``).
    Their vocabularies live in ``app/services/attachment_service.py``; they are
    additive and do not change ``local_path``/``storage_name`` semantics.

    Primary key: (va_sid, filename)
    """

    __tablename__ = "va_submission_attachments"
    __table_args__ = (
        sa.Index(
            "ix_va_submission_attachments_sid_odk",
            "va_sid",
            postgresql_where=sa.text("exists_on_odk IS TRUE"),
        ),
        sa.Index(
            "ix_va_submission_attachments_storage_name",
            "storage_name",
            unique=True,
            postgresql_where=sa.text("storage_name IS NOT NULL"),
        ),
        # Request-path readiness reads filter on source_state; repair selection
        # scans only the audio rows, which are the only ones with a derivative.
        sa.Index(
            "ix_va_submission_attachments_source_state",
            "source_state",
        ),
        sa.Index(
            "ix_va_submission_attachments_derivative_state",
            "derivative_state",
            postgresql_where=sa.text("derivative_state IS NOT NULL"),
        ),
    )

    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64), sa.ForeignKey("va_submissions.va_sid"), primary_key=True
    )
    filename: so.Mapped[str] = so.mapped_column(sa.String(255), primary_key=True)
    # Actual path on disk — may differ from filename (.amr stored as .mp3)
    local_path: so.Mapped[str | None] = so.mapped_column(sa.String(512), nullable=True)
    mime_type: so.Mapped[str | None] = so.mapped_column(sa.String(64), nullable=True)
    etag: so.Mapped[str | None] = so.mapped_column(sa.String(128), nullable=True)
    exists_on_odk: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=True
    )
    last_downloaded_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    storage_name: so.Mapped[str | None] = so.mapped_column(
        sa.String(64), nullable=True,
    )

    # --- Source state (the original, owned by ODK Central) -----------------
    source_state: so.Mapped[str] = so.mapped_column(
        sa.String(16),
        nullable=False,
        default="unknown",
        server_default=sa.text("'unknown'"),
    )
    # Last observed Central content response for this attachment.
    source_verified_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    # Last error *category* only; upstream free text is never stored.
    source_error_code: so.Mapped[str | None] = so.mapped_column(
        sa.String(32), nullable=True
    )
    # Validated MIME of the ORIGINAL. ``mime_type`` stays whatever sync stored
    # (the derivative's type for AMR rows) and is not repurposed.
    source_mime_type: so.Mapped[str | None] = so.mapped_column(
        sa.String(64), nullable=True
    )

    # --- Derivative state (audio only; NULL for every other row) -----------
    derivative_state: so.Mapped[str | None] = so.mapped_column(
        sa.String(16), nullable=True
    )
    derivative_mime_type: so.Mapped[str | None] = so.mapped_column(
        sa.String(64), nullable=True
    )
    # Opaque source ETag the current MP3 was built from (plan Finding 6).
    derivative_source_validator: so.Mapped[str | None] = so.mapped_column(
        sa.String(128), nullable=True
    )
    derivative_verified_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    derivative_error_code: so.Mapped[str | None] = so.mapped_column(
        sa.String(32), nullable=True
    )

    # --- Local copy under APP_DATA ----------------------------------------
    local_fallback_state: so.Mapped[str] = so.mapped_column(
        sa.String(16),
        nullable=False,
        default="present",
        server_default=sa.text("'present'"),
    )

    def __repr__(self) -> str:
        return f"<VaSubmissionAttachments {self.va_sid}/{self.filename}>"
