"""Workflow event history JSON API."""

import sqlalchemy as sa
from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from app import db
from app.models import VaSubmissions, VaSubmissionWorkflowEvent
from app.services.authz import READ_EVENTS, can

bp = Blueprint("workflow", __name__)


@bp.get("/events/<va_sid>")
@login_required
def get_events(va_sid: str):
    """Return the workflow event history for a submission.

    Access is per submission, not per form: the same ``VIEW`` scope as the
    submission page, evaluated against the submission's current routing.
    """
    submission = db.session.get(VaSubmissions, va_sid)
    if not submission:
        return jsonify({"error": "Submission not found."}), 404

    if not _may_read_events(current_user, submission):
        return jsonify({"error": "Access denied."}), 403

    events = db.session.scalars(
        sa.select(VaSubmissionWorkflowEvent)
        .where(VaSubmissionWorkflowEvent.va_sid == va_sid)
        .order_by(VaSubmissionWorkflowEvent.event_created_at)
    ).all()

    return jsonify(
        {
            "va_sid": va_sid,
            "events": [
                {
                    "event_id": str(e.workflow_event_id),
                    "transition_id": e.transition_id,
                    "previous_state": e.previous_state,
                    "current_state": e.current_state,
                    "actor_kind": e.actor_kind,
                    "actor_role": e.actor_role,
                    "transition_reason": e.transition_reason,
                    "event_created_at": e.event_created_at.isoformat(),
                }
                for e in events
            ],
        }
    )


def _may_read_events(user, submission) -> bool:
    """Whether *user* may read this one submission's workflow history.

    Events are part of viewing the submission, so the answer is the page's:
    the ``VIEW`` scope (``authz.READ_EVENTS``, digitva-0wc F13).
    """
    return can(user, READ_EVENTS, submission.va_sid)
