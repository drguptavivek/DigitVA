"""District-staff suggestions for an instrument translation string.

Policy: docs/policy/va-form-project-configuration.md ("District review and
suggestions", digitva-5op).

A suggestion is a *proposal*, never a translation: it changes nothing until an
administrator or the suggesting project's PI accepts it, and the accept goes
through ``instrument_translation_service.update_string`` (source ``edited``).
The row keeps the audit of both sides: who suggested and who decided.
``seen_text`` is the served translation the suggester was shown (NULL when the
string had none), so an accept can refuse when the string changed since.
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db

SUGGESTION_PENDING = "pending"
SUGGESTION_ACCEPTED = "accepted"
SUGGESTION_REJECTED = "rejected"
SUGGESTION_STATUSES = (SUGGESTION_PENDING, SUGGESTION_ACCEPTED, SUGGESTION_REJECTED)


class MapInstrumentTranslationSuggestions(db.Model):
    """One proposed wording for one string of one instrument locale."""

    __tablename__ = "map_instrument_translation_suggestions"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["instrument_code", "locale_code"],
            ["mas_instrument_locales.instrument_code", "mas_instrument_locales.locale_code"],
            name="fk_mits_locale",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')", name="status"
        ),
        # A decided suggestion says who decided and when.
        sa.CheckConstraint(
            "status = 'pending' OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)",
            name="decided_has_decider",
        ),
        # The admin queue: pending suggestions of a locale, oldest first.
        sa.Index("ix_mits_locale_status", "instrument_code", "locale_code", "status", "id"),
        # A PI's queue: pending suggestions made in a project.
        sa.Index("ix_mits_project_status", "project_id", "status", "id"),
        # One open suggestion per user and string.
        sa.Index(
            "uq_mits_pending_per_user",
            "suggested_by", "instrument_code", "locale_code", "item_kind", "item_key", "field",
            unique=True,
            postgresql_where=sa.text("status = 'pending'"),
        ),
    )

    id: so.Mapped[int] = so.mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    instrument_code: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    locale_code: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    item_kind: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False)
    item_key: so.Mapped[str] = so.mapped_column(sa.String(255), nullable=False)
    field: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    proposed_text: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    # The served translation the suggester saw; NULL when there was none.
    seen_text: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    reason: so.Mapped[str] = so.mapped_column(sa.String(1000), nullable=False)
    # The project the suggestion was made in: whose PI may decide it.
    project_id: so.Mapped[str] = so.mapped_column(
        sa.String(6),
        sa.ForeignKey("va_project_master.project_id", name="fk_mits_project"),
        nullable=False,
    )
    suggested_by: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", name="fk_mits_suggested_by"),
        nullable=False,
    )
    suggested_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
    status: so.Mapped[str] = so.mapped_column(
        sa.String(16), nullable=False, default=SUGGESTION_PENDING,
        server_default=SUGGESTION_PENDING,
    )
    decided_by: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey("va_users.user_id", name="fk_mits_decided_by"),
        nullable=True,
    )
    decided_at: so.Mapped[datetime | None] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    decision_note: so.Mapped[str | None] = so.mapped_column(sa.String(1000), nullable=True)

    def __repr__(self) -> str:
        return (
            f"TranslationSuggestion({self.id} {self.instrument_code}/{self.locale_code}"
            f"/{self.item_kind}/{self.item_key}/{self.field} {self.status})"
        )
