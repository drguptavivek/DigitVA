import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from typing import Optional
from datetime import datetime, timezone


class VaSubmissionsAuditlog(db.Model):
    __tablename__ = "va_submissions_auditlog"
    
    va_audit_id: so.Mapped[int] = so.mapped_column(primary_key=True)
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64), sa.ForeignKey("va_submissions.va_sid"), index=True, nullable=False
    )
    va_audit_byrole: so.Mapped[str] = so.mapped_column(
        sa.String(30), nullable=False
    )
    va_audit_by: so.Mapped[Optional[uuid.UUID]] = so.mapped_column(
        sa.Uuid(as_uuid=True), nullable=True
    )
    va_audit_operation: so.Mapped[str] = so.mapped_column(
        sa.String(1), nullable=False
    )
    va_audit_action: so.Mapped[str] = so.mapped_column(
        sa.String(128), nullable=False
    )
    va_audit_entityid: so.Mapped[Optional[uuid.UUID]] = so.mapped_column(
        sa.Uuid(as_uuid=True), nullable=True
    )
    va_audit_createdat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    def __repr__(self):
        return f"VA Submission Audit -> {self.va_sid} | {self.va_audit_action}"
