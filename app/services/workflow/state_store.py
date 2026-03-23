"""Canonical submission workflow-state persistence helpers."""

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
)
from app.services.workflow.events import (
    DIRECT_STATE_SET_TRANSITION_ID,
    actor_kind_from_role,
    record_workflow_event,
)
from app.services.workflow.definition import (
    CODER_READY_POOL_STATES,
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_CONSENT_REFUSED,
    WORKFLOW_CLOSED,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
    WORKFLOW_PARTIAL_CODING_SAVED,
    WORKFLOW_READY_FOR_CODING,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_SCREENING_PENDING,
    WORKFLOW_SMARTVA_PENDING,
)

def get_submission_workflow_record(
    va_sid: str,
    *,
    for_update: bool = False,
) -> VaSubmissionWorkflow | None:
    """Return the canonical workflow row for a submission, optionally locked."""
    stmt = sa.select(VaSubmissionWorkflow).where(VaSubmissionWorkflow.va_sid == va_sid)
    if for_update:
        stmt = stmt.with_for_update()
    return db.session.scalar(stmt)


def set_submission_workflow_state(
    va_sid: str,
    workflow_state: str,
    *,
    reason: str | None = None,
    by_user_id: UUID | None = None,
    by_role: str | None = None,
    record: VaSubmissionWorkflow | None = None,
    emit_event: bool = True,
) -> VaSubmissionWorkflow:
    """Upsert the canonical workflow state for a submission."""
    if record is None:
        record = get_submission_workflow_record(va_sid, for_update=True)
    previous_state = record.workflow_state if record else None
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
        db.session.flush()
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

    if changed and emit_event:
        record_workflow_event(
            va_sid,
            transition_id=DIRECT_STATE_SET_TRANSITION_ID,
            previous_state=previous_state,
            current_state=workflow_state,
            actor_kind=actor_kind_from_role(by_role),
            actor_role=by_role or "vasystem",
            actor_user_id=by_user_id,
            reason=reason,
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
    record = get_submission_workflow_record(va_sid)
    return record.workflow_state if record else None
