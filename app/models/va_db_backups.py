import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class VaDbBackup(db.Model):
    """Records each database dump — where it went, how big it was, and its hash.

    One row per ``create_db_backup()`` call, written ``running`` before
    ``pg_dump`` starts so an interrupted run is visible rather than silent. The
    row is the only history the VM keeps: with ``ATTACHMENT_STORE=s3`` the dump
    itself lives in the bucket under ``db-backups/`` and nothing stays on disk.

    ``object_key`` is the bucket key (or the file name on the local store) and
    is the one identifier safe to show an admin; ``error_code`` is a short
    category, never a message from ``pg_dump`` or the transport.
    """

    __tablename__ = "va_db_backups"
    __table_args__ = (
        sa.Index("ix_va_db_backups_started_at", sa.text("started_at DESC")),
        sa.Index("ix_va_db_backups_status", "status"),
    )

    # triggered_by
    TRIGGER_SCHEDULED = "scheduled"
    TRIGGER_MANUAL = "manual"
    TRIGGER_CLI = "cli"

    # status
    STATUS_RUNNING = "running"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_PRUNED = "pruned"
    STATUSES = (STATUS_RUNNING, STATUS_SUCCESS, STATUS_FAILED, STATUS_PRUNED)

    backup_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True
    )
    started_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    triggered_by: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False
    )  # "scheduled" | "manual" | "cli"
    triggered_user_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", name="fk_va_db_backups_triggered_user_id"),
        nullable=True,
    )
    status: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default=STATUS_RUNNING
    )  # "running" | "success" | "failed" | "pruned"
    store: so.Mapped[str] = so.mapped_column(sa.String(8), nullable=False)  # "local" | "s3"
    object_key: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    size_bytes: so.Mapped[int | None] = so.mapped_column(sa.BigInteger, nullable=True)
    sha256: so.Mapped[str | None] = so.mapped_column(sa.String(64), nullable=True)
    error_code: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    pruned_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"<VaDbBackup {self.backup_id} status={self.status} store={self.store}>"
