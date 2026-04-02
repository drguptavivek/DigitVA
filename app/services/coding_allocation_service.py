"""Helpers for coding allocation lifecycle."""

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from app import db
from app.models import (
    VaAllocation,
    VaAllocations,
    VaFinalAssessments,
    VaInitialAssessments,
    VaNarrativeAssessment,
    VaReviewerReview,
    VaSocialAutopsyAnalysis,
    VaStatuses,
    VaSubmissionsAuditlog,
)
from app.services.final_cod_authority_service import (
    abandon_active_recode_episode,
    get_active_recode_episode,
    upsert_final_cod_authority,
)
from app.services.demo_project_service import (
    get_demo_coding_allocation_timeout_minutes,
    should_use_demo_actiontype_for_submission,
)
from app.services.workflow.transitions import (
    reset_demo_state,
    reset_incomplete_first_pass,
    reset_incomplete_recode,
    reset_incomplete_reviewer_session,
    system_actor,
)


def _naive_utc_now() -> datetime:
    """Return current UTC as a naive datetime to match legacy DB columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
    now = _naive_utc_now()
    stale_allocations = db.session.scalars(
        sa.select(VaAllocations).where(
            VaAllocations.va_allocation_status == VaStatuses.active,
            VaAllocations.va_allocation_for == VaAllocation.coding,
        )
    ).all()

    released = 0
    for record in stale_allocations:
        if should_use_demo_actiontype_for_submission(record.va_sid):
            cutoff = now - timedelta(
                minutes=get_demo_coding_allocation_timeout_minutes(record.va_sid)
            )
        else:
            cutoff = now - timedelta(hours=timeout_hours)
        if record.va_allocation_createdat >= cutoff:
            continue

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
        if recode_episode is None:
            reset_incomplete_first_pass(
                record.va_sid,
                reason="allocation_timeout_release",
                actor=system_actor(),
            )
        else:
            reset_incomplete_recode(
                record.va_sid,
                reason="allocation_timeout_release",
                actor=system_actor(),
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

    cleanup_expired_demo_coding_artifacts(now=now)
    return released


def _deactivate_reviewer_session_artifacts(record: VaAllocations) -> None:
    """Deactivate all intermediate reviewer session artifacts for a timed-out allocation.

    Reviewer sessions follow first-pass coder behaviour: the reviewer final COD
    is the only terminal action. If the session times out before that, all
    intermediate work disappears — VaReviewerReview (reviewer NQA),
    VaNarrativeAssessment, and VaSocialAutopsyAnalysis filled by this reviewer.
    """
    for rr in db.session.scalars(
        sa.select(VaReviewerReview).where(
            VaReviewerReview.va_sid == record.va_sid,
            VaReviewerReview.va_rreview_by == record.va_allocated_to,
            VaReviewerReview.va_rreview_status == VaStatuses.active,
        )
    ).all():
        rr.va_rreview_status = VaStatuses.deactive
        db.session.add(VaSubmissionsAuditlog(
            va_sid=record.va_sid,
            va_audit_entityid=rr.va_rreview_id,
            va_audit_byrole="vasystem",
            va_audit_operation="u",
            va_audit_action="reviewer nqa reverted due to timeout",
        ))

    for nqa in db.session.scalars(
        sa.select(VaNarrativeAssessment).where(
            VaNarrativeAssessment.va_sid == record.va_sid,
            VaNarrativeAssessment.va_nqa_by == record.va_allocated_to,
            VaNarrativeAssessment.va_nqa_status == VaStatuses.active,
        )
    ).all():
        nqa.va_nqa_status = VaStatuses.deactive
        db.session.add(VaSubmissionsAuditlog(
            va_sid=record.va_sid,
            va_audit_entityid=nqa.va_nqa_id,
            va_audit_byrole="vasystem",
            va_audit_operation="u",
            va_audit_action="narrative quality assessment reverted due to reviewer timeout",
        ))

    for saa in db.session.scalars(
        sa.select(VaSocialAutopsyAnalysis).where(
            VaSocialAutopsyAnalysis.va_sid == record.va_sid,
            VaSocialAutopsyAnalysis.va_saa_by == record.va_allocated_to,
            VaSocialAutopsyAnalysis.va_saa_status == VaStatuses.active,
        )
    ).all():
        saa.va_saa_status = VaStatuses.deactive
        db.session.add(VaSubmissionsAuditlog(
            va_sid=record.va_sid,
            va_audit_entityid=saa.va_saa_id,
            va_audit_byrole="vasystem",
            va_audit_operation="u",
            va_audit_action="social autopsy analysis reverted due to reviewer timeout",
        ))


def release_stale_reviewer_allocations(timeout_hours: int = 1) -> int:
    """Release stale active reviewer allocations and revert incomplete sessions.

    Reviewer sessions behave like first-pass coder sessions: the final COD
    submission is the only completion action. A timed-out reviewer session
    deactivates all intermediate artifacts and returns the submission to
    reviewer_eligible so a reviewer may start a fresh session.
    """
    cutoff = _naive_utc_now() - timedelta(hours=timeout_hours)
    stale_allocations = db.session.scalars(
        sa.select(VaAllocations).where(
            VaAllocations.va_allocation_status == VaStatuses.active,
            VaAllocations.va_allocation_for == VaAllocation.reviewing,
            VaAllocations.va_allocation_createdat < cutoff,
        )
    ).all()

    released = 0
    for record in stale_allocations:
        record.va_allocation_status = VaStatuses.deactive
        _deactivate_reviewer_session_artifacts(record)
        reset_incomplete_reviewer_session(
            record.va_sid,
            reason="reviewer_allocation_timeout_release",
            actor=system_actor(),
        )
        db.session.add(VaSubmissionsAuditlog(
            va_sid=record.va_sid,
            va_audit_entityid=record.va_allocation_id,
            va_audit_byrole="vasystem",
            va_audit_operation="d",
            va_audit_action="reviewer_allocation_released_due_to_timeout",
        ))
        released += 1

    if released:
        db.session.commit()

    return released


def cleanup_expired_demo_coding_artifacts(
    *,
    now: datetime | None = None,
) -> int:
    """Deactivate demo-coded artifacts whose retention window has expired."""
    cutoff = now or _naive_utc_now()
    expired_count = 0
    affected_sids: set[str] = set()

    expired_narratives = db.session.scalars(
        sa.select(VaNarrativeAssessment).where(
            VaNarrativeAssessment.va_nqa_status == VaStatuses.active,
            VaNarrativeAssessment.demo_expires_at.is_not(None),
            VaNarrativeAssessment.demo_expires_at < cutoff,
        )
    ).all()
    for narrative in expired_narratives:
        narrative.va_nqa_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=narrative.va_sid,
                va_audit_entityid=narrative.va_nqa_id,
                va_audit_byrole="vasystem",
                va_audit_operation="u",
                va_audit_action="narrative quality assessment expired after demo retention",
            )
        )
        affected_sids.add(narrative.va_sid)
        expired_count += 1

    expired_social = db.session.scalars(
        sa.select(VaSocialAutopsyAnalysis).where(
            VaSocialAutopsyAnalysis.va_saa_status == VaStatuses.active,
            VaSocialAutopsyAnalysis.demo_expires_at.is_not(None),
            VaSocialAutopsyAnalysis.demo_expires_at < cutoff,
        )
    ).all()
    for analysis in expired_social:
        analysis.va_saa_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=analysis.va_sid,
                va_audit_entityid=analysis.va_saa_id,
                va_audit_byrole="vasystem",
                va_audit_operation="u",
                va_audit_action="social autopsy analysis expired after demo retention",
            )
        )
        affected_sids.add(analysis.va_sid)
        expired_count += 1

    expired_finals = db.session.scalars(
        sa.select(VaFinalAssessments).where(
            VaFinalAssessments.va_finassess_status == VaStatuses.active,
            VaFinalAssessments.demo_expires_at.is_not(None),
            VaFinalAssessments.demo_expires_at < cutoff,
        )
    ).all()
    for final_row in expired_finals:
        final_row.va_finassess_status = VaStatuses.deactive
        replacement_final = db.session.scalar(
            sa.select(VaFinalAssessments).where(
                VaFinalAssessments.va_sid == final_row.va_sid,
                VaFinalAssessments.va_finassess_status == VaStatuses.active,
            ).order_by(VaFinalAssessments.va_finassess_createdat.desc())
        )
        upsert_final_cod_authority(
            final_row.va_sid,
            replacement_final,
            reason="demo_retention_expired",
            source_role="vasystem",
        )
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=final_row.va_sid,
                va_audit_entityid=final_row.va_finassess_id,
                va_audit_byrole="vasystem",
                va_audit_operation="u",
                va_audit_action="final cod expired after demo retention",
            )
        )
        affected_sids.add(final_row.va_sid)
        expired_count += 1

    for va_sid in affected_sids:
        reset_demo_state(
            va_sid,
            reason="demo_retention_cleanup",
            actor=system_actor(),
        )

    if expired_count:
        db.session.commit()

    return expired_count
