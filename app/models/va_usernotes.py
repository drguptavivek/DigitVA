import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from typing import Optional
from datetime import datetime, timezone
from app.models.va_selectives import VaUsernotesFor, VaStatuses


class VaUsernotes(db.Model):
    __tablename__ = "va_usernotes"
    note_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, index=True, primary_key=True
    )
    note_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), index=True
    )
    note_recordedwhen: so.Mapped[VaUsernotesFor] = so.mapped_column(
        sa.Enum(VaUsernotesFor, name="usernote_enum"),
        default=VaUsernotesFor.viewing,
        nullable=False,
    )
    note_vasubmission: so.Mapped[str] = so.mapped_column(
        sa.String(64), sa.ForeignKey("va_submissions.va_sid"), index=True
    )
    note_content: so.Mapped[Optional[str]] = so.mapped_column(sa.Text, nullable=True)
    note_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True
    )
    note_added_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    note_updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"VA Usernote -> {self.note_id} ({self.note_status}): {self.note_content}"
