"""The web-intake visit note, read from a submission's active payload.

An identity-less consent refusal stores ``visit_address``, ``visit_date`` and
``visit_remarks`` in the payload (``web_intake_service._visit_note``). This
module is the one place readers (area dashboard count, data manager list and
filter, case view) ask "has a note" and "what may this viewer see".
Policy: docs/policy/web-intake.md, "Visit note".

Imports no service, so any reader can import it.
"""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import VaSubmissionPayloadVersion, VaSubmissions

ADDRESS_KEY = "visit_address"
DATE_KEY = "visit_date"
REMARKS_KEY = "visit_remarks"


def _payload_text(key: str):
    return sa.func.coalesce(VaSubmissionPayloadVersion.payload_data[key].astext, "")


def has_visit_note_condition(va_sid_expr=VaSubmissions.va_sid):
    """SQL predicate: *va_sid_expr*'s active payload carries a visit note.

    A correlated EXISTS on the one active version (partial unique index on
    ``va_sid``). The consent test is a cheap prefilter: only a consent
    refusal carries a note, so the JSONB keys are read for those rows only.
    """
    return sa.and_(
        sa.func.lower(sa.func.btrim(VaSubmissions.va_consent)) == "no",
        sa.exists(
            sa.select(1).where(
                VaSubmissionPayloadVersion.va_sid == va_sid_expr,
                VaSubmissionPayloadVersion.version_status == "active",
                sa.or_(_payload_text(DATE_KEY) != "", _payload_text(ADDRESS_KEY) != ""),
            )
        ),
    )


def visit_notes_for(va_sids) -> dict:
    """``{va_sid: {"address", "date", "remarks"}}`` for those submissions that
    have a note, in one query that extracts only the three keys."""
    sids = list(va_sids)
    if not sids:
        return {}
    rows = db.session.execute(
        sa.select(
            VaSubmissionPayloadVersion.va_sid,
            _payload_text(ADDRESS_KEY),
            _payload_text(DATE_KEY),
            _payload_text(REMARKS_KEY),
        ).where(
            VaSubmissionPayloadVersion.va_sid.in_(sids),
            VaSubmissionPayloadVersion.version_status == "active",
        )
    ).all()
    return {
        sid: {"address": address, "date": date, "remarks": remarks}
        for sid, address, date, remarks in rows
        if address or date
    }


def visit_note_for_viewer(note: dict | None, *, redact_pii: bool) -> dict | None:
    """The note as the viewer may see it, or None when there is none.

    Address is a PII location field and remarks are free text that can name
    people or places, so a viewer ``should_redact_pii`` redacts gets the date
    only (``redacted`` True, address and remarks None). Done here, server-side.
    """
    if not note or not (note.get("address") or note.get("date")):
        return None
    if redact_pii:
        return {"date": note.get("date") or None, "address": None, "remarks": None, "redacted": True}
    return {
        "date": note.get("date") or None,
        "address": note.get("address") or None,
        "remarks": note.get("remarks") or None,
        "redacted": False,
    }


def note_from_payload(payload: dict | None) -> dict | None:
    """The note held in an already-loaded payload dict (case view)."""
    if not payload:
        return None
    return {
        "address": payload.get(ADDRESS_KEY) or "",
        "date": payload.get(DATE_KEY) or "",
        "remarks": payload.get(REMARKS_KEY) or "",
    }
