from __future__ import annotations

import sqlalchemy as sa

from app.authz.access import ResourceContext
from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaReviewerFinalAssessments,
    VaStatuses,
    VaSubmissionPayloadVersion,
)
from app.services.workflow.definition import (
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_SCREENING_PENDING,
)
from app.services.workflow.state_store import get_submission_workflow_state


def _submission_workflow_state(resource: ResourceContext | None) -> str | None:
    submission = resource.obj if resource else None
    if submission is None:
        return None
    return get_submission_workflow_state(submission.va_sid)


def _has_pending_upstream_payload(va_sid: str) -> bool:
    return bool(
        db.session.scalar(
            sa.select(VaSubmissionPayloadVersion.payload_version_id).where(
                VaSubmissionPayloadVersion.va_sid == va_sid,
                VaSubmissionPayloadVersion.version_status == "pending_upstream",
            )
        )
    )


def can_accept_upstream_change(_user, resource: ResourceContext | None) -> bool:
    if not resource or not resource.obj:
        return False
    return (
        _submission_workflow_state(resource) == WORKFLOW_FINALIZED_UPSTREAM_CHANGED
        and _has_pending_upstream_payload(resource.obj.va_sid)
    )


def can_keep_current_icd_on_upstream_change(_user, resource: ResourceContext | None) -> bool:
    return can_accept_upstream_change(_user, resource)


def can_screening_pass(_user, resource: ResourceContext | None) -> bool:
    if not resource or not resource.obj:
        return False
    return _submission_workflow_state(resource) == WORKFLOW_SCREENING_PENDING


def can_screening_reject(_user, resource: ResourceContext | None) -> bool:
    return can_screening_pass(_user, resource)


def can_resume_reviewing(user, _resource: ResourceContext | None) -> bool:
    return bool(
        db.session.scalar(
            sa.select(VaAllocations.va_sid).where(
                VaAllocations.va_allocated_to == user.user_id,
                VaAllocations.va_allocation_for == VaAllocation.reviewing,
                VaAllocations.va_allocation_status == VaStatuses.active,
            )
        )
    )


def can_view_reviewed_submission(user, resource: ResourceContext | None) -> bool:
    if not resource or not resource.obj:
        return False
    return bool(
        db.session.scalar(
            sa.select(VaReviewerFinalAssessments.va_sid).where(
                VaReviewerFinalAssessments.va_sid == resource.obj.va_sid,
                VaReviewerFinalAssessments.va_rfinassess_by == user.user_id,
                VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
            )
        )
    )


def register_predicates():
    return {
        "can_accept_upstream_change": can_accept_upstream_change,
        "can_keep_current_icd_on_upstream_change": can_keep_current_icd_on_upstream_change,
        "can_screening_pass": can_screening_pass,
        "can_screening_reject": can_screening_reject,
        "can_resume_reviewing": can_resume_reviewing,
        "can_view_reviewed_submission": can_view_reviewed_submission,
    }
