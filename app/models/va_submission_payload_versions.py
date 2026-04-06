import sqlalchemy as sa
import sqlalchemy.orm as so
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.dialects.postgresql import JSONB, UUID

from app import db


PAYLOAD_VERSION_STATUS_ACTIVE = "active"
PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM = "pending_upstream"
PAYLOAD_VERSION_STATUS_SUPERSEDED = "superseded"
PAYLOAD_VERSION_STATUS_REJECTED = "rejected"

PAYLOAD_VERSION_STATUSES = (
    PAYLOAD_VERSION_STATUS_ACTIVE,
    PAYLOAD_VERSION_STATUS_PENDING_UPSTREAM,
    PAYLOAD_VERSION_STATUS_SUPERSEDED,
    PAYLOAD_VERSION_STATUS_REJECTED,
)


class VaSubmissionPayloadVersion(db.Model):
    __tablename__ = "va_submission_payload_versions"
    __table_args__ = (
        sa.CheckConstraint(
            "version_status IN ('active', 'pending_upstream', 'superseded', 'rejected')",
            name="ck_va_submission_payload_versions_status",
        ),
        sa.Index(
            "ix_va_submission_payload_versions_active_unique",
            "va_sid",
            unique=True,
            postgresql_where=sa.text("version_status = 'active'"),
        ),
    )

    payload_version_id: so.Mapped[UUID] = so.mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64),
        sa.ForeignKey("va_submissions.va_sid"),
        nullable=False,
        index=True,
    )
    source_updated_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime,
        nullable=True,
        index=True,
    )
    payload_fingerprint: so.Mapped[str] = so.mapped_column(
        sa.String(128),
        nullable=False,
    )
    payload_data: so.Mapped[dict] = so.mapped_column(
        JSONB,
        nullable=False,
    )
    version_status: so.Mapped[str] = so.mapped_column(
        sa.String(32),
        nullable=False,
        index=True,
    )
    created_by_role: so.Mapped[str] = so.mapped_column(
        sa.String(32),
        nullable=False,
        default="vasystem",
    )
    created_by: so.Mapped[UUID | None] = so.mapped_column(
        UUID(as_uuid=True),
        sa.ForeignKey("va_users.user_id"),
        nullable=True,
    )
    version_created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    version_activated_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime,
        nullable=True,
    )
    superseded_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime,
        nullable=True,
    )
    rejected_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime,
        nullable=True,
    )
    rejected_reason: so.Mapped[str | None] = so.mapped_column(
        sa.Text,
        nullable=True,
    )

    # Precomputed sync-completeness fields — set at insert time, never changed.
    # Eliminates expensive per-row JSONB extraction in the backfill-stats query.
    has_required_metadata: so.Mapped[bool] = so.mapped_column(
        sa.Boolean(),
        nullable=False,
        server_default=sa.false(),
    )
    attachments_expected: so.Mapped[int | None] = so.mapped_column(
        sa.Integer(),
        nullable=True,
    )

    def __repr__(self) -> str:
        return (
            "VaSubmissionPayloadVersion("
            f"va_sid={self.va_sid}, version_status={self.version_status})"
        )
