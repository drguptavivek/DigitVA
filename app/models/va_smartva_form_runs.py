import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class VaSmartvaFormRun(db.Model):
    __tablename__ = "va_smartva_form_runs"
    __table_args__ = (
        # The naming convention (app/__init__.py) already prefixes this with
        # "ck_%(table_name)s_"; pass only the discriminator (digitva-liu).
        sa.CheckConstraint(
            "outcome IN ('success', 'partial', 'failed')",
            name="outcome",
        ),
        # Legacy index names from the creating migration, kept as-is.
        sa.Index("ix_va_smartva_form_runs_id", "form_run_id"),
        sa.Index("ix_va_smartva_form_runs_started_at", "run_started_at"),
        sa.Index("ix_va_smartva_form_runs_archive_state", "archive_state"),
    )

    OUTCOME_SUCCESS = "success"
    OUTCOME_PARTIAL = "partial"
    OUTCOME_FAILED = "failed"

    # Where this run's working directory lives now. The directory is an
    # operational/debug artifact layer: nothing in the app reads it once the
    # likelihood rows are in va_smartva_run_outputs, so it is archived to the
    # DigitVA object store and removed from the VM.
    # Baseline: docs/policy/smartva-generation-policy.md.
    ARCHIVE_STATE_LOCAL = "local"        # on this VM only (local store, or not yet archived)
    ARCHIVE_STATE_ARCHIVED = "archived"  # verified in the object store
    ARCHIVE_STATE_FAILED = "failed"      # archive attempt failed; local copy kept
    ARCHIVE_STATE_ABSENT = "absent"      # no directory to archive (never written, or removed by hand)
    ARCHIVE_STATES = (
        ARCHIVE_STATE_LOCAL,
        ARCHIVE_STATE_ARCHIVED,
        ARCHIVE_STATE_FAILED,
        ARCHIVE_STATE_ABSENT,
    )

    form_run_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        default=uuid.uuid4,
        primary_key=True,
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
    )
    run_completed_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime,
        nullable=True,
    )
    archive_state: so.Mapped[str] = so.mapped_column(
        sa.String(16),
        nullable=False,
        server_default=sa.text("'local'"),
    )
    # Key prefix the run directory was archived under, relative to the store's
    # own S3_PREFIX: smartva_runs/<project_id>/<form_id>/<form_run_id>/
    archive_key_prefix: so.Mapped[str | None] = so.mapped_column(
        sa.Text,
        nullable=True,
    )
    archived_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    # A short category, never a path, a key or a message with PHI in it.
    archive_error_code: so.Mapped[str | None] = so.mapped_column(
        sa.String(32),
        nullable=True,
    )
    archive_file_count: so.Mapped[int | None] = so.mapped_column(
        sa.Integer,
        nullable=True,
    )
    archive_bytes: so.Mapped[int | None] = so.mapped_column(
        sa.BigInteger,
        nullable=True,
    )

