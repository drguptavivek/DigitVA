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
    VaReviewerFinalAssessments,
    VaReviewerInitialAssessments,
    VaReviewerReview,
    VaSocialAutopsyAnalysis,
    VaStatuses,
    VaSubmissionWorkflow,
    VaSubmissionsAuditlog,
)
from app.services.final_cod_authority_service import (
    abandon_active_recode_episode,
    get_active_recode_episode,
    upsert_final_cod_authority,
)
from app.services.coder_dashboard_service import bust_coder_dashboard_cache
from app.services.demo_project_service import (
    get_demo_coding_allocation_timeout_minutes,
    should_use_demo_actiontype_for_submission,
)
from app.services.payload_bound_coding_artifact_service import (
    deactivate_active_narrative_assessments_for_submission,
    deactivate_active_reviewer_reviews_for_submission,
    deactivate_active_social_autopsy_analyses_for_submission,
)
from app.services.workflow.definition import (
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
)
from app.services.workflow.transitions import (
    WorkflowActor,
    coder_actor,
    mark_tester_coding_returned,
    reset_demo_state,
    reset_incomplete_first_pass,
    reset_incomplete_recode,
    reset_incomplete_reviewer_session,
    system_actor,
)
from app.services.workflow.state_store import (
    get_submission_workflow_state,
    sync_submission_workflow_from_legacy_records,
)


def _naive_utc_now() -> datetime:
    """Return current UTC as a naive datetime to match legacy DB columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _deactivate_stale_initial_assessments(
    record: VaAllocations, cause: str, actor: WorkflowActor | None = None
) -> None:
    """Deactivate unfinished Step 1 COD drafts for a released coding allocation.

    Rows are audited under *actor* (default: the system).
    """
    actor = actor or system_actor()
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
                va_audit_byrole=actor.audit_role,
                va_audit_by=actor.user_id,
                va_audit_operation="u",
                va_audit_action=f"initial cod draft reverted due to {cause}",
            )
        )


def _deactivate_first_pass_analysis_artifacts(
    record: VaAllocations, cause: str, actor: WorkflowActor | None = None
) -> None:
    """Deactivate first-pass analysis artifacts that must not survive a release.

    Rows are audited under *actor* (default: the system).
    """
    actor = actor or system_actor()
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
                va_audit_byrole=actor.audit_role,
                va_audit_by=actor.user_id,
                va_audit_operation="u",
                va_audit_action=f"narrative quality assessment reverted due to {cause}",
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
                va_audit_byrole=actor.audit_role,
                va_audit_by=actor.user_id,
                va_audit_operation="u",
                va_audit_action=f"social autopsy analysis reverted due to {cause}",
            )
        )


def _release_coding_allocation(record: VaAllocations, *, cause: str, reason: str,
                               audit_action: str, actor: WorkflowActor | None = None) -> None:
    """Release one active coding allocation without discarding coding work.

    First pass: unfinished drafts and first-pass analyses are deactivated and
    the submission returns to ``ready_for_coding``. Recode: the episode is
    abandoned and the submission returns to ``coder_finalized`` with its
    authoritative final COD intact (docs/policy/coding-allocation-timeouts.md).
    *cause* words the artifact audit rows ("reverted due to <cause>"). *actor*
    is who released it (the allocation's coder, for a coder release); the
    timeout release is the system's.
    """
    actor = actor or system_actor()
    recode_episode = get_active_recode_episode(record.va_sid)
    record.va_allocation_status = VaStatuses.deactive
    _deactivate_stale_initial_assessments(record, cause, actor)
    if recode_episode is None:
        _deactivate_first_pass_analysis_artifacts(record, cause, actor)
        reset_incomplete_first_pass(record.va_sid, reason=reason, actor=actor)
    else:
        abandon_active_recode_episode(
            record.va_sid,
            by_role=actor.audit_role,
            by_user_id=actor.user_id,
            audit_action=f"recode episode abandoned due to {cause}",
        )
        reset_incomplete_recode(record.va_sid, reason=reason, actor=actor)
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=record.va_sid,
            va_audit_entityid=record.va_allocation_id,
            va_audit_byrole=actor.audit_role,
            va_audit_by=actor.user_id,
            va_audit_operation="d",
            va_audit_action=audit_action,
        )
    )


def return_tester_coding_to_pool(record: VaAllocations, *, reason: str) -> None:
    """Close a coding_tester's session on a real submission (digitva-ggc3).

    The caller has already written the tester's outcome (final COD or
    not-codeable report) deactive with ``is_tester`` set. Here the tester's
    Step 1 draft, NQA and social autopsy analysis are deactivated, the
    allocation is released and the case goes back to ``ready_for_coding``
    through ``mark_tester_coding_returned``. No coder result is touched: no
    final is superseded, the final-COD authority and any recode episode stay
    as they were. Does not commit.
    """
    cause = "tester coding"
    record.va_allocation_status = VaStatuses.deactive
    _deactivate_stale_initial_assessments(record, cause)
    _deactivate_first_pass_analysis_artifacts(record, cause)
    mark_tester_coding_returned(
        record.va_sid, reason=reason, actor=coder_actor(record.va_allocated_to)
    )
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=record.va_sid,
            va_audit_entityid=record.va_allocation_id,
            va_audit_byrole="vacoder",
            va_audit_by=record.va_allocated_to,
            va_audit_operation="d",
            va_audit_action="allocated form released from coding tester; returned to coding pool",
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

        _release_coding_allocation(
            record,
            cause="timeout",
            reason="allocation_timeout_release",
            audit_action="va_allocation_released_due_to_timeout",
        )
        released += 1

    if released:
        db.session.commit()

    cleanup_expired_demo_coding_artifacts(now=now)
    return released


def _deactivate_reviewer_session_artifacts(record: VaAllocations, cause: str) -> None:
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
            va_audit_action=f"reviewer nqa reverted due to {cause}",
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
            va_audit_action=f"narrative quality assessment reverted due to reviewer {cause}",
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
            va_audit_action=f"social autopsy analysis reverted due to reviewer {cause}",
        ))


def _release_reviewer_allocation(record: VaAllocations, *, cause: str, reason: str,
                                 audit_action: str) -> None:
    """Release one active reviewer allocation: session artifacts go, state -> reviewer_eligible."""
    record.va_allocation_status = VaStatuses.deactive
    _deactivate_reviewer_session_artifacts(record, cause)
    reset_incomplete_reviewer_session(record.va_sid, reason=reason, actor=system_actor())
    db.session.add(VaSubmissionsAuditlog(
        va_sid=record.va_sid,
        va_audit_entityid=record.va_allocation_id,
        va_audit_byrole="vasystem",
        va_audit_operation="d",
        va_audit_action=audit_action,
    ))


def release_reviewer_session_for_send_back(va_sid: str) -> None:
    """Release the active reviewer allocation on *va_sid* because the reviewer
    is sending the interview back for revision: the unfinished session
    artifacts go and the state returns to reviewer_eligible, as a timed-out
    session does. Does not commit; no-op when no reviewer holds it."""
    record = db.session.scalar(
        sa.select(VaAllocations).where(
            VaAllocations.va_sid == va_sid,
            VaAllocations.va_allocation_for == VaAllocation.reviewing,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    )
    if record is not None:
        _release_reviewer_allocation(
            record,
            cause="send_back",
            reason="reviewer_session_released_for_send_back",
            audit_action="reviewer_session_released_for_send_back",
        )


def revoke_active_allocations(va_sid: str) -> int:
    """Revoke every active coding and reviewing allocation on *va_sid*.

    Used when the submission's web case is confirmed as a duplicate
    (docs/policy/coding-workflow-state-machine.md, "Confirmed duplicate
    cases"): each allocation is released exactly as a timed-out one is
    (docs/policy/coding-allocation-timeouts.md), audited as a revocation.
    Finished coding is never touched. Does not commit: it runs inside the
    caller's transaction. Returns the number of allocations revoked.
    """
    allocations = db.session.scalars(
        sa.select(VaAllocations).where(
            VaAllocations.va_sid == va_sid,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    ).all()
    for record in allocations:
        if record.va_allocation_for == VaAllocation.reviewing:
            _release_reviewer_allocation(
                record,
                cause="duplicate",
                reason="reviewer_allocation_revoked_duplicate",
                audit_action="reviewer_allocation_revoked_duplicate",
            )
        else:
            _release_coding_allocation(
                record,
                cause="duplicate",
                reason="allocation_revoked_duplicate",
                audit_action="va_allocation_revoked_duplicate",
            )
    return len(allocations)


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
        _release_reviewer_allocation(
            record,
            cause="timeout",
            reason="reviewer_allocation_timeout_release",
            audit_action="reviewer_allocation_released_due_to_timeout",
        )
        released += 1

    if released:
        db.session.commit()

    return released


def _expire_demo_review_for_submission(va_sid: str) -> int:
    """Deactivate the review on a case whose demo coder final COD expired.

    Reviewer rows carry no demo_expires_at; the review expires with the coder
    final it reviewed (docs/policy/demo-coding-retention.md, "Demo
    Reviewing"). Covers a finished review and one still in progress. The
    caller has already cleared the reviewer authority pointer through
    upsert_final_cod_authority. Returns the number of rows deactivated.
    """
    expired = 0
    reviewer_finals = db.session.scalars(
        sa.select(VaReviewerFinalAssessments).where(
            VaReviewerFinalAssessments.va_sid == va_sid,
            VaReviewerFinalAssessments.va_rfinassess_status == VaStatuses.active,
        )
    ).all()
    for row in reviewer_finals:
        row.va_rfinassess_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_entityid=row.va_rfinassess_id,
                va_audit_byrole="vasystem",
                va_audit_operation="u",
                va_audit_action="reviewer final cod expired after demo retention",
            )
        )
        expired += 1

    reviewer_initials = db.session.scalars(
        sa.select(VaReviewerInitialAssessments).where(
            VaReviewerInitialAssessments.va_sid == va_sid,
            VaReviewerInitialAssessments.va_riniassess_status == VaStatuses.active,
        )
    ).all()
    for row in reviewer_initials:
        row.va_riniassess_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_entityid=row.va_riniassess_id,
                va_audit_byrole="vasystem",
                va_audit_operation="u",
                va_audit_action="reviewer initial cod expired after demo retention",
            )
        )
        expired += 1

    expired += deactivate_active_reviewer_reviews_for_submission(
        va_sid,
        audit_byrole="vasystem",
        audit_action="reviewer review expired after demo retention",
    )
    expired += deactivate_active_narrative_assessments_for_submission(
        va_sid,
        audit_byrole="vasystem",
        audit_action="narrative quality assessment expired after demo retention",
    )
    expired += deactivate_active_social_autopsy_analyses_for_submission(
        va_sid,
        audit_byrole="vasystem",
        audit_action="social autopsy analysis expired after demo retention",
    )

    reviewing_allocations = db.session.scalars(
        sa.select(VaAllocations).where(
            VaAllocations.va_sid == va_sid,
            VaAllocations.va_allocation_for == VaAllocation.reviewing,
            VaAllocations.va_allocation_status == VaStatuses.active,
        )
    ).all()
    for allocation in reviewing_allocations:
        allocation.va_allocation_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=va_sid,
                va_audit_entityid=allocation.va_allocation_id,
                va_audit_byrole="vasystem",
                va_audit_operation="d",
                va_audit_action="reviewer allocation released after demo retention",
            )
        )
        expired += 1
    return expired


def cleanup_expired_demo_coding_artifacts(
    *,
    now: datetime | None = None,
) -> int:
    """Deactivate demo-coded artifacts whose retention window has expired."""
    cutoff = now or _naive_utc_now()
    expired_count = 0
    affected_sids: set[str] = set()
    expired_final_users_by_sid: dict[str, set] = {}

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
        expired_final_users_by_sid.setdefault(final_row.va_sid, set()).add(
            final_row.va_finassess_by
        )
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

    for va_sid, user_ids in expired_final_users_by_sid.items():
        expired_initials = db.session.scalars(
            sa.select(VaInitialAssessments).where(
                VaInitialAssessments.va_sid == va_sid,
                VaInitialAssessments.va_iniassess_by.in_(user_ids),
                VaInitialAssessments.va_iniassess_status == VaStatuses.active,
            )
        ).all()
        for initial_row in expired_initials:
            initial_row.va_iniassess_status = VaStatuses.deactive
            db.session.add(
                VaSubmissionsAuditlog(
                    va_sid=initial_row.va_sid,
                    va_audit_entityid=initial_row.va_iniassess_id,
                    va_audit_byrole="vasystem",
                    va_audit_operation="u",
                    va_audit_action="initial cod expired after demo retention",
                )
            )
            affected_sids.add(initial_row.va_sid)
            expired_count += 1

    stale_demo_initials = db.session.scalars(
        sa.select(VaInitialAssessments)
        .join(
            VaSubmissionWorkflow,
            VaSubmissionWorkflow.va_sid == VaInitialAssessments.va_sid,
        )
        .where(
            VaInitialAssessments.va_iniassess_status == VaStatuses.active,
            VaSubmissionWorkflow.workflow_state == WORKFLOW_CODER_STEP1_SAVED,
            sa.exists(
                sa.select(sa.literal(True)).where(
                    VaFinalAssessments.va_sid == VaInitialAssessments.va_sid,
                    VaFinalAssessments.va_finassess_by
                    == VaInitialAssessments.va_iniassess_by,
                    VaFinalAssessments.va_finassess_status == VaStatuses.deactive,
                    VaFinalAssessments.demo_expires_at.is_not(None),
                    VaFinalAssessments.demo_expires_at < cutoff,
                )
            ),
            ~sa.exists(
                sa.select(sa.literal(True)).where(
                    VaFinalAssessments.va_sid == VaInitialAssessments.va_sid,
                    VaFinalAssessments.va_finassess_status == VaStatuses.active,
                )
            ),
            ~sa.exists(
                sa.select(sa.literal(True)).where(
                    VaAllocations.va_sid == VaInitialAssessments.va_sid,
                    VaAllocations.va_allocation_for == VaAllocation.coding,
                    VaAllocations.va_allocation_status == VaStatuses.active,
                )
            ),
        )
    ).all()
    for initial_row in stale_demo_initials:
        initial_row.va_iniassess_status = VaStatuses.deactive
        db.session.add(
            VaSubmissionsAuditlog(
                va_sid=initial_row.va_sid,
                va_audit_entityid=initial_row.va_iniassess_id,
                va_audit_byrole="vasystem",
                va_audit_operation="u",
                va_audit_action="initial cod expired after demo retention",
            )
        )
        affected_sids.add(initial_row.va_sid)
        expired_count += 1

    for va_sid in affected_sids:
        has_active_coding_allocation = bool(
            db.session.scalar(
                sa.select(sa.literal(True))
                .select_from(VaAllocations)
                .where(
                    VaAllocations.va_sid == va_sid,
                    VaAllocations.va_allocation_for == VaAllocation.coding,
                    VaAllocations.va_allocation_status == VaStatuses.active,
                )
                .limit(1)
            )
        )
        if has_active_coding_allocation:
            # Demo retention can prune stale artifacts from an older session
            # while a live coding/recode session is still in progress. Do not
            # emit a demo reset in that case; resync the canonical state from
            # current live records instead.
            sync_submission_workflow_from_legacy_records(
                va_sid,
                reason="demo_retention_cleanup_active_session",
                by_role="vasystem",
            )
            continue
        if va_sid in expired_final_users_by_sid:
            expired_count += _expire_demo_review_for_submission(va_sid)
        elif get_submission_workflow_state(va_sid) in (
            WORKFLOW_REVIEWER_ELIGIBLE,
            WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
            WORKFLOW_REVIEWER_FINALIZED,
        ):
            # The coder's NQA and Social Autopsy are saved before the final
            # code, so they expire first. A case under review stays as it is
            # until the coder's final code itself expires.
            continue
        reset_demo_state(
            va_sid,
            reason="demo_retention_cleanup",
            actor=system_actor(),
        )

    if expired_count:
        db.session.commit()
        for user_ids in expired_final_users_by_sid.values():
            for user_id in user_ids:
                bust_coder_dashboard_cache(user_id)

    return expired_count
