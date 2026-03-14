import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from typing import Optional
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses


class VaDataManagerReview(db.Model):
    __tablename__ = "va_data_manager_review"
    __table_args__ = (
        sa.Index(
            "uq_va_data_manager_review_active_sid",
            "va_sid",
            unique=True,
            postgresql_where=sa.text("va_dmreview_status = 'active'"),
        ),
    )

    va_dmreview_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, index=True, primary_key=True
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64),
        sa.ForeignKey("va_submissions.va_sid"),
        index=True,
        nullable=False,
    )
    va_dmreview_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id"),
        index=True,
        nullable=False,
    )
    va_dmreview_reason: so.Mapped[str] = so.mapped_column(
        sa.String(64), nullable=False
    )
    va_dmreview_other: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text, nullable=True
    )
    va_dmreview_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
    )
    va_dmreview_createdat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    va_dmreview_updatedat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self):
        return (
            "VA Data Manager Review -> "
            f"{self.va_sid} ({self.va_dmreview_status}): "
            f"{self.va_dmreview_reason} | by {self.va_dmreview_by}"
        )
