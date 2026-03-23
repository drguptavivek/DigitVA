import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from typing import Optional
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses


class VaReviewerFinalAssessments(db.Model):
    __tablename__ = "va_reviewer_final_assessments"

    va_rfinassess_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, index=True, primary_key=True
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64),
        sa.ForeignKey("va_submissions.va_sid"),
        index=True,
        nullable=False,
    )
    payload_version_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_submission_payload_versions.payload_version_id"),
        index=True,
        nullable=True,
    )
    va_rfinassess_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id"),
        index=True,
        nullable=False,
    )
    va_conclusive_cod: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    va_rfinassess_remark: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text,
        nullable=True,
    )
    supersedes_coder_final_assessment_id: so.Mapped[uuid.UUID | None] = (
        so.mapped_column(
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("va_final_assessments.va_finassess_id", ondelete="SET NULL"),
            index=True,
            nullable=True,
        )
    )
    va_rfinassess_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
    )
    va_rfinassess_createdat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    va_rfinassess_updatedat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self):
        return (
            "VA Reviewer Conclusive COD -> "
            f"{self.va_sid} ({self.va_rfinassess_status}): "
            f"{self.va_conclusive_cod} | by {self.va_rfinassess_by}"
        )
