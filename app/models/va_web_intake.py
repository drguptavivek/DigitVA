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
#: Case states (docs/policy/web-intake.md, "States and transitions").
#: ``draft_identity`` is a direct start whose form has not yet captured the
#: minimum identity (name, date of death, sex). Only
#: ``app.services.case_transition_service`` writes ``status``.
CASE_STATES = (
    "draft_identity", "registered", "scheduled", "in_progress", "paused",
    "not_reachable", "refused", "submitted", "duplicate", "cancelled",
)
DEATH_REGISTER_STATUSES = CASE_STATES
CASE_SOURCES = ("register", "direct")
CASE_FLAGS = ("duplicate", "cancel")
#: Outcome of one contact attempt (``map_case_contact_attempts``); no notes.
CONTACT_OUTCOMES = ("reached", "no_answer", "wrong_number", "moved", "refused")
WEB_DRAFT_STATUSES = ("draft", "submitted", "discarded")
DEATH_SEX_VALUES = ("male", "female", "undetermined", "unknown")

# Human-readable id numbers come from this sequence (gaps are expected).
DEATH_NUMBER_SEQUENCE = "va_death_register_number_seq"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class VaDeathRegister(db.Model):
    """The case: one death, registered first or started directly as a VA.

    Identity (name, sex, date of death) is empty only while ``status`` is
    ``draft_identity`` (a direct start) or on a cancelled abandoned start.
    """

    __tablename__ = "va_death_register"
    __table_args__ = (
        sa.UniqueConstraint("unique_id", name="uq_va_death_register_unique_id"),
        sa.Index("ix_va_death_register_project_status", "project_id", "status"),
        sa.Index("ix_va_death_register_org_unit", "org_unit_id"),
        sa.Index("ix_va_death_register_updated", "updated_at", "death_id"),
        # The worklist sorts by next visit, then last activity.
        sa.Index("ix_va_death_register_next_visit", "next_visit_at", "updated_at", "death_id"),
        # Every coding reader asks "is this va_sid a confirmed duplicate?"
        # (app/services/duplicate_exclusion.py); only duplicate rows matter.
        sa.Index(
            "ix_va_death_register_duplicate_va_sid", "va_sid",
            postgresql_where=sa.text("status = 'duplicate'"),
        ),
        # The naming convention prefixes "ck_<table>_"; pass the discriminator.
        sa.CheckConstraint(
            "status IN (" + ", ".join(f"'{s}'" for s in CASE_STATES) + ")", name="status"
        ),
        sa.CheckConstraint("source IN ('register', 'direct')", name="source"),
        sa.CheckConstraint(
            "status IN ('draft_identity', 'cancelled') OR "
            "(deceased_name IS NOT NULL AND date_of_death IS NOT NULL AND deceased_sex IS NOT NULL)",
            name="identity",
        ),
        sa.CheckConstraint("pending_flag IN ('duplicate', 'cancel')", name="pending_flag"),
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
    deceased_name: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    deceased_sex: so.Mapped[str | None] = so.mapped_column(sa.String(16), nullable=True)
    # Ayushman Bharat Health Account identifiers of the deceased (PII).
    abha_number: so.Mapped[str | None] = so.mapped_column(sa.String(17), nullable=True)
    abha_address: so.Mapped[str | None] = so.mapped_column(sa.String(64), nullable=True)
    date_of_birth: so.Mapped[date | None] = so.mapped_column(sa.Date, nullable=True)
    age_years: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    date_of_death: so.Mapped[date | None] = so.mapped_column(sa.Date, nullable=True)
    place_of_death: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    address: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    # Structured address beside the free-text one (PII).
    address_house_street: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    address_village_ward: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    address_landmark: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    informant_name: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    # Indian mobile numbers, stored as 10 digits (older rows may hold free text).
    informant_phone: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
    informant_phone_2: so.Mapped[str | None] = so.mapped_column(sa.String(32), nullable=True)
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
    # register: the register form; direct: a questionnaire started directly.
    source: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default="register", server_default="register"
    )
    # Who opened the first interview on this case (no assignment exists).
    started_by_user_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )
    # An interviewer's duplicate or cancel flag, waiting for a supervisor.
    pending_flag: so.Mapped[str | None] = so.mapped_column(sa.String(16), nullable=True)
    # The kept case this one is (flagged or confirmed as) a duplicate of.
    duplicate_of_death_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_death_register.death_id"), nullable=True
    )
    # Appointment or follow-up date, and the latest contact attempt.
    next_visit_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    last_contact_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    def __repr__(self) -> str:
        return f"<VaDeathRegister {self.unique_id} {self.status}>"


class MapCaseTransition(db.Model):
    """Audit row for one case state change or flag (actor, from, to, reason).

    ``reason`` is a short code or a user-typed reason and must hold no
    personal data (names, phone numbers, addresses). Nothing enforces that
    yet: the user-facing warning arrives with the phase 4 worklist UI.
    """

    __tablename__ = "map_case_transitions"
    __table_args__ = (
        sa.Index("ix_map_case_transitions_death_created", "death_id", "created_at"),
        sa.Index("ix_map_case_transitions_actor", "actor_user_id", "death_id"),
    )

    transition_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    death_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_death_register.death_id"), nullable=False
    )
    action: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    # NULL on the row that created the case.
    from_state: so.Mapped[str | None] = so.mapped_column(sa.String(16), nullable=True)
    to_state: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    reason: so.Mapped[str | None] = so.mapped_column(sa.String(200), nullable=True)
    actor_user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )


class MapCaseContactAttempt(db.Model):
    """One attempt to reach a case's family: the outcome only, never notes."""

    __tablename__ = "map_case_contact_attempts"
    __table_args__ = (
        sa.Index("ix_map_case_contact_attempts_death_attempted", "death_id", "attempted_at"),
        # The worklist's "Mine" filter counts attempts the user logged.
        sa.Index("ix_map_case_contact_attempts_by_user", "by_user_id", "death_id"),
        sa.CheckConstraint(
            "outcome IN (" + ", ".join(f"'{o}'" for o in CONTACT_OUTCOMES) + ")", name="outcome"
        ),
    )

    attempt_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    death_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_death_register.death_id"), nullable=False
    )
    attempted_at: so.Mapped[datetime] = so.mapped_column(sa.DateTime(timezone=True), nullable=False)
    outcome: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    next_visit_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    by_user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )


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
