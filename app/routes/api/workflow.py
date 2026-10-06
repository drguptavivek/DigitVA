"""Workflow event history JSON API."""

import base64
import binascii
import uuid
from datetime import datetime

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app import db
from app.models import VaSubmissionWorkflowEvent
from app.routes.api.request_helpers import BadQuery, MAX_PAGE_LIMIT, error as api_error
from app.services.authz import READ_EVENTS, Reason, can

bp = Blueprint("workflow", __name__)


def _encode_cursor(event) -> str:
    """Opaque keyset position: the event's own ``(created_at, id)`` sort key."""
    raw = f"{event.event_created_at.isoformat()}|{event.workflow_event_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    """Inverse of ``_encode_cursor``; ``BadQuery`` for anything else a client sends."""
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        created_at, event_id = raw.split("|")
        position = datetime.fromisoformat(created_at), uuid.UUID(event_id)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        raise BadQuery("cursor is not valid.") from None
    if position[0].tzinfo is None:
        raise BadQuery("cursor is not valid.")
    return position


def _events_page_args() -> tuple[int | None, tuple[datetime, uuid.UUID] | None]:
    """``limit`` (1..``MAX_PAGE_LIMIT``) and ``cursor``; ``cursor`` needs ``limit``."""
    raw_limit = request.args.get("limit")
    cursor = request.args.get("cursor")
    if raw_limit is None:
        if cursor is not None:
            raise BadQuery("cursor requires limit.")
        return None, None
    try:
        limit = int(raw_limit)
    except ValueError:
        raise BadQuery("limit must be a whole number.") from None
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        raise BadQuery(f"limit must be between 1 and {MAX_PAGE_LIMIT}.")
    return limit, _decode_cursor(cursor) if cursor else None


def _event_json(e) -> dict:
    return {
        "event_id": str(e.workflow_event_id),
        "transition_id": e.transition_id,
        "previous_state": e.previous_state,
        "current_state": e.current_state,
        "actor_kind": e.actor_kind,
        "actor_role": e.actor_role,
        "transition_reason": e.transition_reason,
        "event_created_at": e.event_created_at.isoformat(),
    }


@bp.get("/events/<va_sid>")
@login_required
def get_events(va_sid: str):
    """Return the workflow event history for a submission.

    Access is per submission, not per form: events are part of viewing the
    submission, so the answer is the page's ``VIEW`` scope
    (``authz.READ_EVENTS``, digitva-0wc F13), evaluated against the
    submission's current routing. authz also answers "not found".

    Without ``limit``: every event, oldest first, ``{va_sid, events}``.
    With ``limit`` (1..200): newest first, ``{va_sid, events, limit,
    next_cursor}``; pass ``next_cursor`` back as ``cursor`` for the next older
    page (``null`` on the last). The cursor is the last event's
    ``(event_created_at, event_id)``, so ties never gap or repeat. 400
    ``invalid_request`` for a bad ``limit``/``cursor``, ``cursor`` without
    ``limit`` included.
    """
    decision = can(current_user, READ_EVENTS, va_sid)
    if decision.reason is Reason.NOT_FOUND:
        return api_error("Submission not found.", status_code=404)
    if not decision:
        return api_error("Access denied.", status_code=403)

    try:
        limit, cursor = _events_page_args()
    except BadQuery as exc:
        return api_error(str(exc), "invalid_request", 400)

    query = sa.select(VaSubmissionWorkflowEvent).where(VaSubmissionWorkflowEvent.va_sid == va_sid)
    if limit is None:
        events = db.session.scalars(query.order_by(VaSubmissionWorkflowEvent.event_created_at)).all()
        return jsonify({"va_sid": va_sid, "events": [_event_json(e) for e in events]})

    if cursor:
        query = query.where(
            sa.tuple_(
                VaSubmissionWorkflowEvent.event_created_at,
                VaSubmissionWorkflowEvent.workflow_event_id,
            )
            < sa.tuple_(*cursor)
        )
    # limit + 1 answers "is there an older page" without a count.
    events = db.session.scalars(
        query.order_by(
            VaSubmissionWorkflowEvent.event_created_at.desc(),
            VaSubmissionWorkflowEvent.workflow_event_id.desc(),
        ).limit(limit + 1)
    ).all()
    page = events[:limit]
    return jsonify(
        {
            "va_sid": va_sid,
            "events": [_event_json(e) for e in page],
            "limit": limit,
            "next_cursor": _encode_cursor(page[-1]) if len(events) > limit else None,
        }
    )
