import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from datetime import datetime, timezone


class MapProjectSiteOdk(db.Model):
    """Maps a project-site pair to a specific ODK Central project and form.

    A project-site may map **several** ODK forms — one DigitVA project accepts
    submissions from several Central forms over one connection — so uniqueness
    is on the whole identity, project + site + ODK project + ODK form. Each
    mapping materializes its own ``va_forms`` row. The reverse rule still
    holds and is enforced in ``app.services.odk_form_mapping_service``: one ODK
    form belongs to one project-site. The ODK connection is resolved via
    MapProjectOdk.
    """

    __tablename__ = "map_project_site_odk"
    __table_args__ = (
        sa.UniqueConstraint(
            "project_id",
            "site_id",
            "odk_project_id",
            "odk_form_id",
            name="uq_map_project_site_odk_project_site_form",
        ),
        # The naming convention (app/__init__.py) already prefixes this with
        # "ck_%(table_name)s_"; pass only the discriminator (digitva-liu).
        sa.CheckConstraint(
            "icd_classification IN ('icd10', 'icd11')",
            name="icd_classification",
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
    # DEPRECATED (2026-09-24): the ICD classification is a project setting,
    # va_project_master.icd_classification. This column is kept only so the
    # move can be rolled back; nothing reads, writes or shows it. Policy:
    # docs/policy/va-form-project-configuration.md ("5. ICD classification").
    icd_classification: so.Mapped[str] = so.mapped_column(
        sa.String(8), nullable=False, server_default="icd10"
    )
    # Fallback organization unit for submissions of this ODK form whose payload
    # carries no usable unit code. NULL means such submissions stay unrouted
    # and surface in the data manager's unrouted queue.
    # Policy: docs/policy/organization-model.md.
    org_unit_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_org_unit.org_unit_id", name="fk_map_project_site_odk_org_unit"),
        nullable=True,
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
    # Timestamp used in the last successful delta check. NULL = never synced → always download.
    last_synced_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
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
