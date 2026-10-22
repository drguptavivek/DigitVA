"""Training sessions of the Training & demo project (TRN01).

Policy: docs/policy/training-demo-project.md. A session is one training: a
root organization unit with its coder-slot units (20 by default, chosen per
session), ten pseudonymised case copies per slot and the participants an admin
added. Everything is retained; closing a session
only deactivates its participants' grants.
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so
from sqlalchemy.dialects.postgresql import ARRAY

from app import db

SESSION_STATUSES = ("active", "closed")
PARTICIPANT_ROLES = (
    "death_reporter",
    "interview_supervisor",
    "interviewer",
    "coder",
    "reviewer_data_manager",
)
PARTICIPANT_STATUSES = ("active", "removed")
#: The default number of coder slots; each session stores its own (1..MAX_CODER_SLOTS).
CODER_SLOTS = 20
MAX_CODER_SLOTS = 100
CASES_PER_SLOT = 10


def _utcnow() -> datetime:
    return datetime.now(UTC)


class MasTrainingSession(db.Model):
    """One training: its code (S001..), name, root unit, coder slots and status."""

    __tablename__ = "mas_training_sessions"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "session_code", name="uq_mas_training_sessions_project_code"),
        sa.UniqueConstraint("org_unit_id", name="uq_mas_training_sessions_org_unit"),
        sa.CheckConstraint("status IN ('active', 'closed')", name="status"),
        sa.CheckConstraint("coder_slots BETWEEN 1 AND 100", name="coder_slots"),
        sa.Index("ix_mas_training_sessions_project_created", "project_id", "created_at"),
    )

    training_session_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_project_master.project_id"), nullable=False
    )
    session_code: so.Mapped[str] = so.mapped_column(sa.String(8), nullable=False)
    name: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    created_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    org_unit_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("mas_org_unit.org_unit_id"), nullable=False
    )
    status: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default="active", server_default="active"
    )
    coder_slots: so.Mapped[int] = so.mapped_column(
        sa.Integer, nullable=False, default=CODER_SLOTS, server_default=str(CODER_SLOTS)
    )


class MapTrainingCase(db.Model):
    """One case copy: its session, number, coder slot and the answer key.

    ``source_final_cod`` is the source case's authoritative ICD-10 final cause.
    It is read only by the trainer report and never reaches a coder screen.
    """

    __tablename__ = "map_training_cases"
    __table_args__ = (
        sa.UniqueConstraint("training_session_id", "case_number", name="uq_map_training_cases_session_number"),
        sa.CheckConstraint("case_number BETWEEN 1 AND 1000", name="case_number"),
        sa.CheckConstraint("coder_slot BETWEEN 1 AND 100", name="coder_slot"),
        sa.Index("ix_map_training_cases_session_slot", "training_session_id", "coder_slot"),
    )

    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64), sa.ForeignKey("va_submissions.va_sid"), primary_key=True
    )
    training_session_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("mas_training_sessions.training_session_id"), nullable=False
    )
    case_number: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    coder_slot: so.Mapped[int] = so.mapped_column(sa.Integer, nullable=False)
    # Deliberately not a foreign key: the source belongs to another project.
    source_va_sid: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    source_final_cod: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)


class MapTrainingParticipant(db.Model):
    """An existing user added to a session in one role.

    ``grant_ids`` are the unit-scoped grants written for the role (two for
    reviewer_data_manager); remove and close flip only their status.
    """

    __tablename__ = "map_training_participants"
    __table_args__ = (
        sa.UniqueConstraint(
            "training_session_id", "user_id", "role", name="uq_map_training_participants_session_user_role"
        ),
        sa.CheckConstraint(
            "role IN ('death_reporter', 'interview_supervisor', 'interviewer', 'coder', "
            "'reviewer_data_manager')",
            name="role",
        ),
        sa.CheckConstraint("coder_slot IS NULL OR coder_slot BETWEEN 1 AND 100", name="coder_slot"),
        sa.CheckConstraint("(role = 'coder') = (coder_slot IS NOT NULL)", name="coder_slot_role"),
        sa.CheckConstraint("status IN ('active', 'removed')", name="status"),
        sa.Index("ix_map_training_participants_session_role", "training_session_id", "role"),
        sa.Index(
            "uq_map_training_participants_session_slot",
            "training_session_id",
            "coder_slot",
            unique=True,
            postgresql_where=sa.text("coder_slot IS NOT NULL"),
        ),
        # The sign-in onboarding check: one probe per user.
        sa.Index(
            "ix_map_training_participants_pending_onboarding",
            "user_id",
            postgresql_where=sa.text("status = 'active' AND onboarded_at IS NULL"),
        ),
    )

    participant_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    training_session_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("mas_training_sessions.training_session_id"), nullable=False
    )
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    role: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    coder_slot: so.Mapped[int | None] = so.mapped_column(sa.Integer, nullable=True)
    grant_ids: so.Mapped[list[uuid.UUID]] = so.mapped_column(
        ARRAY(sa.Uuid(as_uuid=True)), nullable=False, default=list
    )
    added_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=_utcnow
    )
    added_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    onboarded_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    status: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default="active", server_default="active"
    )
