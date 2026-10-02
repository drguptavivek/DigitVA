"""Workflow event history JSON API."""

import sqlalchemy as sa
from flask import Blueprint, jsonify
from flask_login import current_user, login_required

from app import db
from app.models import VaAccessRoles, VaForms, VaSubmissions, VaSubmissionWorkflowEvent
from app.services.org_grant_service import (
    submission_within_org_scope,
    submission_within_org_view_scope,
)

bp = Blueprint("workflow", __name__)


@bp.get("/events/<va_sid>")
@login_required
def get_events(va_sid: str):
    """Return the workflow event history for a submission.

    Access is per submission, not per form: a form spans several units, so a
    unit-scoped grant reaches only the submissions routed into its subtree.
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

    Each role answers as its own submission surface does: a data manager by
    the submission's routed unit, a coder by the read-only view scope, a
    reviewer by the reviewing scope. A project or project_site coder/reviewer
    grant covers its whole site and is not narrowed. site_pi is never held at
    a unit, and the legacy permission dict has no unit grain; both keep the
    form-level answer.
    """
    form_id = submission.va_form_id
    form = db.session.execute(
        sa.select(VaForms.project_id, VaForms.site_id).where(VaForms.form_id == form_id)
    ).first()
    if form is None:
        return False
    if user.has_data_manager_submission_access(
        form.project_id, form.site_id, submission.org_unit_id
    ):
        return True
    for role, within_scope in (
        (VaAccessRoles.coder, submission_within_org_view_scope),
        (VaAccessRoles.reviewer, submission_within_org_scope),
    ):
        if user.has_va_form_access(form_id, role.value) and (
            form.project_id in user._get_granted_project_ids(role.value)
            or (form.project_id, form.site_id)
            in user._get_granted_project_site_pairs(role.value)
            or within_scope(user, submission.va_sid, role)
        ):
            return True
    if user.is_site_pi(form_id):
        return True
    return any(
        form_id in forms
        for legacy_role, forms in (user.permission or {}).items()
        if legacy_role not in {"coder", "reviewer", "sitepi"}
    )

