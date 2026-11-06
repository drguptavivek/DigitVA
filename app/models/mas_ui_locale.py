"""A UI language the Expo app may offer, and whether it is published (digitva-s028).

Policy: docs/policy/ui-strings.md ("Publishing a UI language"). The text lives
in the bundled export and ``mas_ui_string_override``; this row only says how a
client names and lays out the language, and whether the server serves its
pack. ``mas_languages`` is not reused: its codes are narration-language names
(``hindi``), not the ISO codes the app and the strings use (``hi``).
"""

import uuid

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class MasUiLocale(db.Model):
    """One UI language. Unpublished rows are editable but never listed or served."""

    __tablename__ = "mas_ui_locale"
    __table_args__ = (sa.CheckConstraint("direction IN ('ltr', 'rtl')", name="direction"),)

    locale_code: so.Mapped[str] = so.mapped_column(sa.String(16), primary_key=True)
    #: The language's name in its own script, shown in pickers ("हिन्दी").
    native_name: so.Mapped[str] = so.mapped_column(sa.String(64), nullable=False)
    #: BCP 47 tag for date and number formatting and screen readers ("hi-IN").
    bcp47_tag: so.Mapped[str] = so.mapped_column(sa.String(35), nullable=False)
    direction: so.Mapped[str] = so.mapped_column(
        sa.String(3), nullable=False, default="ltr", server_default="ltr"
    )
    is_published: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=False, server_default=sa.false()
    )
    updated_by: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )
    updated_at: so.Mapped[object] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    def __repr__(self) -> str:
        return f"MasUiLocale({self.locale_code})"
