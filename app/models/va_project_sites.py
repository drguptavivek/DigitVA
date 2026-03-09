import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses


class VaProjectSites(db.Model):
    __tablename__ = "va_project_sites"
    __table_args__ = (
        sa.UniqueConstraint(
            "project_id",
            "site_id",
            name="uq_va_project_sites_project_site",
        ),
    )

    project_site_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True, index=True
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6),
        sa.ForeignKey("va_project_master.project_id"),
        nullable=False,
        index=True,
    )
    site_id: so.Mapped[str] = so.mapped_column(
        sa.String(4),
        sa.ForeignKey("va_site_master.site_id"),
        nullable=False,
        index=True,
    )
    project_site_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
    )
    project_site_registered_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    project_site_updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"VA Project Site -> {self.project_id}/{self.site_id} ({self.project_site_status})"
