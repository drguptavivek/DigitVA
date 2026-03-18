"""Canonical submission workflow-state helpers."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

import sqlalchemy as sa

from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaCoderReview,
    VaDataManagerReview,
    VaFinalAssessments,
    VaInitialAssessments,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissionsAuditlog,
)


WORKFLOW_SCREENING_PENDING = "screening_pending"
WORKFLOW_READY_FOR_CODING = "ready_for_coding"
WORKFLOW_CODING_IN_PROGRESS = "coding_in_progress"
WORKFLOW_PARTIAL_CODING_SAVED = "partial_coding_saved"
WORKFLOW_CODER_STEP1_SAVED = "coder_step1_saved"
WORKFLOW_CODER_FINALIZED = "coder_finalized"
WORKFLOW_NOT_CODEABLE_BY_CODER = "not_codeable_by_coder"
WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER = "not_codeable_by_data_manager"
WORKFLOW_CLOSED = "closed"
WORKFLOW_REVOKED_VA_DATA_CHANGED = "revoked_va_data_changed"
CODER_READY_POOL_STATES = (WORKFLOW_READY_FOR_CODING,)


def set_submission_workflow_state(
    va_sid: str,
    workflow_state: str,
    *,
    reason: str | None = None,
    by_user_id: UUID | None = None,
    by_role: str | None = None,
) -> VaSubmissionWorkflow:
    """Upsert the canonical workflow state for a submission."""
    record = db.session.scalar(
        sa.select(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid == va_sid)
    )
    changed = False
    if not record:
        record = VaSubmissionWorkflow(
            va_sid=va_sid,
            workflow_state=workflow_state,
            workflow_reason=reason,
            workflow_updated_by=by_user_id,
            workflow_updated_by_role=by_role,
        )
        db.session.add(record)
        changed = True
    else:
        if record.workflow_state != workflow_state:
            record.workflow_state = workflow_state
            changed = True
        if record.workflow_reason != reason:
            record.workflow_reason = reason
            changed = True
        if record.workflow_updated_by != by_user_id:
            record.workflow_updated_by = by_user_id
            changed = True
        if record.workflow_updated_by_role != by_role:
            record.workflow_updated_by_role = by_role
            changed = True

    if changed:
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_byrole=by_role or "vasystem",
                va_audit_by=by_user_id,
                va_audit_operation="u",
                va_audit_action=f"workflow state set to {workflow_state}",
                va_audit_entityid=record.workflow_id if record else None,
            )
        )
    return record


def infer_workflow_state_from_legacy_records(va_sid: str) -> str:
    """Infer a canonical workflow state from legacy active workflow records."""
    if db.session.scalar(
        sa.select(VaDataManagerReview.va_dmreview_id).where(
            VaDataManagerReview.va_sid == va_sid,
            VaDataManagerReview.va_dmreview_status == VaStatuses.active,
        )
    ):
        return WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER

    if db.session.scalar(
        sa.select(VaFinalAssessments.va_finassess_id).where(
            VaFinalAssessments.va_sid == va_sid,
            VaFinalAssessments.va_finassess_status == VaStatuses.active,
        )
    ):
        return WORKFLOW_CODER_FINALIZED

    if db.session.scalar(
        sa.select(VaCoderReview.va_creview_id).where(
            VaCoderReview.va_sid == va_sid,
            VaCoderReview.va_creview_status == VaStatuses.active,
        )
    ):
        return WORKFLOW_NOT_CODEABLE_BY_CODER

    if db.session.scalar(
        sa.select(VaInitialAssessments.va_iniassess_id).where(
            VaInitialAssessments.va_sid == va_sid,
            VaInitialAssessments.va_iniassess_status == VaStatuses.active,
        )
    ):
        return WORKFLOW_CODER_STEP1_SAVED

    if db.session.scalar(
        sa.select(VaAllocations.va_allocation_id).where(
            VaAllocations.va_sid == va_sid,
            VaAllocations.va_allocation_for == VaAllocation.coding,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    ):
        return WORKFLOW_CODING_IN_PROGRESS

    return WORKFLOW_READY_FOR_CODING


def infer_workflow_state_after_coding_release(va_sid: str) -> str:
    """Infer post-release state without considering active coding allocations."""
    if db.session.scalar(
        sa.select(VaDataManagerReview.va_dmreview_id).where(
            VaDataManagerReview.va_sid == va_sid,
            VaDataManagerReview.va_dmreview_status == VaStatuses.active,
        )
    ):
        return WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER

    if db.session.scalar(
        sa.select(VaFinalAssessments.va_finassess_id).where(
            VaFinalAssessments.va_sid == va_sid,
            VaFinalAssessments.va_finassess_status == VaStatuses.active,
        )
    ):
        return WORKFLOW_CODER_FINALIZED

    if db.session.scalar(
        sa.select(VaCoderReview.va_creview_id).where(
            VaCoderReview.va_sid == va_sid,
            VaCoderReview.va_creview_status == VaStatuses.active,
        )
    ):
        return WORKFLOW_NOT_CODEABLE_BY_CODER

    if db.session.scalar(
        sa.select(VaInitialAssessments.va_iniassess_id).where(
            VaInitialAssessments.va_sid == va_sid,
            VaInitialAssessments.va_iniassess_status == VaStatuses.active,
        )
    ):
        return WORKFLOW_CODER_STEP1_SAVED

    return WORKFLOW_READY_FOR_CODING


def sync_submission_workflow_from_legacy_records(
    va_sid: str,
    *,
    reason: Optional[str] = None,
    by_user_id: UUID | None = None,
    by_role: str | None = "vasystem",
) -> VaSubmissionWorkflow:
    """Refresh canonical workflow state using current legacy record state."""
    return set_submission_workflow_state(
        va_sid,
        infer_workflow_state_from_legacy_records(va_sid),
        reason=reason,
        by_user_id=by_user_id,
        by_role=by_role,
    )


def get_submission_workflow_state(va_sid: str) -> str | None:
    """Return the current canonical workflow state for a submission, or None."""
    record = db.session.scalar(
        sa.select(VaSubmissionWorkflow.workflow_state).where(
            VaSubmissionWorkflow.va_sid == va_sid
        )
    )
    return record
