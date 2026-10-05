"""Workflow event history JSON API."""

import sqlalchemy as sa
from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from app import db
from app.models import VaSubmissionWorkflowEvent
from app.routes.api.request_helpers import error as api_error
from app.services.authz import READ_EVENTS, Reason, can

bp = Blueprint("workflow", __name__)


@bp.get("/events/<va_sid>")
@login_required
def get_events(va_sid: str):
    """Return the workflow event history for a submission.

    Access is per submission, not per form: events are part of viewing the
    submission, so the answer is the page's ``VIEW`` scope
    (``authz.READ_EVENTS``, digitva-0wc F13), evaluated against the
    submission's current routing. authz also answers "not found".
    """
    decision = can(current_user, READ_EVENTS, va_sid)
    if decision.reason is Reason.NOT_FOUND:
        return api_error("Submission not found.", status_code=404)
    if not decision:
        return api_error("Access denied.", status_code=403)

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

