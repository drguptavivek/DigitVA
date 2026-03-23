"""Structured workflow event logging."""

from __future__ import annotations

from uuid import UUID

from app import db
from app.models import VaSubmissionWorkflowEvent


DIRECT_STATE_SET_TRANSITION_ID = "state_set_direct"


def record_workflow_event(
    va_sid: str,
    *,
    transition_id: str,
    previous_state: str | None,
    current_state: str,
    actor_kind: str | None,
    actor_role: str | None,
    actor_user_id: UUID | None,
    reason: str | None,
) -> VaSubmissionWorkflowEvent:
    """Persist one canonical workflow event row."""
    event = VaSubmissionWorkflowEvent(
        va_sid=va_sid,
        transition_id=transition_id,
        previous_state=previous_state,
        current_state=current_state,
        actor_kind=actor_kind,
        actor_role=actor_role,
        actor_user_id=actor_user_id,
        transition_reason=reason,
    )
    db.session.add(event)
    return event


def actor_kind_from_role(actor_role: str | None) -> str | None:
    """Normalize legacy audit role names to workflow actor kinds."""
    if actor_role == "vasystem":
        return "system"
    if actor_role == "vaadmin":
        return "admin"
    if actor_role == "vacoder":
        return "coder"
    if actor_role == "data_manager":
        return "data_manager"
    return None
