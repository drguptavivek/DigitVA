"""Durable weekly-demo reset outcome; credentials and record contents stay out."""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB

from app import db


class VaDemoResetRun(db.Model):
    """One attempt record per designated project and scheduled Sunday."""

    __tablename__ = "va_demo_reset_runs"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "scheduled_week", name="uq_demo_reset_project_week"),
    )

    reset_run_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_project_master.project_id"), nullable=False
    )
    scheduled_week: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    status: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    backup_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid, sa.ForeignKey("va_db_backups.backup_id")
    )
    backup_key: so.Mapped[str | None] = so.mapped_column(sa.Text)
    backup_size_bytes: so.Mapped[int | None] = so.mapped_column(sa.BigInteger)
    backup_sha256: so.Mapped[str | None] = so.mapped_column(sa.String(64))
    started_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    completed_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True))
    counts: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False, default=dict)
    error_code: so.Mapped[str | None] = so.mapped_column(sa.String(32))
