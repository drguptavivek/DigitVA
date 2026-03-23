import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB

from app import db


class VaSubmissionUpstreamChange(db.Model):
    __tablename__ = "va_submission_upstream_changes"

    upstream_change_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True, index=True
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64),
        sa.ForeignKey("va_submissions.va_sid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_state_before: so.Mapped[str] = so.mapped_column(
        sa.String(64), nullable=False, index=True
    )
    previous_final_assessment_id: so.Mapped[Optional[uuid.UUID]] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_final_assessments.va_finassess_id", ondelete="SET NULL"),
        nullable=True,
    )
    previous_payload_version_id: so.Mapped[Optional[uuid.UUID]] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey(
            "va_submission_payload_versions.payload_version_id", ondelete="SET NULL"
        ),
        nullable=True,
        index=True,
    )
    incoming_payload_version_id: so.Mapped[Optional[uuid.UUID]] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey(
            "va_submission_payload_versions.payload_version_id", ondelete="SET NULL"
        ),
        nullable=True,
        index=True,
    )
    previous_va_data: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False)
    incoming_va_data: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False)
    detected_odk_updatedat: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True, index=True
    )
    resolution_status: so.Mapped[str] = so.mapped_column(
        sa.String(32), nullable=False, default="pending", index=True
    )
    resolved_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    resolved_by: so.Mapped[Optional[uuid.UUID]] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    resolved_by_role: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(32), nullable=True
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
            "VA Submission Upstream Change -> "
            f"{self.va_sid} ({self.resolution_status})"
        )
