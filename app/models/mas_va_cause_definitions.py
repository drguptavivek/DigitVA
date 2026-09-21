import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class MasVaCauseDefinition(db.Model):
    """WHO VA cause code with its physician-review definition.

    One row per cause code (``VAs-01.01`` ... ``VAs-12.99``, ``VAs-99``); the
    WHO section headings are not codes and are not stored, nor is the
    residual ``VAs-98``. Rows are listed in ``va_code`` order.
    ``definition_html`` is sanitized rich
    text (app/utils/rich_text.py). ``updated_by`` is set only by an admin edit;
    a non-null value protects the row from ``flask va-definitions import``
    unless ``--force``. See docs/policy/va-cause-definitions.md.
    """

    __tablename__ = "mas_va_cause_definitions"
    id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), default=uuid.uuid4, primary_key=True
    )
    va_code: so.Mapped[str] = so.mapped_column(sa.String(16), nullable=False, unique=True)
    title: so.Mapped[str] = so.mapped_column(sa.Text, nullable=False)
    definition_html: so.Mapped[str] = so.mapped_column(
        sa.Text, nullable=False, default="", server_default=""
    )
    is_active: so.Mapped[bool] = so.mapped_column(
        sa.Boolean, nullable=False, default=True, server_default=sa.true()
    )
    source: so.Mapped[str | None] = so.mapped_column(sa.Text, nullable=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
    updated_by: so.Mapped[uuid.UUID | None] = so.mapped_column(
        sa.Uuid(as_uuid=True),
        sa.ForeignKey(
            "va_users.user_id",
            name="fk_mas_va_cause_definitions_updated_by",
            ondelete="SET NULL",
        ),
        nullable=True,
    )
