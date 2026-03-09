import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses


class VaSiteMaster(db.Model):
    __tablename__ = "va_site_master"
    site_id: so.Mapped[str] = so.mapped_column(
        sa.String(4), primary_key=True, index=True
    )
    site_name: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    site_abbr: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    site_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
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
        return f"VA Site Master -> {self.site_id} ({self.site_status})"
