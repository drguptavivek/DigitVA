import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from datetime import datetime, timezone


class VaSubmissionAttachments(db.Model):
    """ETag cache and file state for ODK submission attachments.

    Stores one row per (submission, attachment filename) pair.
    Used to implement conditional GET (If-None-Match) so unchanged
    attachments are not re-downloaded on incremental syncs.

    Primary key: (va_sid, filename)
    """

    __tablename__ = "va_submission_attachments"

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

    def __repr__(self) -> str:
        return f"<VaSubmissionAttachments {self.va_sid}/{self.filename}>"
