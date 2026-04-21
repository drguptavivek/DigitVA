"""Workflow event history JSON API."""

import sqlalchemy as sa
from flask import Blueprint, g, jsonify

from app import db
from app.authz.access import action_authorized
from app.authz.resources import submission_from_kwarg
from app.models import VaSubmissionWorkflowEvent

bp = Blueprint("workflow", __name__)


@bp.get("/events/<va_sid>")
@action_authorized("workflow_events_view", resource_resolver=submission_from_kwarg("va_sid"))
def get_events(va_sid: str):
    """Return the workflow event history for a submission.

    Access is scoped: the caller must have at least form-level access
    (coder, reviewer, data manager, or admin role on the form).
    """
    submission = g.authz_resource.obj
    if not submission:
        return jsonify({"error": "Submission not found."}), 404

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
