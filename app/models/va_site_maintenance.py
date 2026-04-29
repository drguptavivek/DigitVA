import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class VaSiteMaintenance(db.Model):
    __tablename__ = "va_site_maintenance"
    __table_args__ = (
        sa.Index("ix_va_site_maintenance_enabled", "enabled"),
        sa.Index("ix_va_site_maintenance_cutoff_at", "cutoff_at"),
    )

    maintenance_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    enabled: so.Mapped[bool] = so.mapped_column(sa.Boolean, nullable=False, default=True)
    starts_at: so.Mapped[datetime] = so.mapped_column(sa.DateTime(timezone=True), nullable=False)
    cutoff_at: so.Mapped[datetime] = so.mapped_column(sa.DateTime(timezone=True), nullable=False)
    message: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    enabled_by_user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", ondelete="RESTRICT"),
        nullable=False,
    )
    disabled_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    disabled_by_user_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def __repr__(self) -> str:
        return f"<VaSiteMaintenance enabled={self.enabled} cutoff_at={self.cutoff_at.isoformat()}>"
