import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class VaSubmissionWorkflow(db.Model):
    __tablename__ = "va_submission_workflow"

    workflow_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True, index=True
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64),
        sa.ForeignKey("va_submissions.va_sid", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    workflow_state: so.Mapped[str] = so.mapped_column(
        sa.String(64), nullable=False, index=True
    )
    workflow_reason: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(128), nullable=True
    )
    workflow_updated_by_role: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(32), nullable=True
    )
    workflow_updated_by: so.Mapped[Optional[uuid.UUID]] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )
    workflow_created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    workflow_updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return f"VA Workflow -> {self.va_sid}: {self.workflow_state}"
