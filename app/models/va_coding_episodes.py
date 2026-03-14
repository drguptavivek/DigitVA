import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class VaCodingEpisode(db.Model):
    __tablename__ = "va_coding_episodes"

    episode_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True, index=True
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64),
        sa.ForeignKey("va_submissions.va_sid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    episode_type: so.Mapped[str] = so.mapped_column(
        sa.String(32), nullable=False, index=True
    )
    episode_status: so.Mapped[str] = so.mapped_column(
        sa.String(32), nullable=False, index=True
    )
    started_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    base_final_assessment_id: so.Mapped[Optional[uuid.UUID]] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_final_assessments.va_finassess_id"),
        nullable=True,
    )
    replacement_final_assessment_id: so.Mapped[Optional[uuid.UUID]] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_final_assessments.va_finassess_id"),
        nullable=True,
    )
    started_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    completed_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime, nullable=True
    )
    abandoned_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime, nullable=True
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            f"VA Coding Episode -> {self.va_sid} ({self.episode_type}/"
            f"{self.episode_status})"
        )
