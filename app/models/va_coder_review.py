import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from typing import Optional
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses


class VaCoderReview(db.Model):
    __tablename__ = "va_coder_review"

    va_creview_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, index=True, primary_key=True
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64),
        sa.ForeignKey("va_submissions.va_sid"),
        index=True,
        nullable=False,
    )
    va_creview_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id"),
        index=True,
        nullable=False,
    )
    va_creview_reason: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    va_creview_other: so.Mapped[Optional[str]] = so.mapped_column(sa.Text, nullable=True)
    va_creview_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
    )
    va_creview_createdat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    va_creview_updatedat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self):
        return f"VA Coder Review Error -> {self.va_sid} ({self.va_creview_status}): {self.va_creview_reason} | by {self.va_creview_by}"
