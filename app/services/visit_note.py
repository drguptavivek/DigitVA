"""The web-intake visit note, read from a submission's active payload.

An identity-less consent refusal stores ``visit_address``, ``visit_date`` and
``visit_remarks`` in the payload (``web_intake_service._visit_note``). This
module is the one place readers (area dashboard count, data manager list and
filter, case view) ask "has a note" and "what may this viewer see".
Policy: docs/policy/web-intake.md, "Visit note".

Imports no service at module level, so any reader can import it. With
``PAYLOAD_PII_SPLIT_ENABLED`` on, ``visit_address`` and ``visit_remarks`` are
sealed (PII slice 1b): "has a note" asks the side row for the sealed key
(``sealed ? 'visit_address'``, no decrypt) and the text itself is opened only
for a viewer who may see PII.
"""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import MapPayloadVersionPii, VaSubmissionPayloadVersion, VaSubmissions

ADDRESS_KEY = "visit_address"
DATE_KEY = "visit_date"
REMARKS_KEY = "visit_remarks"


def _payload_text(key: str):
    return sa.func.coalesce(VaSubmissionPayloadVersion.payload_data[key].astext, "")


def _sealed_address():
    """SQL predicate: the version's side row holds a sealed visit address
    (no decrypt). False for a version with no side row."""
    return (
        sa.exists()
        .where(
            MapPayloadVersionPii.payload_version_id == VaSubmissionPayloadVersion.payload_version_id,
            MapPayloadVersionPii.sealed.has_key(ADDRESS_KEY),
        )
        .correlate(VaSubmissionPayloadVersion)
    )


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
                sa.or_(
                    _payload_text(DATE_KEY) != "", _payload_text(ADDRESS_KEY) != "", _sealed_address()
                ),
            )
        ),
    )


def visit_notes_for(va_sids, *, redact_pii: bool) -> dict:
    """``{va_sid: {"address", "date", "remarks"}}`` for those submissions that
    have a note, in one query that extracts only the three keys plus one batch
    read of the side rows. A *redact_pii* viewer's address and remarks are
    never opened (``visit_note_for_viewer`` withholds them), so a sealed
    address stays sealed for them. A note with a sealed address and no date
    is listed here but ``visit_note_for_viewer`` shows a redacting viewer
    nothing for it; real notes always carry a date."""
    sids = list(va_sids)
    if not sids:
        return {}
    rows = db.session.execute(
        sa.select(
            VaSubmissionPayloadVersion.va_sid,
            VaSubmissionPayloadVersion.payload_version_id,
            _payload_text(ADDRESS_KEY),
            _payload_text(DATE_KEY),
            _payload_text(REMARKS_KEY),
            _sealed_address(),
        ).where(
            VaSubmissionPayloadVersion.va_sid.in_(sids),
            VaSubmissionPayloadVersion.version_status == "active",
        )
    ).all()
    opened = {}
    if not redact_pii:
        from app.services.payload_pii_accessor import get_pii_many

        opened = get_pii_many(version_id for _, version_id, _, _, _, sealed in rows if sealed)
    notes = {}
    for sid, version_id, address, date, remarks, sealed in rows:
        pii = opened.get(version_id, {})
        address = address or str(pii.get(ADDRESS_KEY) or "")
        remarks = remarks or str(pii.get(REMARKS_KEY) or "")
        if address or date or sealed:
            notes[sid] = {"address": address, "date": date, "remarks": remarks}
    return notes


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
