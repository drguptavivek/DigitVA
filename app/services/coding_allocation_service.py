"""Helpers for coding allocation lifecycle."""

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app import db
from app.models import VaAllocations, VaAllocation, VaStatuses, VaSubmissionsAuditlog
from app.services.submission_workflow_service import (
    infer_workflow_state_after_coding_release,
    set_submission_workflow_state,
)


def release_stale_coding_allocations(timeout_hours: int = 1) -> int:
    """Release stale active coding allocations without discarding coding work."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=timeout_hours)
    stale_allocations = db.session.scalars(
        sa.select(VaAllocations).where(
            VaAllocations.va_allocation_status == VaStatuses.active,
            VaAllocations.va_allocation_for == VaAllocation.coding,
            VaAllocations.va_allocation_createdat < cutoff,
        )
    ).all()

    released = 0
    for record in stale_allocations:
        record.va_allocation_status = VaStatuses.deactive
        set_submission_workflow_state(
            record.va_sid,
            infer_workflow_state_after_coding_release(record.va_sid),
            reason="allocation_timeout_release",
            by_role="vasystem",
        )
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=record.va_sid,
                va_audit_entityid=record.va_allocation_id,
                va_audit_byrole="vasystem",
                va_audit_operation="d",
                va_audit_action="va_allocation_released_due_to_timeout",
            )
        )
        released += 1

    if released:
        db.session.commit()

    return released
