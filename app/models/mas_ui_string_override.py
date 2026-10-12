"""A reader's correction to one Expo UI string in one locale (digitva-fsjz).

Policy: docs/policy/ui-strings.md. The bundled JSON under
``mobile/digitva-collect/src/strings`` stays the shipped default; a row here
replaces one string for every browser and phone. Reverting deletes the row, so
the bundled text is what remains. Written only by
``app.services.ui_string_service``.
"""

import uuid

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class MasUiStringOverride(db.Model):
    """One corrected UI string of one locale. The key pair is the primary key."""

    __tablename__ = "mas_ui_string_override"

    locale_code: so.Mapped[str] = so.mapped_column(sa.String(16), primary_key=True)
    string_key: so.Mapped[str] = so.mapped_column(sa.String(255), primary_key=True)
    text: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    updated_by: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=True
    )
    updated_at: so.Mapped[object] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )

    def __repr__(self) -> str:
        return f"MasUiStringOverride({self.locale_code}/{self.string_key})"
