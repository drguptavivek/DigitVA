import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class VaFinalCodAuthority(db.Model):
    __tablename__ = "va_final_cod_authority"
    __table_args__ = (
        sa.UniqueConstraint("va_sid", name="uq_va_final_cod_authority_sid"),
        # Hand-picked names from the creating migration; they predate the
        # metadata naming convention and are kept as the database has them.
        sa.UniqueConstraint(
            "authoritative_final_assessment_id",
            name="uq_va_final_cod_authority_final_assessment_id",
        ),
        sa.UniqueConstraint(
            "authoritative_reviewer_final_assessment_id",
            name="uq_va_final_cod_authority_authoritative_reviewer_final",
        ),
    )

    authority_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True, index=True
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64),
        sa.ForeignKey("va_submissions.va_sid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    authoritative_final_assessment_id: so.Mapped[Optional[uuid.UUID]] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_final_assessments.va_finassess_id"),
        nullable=True,
    )
    authoritative_reviewer_final_assessment_id: so.Mapped[Optional[uuid.UUID]] = (
        so.mapped_column(
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("va_reviewer_final_assessments.va_rfinassess_id"),
            nullable=True,
        )
    )
    authority_source_role: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(32), nullable=True
    )
    authority_reason: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(128), nullable=True
    )
    effective_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime, nullable=True, index=True
    )
    updated_by: so.Mapped[Optional[uuid.UUID]] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return (
            "VA Final COD Authority -> "
            f"{self.va_sid}: coder={self.authoritative_final_assessment_id} "
            f"reviewer={self.authoritative_reviewer_final_assessment_id}"
        )
