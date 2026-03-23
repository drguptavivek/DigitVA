import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class VaSmartvaFormRun(db.Model):
    __tablename__ = "va_smartva_form_runs"
    __table_args__ = (
        sa.CheckConstraint(
            "outcome IN ('success', 'partial', 'failed')",
            name="ck_va_smartva_form_runs_outcome",
        ),
    )

    OUTCOME_SUCCESS = "success"
    OUTCOME_PARTIAL = "partial"
    OUTCOME_FAILED = "failed"

    form_run_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        default=uuid.uuid4,
        primary_key=True,
        index=True,
    )
    form_id: so.Mapped[str] = so.mapped_column(
        sa.String(12),
        sa.ForeignKey("va_forms.form_id"),
        nullable=False,
        index=True,
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6),
        sa.ForeignKey("va_research_projects.project_id"),
        nullable=False,
        index=True,
    )
    trigger_source: so.Mapped[str] = so.mapped_column(
        sa.String(32),
        nullable=False,
        index=True,
    )
    pending_sid_count: so.Mapped[int] = so.mapped_column(
        sa.Integer,
        nullable=False,
    )
    outcome: so.Mapped[str | None] = so.mapped_column(
        sa.String(16),
        nullable=True,
        index=True,
    )
    disk_path: so.Mapped[str | None] = so.mapped_column(
        sa.String(255),
        nullable=True,
    )
    run_started_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    run_completed_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime,
        nullable=True,
    )

