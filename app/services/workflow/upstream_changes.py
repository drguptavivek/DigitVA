"""Helpers for preserving and resolving protected upstream ODK changes."""

from __future__ import annotations

from datetime import datetime, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    VaFinalAssessments,
    VaFinalCodAuthority,
    VaReviewerFinalAssessments,
    VaSubmissionNotification,
    VaSubmissionUpstreamChange,
    VaStatuses,
)


UPSTREAM_CHANGE_STATUS_PENDING = "pending"
UPSTREAM_CHANGE_STATUS_ACCEPTED = "accepted"
UPSTREAM_CHANGE_STATUS_REJECTED = "rejected"
UPSTREAM_CHANGE_STATUS_KEPT_CURRENT_ICD = "kept_current_icd"
UPSTREAM_CHANGE_NOTIFICATION_TYPE = "protected_upstream_odk_change"
UPSTREAM_CHANGE_NOTIFICATION_PENDING = "pending"
UPSTREAM_CHANGE_NOTIFICATION_RESOLVED = "resolved"


def get_latest_pending_upstream_change(va_sid: str) -> VaSubmissionUpstreamChange | None:
    """Return the latest unresolved upstream-change record for a submission."""
    return db.session.scalar(
        sa.select(VaSubmissionUpstreamChange)
        .where(
            VaSubmissionUpstreamChange.va_sid == va_sid,
            VaSubmissionUpstreamChange.resolution_status == UPSTREAM_CHANGE_STATUS_PENDING,
        )
        .order_by(VaSubmissionUpstreamChange.created_at.desc())
    )


def record_protected_upstream_change(
    existing_submission,
    incoming_va_data: dict,
    *,
    workflow_state_before: str,
    detected_odk_updatedat=None,
    previous_payload_version_id=None,
    incoming_payload_version_id=None,
):
    """Create or update the durable record for a protected upstream ODK change."""
    authoritative_final_id = _get_coder_final_assessment_id(existing_submission.va_sid)
    authoritative_reviewer_final_id = _get_reviewer_final_assessment_id(existing_submission.va_sid)
    pending = get_latest_pending_upstream_change(existing_submission.va_sid)

    if pending is None:
        pending = VaSubmissionUpstreamChange(
            va_sid=existing_submission.va_sid,
            workflow_state_before=workflow_state_before,
            previous_final_assessment_id=authoritative_final_id,
            previous_reviewer_final_assessment_id=authoritative_reviewer_final_id,
            previous_payload_version_id=previous_payload_version_id,
            incoming_payload_version_id=incoming_payload_version_id,
            previous_va_data=existing_submission.va_data,
            incoming_va_data=incoming_va_data,
            detected_odk_updatedat=detected_odk_updatedat,
            resolution_status=UPSTREAM_CHANGE_STATUS_PENDING,
        )
        db.session.add(pending)
        db.session.flush()
    else:
        pending.workflow_state_before = workflow_state_before
        if pending.previous_final_assessment_id is None and authoritative_final_id is not None:
            pending.previous_final_assessment_id = authoritative_final_id
        if pending.previous_reviewer_final_assessment_id is None and authoritative_reviewer_final_id is not None:
            pending.previous_reviewer_final_assessment_id = authoritative_reviewer_final_id
        if previous_payload_version_id is not None:
            pending.previous_payload_version_id = previous_payload_version_id
        if incoming_payload_version_id is not None:
            pending.incoming_payload_version_id = incoming_payload_version_id
        pending.incoming_va_data = incoming_va_data
        pending.detected_odk_updatedat = detected_odk_updatedat

    _ensure_notifications(pending)
    return pending


def resolve_pending_upstream_change(
    va_sid: str,
    *,
    resolution_status: str,
    resolved_by=None,
    resolved_by_role: str | None = None,
):
    """Resolve the current pending upstream-change record and its notifications."""
    pending = get_latest_pending_upstream_change(va_sid)
    if pending is None:
        return None

    now = datetime.now(timezone.utc)
    pending.resolution_status = resolution_status
    pending.resolved_at = now
    pending.resolved_by = resolved_by
    pending.resolved_by_role = resolved_by_role

    notifications = db.session.scalars(
        sa.select(VaSubmissionNotification).where(
            VaSubmissionNotification.upstream_change_id == pending.upstream_change_id,
            VaSubmissionNotification.notification_status == UPSTREAM_CHANGE_NOTIFICATION_PENDING,
        )
    ).all()
    for notification in notifications:
        notification.notification_status = UPSTREAM_CHANGE_NOTIFICATION_RESOLVED
        notification.resolved_at = now

    return pending


def _ensure_notifications(upstream_change: VaSubmissionUpstreamChange) -> None:
    """Ensure pending notification rows exist for vaadmin and data_manager roles."""
    message = (
        "Protected submission ODK data changed after finalization and requires "
        "manual resolution."
    )
    for audience_role in ("vaadmin", "data_manager"):
        existing = db.session.scalar(
            sa.select(VaSubmissionNotification).where(
                VaSubmissionNotification.upstream_change_id == upstream_change.upstream_change_id,
                VaSubmissionNotification.audience_role == audience_role,
                VaSubmissionNotification.notification_type == UPSTREAM_CHANGE_NOTIFICATION_TYPE,
                VaSubmissionNotification.notification_status == UPSTREAM_CHANGE_NOTIFICATION_PENDING,
            )
        )
        if existing is not None:
            continue

        db.session.add(
            VaSubmissionNotification(
                va_sid=upstream_change.va_sid,
                upstream_change_id=upstream_change.upstream_change_id,
                audience_role=audience_role,
                notification_type=UPSTREAM_CHANGE_NOTIFICATION_TYPE,
                notification_status=UPSTREAM_CHANGE_NOTIFICATION_PENDING,
                title="Finalized - ODK Data Changed",
                message=message,
            )
        )


def _get_coder_final_assessment_id(va_sid: str):
    """Return the authoritative coder final assessment id for snapshotting."""
    authority_id = db.session.scalar(
        sa.select(VaFinalCodAuthority.authoritative_final_assessment_id).where(
            VaFinalCodAuthority.va_sid == va_sid
        )
    )
    if authority_id:
        return authority_id

    return db.session.scalar(
        sa.select(VaFinalAssessments.va_finassess_id)
        .where(
            VaFinalAssessments.va_sid == va_sid,
            VaFinalAssessments.va_finassess_status == VaStatuses.active,
        )
        .order_by(VaFinalAssessments.va_finassess_createdat.desc())
    )


def _get_reviewer_final_assessment_id(va_sid: str):
    """Return the authoritative reviewer final assessment id for snapshotting, if any."""
    authority_id = db.session.scalar(
        sa.select(VaFinalCodAuthority.authoritative_reviewer_final_assessment_id).where(
            VaFinalCodAuthority.va_sid == va_sid
        )
    )
    if authority_id:
        return authority_id

    return db.session.scalar(
        sa.select(VaReviewerFinalAssessments.va_rfinassess_id)
        .where(
            VaReviewerFinalAssessments.va_sid == va_sid,
            VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
        )
        .order_by(VaReviewerFinalAssessments.va_rfinassess_createdat.desc())
    )
