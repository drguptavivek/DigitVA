import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from typing import Optional
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses


class VaReviewerReview(db.Model):
    __tablename__ = "va_reviewer_review"
    __table_args__ = (
        sa.Index(
            "ix_va_reviewer_review_active_sid_by_unique",
            "va_sid",
            "va_rreview_by",
            unique=True,
            postgresql_where=sa.text("va_rreview_status = 'active'"),
        ),
    )

    va_rreview_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, index=True, primary_key=True
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64), sa.ForeignKey("va_submissions.va_sid"), index=True, nullable=False
    )
    va_rreview_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id"),
        index=True,
        nullable=False,
    )
    payload_version_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey(
            "va_submission_payload_versions.payload_version_id",
            ondelete="SET NULL",
        ),
        index=True,
        nullable=True,
    )
    va_rreview_narrpos: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    va_rreview_narrneg: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    va_rreview_narrchrono: so.Mapped[str] = so.mapped_column(
        sa.String(32), nullable=False
    )
    va_rreview_narrdoc: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    va_rreview_narrcomorb: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False
    )
    va_rreview: so.Mapped[str] = so.mapped_column(
        sa.String(16), index=True, nullable=False
    )
    va_rreview_fail: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text, nullable=True
    )
    va_rreview_remark: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text, nullable=True
    )
    va_rreview_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
    )
    va_rreview_createdat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False
    )
    va_rreview_updatedat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self):
        return f"VA Reviewer Review -> {self.va_sid} ({self.va_rreview_status}): {self.va_rreview} | by {self.va_rreview_by}"
