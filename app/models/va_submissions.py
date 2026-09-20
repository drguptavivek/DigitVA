import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from typing import Optional
from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy.dialects.postgresql import JSONB, ARRAY, UUID


class VaSubmissions(db.Model):
    __tablename__ = "va_submissions"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["active_payload_version_id"],
            ["va_submission_payload_versions.payload_version_id"],
            name="fk_va_submissions_active_payload_version_id",
            use_alter=True,
        ),
        # Case-insensitive language filter for the coding intake queue.
        sa.Index(
            "ix_va_submissions_form_lower_language_sid",
            "va_form_id",
            sa.text("lower(va_narration_language::text)"),
            "va_sid",
        ),
        # A submission is either routed to a unit with a stated resolution, or
        # neither. See docs/policy/organization-model.md.
        # The naming convention (app/__init__.py) already prefixes these with
        # "ck_%(table_name)s_"; pass only the discriminator (digitva-liu).
        sa.CheckConstraint(
            "(org_unit_id IS NULL AND org_unit_resolution IS NULL) OR "
            "(org_unit_id IS NOT NULL AND org_unit_resolution IS NOT NULL)",
            name="org_unit_resolution_pair",
        ),
        sa.CheckConstraint(
            "org_unit_resolution IS NULL OR "
            "org_unit_resolution IN ('form_field', 'mapping_fallback', 'manual')",
            name="org_unit_resolution_value",
        ),
        # Pin metadata belongs to a manual routing decision only.
        sa.CheckConstraint(
            "(org_unit_pinned_by IS NULL AND org_unit_pinned_at IS NULL) OR "
            "org_unit_resolution = 'manual'",
            name="org_unit_pin_manual",
        ),
        sa.Index(
            "ix_va_submissions_org_unit_resolution",
            "org_unit_id",
            "org_unit_resolution",
        ),
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64), primary_key=True, index=True
    )
    va_form_id: so.Mapped[str] = so.mapped_column(
        sa.String(12), sa.ForeignKey("va_forms.form_id"), index=True
    )
    active_payload_version_id: so.Mapped[UUID | None] = so.mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    va_submission_date: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime, nullable=True, index=True
    )
    va_odk_updatedat: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime, nullable=True, index=True
    )
    va_data_collector: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=False)
    va_odk_reviewstate: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(16), nullable=True, index=True
    )
    va_odk_reviewcomments: so.Mapped[Optional[list[dict]]] = so.mapped_column(
        JSONB, nullable=True
    )
    va_sync_issue_code: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(32), nullable=True, index=True
    )
    va_sync_issue_detail: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(255), nullable=True
    )
    va_sync_issue_updated_at: so.Mapped[Optional[datetime]] = so.mapped_column(
        sa.DateTime, nullable=True, index=True
    )
    va_instance_name: so.Mapped[str] = so.mapped_column(sa.String(128), nullable=True)
    va_uniqueid_real: so.Mapped[Optional[str]] = so.mapped_column(sa.String(128), nullable=True)
    va_uniqueid_masked: so.Mapped[Optional[str]] = so.mapped_column(sa.String(128), nullable=False)    
    va_consent: so.Mapped[str] = so.mapped_column(
        sa.String(32), nullable=False, index=True
    )
    va_narration_language: so.Mapped[str] = so.mapped_column(
        sa.String(32), nullable=False, index=True
    )
    va_deceased_age: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    va_deceased_age_normalized_days: so.Mapped[Optional[Decimal]] = so.mapped_column(
        sa.Numeric, nullable=True
    )
    va_deceased_age_normalized_years: so.Mapped[Optional[Decimal]] = so.mapped_column(
        sa.Numeric, nullable=True
    )
    va_deceased_age_source: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(32), nullable=True
    )
    va_deceased_gender: so.Mapped[str] = so.mapped_column(sa.String(20), nullable=False)
    va_summary: so.Mapped[Optional[list[str]]] = so.mapped_column(
        ARRAY(sa.String), nullable=True
    )
    va_catcount: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False)
    va_category_list: so.Mapped[list[str]] = so.mapped_column(
        ARRAY(sa.String), nullable=False
    )
    va_created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )
    va_updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        index=True,
        nullable=False,
    )

    # -- organization routing (health-system projects) ---------------------
    #
    # The unit this death is attributed to, routed at sync time from the
    # payload's org_<level_code>_code fields, or pinned by hand by a data
    # manager. NULL means unrouted: either the project has no organization
    # tree, or nothing in the payload matched and the mapping named no
    # fallback unit. Policy: docs/policy/organization-model.md.
    org_unit_id: so.Mapped[UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("mas_org_unit.org_unit_id", name="fk_va_submissions_org_unit"),
        nullable=True,
        index=True,
    )
    # How the unit was decided: 'form_field' (a unit code in the payload),
    # 'mapping_fallback' (the ODK mapping's own unit), or 'manual' (pinned).
    # A manual routing is never overwritten by a later sync.
    org_unit_resolution: so.Mapped[str | None] = so.mapped_column(
        sa.String(16), nullable=True
    )
    org_unit_pinned_by: so.Mapped[UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", name="fk_va_submissions_org_unit_pinned_by"),
        nullable=True,
    )
    org_unit_pinned_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:
        return f"VA Submission -> {self.va_sid}"
