import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class VaSubmissionWorkflowEvent(db.Model):
    __tablename__ = "va_submission_workflow_events"
    __table_args__ = (
        sa.Index(
            "ix_va_submission_workflow_events_sid_created",
            "va_sid",
            "event_created_at",
        ),
        sa.Index(
            "ix_va_submission_workflow_events_transition_created",
            "transition_id",
            "event_created_at",
        ),
    )

    workflow_event_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True, index=True
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64),
        sa.ForeignKey("va_submissions.va_sid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    transition_id: so.Mapped[str] = so.mapped_column(
        sa.String(64),
        nullable=False,
        index=True,
    )
    previous_state: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(64),
        nullable=True,
        index=True,
    )
    current_state: so.Mapped[str] = so.mapped_column(
        sa.String(64),
        nullable=False,
        index=True,
    )
    actor_kind: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(32),
        nullable=True,
    )
    actor_role: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(32),
        nullable=True,
    )
    actor_user_id: so.Mapped[Optional[uuid.UUID]] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    transition_reason: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(128),
        nullable=True,
    )
    event_created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return (
            "VA Submission Workflow Event -> "
            f"{self.va_sid} {self.transition_id}: "
            f"{self.previous_state} -> {self.current_state}"
        )
