import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db
from app.models.va_selectives import VaStatuses


class VaReviewerInitialAssessments(db.Model):
    __tablename__ = "va_reviewer_initial_assessments"

    va_riniassess_id: so.Mapped[uuid.UUID] = so.mapped_column(
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
    va_riniassess_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id"),
        index=True,
        nullable=False,
    )
    va_immediate_cod: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    va_antecedent_cod: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    va_other_conditions: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text, nullable=True
    )
    va_riniassess_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
    )
    va_riniassess_createdat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    va_riniassess_updatedat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self):
        return (
            "VA Reviewer Initial COD -> "
            f"{self.va_sid} ({self.va_riniassess_status}) | "
            f"by {self.va_riniassess_by}"
        )
