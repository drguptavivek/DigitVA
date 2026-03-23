from app import db
import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from typing import Optional
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses


class VaSmartvaResults(db.Model):
    __tablename__ = "va_smartva_results"

    OUTCOME_SUCCESS = "success"
    OUTCOME_FAILED = "failed"

    va_smartva_id: so.Mapped[uuid.UUID] = so.mapped_column(
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
        sa.ForeignKey(
            "va_submission_payload_versions.payload_version_id",
            ondelete="SET NULL",
        ),
        index=True,
        nullable=True,
    )
    smartva_run_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_smartva_runs.va_smartva_run_id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    va_smartva_age: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(8), nullable=True
    )
    va_smartva_gender: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(8), nullable=True
    )
    va_smartva_cause1: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text, nullable=True
    )
    va_smartva_likelihood1: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(32), nullable=True
    )
    va_smartva_keysymptom1: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text, nullable=True
    )
    va_smartva_cause2: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text, nullable=True
    )
    va_smartva_likelihood2: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(32), nullable=True
    )
    va_smartva_keysymptom2: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text, nullable=True
    )
    va_smartva_cause3: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text, nullable=True
    )
    va_smartva_likelihood3: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(32), nullable=True
    )
    va_smartva_keysymptom3: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text, nullable=True
    )
    va_smartva_allsymptoms: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text, nullable=True
    )
    va_smartva_resultfor: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(16), nullable=True
    )
    va_smartva_cause1icd: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(8), nullable=True
    )
    va_smartva_cause2icd: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(8), nullable=True
    )
    va_smartva_cause3icd: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(8), nullable=True
    )
    va_smartva_outcome: so.Mapped[str] = so.mapped_column(
        sa.String(16),
        default=OUTCOME_SUCCESS,
        nullable=False,
        index=True,
    )
    va_smartva_failure_stage: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(32), nullable=True
    )
    va_smartva_failure_detail: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text, nullable=True
    )

    va_smartva_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
    )
    va_smartva_addedat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    va_smartva_updatedat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"SmartVaResult {self.sid}"
