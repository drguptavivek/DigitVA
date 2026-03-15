import uuid
import sqlalchemy as sa
import sqlalchemy.orm as so
from app import db
from datetime import datetime, timezone
from app.models.va_selectives import VaStatuses


class VaNarrativeAssessment(db.Model):
    __tablename__ = "va_narrative_assessments"

    va_nqa_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True, index=True
    )
    va_sid: so.Mapped[str] = so.mapped_column(
        sa.String(64), sa.ForeignKey("va_submissions.va_sid", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    va_nqa_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"),
        nullable=False, index=True,
    )
    # Q1: Length of Narrative   — 1 (<3 sentences) | 2 (3-5) | 3 (>5)
    va_nqa_length: so.Mapped[int] = so.mapped_column(sa.SmallInteger(), nullable=False)
    # Q2: Positive Symptoms     — 1 (<3) | 2 (3-5) | 3 (>5)
    va_nqa_pos_symptoms: so.Mapped[int] = so.mapped_column(sa.SmallInteger(), nullable=False)
    # Q3: Negative Symptoms     — 0 (absent) | 1 (present)
    va_nqa_neg_symptoms: so.Mapped[int] = so.mapped_column(sa.SmallInteger(), nullable=False)
    # Q4: Chronology            — 0 (cannot establish) | 1 (can establish)
    va_nqa_chronology: so.Mapped[int] = so.mapped_column(sa.SmallInteger(), nullable=False)
    # Q5: Document Review       — 0 (not present/inconclusive) | 1 (provides useful data)
    va_nqa_doc_review: so.Mapped[int] = so.mapped_column(sa.SmallInteger(), nullable=False)
    # Q6: Comorbidity & Risk    — 0 (not present) | 1 (present)
    va_nqa_comorbidity: so.Mapped[int] = so.mapped_column(sa.SmallInteger(), nullable=False)
    # Computed total (0-10)
    va_nqa_score: so.Mapped[int] = so.mapped_column(sa.SmallInteger(), nullable=False)

    va_nqa_status: so.Mapped[VaStatuses] = so.mapped_column(
        sa.Enum(VaStatuses, name="status_enum"),
        default=VaStatuses.active,
        nullable=False,
        index=True,
    )
    va_nqa_createdat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc),
        nullable=False, index=True,
    )
    va_nqa_updatedat: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc), nullable=False,
    )
    demo_expires_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime,
        nullable=True,
        index=True,
    )

    __table_args__ = (
        sa.UniqueConstraint("va_sid", "va_nqa_by", name="uq_nqa_sid_by"),
    )

    @property
    def rating(self) -> str:
        if self.va_nqa_score >= 7:
            return "Good"
        if self.va_nqa_score >= 5:
            return "Fair"
        return "Poor"

    @property
    def rating_class(self) -> str:
        if self.va_nqa_score >= 7:
            return "success"
        if self.va_nqa_score >= 5:
            return "warning"
        return "danger"

    def __repr__(self):
        return (f"VaNarrativeAssessment -> {self.va_sid} by {self.va_nqa_by} "
                f"score={self.va_nqa_score} ({self.rating})")
