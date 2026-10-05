"""A user's private note on a case: one active note per user per case.

Shared by the web ``vausernote`` partial and ``/api/v1/va/<sid>/note`` so both
read and write the same row. Authorization is the caller's.
"""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import VaStatuses, VaUsernotes


def get_active_note(user_id, va_sid: str) -> VaUsernotes | None:
    """The user's latest active note on the case, or None."""
    return db.session.scalar(
        sa.select(VaUsernotes)
        .where(
            VaUsernotes.note_by == user_id,
            VaUsernotes.note_vasubmission == va_sid,
            VaUsernotes.note_status == VaStatuses.active,
        )
        .order_by(VaUsernotes.note_updated_at.desc())
        .limit(1)
    )


def save_note(user_id, va_sid: str, content: str | None) -> VaUsernotes:
    """Update the user's active note on the case, or create it; commits."""
    note = get_active_note(user_id, va_sid)
    if note is None:
        # ponytail: two concurrent first saves can both insert (no unique
        # constraint; the web had the same limit). Upgrade: a partial unique
        # index on (note_by, note_vasubmission) WHERE note_status = 'active'
        # and an ON CONFLICT upsert.
        note = VaUsernotes(note_by=user_id, note_vasubmission=va_sid, note_content=content)
        db.session.add(note)
    else:
        note.note_content = content
    db.session.commit()
    return note
