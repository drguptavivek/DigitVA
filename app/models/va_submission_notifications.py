import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class VaSubmissionNotification(db.Model):
    __tablename__ = "va_submission_notifications"

    notification_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True, index=True
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64),
        sa.ForeignKey("va_submissions.va_sid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    upstream_change_id: so.Mapped[Optional[uuid.UUID]] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_submission_upstream_changes.upstream_change_id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    audience_role: so.Mapped[str] = so.mapped_column(
        sa.String(32), nullable=False, index=True
    )
    notification_type: so.Mapped[str] = so.mapped_column(
        sa.String(64), nullable=False, index=True
    )
    notification_status: so.Mapped[str] = so.mapped_column(
        sa.String(32), nullable=False, default="pending", index=True
    )
    title: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    message: so.Mapped[Optional[str]] = so.mapped_column(sa.Text, nullable=True)
    resolved_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            "VA Submission Notification -> "
            f"{self.va_sid} ({self.audience_role}/{self.notification_status})"
        )
