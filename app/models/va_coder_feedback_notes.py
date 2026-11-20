"""A mentor's feedback note on one coder's coded case (digitva-oux5).

Append-only: the body is never edited. ``read_at`` (set once by the coder)
and the retraction pair are the only in-place updates; a retracted note stays
for audit and is returned to nobody but admins
(docs/policy/mentor-view.md, "Feedback notes").
"""

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db

#: Largest note body, characters (policy: 1 to 2000).
NOTE_MAX_LENGTH = 2000


class VaCoderFeedbackNote(db.Model):
    __tablename__ = "va_coder_feedback_notes"
    __table_args__ = (
        sa.Index("ix_va_coder_feedback_notes_coder_created", "coder_user_id", "created_at"),
        sa.CheckConstraint(
            "char_length(body) BETWEEN 1 AND 2000", name="body_length"
        ),
    )

    note_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64), sa.ForeignKey("va_submissions.va_sid", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    coder_user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    author_user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    # Why the author could write: "mentor", "data_manager", "site_pi" or "admin";
    # with institute_id, what the coder sees next to the author's name.
    author_basis: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    institute_id: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("mas_mentor_institute.institute_id"), nullable=True
    )
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6), sa.ForeignKey("va_project_master.project_id"), nullable=False
    )
    # The district at write time.
    org_unit_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("mas_org_unit.org_unit_id"), nullable=False
    )
    body: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    read_at: so.Mapped[datetime | None] = so.mapped_column(sa.DateTime(timezone=True), nullable=True)
    retracted_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    retracted_by: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )
