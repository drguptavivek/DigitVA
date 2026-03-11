import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from datetime import datetime, timezone


class MapProjectSiteOdk(db.Model):
    """Maps a project-site pair to a specific ODK Central project and form.

    A project-site combination has at most one ODK form mapping (unique on
    project_id + site_id). The ODK connection is resolved via MapProjectOdk.
    """

    __tablename__ = "map_project_site_odk"
    __table_args__ = (
        sa.UniqueConstraint(
            "project_id", "site_id", name="uq_map_project_site_odk_project_site"
        ),
    )

    id: so.Mapped[uuid.UUID] = so.mapped_column(
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
    odk_project_id: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    odk_form_id: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    form_type_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_form_types.form_type_id"),
        nullable=True,
        index=True,
    )

    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship to form type (lazy load — used when resolving rendering config)
    form_type: so.Mapped["MasFormTypes | None"] = so.relationship(
        "MasFormTypes", foreign_keys=[form_type_id], lazy="select"
    )

    def __repr__(self) -> str:
        return (
            f"<MapProjectSiteOdk {self.project_id}/{self.site_id} → "
            f"odk_project={self.odk_project_id} form={self.odk_form_id}>"
        )
