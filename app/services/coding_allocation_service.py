"""Helpers for coding allocation lifecycle."""

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaInitialAssessments,
    VaNarrativeAssessment,
    VaSocialAutopsyAnalysis,
    VaStatuses,
    VaSubmissionsAuditlog,
)
from app.services.final_cod_authority_service import (
    abandon_active_recode_episode,
    get_active_recode_episode,
)
from app.services.submission_workflow_service import (
    infer_workflow_state_after_coding_release,
    set_submission_workflow_state,
)


def _deactivate_stale_initial_assessments(record: VaAllocations) -> None:
    """Deactivate unfinished Step 1 COD drafts for a stale coding allocation."""
    initial_rows = db.session.scalars(
        sa.select(VaInitialAssessments).where(
            VaInitialAssessments.va_sid == record.va_sid,
            VaInitialAssessments.va_iniassess_by == record.va_allocated_to,
            VaInitialAssessments.va_iniassess_status == VaStatuses.active,
        )
    ).all()
    for initial_row in initial_rows:
        initial_row.va_iniassess_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=record.va_sid,
                va_audit_entityid=initial_row.va_iniassess_id,
                va_audit_byrole="vasystem",
                va_audit_operation="u",
                va_audit_action="initial cod draft reverted due to timeout",
            )
        )


def _deactivate_first_pass_analysis_artifacts(record: VaAllocations) -> None:
    """Deactivate first-pass analysis artifacts that must not survive timeout reversion."""
    narrative_assessment = db.session.scalar(
        sa.select(VaNarrativeAssessment).where(
            VaNarrativeAssessment.va_sid == record.va_sid,
            VaNarrativeAssessment.va_nqa_by == record.va_allocated_to,
            VaNarrativeAssessment.va_nqa_status == VaStatuses.active,
        )
    )
    if narrative_assessment:
        narrative_assessment.va_nqa_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=record.va_sid,
                va_audit_entityid=narrative_assessment.va_nqa_id,
                va_audit_byrole="vasystem",
                va_audit_operation="u",
                va_audit_action="narrative quality assessment reverted due to timeout",
            )
        )

    social_analysis = db.session.scalar(
        sa.select(VaSocialAutopsyAnalysis).where(
            VaSocialAutopsyAnalysis.va_sid == record.va_sid,
            VaSocialAutopsyAnalysis.va_saa_by == record.va_allocated_to,
            VaSocialAutopsyAnalysis.va_saa_status == VaStatuses.active,
        )
    )
    if social_analysis:
        social_analysis.va_saa_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=record.va_sid,
                va_audit_entityid=social_analysis.va_saa_id,
                va_audit_byrole="vasystem",
                va_audit_operation="u",
                va_audit_action="social autopsy analysis reverted due to timeout",
            )
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
        recode_episode = get_active_recode_episode(record.va_sid)
        record.va_allocation_status = VaStatuses.deactive
        _deactivate_stale_initial_assessments(record)
        if recode_episode is None:
            _deactivate_first_pass_analysis_artifacts(record)
        else:
            abandon_active_recode_episode(
                record.va_sid,
                by_role="vasystem",
                audit_action="recode episode abandoned due to timeout",
            )
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
