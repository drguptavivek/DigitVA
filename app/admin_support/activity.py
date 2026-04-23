import uuid
from types import SimpleNamespace

import sqlalchemy as sa

from app import db

AUDIT_STAGE_CONFIG = {
    "form allocated to coder": ("Coding Started", "primary"),
    "form allocated to admin for demo coding": ("Coding Started", "primary"),
    "form allocated to coder for recoding": ("Coding Restarted", "warning"),
    "va_allocation_released_by_admin_for_demo": ("Demo Allocation", "secondary"),
    "social autopsy analysis saved": ("Social Autopsy", "info"),
    "social autopsy analysis updated": ("Social Autopsy", "info"),
    "narrative quality assessment saved": ("Narrative Quality", "info"),
    "narrative quality assessment updated": ("Narrative Quality", "info"),
    "initial cod submitted": ("Step 1 COD", "warning"),
    "final cod submitted": ("Step 2 COD", "success"),
    "error reported by coder": ("Not Codeable", "danger"),
    "submission flagged not codeable by data manager": ("Data Triage", "danger"),
    "data manager not codeable updated": ("Data Triage", "warning"),
    "odk review state set to hasIssues": ("ODK Central", "info"),
    "odk review state update failed": ("ODK Central", "warning"),
    "allocated form released from coder": ("Allocation Released", "secondary"),
    "va_allocation_released_due_to_timeout": ("Timeout Release", "secondary"),
}

AUDIT_ACTION_DISPLAY = {
    "form allocated to coder": "Form allocated to coder",
    "form allocated to admin for demo coding": "Form allocated for demo coding",
    "form allocated to coder for recoding": "Form allocated for recoding",
    "allocated form released from coder": "Allocation released from coder",
    "va_allocation_released_by_admin_for_demo": "Demo allocation reset",
    "va_allocation_released_due_to_timeout": "Allocation released (timeout)",
    "va_allocation_deletion_due to timeout": "Allocation deleted (timeout)",
    "va_allocation_deletion_during_datasync": "Allocation deleted (sync)",
    "initial cod submitted": "Initial COD submitted",
    "final cod submitted": "Final COD submitted",
    "error reported by coder": "Error reported by coder",
    "submission flagged not codeable by data manager": "Flagged not codeable by data manager",
    "data manager not codeable updated": "Data-manager not codeable updated",
    "social autopsy analysis saved": "Social autopsy saved",
    "social autopsy analysis updated": "Social autopsy updated",
    "narrative quality assessment saved": "Narrative QA saved",
    "narrative quality assessment updated": "Narrative QA updated",
    "odk review state set to hasIssues": "ODK revision flag applied",
    "odk review state update failed": "ODK revision flag failed",
    "va_submission_creation_during_datasync": "Submission created (sync)",
    "va_submission_updation_during_datasync": "Submission updated (sync)",
    "va_smartva_creation_during_datasync": "SmartVA result created (sync)",
    "va_smartva_deletion_during_datasync": "SmartVA result replaced (sync)",
    "va_coderreview_deletion_during_datasync": "Coder review reset (sync)",
    "va_finalasses_deletion_during_datasync": "Final assessment reset (sync)",
    "va_initialasses_deletion_during_datasync": "Initial assessment reset (sync)",
    "va_usernote_deletion_during_datasync": "User note reset (sync)",
    "va_partial_coder review_deletion due to recode": "Partial review reset (recode)",
    "va_partial_finassess_deletion due to recode": "Partial final assessment reset (recode)",
    "va_partial_iniasses_deletion due to recode": "Partial initial assessment reset (recode)",
    "va_partial_iniasses_deletion due to timeout": "Partial assessment reset (timeout)",
    "upstream_odk_data_changed_on_protected_submission": "ODK data changed (protected — revoked)",
    "data_manager_requested_submission_refresh": "Submission refresh requested (data manager)",
    "data_manager_accepted_upstream_odk_change": "Upstream ODK change accepted (data manager)",
    "data_manager_rejected_upstream_odk_change": "Upstream ODK change rejected (data manager)",
}

AUDIT_ACTION_EXPLANATIONS = {
    "form allocated to coder": {
        "label": "Form Allocated to Coder",
        "category": "Allocation",
        "explanation": "A VA form has been assigned to a specific coder for processing. The coder can now begin the coding workflow.",
    },
    "form allocated to admin for demo coding": {
        "label": "Form Allocated for Demo Coding",
        "category": "Allocation",
        "explanation": "A VA form has been assigned to an admin user for demonstration or training purposes.",
    },
    "form allocated to coder for recoding": {
        "label": "Form Allocated for Recoding",
        "category": "Allocation",
        "explanation": "A previously coded form has been returned to a coder (possibly a different one) for re-evaluation. This typically happens after a review rejection or quality issue.",
    },
    "allocated form released from coder": {
        "label": "Allocation Released",
        "category": "Allocation",
        "explanation": "The coder's allocation has been released, making the form available for re-allocation. This may be voluntary or admin-initiated.",
    },
    "va_allocation_released_by_admin_for_demo": {
        "label": "Demo Allocation Reset",
        "category": "Allocation",
        "explanation": "An admin has reset a demo allocation, returning the form to the available pool.",
    },
    "va_allocation_released_due_to_timeout": {
        "label": "Allocation Released (Timeout)",
        "category": "Allocation",
        "explanation": "The allocation was automatically released because the coder exceeded the maximum allowed time without completing the form.",
    },
    "va_allocation_deletion_due to timeout": {
        "label": "Allocation Deleted (Timeout)",
        "category": "Allocation",
        "explanation": "The allocation record was deleted due to timeout. The form is now available for re-allocation.",
    },
    "va_allocation_deletion_during_datasync": {
        "label": "Allocation Deleted (Sync)",
        "category": "Allocation",
        "explanation": "All active allocations were cleared during an ODK sync because the underlying submission was updated in ODK Central. This ensures coders work on the latest data.",
    },
    "initial cod submitted": {
        "label": "Initial COD Submitted",
        "category": "Cause of Death",
        "explanation": "The coder has submitted the initial (Step 1) cause of death determination. This is the first COD assessment before final review.",
    },
    "final cod submitted": {
        "label": "Final COD Submitted",
        "category": "Cause of Death",
        "explanation": "The final (Step 2) cause of death has been submitted after review. This represents the completed COD determination.",
    },
    "error reported by coder": {
        "label": "Error Reported by Coder",
        "category": "Cause of Death",
        "explanation": "The coder has flagged this form as 'Not Codeable' due to insufficient or inconsistent information. The form may require additional review or data correction.",
    },
    "submission flagged not codeable by data manager": {
        "label": "Flagged Not Codeable by Data Manager",
        "category": "Data Triage",
        "explanation": "A data manager has excluded this submission from coder allocation because it is unsuitable for coding in its current form.",
    },
    "data manager not codeable updated": {
        "label": "Data-Manager Not Codeable Updated",
        "category": "Data Triage",
        "explanation": "The existing data-manager Not Codeable decision was updated with revised reason or notes.",
    },
    "social autopsy analysis saved": {
        "label": "Social Autopsy Saved",
        "category": "Assessment",
        "explanation": "The social autopsy analysis (contextual information about circumstances of death) has been saved for this submission.",
    },
    "social autopsy analysis updated": {
        "label": "Social Autopsy Updated",
        "category": "Assessment",
        "explanation": "The social autopsy analysis has been modified and resaved.",
    },
    "narrative quality assessment saved": {
        "label": "Narrative QA Saved",
        "category": "Assessment",
        "explanation": "A narrative quality assessment has been recorded, evaluating the completeness and quality of the verbal autopsy narrative.",
    },
    "narrative quality assessment updated": {
        "label": "Narrative QA Updated",
        "category": "Assessment",
        "explanation": "The narrative quality assessment has been modified and resaved.",
    },
    "odk review state set to hasIssues": {
        "label": "ODK Revision Flag Applied",
        "category": "ODK Integration",
        "explanation": "The submission has been flagged in ODK Central as having issues. This notifies data collectors that the submission needs attention or correction.",
    },
    "odk review state update failed": {
        "label": "ODK Revision Flag Failed",
        "category": "ODK Integration",
        "explanation": "An attempt to set the ODK review state failed, possibly due to connectivity issues or ODK Central being unavailable.",
    },
    "va_submission_creation_during_datasync": {
        "label": "Submission Created (Sync)",
        "category": "Data Sync",
        "explanation": "A new VA submission was imported from ODK Central during a scheduled or manual sync operation.",
    },
    "va_submission_updation_during_datasync": {
        "label": "Submission Updated (Sync)",
        "category": "Data Sync",
        "explanation": "An existing VA submission was updated from ODK Central. The submission had been edited in ODK, and the local copy was refreshed.",
    },
    "va_smartva_creation_during_datasync": {
        "label": "SmartVA Result Created (Sync)",
        "category": "Data Sync",
        "explanation": "A new SmartVA algorithmic cause of death prediction was generated and stored for this submission.",
    },
    "va_smartva_deletion_during_datasync": {
        "label": "SmartVA Result Replaced (Sync)",
        "category": "Data Sync",
        "explanation": "An existing SmartVA result was superseded by a new one. The old result was marked inactive; this is normal when submission data changes.",
    },
    "va_coderreview_deletion_during_datasync": {
        "label": "Coder Review Reset (Sync)",
        "category": "Data Sync",
        "explanation": "Coder review data was cleared because the underlying submission was updated in ODK Central. The form needs to be re-coded.",
    },
    "va_finalasses_deletion_during_datasync": {
        "label": "Final Assessment Reset (Sync)",
        "category": "Data Sync",
        "explanation": "Final assessment data was cleared due to an ODK update. The form requires re-evaluation.",
    },
    "va_initialasses_deletion_during_datasync": {
        "label": "Initial Assessment Reset (Sync)",
        "category": "Data Sync",
        "explanation": "Initial assessment data was cleared due to an ODK update. The form requires re-evaluation.",
    },
    "va_usernote_deletion_during_datasync": {
        "label": "User Note Reset (Sync)",
        "category": "Data Sync",
        "explanation": "User notes attached to this submission were cleared because the submission was updated from ODK Central.",
    },
    "va_partial_coder review_deletion due to recode": {
        "label": "Partial Review Reset (Recode)",
        "category": "Partial Reset",
        "explanation": "Partial coder review work was discarded because the form was sent for recoding. In-progress work is cleared to start fresh.",
    },
    "va_partial_finassess_deletion due to recode": {
        "label": "Partial Final Assessment Reset (Recode)",
        "category": "Partial Reset",
        "explanation": "Partial final assessment work was discarded because the form was sent for recoding.",
    },
    "va_partial_iniasses_deletion due to recode": {
        "label": "Partial Initial Assessment Reset (Recode)",
        "category": "Partial Reset",
        "explanation": "Partial initial assessment work was discarded because the form was sent for recoding.",
    },
    "va_partial_iniasses_deletion due to timeout": {
        "label": "Partial Assessment Reset (Timeout)",
        "category": "Partial Reset",
        "explanation": "Partial assessment work was discarded because the allocation timed out before completion.",
    },
    "upstream_odk_data_changed_on_protected_submission": {
        "label": "Protected Submission Revoked",
        "category": "Protected Data",
        "explanation": "A submission in a protected state (coder_finalized or closed) had its data changed in ODK Central. The submission has been moved to finalized_upstream_changed and is pending data-manager review.",
    },
    "data_manager_requested_submission_refresh": {
        "label": "Submission Refresh Requested",
        "category": "Protected Data",
        "explanation": "A data manager has requested that the local submission data be refreshed from ODK Central. This triggers a re-sync of the submission's content.",
    },
    "data_manager_accepted_upstream_odk_change": {
        "label": "Upstream Change Accepted",
        "category": "Protected Data",
        "explanation": "A data manager has accepted the upstream ODK data change for a revoked submission. The workflow has been reset and the submission is now ready for re-coding.",
    },
    "data_manager_rejected_upstream_odk_change": {
        "label": "Upstream Change Rejected",
        "category": "Protected Data",
        "explanation": "A data manager has rejected the upstream ODK data change for a revoked submission. The submission has been restored to its previous coder_finalized state, preserving all coding work.",
    },
}


def build_activity_rows(limit=100, page=1, sid=None, project_id=None, site_id=None, user_id=None, action=None):
    from sqlalchemy import select as sa_select

    from app.models import VaForms, VaSubmissions, VaSubmissionsAuditlog, VaUsers

    query = (
        sa_select(
            VaSubmissionsAuditlog.va_audit_id,
            VaSubmissionsAuditlog.va_sid,
            VaSubmissionsAuditlog.va_audit_createdat,
            VaSubmissionsAuditlog.va_audit_byrole,
            VaSubmissionsAuditlog.va_audit_by,
            VaSubmissionsAuditlog.va_audit_operation,
            VaSubmissionsAuditlog.va_audit_action,
            VaSubmissionsAuditlog.va_audit_entityid,
            VaSubmissions.va_form_id,
            VaForms.project_id,
            VaForms.site_id,
            VaSubmissions.va_uniqueid_masked,
            VaUsers.email.label("actor_email"),
            VaUsers.name.label("actor_name"),
        )
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionsAuditlog.va_sid)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .outerjoin(VaUsers, VaUsers.user_id == VaSubmissionsAuditlog.va_audit_by)
        .order_by(VaSubmissionsAuditlog.va_audit_createdat.desc())
    )

    if sid:
        query = query.where(VaSubmissionsAuditlog.va_sid.ilike(f"%{sid}%"))
    if project_id:
        query = query.where(VaForms.project_id == project_id)
    if site_id:
        query = query.where(VaForms.site_id == site_id)
    if user_id:
        try:
            query = query.where(VaSubmissionsAuditlog.va_audit_by == uuid.UUID(user_id))
        except ValueError:
            query = query.where(sa.false())
    if action:
        query = query.where(VaSubmissionsAuditlog.va_audit_action == action)

    count_query = (
        sa.select(sa.func.count())
        .select_from(VaSubmissionsAuditlog)
        .join(VaSubmissions, VaSubmissions.va_sid == VaSubmissionsAuditlog.va_sid)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
    )
    if sid:
        count_query = count_query.where(VaSubmissionsAuditlog.va_sid.ilike(f"%{sid}%"))
    if project_id:
        count_query = count_query.where(VaForms.project_id == project_id)
    if site_id:
        count_query = count_query.where(VaForms.site_id == site_id)
    if user_id:
        try:
            count_query = count_query.where(VaSubmissionsAuditlog.va_audit_by == uuid.UUID(user_id))
        except ValueError:
            count_query = count_query.where(sa.false())
    if action:
        count_query = count_query.where(VaSubmissionsAuditlog.va_audit_action == action)

    total_count = db.session.scalar(count_query) or 0
    rows = db.session.execute(query.limit(limit).offset((page - 1) * limit)).all()
    activity_rows = []
    for row in rows:
        stage_label, badge_class = AUDIT_STAGE_CONFIG.get(row.va_audit_action, ("Other", "secondary"))
        actor_display = row.actor_email or row.actor_name or "System"
        activity_rows.append(
            SimpleNamespace(
                audit_id=row.va_audit_id,
                sid=row.va_sid,
                created_at=row.va_audit_createdat,
                by_role=row.va_audit_byrole,
                actor_display=actor_display,
                action=AUDIT_ACTION_DISPLAY.get(row.va_audit_action, row.va_audit_action),
                operation=row.va_audit_operation,
                entity_id=row.va_audit_entityid,
                form_id=row.va_form_id,
                project_id=row.project_id,
                site_id=row.site_id,
                unique_id=row.va_uniqueid_masked,
                stage_label=stage_label,
                badge_class=badge_class,
            )
        )
    return activity_rows, total_count
