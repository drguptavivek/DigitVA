import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB

from app import db


class VaSmartvaRun(db.Model):
    __tablename__ = "va_smartva_runs"

    OUTCOME_SUCCESS = "success"
    OUTCOME_FAILED = "failed"

    va_smartva_run_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        default=uuid.uuid4,
        primary_key=True,
        index=True,
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64),
        sa.ForeignKey("va_submissions.va_sid"),
        nullable=False,
        index=True,
    )
    payload_version_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey(
            "va_submission_payload_versions.payload_version_id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    trigger_source: so.Mapped[str] = so.mapped_column(
        sa.String(32),
        nullable=False,
        default="datasync",
        index=True,
    )
    va_smartva_outcome: so.Mapped[str] = so.mapped_column(
        sa.String(16),
        nullable=False,
        default=OUTCOME_SUCCESS,
        index=True,
    )
    va_smartva_failure_stage: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(32),
        nullable=True,
    )
    va_smartva_failure_detail: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text,
        nullable=True,
    )
    run_metadata: so.Mapped[dict | None] = so.mapped_column(
        JSONB,
        nullable=True,
    )
    va_smartva_run_started_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    va_smartva_run_completed_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    va_smartva_run_updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

