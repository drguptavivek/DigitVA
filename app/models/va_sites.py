import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses


class VaSites(db.Model):
    __tablename__ = "va_sites"
    site_id: so.Mapped[str] = so.mapped_column(
        sa.String(4), index=True, primary_key=True
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_research_projects.project_id"), index=True
    )
    site_name: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    site_abbr: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    site_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True
    )
    site_registered_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    site_updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"VA Research Institution -> {self.site_id} ({self.site_status}): {self.site_name}"
