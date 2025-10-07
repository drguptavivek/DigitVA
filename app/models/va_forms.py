import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses


class VaForms(db.Model):
    __tablename__ = "va_forms"
    form_id: so.Mapped[str] = so.mapped_column(
        sa.String(12), index=True, primary_key=True
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_research_projects.project_id"), index=True
    )
    site_id: so.Mapped[str] = so.mapped_column(
        sa.String(4), sa.ForeignKey("va_sites.site_id"), index=True
    )
    odk_form_id: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    odk_project_id: so.Mapped[str] = so.mapped_column(sa.String(2), nullable=False)
    form_type: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    form_smartvahiv: so.Mapped[str] = so.mapped_column(sa.String(8), default="False", nullable=False)
    form_smartvamalaria: so.Mapped[str] = so.mapped_column(sa.String(8), default="False", nullable=False)
    form_smartvahce: so.Mapped[str] = so.mapped_column(sa.String(8), default="True", nullable=False)
    form_smartvafreetext: so.Mapped[str] = so.mapped_column(sa.String(8), default="True", nullable=False)
    form_smartvacountry:so.Mapped[str] = so.mapped_column(sa.String(4), default="IND", nullable=False)
    form_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True
    )
    form_registered_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    form_updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"VA Form -> {self.form_id} ({self.form_status})"
