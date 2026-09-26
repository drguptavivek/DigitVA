import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB
from app import db
from typing import Optional
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses


class VaFinalAssessments(db.Model):
    __tablename__ = "va_final_assessments"
    __table_args__ = (
        sa.Index(
            "uq_va_final_assessments_active_sid_payload",
            "va_sid",
            "payload_version_id",
            unique=True,
            postgresql_where=sa.text(
                "va_finassess_status = 'active' AND payload_version_id IS NOT NULL"
            ),
        ),
    )

    va_finassess_id: so.Mapped[uuid.UUID] = so.mapped_column(
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
            name="fk_va_final_assessments_payload_version_id",
            ondelete="SET NULL",
        ),
        index=True,
        nullable=True,
    )
    va_finassess_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id"),
        index=True,
        nullable=False,
    )
    source_initial_assessment_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_initial_assessments.va_iniassess_id", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    va_conclusive_cod: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    icd11_provenance: so.Mapped[dict | None] = so.mapped_column(
        JSONB, nullable=True
    )
    va_immediate_cod: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    immediate_icd11_provenance: so.Mapped[dict | None] = so.mapped_column(
        JSONB, nullable=True
    )
    va_other_conditions: so.Mapped[str | None] = so.mapped_column(
        sa.Text, nullable=True
    )
    doris_certificate: so.Mapped[dict | None] = so.mapped_column(JSONB, nullable=True)
    doris_result: so.Mapped[dict | None] = so.mapped_column(JSONB, nullable=True)
    codedit_result: so.Mapped[dict | None] = so.mapped_column(JSONB, nullable=True)
    cod_entry_mode_snapshot: so.Mapped[dict | None] = so.mapped_column(
        JSONB, nullable=True
    )
    va_finassess_remark: so.Mapped[Optional[str]] = so.mapped_column(
        sa.Text, nullable=True
    )
    va_finassess_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
    )
    va_finassess_createdat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    va_finassess_updatedat: so.Mapped[datetime] = so.mapped_column(
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

    def __repr__(self):
        return f"VA Conclusive COD -> {self.va_sid} ({self.va_finassess_status}): {self.va_conclusive_cod} | by {self.va_finasses_by}"
