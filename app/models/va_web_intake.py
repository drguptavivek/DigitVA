"""Web intake: death register and questionnaire drafts.

Plan: docs/planning/who-va-2022-web-intake-plan.md
Policy: docs/policy/web-intake.md

A project may register a death first (``VaDeathRegister``) and start the WHO
VA questionnaire from it, or open the questionnaire directly; the project's
``web_intake_mode`` decides. Drafts hold the questionnaire package's draft
envelope so an interview can be resumed on any device.
"""
import uuid
from datetime import UTC, date, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import JSONB

from app import db

WEB_INTAKE_MODES = ("off", "direct", "death_register", "both")
DEATH_REGISTER_STATUSES = ("registered", "va_in_progress", "va_submitted", "cancelled")
WEB_DRAFT_STATUSES = ("draft", "submitted", "discarded")
DEATH_SEX_VALUES = ("male", "female", "undetermined", "unknown")

# Human-readable id numbers come from this sequence (gaps are expected).
DEATH_NUMBER_SEQUENCE = "va_death_register_number_seq"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class VaDeathRegister(db.Model):
    """A death notified to the health system before or without its VA."""

    __tablename__ = "va_death_register"
    __table_args__ = (
        sa.UniqueConstraint("unique_id", name="uq_va_death_register_unique_id"),
        sa.Index("ix_va_death_register_project_status", "project_id", "status"),
        sa.Index("ix_va_death_register_org_unit", "org_unit_id"),
    )

    death_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_project_master.project_id"), nullable=False
    )
    site_id: so.Mapped[str] = so.mapped_column(
        sa.String(4), sa.ForeignKey("va_site_master.site_id"), nullable=False
    )
    org_unit_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("mas_org_unit.org_unit_id"), nullable=True
    )
    death_number: so.Mapped[int] = so.mapped_column(sa.BigInteger, nullable=False)
    unique_id: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    deceased_name: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    deceased_sex: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    # Ayushman Bharat Health Account identifiers of the deceased (PII).
    abha_number: so.Mapped[str | None] = so.mapped_column(sa.String(17), nullable=True)
    abha_address: so.Mapped[str | None] = so.mapped_column(sa.String(64), nullable=True)
    date_of_birth: so.Mapped[date | None] = so.mapped_column(sa.Date, nullable=True)
    age_years: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    date_of_death: so.Mapped[date] = so.mapped_column(sa.Date, nullable=False)
    place_of_death: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    address: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    informant_name: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    informant_phone: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    remarks: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    status: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default="registered", server_default="registered"
    )
    va_sid: so.Mapped[str | None] = so.mapped_column(
        sa.String(64), sa.ForeignKey("va_submissions.va_sid"), nullable=True
    )
    registered_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:
        return f"<VaDeathRegister {self.unique_id} {self.status}>"


class VaWebIntakeDraft(db.Model):
    """A questionnaire draft (the package's envelope) owned by one interviewer."""

    __tablename__ = "va_web_intake_drafts"
    __table_args__ = (
        sa.Index("ix_va_web_intake_drafts_user_status", "user_id", "status"),
        sa.Index("ix_va_web_intake_drafts_project", "project_id"),
        sa.Index("ix_va_web_intake_drafts_death", "death_id"),
    )

    draft_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_project_master.project_id"), nullable=False
    )
    site_id: so.Mapped[str] = so.mapped_column(
        sa.String(4), sa.ForeignKey("va_site_master.site_id"), nullable=False
    )
    org_unit_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("mas_org_unit.org_unit_id"), nullable=True
    )
    death_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_death_register.death_id"), nullable=True
    )
    form_id: so.Mapped[str] = so.mapped_column(
        sa.String(12), sa.ForeignKey("va_forms.form_id"), nullable=False
    )
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    unique_id: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    # Package draft envelope without its ``data`` member: {schemaVersion,
    # formVersion, id, instrumentId, instrumentVersion, currentSection,
    # createdAt, updatedAt}. Answers live per section in VaWebIntakeDraftSection.
    meta: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False, default=dict)
    # Prefill the page applies on first load (deceased, interviewer, location).
    prefill: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False, default=dict)
    current_section: so.Mapped[str | None] = so.mapped_column(sa.String(64), nullable=True)
    status: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default="draft", server_default="draft"
    )
    va_sid: so.Mapped[str | None] = so.mapped_column(
        sa.String(64), sa.ForeignKey("va_submissions.va_sid"), nullable=True
    )
    client_valid: so.Mapped[bool | None] = so.mapped_column(sa.Boolean, nullable=True)
    client_issue_count: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    submitted_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    sections: so.Mapped[list["VaWebIntakeDraftSection"]] = so.relationship(
        "VaWebIntakeDraftSection", back_populates="draft", lazy="select",
        cascade="all, delete-orphan", order_by="VaWebIntakeDraftSection.section_name",
    )

    def __repr__(self) -> str:
        return f"<VaWebIntakeDraft {self.draft_id} {self.status}>"


class VaWebIntakeDraftSection(db.Model):
    """One questionnaire section's answers, saved independently of the others."""

    __tablename__ = "va_web_intake_draft_sections"
    __table_args__ = (
        sa.UniqueConstraint("draft_id", "section_name", name="uq_va_web_intake_draft_sections"),
    )

    section_row_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    draft_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_web_intake_drafts.draft_id"), nullable=False, index=True
    )
    section_name: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    # Answers keyed by question name for the questions of this section only.
    data: so.Mapped[dict] = so.mapped_column(JSONB, nullable=False, default=dict)
    saved_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    draft: so.Mapped["VaWebIntakeDraft"] = so.relationship("VaWebIntakeDraft", back_populates="sections")
