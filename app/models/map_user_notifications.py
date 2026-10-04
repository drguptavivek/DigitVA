import uuid
from datetime import datetime

import sqlalchemy as sa
import sqlalchemy.orm as so

from app import db


class MapUserNotification(db.Model):
    """One polled nudge for one user (digitva-hdrv, docs/policy/app-notifications.md).

    Maps a user to an event that already happened (a send-back, another
    interviewer's draft, a closed case): ids and a fixed ``kind`` only, never a
    name, phone or answer. ``id`` is the poll cursor. Rows are written in the
    transaction of the event and purged after 30 days.
    """

    __tablename__ = "map_user_notifications"
    __table_args__ = (
        # The poll: ``user_id = me AND id > cursor ORDER BY id``.
        sa.Index("ix_map_user_notifications_user_id_id", "user_id", "id"),
        # The daily purge.
        sa.Index("ix_map_user_notifications_created_at", "created_at"),
    )

    id: so.Mapped[int] = so.mapped_column(sa.BigInteger, sa.Identity(), primary_key=True)
    user_id: so.Mapped[uuid.UUID] = so.mapped_column(
        sa.Uuid(as_uuid=True), sa.ForeignKey("va_users.user_id"), nullable=False
    )
    kind: so.Mapped[str] = so.mapped_column(sa.String(32), nullable=False)
    project_id: so.Mapped[str] = so.mapped_column(sa.String(6), nullable=False)
    death_id: so.Mapped[uuid.UUID | None] = so.mapped_column(sa.Uuid(as_uuid=True), nullable=True)
    draft_id: so.Mapped[uuid.UUID | None] = so.mapped_column(sa.Uuid(as_uuid=True), nullable=True)
    va_sid: so.Mapped[str | None] = so.mapped_column(sa.String(64), nullable=True)
    created_at: so.Mapped[datetime] = so.mapped_column(
        sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )
