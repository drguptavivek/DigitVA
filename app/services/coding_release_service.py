"""Drop the coding work on a submission whose payload changed.

One implementation for every path that changes the answers of a submission
that is not yet protected: ODK sync (an edit in ODK Central), an
interviewer's revision (docs/policy/interview-revisions.md) and a supervisor's
choice of the other interviewer's complete interview
(docs/policy/web-intake.md, "Parallel interviews"). The caller
applies the new payload and routes the workflow afterwards; this only
deactivates the coding artifacts and releases the allocations, auditing each.

A protected (finalised) submission has one more path: the data manager's
accept of an upstream change, and the interviewer's revision of a case sent
back or reopened (``deactivate_coding_for_accepted_change``,
``reopen_coding_after_revision``).
"""
import sqlalchemy as sa

from app import db
from app.models import (
    VaAllocations,
    VaCoderReview,
    VaDataManagerReview,
    VaFinalAssessments,
    VaInitialAssessments,
    VaReviewerFinalAssessments,
    VaReviewerReview,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissionsAuditlog,
    VaUsernotes,
)
from app.services.final_cod_authority_service import (
    abandon_active_recode_episode,
    upsert_final_cod_authority,
)
from app.services.payload_bound_coding_artifact_service import (
    deactivate_active_narrative_assessments_for_submission,
    deactivate_active_reviewer_reviews_for_submission,
    deactivate_active_social_autopsy_analyses_for_submission,
)
from app.services.workflow.transitions import (
    INTERVIEW_CHOSEN_REASON,
    REVISION_RESTART_REASON,
    WorkflowActor,
    accept_upstream_change,
    system_actor,
)

#: What each caller audits with. ``trigger`` ends the per-artifact audit
#: actions (``va_coderreview_deletion_during_<trigger>``); the allocation
#: release has its own action so coder statistics can tell the callers apart.
SOURCE_DATASYNC = "datasync"
SOURCE_INTERVIEWER_REVISION = "interviewer_revision"
SOURCE_SUPERVISOR_CHOICE = "supervisor_choice"
_SOURCES = {
    SOURCE_DATASYNC: {
        "trigger": "datasync",
        "role": "vaadmin",
        "allocation_action": "va_allocation_released_during_datasync",
        "authority_reason": "submission_updated_during_sync",
        "recode_action": "recode episode abandoned due to data sync update",
    },
    SOURCE_INTERVIEWER_REVISION: {
        "trigger": "interviewer_revision",
        "role": "vainterviewer",
        "allocation_action": "interviewer_revision",
        "authority_reason": "submission_revised_by_interviewer",
        "recode_action": "recode episode abandoned due to interviewer revision",
    },
    SOURCE_SUPERVISOR_CHOICE: {
        "trigger": "supervisor_choice",
        "role": "interview_supervisor",
        "allocation_action": "supervisor_choice",
        "authority_reason": "interview_chosen_by_supervisor",
        "recode_action": "recode episode abandoned due to supervisor interview choice",
    },
}


def release_coding_for_changed_payload(va_sid: str, *, source: str, audit_by=None) -> int:
    """Deactivate the active coding artifacts of *va_sid* and release its
    active allocations; returns how many artifacts were deactivated (the
    allocations are not counted, as ODK sync always did).

    *source* picks the audit strings (``SOURCE_*``); *audit_by* is the acting
    user's id, None for the sync. Deactivated, never deleted: history stays.
    """
    cfg = _SOURCES[source]
    trigger, role = cfg["trigger"], cfg["role"]
    discarded = 0

    def audit(entity_id, operation, action):
        db.session.add(VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_entityid=entity_id,
            va_audit_byrole=role,
            va_audit_by=audit_by,
            va_audit_operation=operation,
            va_audit_action=action,
        ))

    def deactivate(model, sid_col, status_col, id_col, action):
        nonlocal discarded
        for record in db.session.scalars(
            sa.select(model).where((sid_col == va_sid) & (status_col == VaStatuses.active))
        ).all():
            setattr(record, status_col.key, VaStatuses.deactive)
            discarded += 1
            audit(getattr(record, id_col.key), "d", action)

    deactivate(
        VaCoderReview, VaCoderReview.va_sid, VaCoderReview.va_creview_status,
        VaCoderReview.va_creview_id, f"va_coderreview_deletion_during_{trigger}",
    )
    deactivate(
        VaFinalAssessments, VaFinalAssessments.va_sid, VaFinalAssessments.va_finassess_status,
        VaFinalAssessments.va_finassess_id, f"va_finalasses_deletion_during_{trigger}",
    )
    upsert_final_cod_authority(
        va_sid, None, reason=cfg["authority_reason"], source_role=role, updated_by=audit_by,
    )
    abandon_active_recode_episode(
        va_sid, by_role=role, by_user_id=audit_by, audit_action=cfg["recode_action"],
    )
    deactivate(
        VaInitialAssessments, VaInitialAssessments.va_sid, VaInitialAssessments.va_iniassess_status,
        VaInitialAssessments.va_iniassess_id, f"va_initialasses_deletion_during_{trigger}",
    )
    deactivate(
        VaReviewerReview, VaReviewerReview.va_sid, VaReviewerReview.va_rreview_status,
        VaReviewerReview.va_rreview_id, f"va_reviewerreview_deletion_during_{trigger}",
    )
    deactivate(
        VaUsernotes, VaUsernotes.note_vasubmission, VaUsernotes.note_status,
        VaUsernotes.note_id, f"va_usernote_deletion_during_{trigger}",
    )
    # The data manager's not-codeable decision is superseded by the changed
    # payload; the re-routed workflow state is the sole authority.
    deactivate(
        VaDataManagerReview, VaDataManagerReview.va_sid, VaDataManagerReview.va_dmreview_status,
        VaDataManagerReview.va_dmreview_id, f"va_datamanagerreview_cleared_during_{trigger}",
    )
    # Invalidate a coder's session now rather than at timeout.
    for record in db.session.scalars(
        sa.select(VaAllocations).where(
            (VaAllocations.va_sid == va_sid) & (VaAllocations.va_allocation_status == VaStatuses.active)
        )
    ).all():
        record.va_allocation_status = VaStatuses.deactive
        audit(record.va_allocation_id, "d", cfg["allocation_action"])
    return discarded


def deactivate_coding_for_accepted_change(va_sid: str, *, actor: WorkflowActor, audit_by) -> None:
    """Deactivate every coding artifact of a finalised submission whose new
    payload was accepted, so it re-enters coding from scratch: final and
    initial assessments, coder and data-manager reviews, allocations, SmartVA
    results, reviewer final assessments and reviews, narrative and social
    autopsy assessments. Deactivated, never deleted: the earlier COD stays as
    history. The reviewer, narrative and social-autopsy rows are audited under
    *actor*'s role and *audit_by* (the acting user's id).

    The one block both the data manager's accept of an ODK upstream change
    (``dm_accept_upstream_change``) and the interviewer's revision of a case
    sent back or reopened run. The caller promotes the payload, moves the
    workflow (``accept_upstream_change``) and clears the final COD authority.
    """
    for model, sid_col, status_col in (
        (VaFinalAssessments, VaFinalAssessments.va_sid, VaFinalAssessments.va_finassess_status),
        (VaInitialAssessments, VaInitialAssessments.va_sid, VaInitialAssessments.va_iniassess_status),
        (VaCoderReview, VaCoderReview.va_sid, VaCoderReview.va_creview_status),
        (VaDataManagerReview, VaDataManagerReview.va_sid, VaDataManagerReview.va_dmreview_status),
        (VaAllocations, VaAllocations.va_sid, VaAllocations.va_allocation_status),
        (VaSmartvaResults, VaSmartvaResults.va_sid, VaSmartvaResults.va_smartva_status),
        (VaReviewerFinalAssessments, VaReviewerFinalAssessments.va_sid, VaReviewerFinalAssessments.va_rfinassess_status),
    ):
        for row in db.session.scalars(
            sa.select(model).where(sid_col == va_sid, status_col == VaStatuses.active)
        ).all():
            setattr(row, status_col.key, VaStatuses.deactive)
    deactivate_active_reviewer_reviews_for_submission(
        va_sid,
        audit_byrole=actor.audit_role,
        audit_by=audit_by,
        audit_action="reviewer review deactivated for recoding after upstream change",
    )
    deactivate_active_narrative_assessments_for_submission(
        va_sid,
        audit_byrole=actor.audit_role,
        audit_by=audit_by,
        audit_action="narrative quality assessment deactivated for recoding after upstream change",
    )
    deactivate_active_social_autopsy_analyses_for_submission(
        va_sid,
        audit_byrole=actor.audit_role,
        audit_by=audit_by,
        audit_action="social autopsy analysis deactivated for recoding after upstream change",
    )


def reopen_coding_after_revision(va_sid: str, *, audit_by, source: str = SOURCE_INTERVIEWER_REVISION) -> None:
    """Restart coding of a sent-back or reopened case at once, as the
    interviewer's revision arrives (owner, 2026-10-04: no data-manager accept
    step), or as a supervisor chooses the other interview (``source``
    ``SOURCE_SUPERVISOR_CHOICE``, whose caller has just moved the case to
    ``finalized_upstream_changed``): drop the coding as a data manager's accept
    does, move ``finalized_upstream_changed`` to ``smartva_pending`` and clear
    the final COD authority, all under a system actor and the reason
    ``interviewer_revision`` (``interview_chosen`` for the supervisor's
    choice). The earlier COD stays as inactive history."""
    actor = system_actor()
    reason = INTERVIEW_CHOSEN_REASON if source == SOURCE_SUPERVISOR_CHOICE else REVISION_RESTART_REASON
    # The audited release first (a row per deactivated COD, review, note and
    # allocation, the recode episode abandoned), as any changed revision
    # gets; then the accept block for what only it covers (SmartVA results,
    # reviewer COD and reviews, narrative, social autopsy), whose loops find
    # the already-released rows inactive. Recoded from scratch, auditable.
    release_coding_for_changed_payload(va_sid, source=source, audit_by=audit_by)
    deactivate_coding_for_accepted_change(va_sid, actor=actor, audit_by=audit_by)
    accept_upstream_change(va_sid, reason=reason, actor=actor)
    upsert_final_cod_authority(
        va_sid, None, reason=reason, source_role=actor.audit_role, updated_by=audit_by,
    )
