import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from datetime import datetime, timezone

from app import db
from app.models.va_selectives import VaStatuses


class VaSocialAutopsyAnalysis(db.Model):
    __tablename__ = "va_social_autopsy_analyses"
    __table_args__ = (
        sa.Index(
            "ix_va_social_autopsy_analyses_active_sid_by_unique",
            "va_sid",
            "va_saa_by",
            unique=True,
            postgresql_where=sa.text("va_saa_status = 'active'"),
        ),
    )

    va_saa_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True, index=True
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64),
        sa.ForeignKey("va_submissions.va_sid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    va_saa_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id"),
        nullable=False,
        index=True,
    )
    payload_version_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_submission_payload_versions.payload_version_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    va_saa_remark: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    va_saa_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
    )
    va_saa_createdat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    va_saa_updatedat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    demo_expires_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime,
        nullable=True,
        index=True,
    )

    selected_options: so.Mapped[list["VaSocialAutopsyAnalysisOption"]] = so.relationship(
        "VaSocialAutopsyAnalysisOption",
        back_populates="analysis",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class VaSocialAutopsyAnalysisOption(db.Model):
    __tablename__ = "va_social_autopsy_analysis_options"

    va_saa_option_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True, index=True
    )
    va_saa_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_social_autopsy_analyses.va_saa_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    delay_level: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    option_code: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    analysis: so.Mapped["VaSocialAutopsyAnalysis"] = so.relationship(
        "VaSocialAutopsyAnalysis",
        back_populates="selected_options",
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "va_saa_id",
            "delay_level",
            "option_code",
            name="uq_social_autopsy_analysis_option",
        ),
    )
