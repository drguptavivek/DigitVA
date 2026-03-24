"""Reviewer secondary-coding workflow service."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa

from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaFinalAssessments,
    VaReviewerFinalAssessments,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
)
from app.services.final_cod_authority_service import upsert_reviewer_final_cod_authority
from app.services.reviewer_final_assessment_service import (
    create_reviewer_final_assessment,
    get_latest_active_reviewer_final_assessment,
)
from app.services.workflow.definition import (
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_ELIGIBLE,
)
from app.services.workflow.state_store import get_submission_workflow_state
from app.services.workflow.transitions import (
    mark_reviewer_coding_started,
    mark_reviewer_finalized,
    reviewer_actor,
    system_actor,
)


@dataclass(frozen=True)
class ReviewerCodingResult:
    va_sid: str
    actiontype: str


class ReviewerCodingError(Exception):
    """Raised when reviewer coding cannot proceed."""

    def __init__(self, message: str, status_code: int = 403):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def get_active_reviewing_allocation(user_id) -> str | None:
    return db.session.scalar(
        sa.select(VaAllocations.va_sid).where(
            VaAllocations.va_allocated_to == user_id,
            VaAllocations.va_allocation_for == VaAllocation.reviewing,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    )


def start_reviewer_coding(user, va_sid: str) -> ReviewerCodingResult:
    from app.services.coding_allocation_service import release_stale_reviewer_allocations

    release_stale_reviewer_allocations(timeout_hours=1)

    submission = db.session.get(VaSubmissions, va_sid)
    if not submission:
        raise ReviewerCodingError("Submission not found.", 404)
    if not user.has_va_form_access(submission.va_form_id, "reviewer"):
        raise ReviewerCodingError("Reviewer access is required.", 403)
    if submission.va_narration_language not in user.vacode_language:
        raise ReviewerCodingError(
            f"Your profile does not support reviewing forms in {submission.va_narration_language}.",
            403,
        )
    current_state = get_submission_workflow_state(va_sid)
    if current_state != WORKFLOW_REVIEWER_ELIGIBLE:
        raise ReviewerCodingError(
            "Only reviewer-eligible submissions can start reviewer coding."
        )
    if get_latest_active_reviewer_final_assessment(va_sid):
        raise ReviewerCodingError(
            "A reviewer final COD already exists for this submission."
        )

    active_sid = get_active_reviewing_allocation(user.user_id)
    if active_sid:
        if active_sid != va_sid:
            raise ReviewerCodingError(
                "You already have an active reviewer allocation.", 409
            )
        return ReviewerCodingResult(va_sid=va_sid, actiontype="varesumereviewing")

    allocation_id = uuid.uuid4()
    db.session.add(
        VaAllocations(
            va_allocation_id=allocation_id,
            va_sid=va_sid,
            va_allocated_to=user.user_id,
            va_allocation_for=VaAllocation.reviewing,
        )
    )
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="reviewer",
            va_audit_by=user.user_id,
            va_audit_operation="c",
            va_audit_action="form allocated to reviewer for coding",
            va_audit_entityid=allocation_id,
        )
    )
    mark_reviewer_coding_started(
        va_sid,
        reason="reviewer_allocation_created",
        actor=reviewer_actor(user.user_id),
    )
    db.session.commit()
    return ReviewerCodingResult(va_sid=va_sid, actiontype="vastartreviewing")


def submit_reviewer_final_cod(
    user,
    va_sid: str,
    *,
    conclusive_cod: str,
    remark: str | None = None,
) -> VaReviewerFinalAssessments:
    submission = db.session.get(VaSubmissions, va_sid)
    if not submission:
        raise ReviewerCodingError("Submission not found.", 404)
    if not user.has_va_form_access(submission.va_form_id, "reviewer"):
        raise ReviewerCodingError("Reviewer access is required.", 403)
    current_state = get_submission_workflow_state(va_sid)
    if current_state != WORKFLOW_REVIEWER_CODING_IN_PROGRESS:
        raise ReviewerCodingError(
            "Reviewer final COD can only be submitted from reviewer_coding_in_progress."
        )

    active_allocation = db.session.scalar(
        sa.select(VaAllocations).where(
            VaAllocations.va_sid == va_sid,
            VaAllocations.va_allocated_to == user.user_id,
            VaAllocations.va_allocation_for == VaAllocation.reviewing,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    )
    if not active_allocation:
        raise ReviewerCodingError(
            "An active reviewer allocation is required to submit reviewer final COD."
        )

    active_payload_version_id = submission.active_payload_version_id
    prior_active_reviewer_finals = db.session.scalars(
        sa.select(VaReviewerFinalAssessments).where(
            VaReviewerFinalAssessments.va_sid == va_sid,
            VaReviewerFinalAssessments.payload_version_id == active_payload_version_id,
            VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
        )
    ).all()
    for existing in prior_active_reviewer_finals:
        existing.va_rfinassess_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_byrole="reviewer",
                va_audit_by=user.user_id,
                va_audit_operation="d",
                va_audit_action="deactivated superseded reviewer final cod",
                va_audit_entityid=existing.va_rfinassess_id,
            )
        )

    supersedes_coder_final = db.session.scalar(
        sa.select(VaFinalAssessments)
        .where(
            VaFinalAssessments.va_sid == va_sid,
            VaFinalAssessments.payload_version_id == active_payload_version_id,
            VaFinalAssessments.va_finassess_status == VaStatuses.active,
        )
        .order_by(VaFinalAssessments.va_finassess_createdat.desc())
    )
    reviewer_final = create_reviewer_final_assessment(
        va_sid=va_sid,
        reviewer_user_id=user.user_id,
        conclusive_cod=conclusive_cod,
        remark=remark,
        supersedes_coder_final_assessment=supersedes_coder_final,
    )
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="reviewer",
            va_audit_by=user.user_id,
            va_audit_operation="c",
            va_audit_action="reviewer final cod submitted",
            va_audit_entityid=reviewer_final.va_rfinassess_id,
        )
    )

    active_allocation.va_allocation_status = VaStatuses.deactive
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="reviewer",
            va_audit_by=user.user_id,
            va_audit_operation="d",
            va_audit_action="allocated form released from reviewer",
            va_audit_entityid=active_allocation.va_allocation_id,
        )
    )
    mark_reviewer_finalized(
        va_sid,
        reason="reviewer_final_cod_submitted",
        actor=reviewer_actor(user.user_id),
    )
    upsert_reviewer_final_cod_authority(
        va_sid,
        reviewer_final,
        reason="reviewer_final_cod_submitted",
        updated_by=user.user_id,
    )
    db.session.commit()
    return reviewer_final
