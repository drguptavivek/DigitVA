import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from datetime import datetime, timezone


class VaSyncRun(db.Model):
    """Records each ODK sync run — start time, outcome, and submission metrics."""

    __tablename__ = "va_sync_runs"

    sync_run_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True
    )
    triggered_by: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False
    )  # "scheduled" | "manual"
    triggered_user_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id"),
        nullable=True,
        index=True,
    )
    started_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        index=True,
        default=lambda: datetime.now(timezone.utc),
    )
    finished_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    status: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default="running"
    )  # "running" | "success" | "partial" | "error"
    records_added: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    records_updated: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    records_skipped: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    error_message: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    # JSON array of {"ts": ISO-string, "msg": str} — appended during run for live progress
    progress_log: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)

    def __repr__(self) -> str:
        return f"<VaSyncRun {self.sync_run_id} status={self.status}>"
