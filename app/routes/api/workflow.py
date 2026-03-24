"""Workflow event history JSON API."""

import sqlalchemy as sa
from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from app import db
from app.models import VaSubmissions, VaSubmissionWorkflowEvent

bp = Blueprint("workflow", __name__)


@bp.get("/events/<va_sid>")
@login_required
def get_events(va_sid: str):
    """Return the workflow event history for a submission.

    Access is scoped: the caller must have at least form-level access
    (coder, reviewer, data manager, or admin role on the form).
    """
    submission = db.session.get(VaSubmissions, va_sid)
    if not submission:
        return jsonify({"error": "Submission not found."}), 404

    if not current_user.has_va_form_access(submission.va_form_id):
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
