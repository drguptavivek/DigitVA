"""Drop the coding work on a submission whose payload changed.

One implementation for every path that changes the answers of a submission
that is not yet protected: ODK sync (an edit in ODK Central) and an
interviewer's revision (docs/policy/interview-revisions.md). The caller
applies the new payload and routes the workflow afterwards; this only
deactivates the coding artifacts and releases the allocations, auditing each.
"""
import sqlalchemy as sa

from app import db
from app.models import (
    VaAllocations,
    VaCoderReview,
    VaDataManagerReview,
    VaFinalAssessments,
    VaInitialAssessments,
    VaReviewerReview,
    VaStatuses,
    VaSubmissionsAuditlog,
    VaUsernotes,
)
from app.services.final_cod_authority_service import (
    abandon_active_recode_episode,
    upsert_final_cod_authority,
)

#: What each caller audits with. ``trigger`` ends the per-artifact audit
#: actions (``va_coderreview_deletion_during_<trigger>``); the allocation
#: release has its own action so coder statistics can tell the callers apart.
SOURCE_DATASYNC = "datasync"
SOURCE_INTERVIEWER_REVISION = "interviewer_revision"
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
