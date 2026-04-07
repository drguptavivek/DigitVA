import logging
import json
import re
import uuid
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from secrets import token_hex
from types import SimpleNamespace

log = logging.getLogger(__name__)

import sqlalchemy as sa
from dateutil import parser
from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user
from flask_wtf.csrf import generate_csrf

from app import db, limiter
from app.decorators import role_required
from app.services.odk_connection_guard_service import (
    OdkConnectionCooldownError,
    guarded_odk_call,
    serialize_connection_guard_state,
)
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    MasOdkConnections,
    MapProjectOdk,
    MapProjectSiteOdk,
    VaForms,
    VaSyncRun,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.models.va_submission_payload_versions import VaSubmissionPayloadVersion


admin = Blueprint("admin", __name__)


def _json_error(message, status_code):
    return jsonify({"error": message}), status_code


def _validate_entity_id(entity_id, length, name="ID"):
    if not entity_id or len(entity_id) != length:
        return f"{name} must be exactly {length} characters."
    if not re.match(r'^[A-Z0-9]+$', entity_id):
        return f"{name} must contain only uppercase letters and digits."
    return None


def _ordered_field_lists_for_form_type(form_type_id):
    """Return ordered field objects keyed by category and subcategory."""
    from sqlalchemy import select as sa_select
    from sqlalchemy.orm import aliased
    from app.models import MasFieldDisplayConfig
    from app.models.va_field_mapping import MasSubcategoryOrder

    subcat_order = aliased(MasSubcategoryOrder)
    rows = db.session.execute(
        sa_select(
            MasFieldDisplayConfig.category_code,
            MasFieldDisplayConfig.subcategory_code,
            MasFieldDisplayConfig.field_id,
            MasFieldDisplayConfig.short_label,
            MasFieldDisplayConfig.display_order,
            MasFieldDisplayConfig.flip_color,
            MasFieldDisplayConfig.is_info,
            MasFieldDisplayConfig.is_pii,
            MasFieldDisplayConfig.summary_include,
            subcat_order.display_order.label("subcategory_display_order"),
        )
        .outerjoin(
            subcat_order,
            sa.and_(
                subcat_order.form_type_id == MasFieldDisplayConfig.form_type_id,
                subcat_order.category_code == MasFieldDisplayConfig.category_code,
                subcat_order.subcategory_code == MasFieldDisplayConfig.subcategory_code,
                subcat_order.is_active == True,
            )
        )
        .where(
            MasFieldDisplayConfig.form_type_id == form_type_id,
            MasFieldDisplayConfig.is_active == True,
            MasFieldDisplayConfig.category_code.is_not(None),
        )
        .order_by(
            subcat_order.display_order.is_(None),
            subcat_order.display_order,
            MasFieldDisplayConfig.subcategory_code,
            MasFieldDisplayConfig.display_order,
            MasFieldDisplayConfig.field_id,
        )
    ).all()

    by_category = {}
    by_subcategory = {}
    for row in rows:
        field_data = {
            "field_id": row.field_id,
            "label": row.short_label or row.field_id,
            "display_order": str(row.display_order),
            "subcategory_code": row.subcategory_code,
            "flip_color": bool(getattr(row, "flip_color", False)),
            "is_info": bool(getattr(row, "is_info", False)),
            "is_pii": bool(getattr(row, "is_pii", False)),
            "summary_include": bool(getattr(row, "summary_include", False)),
        }
        by_category.setdefault(row.category_code, []).append(field_data)
        if row.subcategory_code:
            by_subcategory[(row.category_code, row.subcategory_code)] = (
                by_subcategory.get((row.category_code, row.subcategory_code), []) + [field_data]
            )
    return by_category, by_subcategory


def _get_ordered_category_configs_for_form_type(form_type_id):
    """Return ordered category display configs for a form type."""
    from sqlalchemy import select as sa_select
    from app.models.va_field_mapping import MasCategoryDisplayConfig

    return db.session.scalars(
        sa_select(MasCategoryDisplayConfig)
        .where(
            MasCategoryDisplayConfig.form_type_id == form_type_id,
            MasCategoryDisplayConfig.is_active == True,
        )
        .order_by(MasCategoryDisplayConfig.display_order, MasCategoryDisplayConfig.nav_label)
    ).all()


def _serialize_category_browser_state(form_type, category_code):
    """Return category + subcategory field-browser state for the 3-panel UI."""
    from sqlalchemy import select as sa_select
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasSubcategoryOrder

    category = db.session.scalar(
        sa_select(MasCategoryDisplayConfig).where(
            MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
            MasCategoryDisplayConfig.category_code == category_code,
            MasCategoryDisplayConfig.is_active == True,
        )
    )
    if not category:
        return None

    fields_by_category, fields_by_subcategory = _ordered_field_lists_for_form_type(
        form_type.form_type_id
    )
    subcategories = db.session.scalars(
        sa_select(MasSubcategoryOrder)
        .where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id,
            MasSubcategoryOrder.category_code == category_code,
        )
        .order_by(MasSubcategoryOrder.display_order)
    ).all()

    return {
        "category": {
            "category_code": category.category_code,
            "category_name": category.display_label,
            "display_order": category.display_order,
            "ordered_fields": fields_by_category.get(category_code, []),
        },
        "subcategories": [
            {
                "subcategory_code": sub.subcategory_code,
                "subcategory_name": sub.subcategory_name,
                "display_order": sub.display_order,
                "render_mode": sub.render_mode,
                "ordered_fields": fields_by_subcategory.get(
                    (category_code, sub.subcategory_code), []
                ),
            }
            for sub in subcategories
        ],
    }





def _current_user_can_manage_project(project_id):
    return current_user.is_admin() or current_user.can_manage_project(project_id)


def _grant_project_id_expression():
    return sa.case(
        (
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
            VaUserAccessGrants.project_id,
        ),
        else_=VaProjectSites.project_id,
    )


def _grant_site_id_expression():
    return sa.case(
        (
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
            VaProjectSites.site_id,
        ),
        else_=sa.null(),
    )


def _serialize_project(project):
    return {
        "project_id": project.project_id,
        "project_code": project.project_code,
        "project_name": project.project_name,
        "project_nickname": project.project_nickname,
        "status": project.project_status.value,
        "narrative_qa_enabled": project.narrative_qa_enabled,
        "social_autopsy_enabled": project.social_autopsy_enabled,
        "coding_intake_mode": project.coding_intake_mode,
        "demo_training_enabled": project.demo_training_enabled,
        "demo_retention_minutes": project.demo_retention_minutes,
    }


def _serialize_site(site):
    return {
        "site_id": site.site_id,
        "site_name": site.site_name,
        "site_abbr": site.site_abbr,
        "status": site.site_status.value,
    }


_AUDIT_STAGE_CONFIG = {
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

_AUDIT_ACTION_DISPLAY = {
    # Workflow actions
    "form allocated to coder": "Form allocated to coder",
    "form allocated to admin for demo coding": "Form allocated for demo coding",
    "form allocated to coder for recoding": "Form allocated for recoding",
    "allocated form released from coder": "Allocation released from coder",
    "va_allocation_released_by_admin_for_demo": "Demo allocation reset",
    "va_allocation_released_due_to_timeout": "Allocation released (timeout)",
    "va_allocation_deletion_due to timeout": "Allocation deleted (timeout)",
    "va_allocation_deletion_during_datasync": "Allocation deleted (sync)",
    # COD actions
    "initial cod submitted": "Initial COD submitted",
    "final cod submitted": "Final COD submitted",
    "error reported by coder": "Error reported by coder",
    "submission flagged not codeable by data manager": "Flagged not codeable by data manager",
    "data manager not codeable updated": "Data-manager not codeable updated",
    # Assessment actions
    "social autopsy analysis saved": "Social autopsy saved",
    "social autopsy analysis updated": "Social autopsy updated",
    "narrative quality assessment saved": "Narrative QA saved",
    "narrative quality assessment updated": "Narrative QA updated",
    # ODK actions
    "odk review state set to hasIssues": "ODK revision flag applied",
    "odk review state update failed": "ODK revision flag failed",
    # Sync actions
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
    # Protected-submission upstream change actions
    "upstream_odk_data_changed_on_protected_submission": "ODK data changed (protected — revoked)",
    "data_manager_requested_submission_refresh": "Submission refresh requested (data manager)",
    "data_manager_accepted_upstream_odk_change": "Upstream ODK change accepted (data manager)",
    "data_manager_rejected_upstream_odk_change": "Upstream ODK change rejected (data manager)",
}

# Detailed explanations for each action type (for help modal)
_AUDIT_ACTION_EXPLANATIONS = {
    # Allocation & Workflow
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
    # Cause of Death
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
    # Assessments
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
    # ODK Integration
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
    # Sync Operations
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
    # Partial Work Reset
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
    # Protected Submission Data-Change Actions
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


def _build_activity_rows(limit=100, page=1, sid=None, project_id=None, site_id=None, user_id=None, action=None):
    """Return paginated submission audit rows with lightweight workflow context."""
    from sqlalchemy import select as sa_select
    from app.models import VaSubmissions, VaSubmissionsAuditlog, VaUsers

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
            resolved_user_id = uuid.UUID(user_id)
            query = query.where(VaSubmissionsAuditlog.va_audit_by == resolved_user_id)
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
            resolved_user_id = uuid.UUID(user_id)
            count_query = count_query.where(VaSubmissionsAuditlog.va_audit_by == resolved_user_id)
        except ValueError:
            count_query = count_query.where(sa.false())
    if action:
        count_query = count_query.where(VaSubmissionsAuditlog.va_audit_action == action)

    total_count = db.session.scalar(count_query) or 0
    rows = db.session.execute(
        query.limit(limit).offset((page - 1) * limit)
    ).all()
    activity_rows = []
    for row in rows:
        stage_label, badge_class = _AUDIT_STAGE_CONFIG.get(
            row.va_audit_action,
            ("Other", "secondary"),
        )
        actor_display = row.actor_email or row.actor_name or "System"
        activity_rows.append(
            SimpleNamespace(
                audit_id=row.va_audit_id,
                sid=row.va_sid,
                created_at=row.va_audit_createdat,
                by_role=row.va_audit_byrole,
                actor_display=actor_display,
                action=_AUDIT_ACTION_DISPLAY.get(row.va_audit_action, row.va_audit_action),
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


def _serialize_project_site(row):
    return {
        "project_site_id": str(row.project_site_id),
        "project_id": row.project_id,
        "site_id": row.site_id,
        "project_name": row.project_name,
        "site_name": row.site_name,
        "status": row.project_site_status.value,
    }


def _serialize_grant(row):
    return {
        "grant_id": str(row.grant_id),
        "user_id": str(row.user_id),
        "user_email": row.email,
        "user_name": row.name,
        "role": row.role.value,
        "scope_type": row.scope_type.value,
        "project_id": row.resolved_project_id,
        "site_id": row.resolved_site_id,
        "project_site_id": str(row.project_site_id) if row.project_site_id else None,
        "status": row.grant_status.value,
        "notes": row.notes,
    }


def _resolve_scope_from_payload(payload):
    role_value = payload.get("role")
    scope_value = payload.get("scope_type")
    if role_value not in {role.value for role in VaAccessRoles}:
        raise ValueError("Invalid role.")
    if scope_value not in {scope.value for scope in VaAccessScopeTypes}:
        raise ValueError("Invalid scope_type.")

    role = VaAccessRoles(role_value)
    scope_type = VaAccessScopeTypes(scope_value)
    project_id = payload.get("project_id")
    project_site_id_value = payload.get("project_site_id")
    project_site_id = None
    project_site = None

    if scope_type == VaAccessScopeTypes.global_scope:
        if role != VaAccessRoles.admin:
            raise ValueError("Only admin may use global scope.")
        if project_id or project_site_id_value:
            raise ValueError("Global scope must not include project_id or project_site_id.")
        return role, scope_type, None, None

    if scope_type == VaAccessScopeTypes.project:
        if role not in {
            VaAccessRoles.project_pi,
            VaAccessRoles.collaborator,
            VaAccessRoles.coder,
            VaAccessRoles.reviewer,
            VaAccessRoles.data_manager,
        }:
            raise ValueError("This role cannot use project scope.")
        if not project_id or project_site_id_value:
            raise ValueError("Project scope requires project_id only.")
        return role, scope_type, project_id, None

    if role not in {
        VaAccessRoles.site_pi,
        VaAccessRoles.collaborator,
        VaAccessRoles.coder,
        VaAccessRoles.reviewer,
        VaAccessRoles.data_manager,
    }:
        raise ValueError("This role cannot use project_site scope.")
    if payload.get("project_id"):
        raise ValueError("Project-site scope must not include project_id.")
    if not project_site_id_value:
        raise ValueError("Project-site scope requires project_site_id.")
    try:
        project_site_id = uuid.UUID(project_site_id_value)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid project_site_id.") from exc

    project_site = db.session.get(VaProjectSites, project_site_id)
    if not project_site or project_site.project_site_status != VaStatuses.active:
        raise ValueError("Active project-site mapping not found.")
    return role, scope_type, project_site.project_id, project_site.project_site_id


def _project_access_filter(project_id_expression):
    if current_user.is_authenticated and current_user.is_admin():
        return sa.true()
    if current_user.is_authenticated:
        return project_id_expression.in_(list(current_user.get_project_pi_projects()))
    return sa.false()


@admin.get("/api/bootstrap")
@role_required("admin", "project_pi")
def admin_bootstrap():
    if "csrf_token" not in session:
        session["csrf_token"] = token_hex(32)
    accessible_projects = sorted(current_user.get_project_pi_projects())
    if current_user.is_admin():
        accessible_projects = sorted(
            db.session.scalars(
                sa.select(VaProjectMaster.project_id).where(
                    VaProjectMaster.project_status == VaStatuses.active
                )
            ).all()
        )
    return jsonify(
        {
            "csrf_header_name": "X-CSRFToken",
            "csrf_token": generate_csrf(),
            "user": {
                "user_id": str(current_user.user_id),
                "email": current_user.email,
                "name": current_user.name,
                "is_admin": current_user.is_admin(),
                "project_pi_projects": sorted(current_user.get_project_pi_projects()),
            },
            "accessible_projects": sorted(accessible_projects),
        }
    )


@admin.get("/api/projects")
@role_required("admin", "project_pi")
def admin_projects():
    master = request.args.get("master") == "1"
    
    if master:
        if not current_user.is_admin():
            return _json_error("Admin access required.", 403)
        stmt = sa.select(VaProjectMaster)
        if request.args.get("include_inactive") != "1":
            stmt = stmt.where(VaProjectMaster.project_status == VaStatuses.active)
    else:
        stmt = sa.select(VaProjectMaster).where(
            VaProjectMaster.project_status == VaStatuses.active
        )
        if not current_user.is_admin():
            stmt = stmt.where(
                VaProjectMaster.project_id.in_(list(current_user.get_project_pi_projects()))
            )
    projects = db.session.scalars(stmt.order_by(VaProjectMaster.project_id)).all()
    return jsonify({"projects": [_serialize_project(project) for project in projects]})


@admin.post("/api/projects")
@role_required("admin")
def admin_create_project():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
    payload = request.get_json(silent=True) or {}
    project_id = (payload.get("project_id") or "").strip().upper()
    project_code = (payload.get("project_code") or "").strip().upper() or project_id
    project_name = (payload.get("project_name") or "").strip()
    project_nickname = (payload.get("project_nickname") or "").strip()
    try:
        demo_retention_minutes = max(
            int(payload.get("demo_retention_minutes") or 10),
            1,
        )
    except (TypeError, ValueError):
        return _json_error("demo_retention_minutes must be a positive integer.", 400)
    
    if not project_id or not project_name or not project_nickname:
        return _json_error("project_id, project_name, and project_nickname are required.", 400)
        
    if err := _validate_entity_id(project_id, 6, "project_id"):
        return _json_error(err, 400)
        
    existing = db.session.get(VaProjectMaster, project_id)
    if existing:
        return _json_error("Project ID already exists.", 400)
        
    project = VaProjectMaster(
        project_id=project_id,
        project_code=project_code,
        project_name=project_name,
        project_nickname=project_nickname,
        project_status=VaStatuses.active,
        social_autopsy_enabled=bool(payload.get("social_autopsy_enabled", True)),
        coding_intake_mode="random_form_allocation",
        demo_training_enabled=bool(payload.get("demo_training_enabled", False)),
        demo_retention_minutes=demo_retention_minutes,
    )
    db.session.add(project)
    db.session.commit()
    return jsonify({"project": _serialize_project(project)}), 201


@admin.put("/api/projects/<project_id>")
@role_required("admin")
def admin_update_project(project_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
        
    project = db.session.get(VaProjectMaster, project_id)
    if not project:
        return _json_error("Project not found.", 404)
        
    payload = request.get_json(silent=True) or {}
    
    if "project_code" in payload:
        project.project_code = (payload["project_code"] or "").strip().upper() or project.project_id
        
    if "project_name" in payload:
        project_name = (payload["project_name"] or "").strip()
        if not project_name:
            return _json_error("project_name cannot be empty.", 400)
        project.project_name = project_name
        
    if "project_nickname" in payload:
        project_nickname = (payload["project_nickname"] or "").strip()
        if not project_nickname:
            return _json_error("project_nickname cannot be empty.", 400)
        project.project_nickname = project_nickname
        
    if "status" in payload:
        try:
            project.project_status = VaStatuses(payload["status"])
        except ValueError:
            return _json_error("Invalid status.", 400)

    if "narrative_qa_enabled" in payload:
        project.narrative_qa_enabled = bool(payload["narrative_qa_enabled"])

    if "social_autopsy_enabled" in payload:
        project.social_autopsy_enabled = bool(payload["social_autopsy_enabled"])

    if "coding_intake_mode" in payload:
        coding_intake_mode = (payload["coding_intake_mode"] or "").strip()
        if coding_intake_mode not in {
            "random_form_allocation",
            "pick_and_choose",
        }:
            return _json_error("Invalid coding_intake_mode.", 400)
        project.coding_intake_mode = coding_intake_mode

    if "demo_training_enabled" in payload:
        project.demo_training_enabled = bool(payload["demo_training_enabled"])

    if "demo_retention_minutes" in payload:
        try:
            demo_retention_minutes = int(payload["demo_retention_minutes"])
        except (TypeError, ValueError):
            return _json_error("demo_retention_minutes must be a positive integer.", 400)
        if demo_retention_minutes < 1:
            return _json_error("demo_retention_minutes must be a positive integer.", 400)
        project.demo_retention_minutes = demo_retention_minutes

    db.session.commit()
    return jsonify({"project": _serialize_project(project)})


@admin.post("/api/projects/<project_id>/toggle")
@role_required("admin")
def admin_toggle_project(project_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
        
    project = db.session.get(VaProjectMaster, project_id)
    if not project:
        return _json_error("Project not found.", 404)
        
    project.project_status = (
        VaStatuses.deactive
        if project.project_status == VaStatuses.active
        else VaStatuses.active
    )
    db.session.commit()
    return jsonify({
        "project_id": project.project_id,
        "status": project.project_status.value,
    })


@admin.get("/api/sites")
@role_required("admin", "project_pi")
def admin_sites():
    master = request.args.get("master") == "1"
    
    if master:
        if not current_user.is_admin():
            return _json_error("Admin access required.", 403)
        stmt = sa.select(VaSiteMaster)
        if request.args.get("include_inactive") != "1":
            stmt = stmt.where(VaSiteMaster.site_status == VaStatuses.active)
    else:
        project_id = request.args.get("project_id")
        stmt = (
            sa.select(VaSiteMaster)
            .join(VaProjectSites, VaProjectSites.site_id == VaSiteMaster.site_id)
            .where(
                VaSiteMaster.site_status == VaStatuses.active,
                VaProjectSites.project_site_status == VaStatuses.active,
            )
        )
        if project_id:
            if not _current_user_can_manage_project(project_id):
                return _json_error("You do not have access to that project.", 403)
            stmt = stmt.where(VaProjectSites.project_id == project_id)
        elif not current_user.is_admin():
            stmt = stmt.where(
                VaProjectSites.project_id.in_(list(current_user.get_project_pi_projects()))
            )
            
    sites = db.session.scalars(stmt.distinct().order_by(VaSiteMaster.site_id)).all()
    return jsonify({"sites": [_serialize_site(site) for site in sites]})


@admin.post("/api/sites")
@role_required("admin")
def admin_create_site():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
    payload = request.get_json(silent=True) or {}
    site_id = (payload.get("site_id") or "").strip().upper()
    site_name = (payload.get("site_name") or "").strip()
    site_abbr = (payload.get("site_abbr") or "").strip()
    
    if not site_id or not site_name or not site_abbr:
        return _json_error("site_id, site_name, and site_abbr are required.", 400)
        
    if err := _validate_entity_id(site_id, 4, "site_id"):
        return _json_error(err, 400)
        
    existing = db.session.get(VaSiteMaster, site_id)
    if existing:
        return _json_error("Site ID already exists.", 400)
        
    site = VaSiteMaster(
        site_id=site_id,
        site_name=site_name,
        site_abbr=site_abbr,
        site_status=VaStatuses.active
    )
    db.session.add(site)
    db.session.commit()
    return jsonify({"site": _serialize_site(site)}), 201


@admin.put("/api/sites/<site_id>")
@role_required("admin")
def admin_update_site(site_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
        
    site = db.session.get(VaSiteMaster, site_id)
    if not site:
        return _json_error("Site not found.", 404)
        
    payload = request.get_json(silent=True) or {}
    if "site_name" in payload:
        site_name = (payload["site_name"] or "").strip()
        if not site_name:
            return _json_error("site_name cannot be empty.", 400)
        site.site_name = site_name
        
    if "site_abbr" in payload:
        site_abbr = (payload["site_abbr"] or "").strip()
        if not site_abbr:
            return _json_error("site_abbr cannot be empty.", 400)
        site.site_abbr = site_abbr
        
    if "status" in payload:
        try:
            site.site_status = VaStatuses(payload["status"])
        except ValueError:
            return _json_error("Invalid status.", 400)
            
    db.session.commit()
    return jsonify({"site": _serialize_site(site)})


@admin.post("/api/sites/<site_id>/toggle")
@role_required("admin")
def admin_toggle_site(site_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
        
    site = db.session.get(VaSiteMaster, site_id)
    if not site:
        return _json_error("Site not found.", 404)
        
    site.site_status = (
        VaStatuses.deactive
        if site.site_status == VaStatuses.active
        else VaStatuses.active
    )
    db.session.commit()
    return jsonify({
        "site_id": site.site_id,
        "status": site.site_status.value,
    })


@admin.get("/api/project-sites")
@role_required("admin", "project_pi")
def admin_project_sites():
    project_id = request.args.get("project_id")
    stmt = (
        sa.select(
            VaProjectSites.project_site_id,
            VaProjectSites.project_id,
            VaProjectSites.site_id,
            VaProjectSites.project_site_status,
            VaProjectMaster.project_name,
            VaSiteMaster.site_name,
        )
        .join(VaProjectMaster, VaProjectMaster.project_id == VaProjectSites.project_id)
        .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
    )
    if project_id:
        if not _current_user_can_manage_project(project_id):
            return _json_error("You do not have access to that project.", 403)
        stmt = stmt.where(VaProjectSites.project_id == project_id)
    elif not current_user.is_admin():
        stmt = stmt.where(
            VaProjectSites.project_id.in_(list(current_user.get_project_pi_projects()))
        )
    include_inactive = request.args.get("include_inactive") == "1"
    if not include_inactive:
        stmt = stmt.where(VaProjectSites.project_site_status == VaStatuses.active)
    rows = db.session.execute(
        stmt.order_by(VaProjectSites.project_id, VaProjectSites.site_id)
    ).all()
    return jsonify({"project_sites": [_serialize_project_site(row) for row in rows]})


@admin.post("/api/project-sites")
@role_required("admin", "project_pi")
def admin_create_project_site():
    payload = request.get_json(silent=True) or {}
    project_id = payload.get("project_id")
    site_id = payload.get("site_id")
    if not project_id or not site_id:
        return _json_error("project_id and site_id are required.", 400)
    if not _current_user_can_manage_project(project_id):
        return _json_error("You do not have access to that project.", 403)

    project = db.session.get(VaProjectMaster, project_id)
    site = db.session.get(VaSiteMaster, site_id)
    if not project or project.project_status != VaStatuses.active:
        return _json_error("Active project not found.", 404)
    if not site or site.site_status != VaStatuses.active:
        return _json_error("Active site not found.", 404)

    mapping = db.session.scalar(
        sa.select(VaProjectSites).where(
            VaProjectSites.project_id == project_id,
            VaProjectSites.site_id == site_id,
        )
    )
    status_code = 201
    if mapping:
        if mapping.project_site_status != VaStatuses.active:
            mapping.project_site_status = VaStatuses.active
        status_code = 200
    else:
        mapping = VaProjectSites(
            project_id=project_id,
            site_id=site_id,
            project_site_status=VaStatuses.active,
        )
        db.session.add(mapping)
    db.session.commit()
    db.session.refresh(mapping)
    row = db.session.execute(
        sa.select(
            VaProjectSites.project_site_id,
            VaProjectSites.project_id,
            VaProjectSites.site_id,
            VaProjectSites.project_site_status,
            VaProjectMaster.project_name,
            VaSiteMaster.site_name,
        )
        .join(VaProjectMaster, VaProjectMaster.project_id == VaProjectSites.project_id)
        .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
        .where(VaProjectSites.project_site_id == mapping.project_site_id)
    ).one()
    return jsonify({"project_site": _serialize_project_site(row)}), status_code


@admin.post("/api/project-sites/<uuid:project_site_id>/toggle")
@role_required("admin", "project_pi")
def admin_toggle_project_site(project_site_id):
    mapping = db.session.get(VaProjectSites, project_site_id)
    if not mapping:
        return _json_error("Project-site mapping not found.", 404)
    if not _current_user_can_manage_project(mapping.project_id):
        return _json_error("You do not have access to that project.", 403)
    mapping.project_site_status = (
        VaStatuses.deactive
        if mapping.project_site_status == VaStatuses.active
        else VaStatuses.active
    )
    db.session.commit()
    return jsonify({
        "project_site_id": str(mapping.project_site_id),
        "status": mapping.project_site_status.value,
    })


def _serialize_user(user):
    return {
        "user_id": str(user.user_id),
        "email": user.email,
        "name": user.name,
        "status": user.user_status.value,
        "email_verified": bool(user.email_verified),
        "phone": user.phone,
        "landing_page": user.landing_page,
        "languages": user.vacode_language or [],
        "is_admin": user.is_admin(),
    }


@admin.get("/api/users")
@role_required("admin", "project_pi")
def admin_users():
    query = (request.args.get("query") or "").strip()
    master = request.args.get("master") == "1"
    
    stmt = sa.select(VaUsers)
    
    if master:
        if not current_user.is_admin():
            return _json_error("Admin access required.", 403)
        if request.args.get("include_inactive") != "1":
            stmt = stmt.where(VaUsers.user_status == VaStatuses.active)
    else:
        stmt = stmt.where(VaUsers.user_status == VaStatuses.active)
        
    if query:
        pattern = f"%{query}%"
        stmt = stmt.where(
            sa.or_(VaUsers.email.ilike(pattern), VaUsers.name.ilike(pattern))
        )
        
    users = db.session.scalars(stmt.order_by(VaUsers.email).limit(25 if not master else None)).all()
    return jsonify({"users": [_serialize_user(u) for u in users]})


@admin.post("/api/users")
@role_required("admin")
def admin_create_user():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
    from app.models.mas_languages import MasLanguages

    payload = request.get_json(silent=True) or {}
    email = (payload.get("email") or "").strip().lower()
    email_confirm = (payload.get("email_confirm") or "").strip().lower()
    name = (payload.get("name") or "").strip()
    phone = (payload.get("phone") or "").strip()
    languages = payload.get("languages")
    
    if not email or not email_confirm or not name:
        return _json_error("email, email_confirm, and name are required.", 400)
    if email != email_confirm:
        return _json_error("Email confirmation does not match.", 400)
    if not isinstance(languages, list) or not languages:
        return _json_error("At least one language must be selected.", 400)

    valid_codes = set(
        db.session.scalars(
            sa.select(MasLanguages.language_code).where(MasLanguages.is_active == True)
        ).all()
    )
    invalid = [code for code in languages if code not in valid_codes]
    if invalid:
        return _json_error(f"Invalid language codes: {invalid}", 400)
        
    existing = db.session.scalar(sa.select(VaUsers).where(VaUsers.email == email))
    if existing:
        return _json_error("Email already in use.", 400)
        
    new_user = VaUsers(
        email=email,
        name=name,
        phone=phone or None,
        user_status=VaStatuses.active,
        vacode_language=languages,
        permission={},
        landing_page="coder",
        pw_reset_t_and_c=False,
        email_verified=False
    )
    # Invite-only onboarding: user sets their own password via reset link.
    new_user.set_password(secrets.token_urlsafe(32))

    db.session.add(new_user)
    db.session.commit()

    # Send verification + password-setup emails (async via Celery).
    try:
        from app.services.token_service import generate_token
        from app.services.email_service import (
            send_verification_email,
            send_password_reset_email,
        )
        verify_token = generate_token(new_user.user_id, "email_verify")
        reset_token = generate_token(new_user.user_id, "password_reset")
        send_verification_email(new_user, verify_token)
        send_password_reset_email(new_user, reset_token)
    except Exception:
        pass  # non-critical — user can request resend/reset

    return jsonify({"user": _serialize_user(new_user)}), 201


@admin.put("/api/users/<uuid:target_user_id>")
@role_required("admin")
def admin_update_user(target_user_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
    from app.models.mas_languages import MasLanguages

    target_user = db.session.get(VaUsers, target_user_id)
    if not target_user:
        return _json_error("User not found.", 404)
        
    payload = request.get_json(silent=True) or {}
    
    if "name" in payload:
        name = (payload["name"] or "").strip()
        if not name:
            return _json_error("Name cannot be empty.", 400)
        target_user.name = name
        
    if "phone" in payload:
        target_user.phone = (payload["phone"] or "").strip() or None
        
    if "status" in payload:
        try:
            target_user.user_status = VaStatuses(payload["status"])
        except ValueError:
            return _json_error("Invalid status.", 400)
            
    if payload.get("password"):
        from app.utils.password_policy import password_error_message
        pw_err = password_error_message(payload["password"])
        if pw_err:
            return _json_error(pw_err, 400)
        target_user.set_password(payload["password"])

    if "languages" in payload:
        languages = payload.get("languages")
        if not isinstance(languages, list) or not languages:
            return _json_error("At least one language must be selected.", 400)
        valid_codes = set(
            db.session.scalars(
                sa.select(MasLanguages.language_code).where(
                    MasLanguages.is_active == True
                )
            ).all()
        )
        invalid = [code for code in languages if code not in valid_codes]
        if invalid:
            return _json_error(f"Invalid language codes: {invalid}", 400)
        target_user.vacode_language = languages
        
    db.session.commit()
    return jsonify({"user": _serialize_user(target_user)})


@admin.post("/api/users/<uuid:target_user_id>/toggle")
@role_required("admin")
def admin_toggle_user(target_user_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)
        
    target_user = db.session.get(VaUsers, target_user_id)
    if not target_user:
        return _json_error("User not found.", 404)
        
    if target_user.user_id == current_user.user_id:
        return _json_error("You cannot deactivate yourself.", 400)
        
    target_user.user_status = (
        VaStatuses.deactive
        if target_user.user_status == VaStatuses.active
        else VaStatuses.active
    )
    db.session.commit()
    return jsonify({
        "user_id": str(target_user.user_id),
        "status": target_user.user_status.value,
    })


@admin.post("/api/users/<uuid:target_user_id>/toggle-admin")
@role_required("admin")
def admin_toggle_user_admin(target_user_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    target_user = db.session.get(VaUsers, target_user_id)
    if not target_user:
        return _json_error("User not found.", 404)

    if target_user.user_id == current_user.user_id:
        return _json_error("You cannot change your own admin status.", 400)

    from app.models.va_user_access_grants import VaUserAccessGrants
    from app.models.va_selectives import VaAccessRoles, VaAccessScopeTypes

    grant = db.session.scalar(
        sa.select(VaUserAccessGrants).where(
            VaUserAccessGrants.user_id == target_user.user_id,
            VaUserAccessGrants.role == VaAccessRoles.admin,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.global_scope,
        )
    )

    if grant and grant.grant_status == VaStatuses.active:
        grant.grant_status = VaStatuses.deactive
        is_admin = False
    else:
        if grant is None:
            grant = VaUserAccessGrants(
                user_id=target_user.user_id,
                role=VaAccessRoles.admin,
                scope_type=VaAccessScopeTypes.global_scope,
                grant_status=VaStatuses.active,
                notes="toggled via admin panel",
            )
            db.session.add(grant)
        else:
            grant.grant_status = VaStatuses.active
        is_admin = True

    db.session.commit()
    return jsonify({
        "user_id": str(target_user.user_id),
        "is_admin": is_admin,
    })


@admin.get("/api/access-grants")
@role_required("admin", "project_pi")
def admin_access_grants():
    project_id_expression = _grant_project_id_expression()
    site_id_expression = _grant_site_id_expression()
    stmt = (
        sa.select(
            VaUserAccessGrants.grant_id,
            VaUserAccessGrants.user_id,
            VaUserAccessGrants.role,
            VaUserAccessGrants.scope_type,
            VaUserAccessGrants.project_site_id,
            VaUserAccessGrants.grant_status,
            VaUserAccessGrants.notes,
            VaUsers.email,
            VaUsers.name,
            project_id_expression.label("resolved_project_id"),
            site_id_expression.label("resolved_site_id"),
        )
        .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
        .outerjoin(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        )
        .where(
            VaUserAccessGrants.grant_status == VaStatuses.active,
            _project_access_filter(project_id_expression),
        )
    )
    project_id = request.args.get("project_id")
    if project_id:
        if not _current_user_can_manage_project(project_id):
            return _json_error("You do not have access to that project.", 403)
        stmt = stmt.where(project_id_expression == project_id)
    role = request.args.get("role")
    if role:
        if role not in {member.value for member in VaAccessRoles}:
            return _json_error("Invalid role.", 400)
        stmt = stmt.where(VaUserAccessGrants.role == VaAccessRoles(role))
    user_id = request.args.get("user_id")
    if user_id:
        try:
            stmt = stmt.where(VaUserAccessGrants.user_id == uuid.UUID(user_id))
        except (ValueError, TypeError):
            return _json_error("Invalid user_id.", 400)
    rows = db.session.execute(
        stmt.order_by(project_id_expression, site_id_expression, VaUsers.email)
    ).all()
    return jsonify({"grants": [_serialize_grant(row) for row in rows]})


@admin.get("/api/access-grants/orphaned")
@role_required("admin", "project_pi")
def admin_orphaned_grants():
    project_id_expression = _grant_project_id_expression()
    site_id_expression = _grant_site_id_expression()
    
    stmt = (
        sa.select(
            VaUserAccessGrants.grant_id,
            VaUserAccessGrants.user_id,
            VaUserAccessGrants.role,
            VaUserAccessGrants.scope_type,
            VaUserAccessGrants.project_site_id,
            VaUserAccessGrants.grant_status,
            VaUserAccessGrants.notes,
            VaUsers.email,
            VaUsers.name,
            project_id_expression.label("resolved_project_id"),
            site_id_expression.label("resolved_site_id"),
        )
        .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
        .outerjoin(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        )
        .where(
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
            sa.or_(
                VaProjectSites.project_site_id == None,
                VaProjectSites.project_site_status == VaStatuses.deactive
            ),
            _project_access_filter(project_id_expression),
        )
    )
    
    project_id = request.args.get("project_id")
    if project_id:
        if not _current_user_can_manage_project(project_id):
            return _json_error("You do not have access to that project.", 403)
        stmt = stmt.where(project_id_expression == project_id)
        
    rows = db.session.execute(
        stmt.order_by(project_id_expression, site_id_expression, VaUsers.email)
    ).all()
    return jsonify({"grants": [_serialize_grant(row) for row in rows]})


@admin.post("/api/access-grants")
@role_required("admin", "project_pi")
def admin_create_access_grant():
    payload = request.get_json(silent=True) or {}
    user_id_value = payload.get("user_id")
    if not user_id_value:
        return _json_error("user_id is required.", 400)
    try:
        user_id = uuid.UUID(user_id_value)
    except (ValueError, TypeError):
        return _json_error("Invalid user_id.", 400)

    target_user = db.session.get(VaUsers, user_id)
    if not target_user or target_user.user_status != VaStatuses.active:
        return _json_error("Active user not found.", 404)

    try:
        role, scope_type, resolved_project_id, project_site_id = _resolve_scope_from_payload(
            payload
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)

    if scope_type == VaAccessScopeTypes.project:
        project = db.session.get(VaProjectMaster, resolved_project_id)
        if not project or project.project_status != VaStatuses.active:
            return _json_error("Active project not found.", 404)

    if not current_user.is_admin():
        if role in {VaAccessRoles.admin, VaAccessRoles.project_pi}:
            return _json_error("Project PI may not manage admin or project_pi grants.", 403)
        if not _current_user_can_manage_project(resolved_project_id):
            return _json_error("You do not have access to that project.", 403)

    status_code = 201
    existing = None
    if scope_type == VaAccessScopeTypes.global_scope:
        existing = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == user_id,
                VaUserAccessGrants.role == role,
                VaUserAccessGrants.scope_type == scope_type,
            )
        )
    elif scope_type == VaAccessScopeTypes.project:
        existing = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == user_id,
                VaUserAccessGrants.role == role,
                VaUserAccessGrants.scope_type == scope_type,
                VaUserAccessGrants.project_id == resolved_project_id,
            )
        )
    else:
        existing = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == user_id,
                VaUserAccessGrants.role == role,
                VaUserAccessGrants.scope_type == scope_type,
                VaUserAccessGrants.project_site_id == project_site_id,
            )
        )

    if existing:
        existing.grant_status = VaStatuses.active
        existing.notes = payload.get("notes") or existing.notes
        grant = existing
        status_code = 200
    else:
        grant = VaUserAccessGrants(
            user_id=user_id,
            role=role,
            scope_type=scope_type,
            project_id=resolved_project_id
            if scope_type == VaAccessScopeTypes.project
            else None,
            project_site_id=project_site_id,
            notes=payload.get("notes"),
            grant_status=VaStatuses.active,
        )
        db.session.add(grant)

    db.session.commit()
    row = db.session.execute(
        sa.select(
            VaUserAccessGrants.grant_id,
            VaUserAccessGrants.user_id,
            VaUserAccessGrants.role,
            VaUserAccessGrants.scope_type,
            VaUserAccessGrants.project_site_id,
            VaUserAccessGrants.grant_status,
            VaUserAccessGrants.notes,
            VaUsers.email,
            VaUsers.name,
            _grant_project_id_expression().label("resolved_project_id"),
            _grant_site_id_expression().label("resolved_site_id"),
        )
        .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
        .outerjoin(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        )
        .where(VaUserAccessGrants.grant_id == grant.grant_id)
    ).one()
    return jsonify({"grant": _serialize_grant(row)}), status_code


@admin.post("/api/access-grants/<uuid:grant_id>/toggle")
@role_required("admin", "project_pi")
def admin_toggle_access_grant(grant_id):
    grant = db.session.get(VaUserAccessGrants, grant_id)
    if not grant:
        return _json_error("Grant not found.", 404)

    if grant.scope_type == VaAccessScopeTypes.project:
        resolved_project_id = grant.project_id
    elif grant.scope_type == VaAccessScopeTypes.project_site:
        project_site = db.session.get(VaProjectSites, grant.project_site_id)
        resolved_project_id = project_site.project_id if project_site else None
    else:
        resolved_project_id = None

    if not current_user.is_admin():
        if grant.role in {VaAccessRoles.admin, VaAccessRoles.project_pi}:
            return _json_error("Project PI may not manage admin or project_pi grants.", 403)
        if not resolved_project_id or not _current_user_can_manage_project(
            resolved_project_id
        ):
            return _json_error("This operation is not permitted for this resource.", 403)

    grant.grant_status = (
        VaStatuses.deactive
        if grant.grant_status == VaStatuses.active
        else VaStatuses.active
    )
    db.session.commit()

    return jsonify({"grant_id": str(grant.grant_id), "status": grant.grant_status.value})


# ---------------------------------------------------------------------------
# Admin UI shell and panel routes
# ---------------------------------------------------------------------------


@admin.get("/", strict_slashes=False)
@role_required("admin", "project_pi")
def admin_index():
    return render_template("admin/admin_index.html")


@admin.get("/panels/access-grants")
@role_required("admin", "project_pi")
def admin_panel_access_grants():
    project_id = request.args.get("project_id") or ""
    return render_template("admin/panels/access_grants.html", project_id=project_id)


@admin.get("/panels/project-sites")
@role_required("admin", "project_pi")
def admin_panel_project_sites():
    project_id = request.args.get("project_id") or ""
    return render_template("admin/panels/project_sites.html", project_id=project_id)


@admin.get("/panels/project-forms")
@role_required("admin")
def admin_panel_project_forms():
    from app.utils import smartva_allowed_countries
    return render_template(
        "admin/panels/project_forms.html",
        smartva_countries=smartva_allowed_countries,
    )


@admin.get("/panels/projects")
@role_required("admin")
def admin_panel_projects():
    return render_template("admin/panels/projects.html")


@admin.get("/panels/sites")
@role_required("admin")
def admin_panel_sites():
    return render_template("admin/panels/sites.html")


@admin.get("/panels/users")
@role_required("admin")
def admin_panel_users():
    from app.models.mas_languages import MasLanguages

    languages = db.session.scalars(
        sa.select(MasLanguages)
        .where(MasLanguages.is_active == True)
        .order_by(MasLanguages.language_name)
    ).all()
    return render_template(
        "admin/panels/users.html",
        available_languages=[
            {"code": language.language_code, "name": language.language_name}
            for language in languages
        ],
    )


@admin.get("/panels/project-pi")
@role_required("admin")
def admin_panel_project_pi():
    return render_template("admin/panels/project_pi.html")


@admin.get("/panels/languages")
@role_required("admin")
def admin_panel_languages():
    return render_template("admin/panels/languages.html")


@admin.get("/panels/odk-connections")
@role_required("admin")
def admin_panel_odk_connections():
    return render_template("admin/panels/odk_connections.html")


# ---------------------------------------------------------------------------
# Field Mapping Admin  (admin-only)
# ---------------------------------------------------------------------------

@admin.get("/api/form-types/<form_type_code>/categories/<category_code>/subcategories")
@role_required("admin")
def admin_form_type_subcategories(form_type_code, category_code):
    """Return subcategories for a given form type + category."""
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    state = _serialize_category_browser_state(form_type, category_code)
    if not state:
        return _json_error("Category not found.", 404)
    return jsonify({"subcategories": state["subcategories"]})


@admin.get("/api/form-types/<form_type_code>/categories/<category_code>/browser-state")
@role_required("admin")
def admin_form_type_category_browser_state(form_type_code, category_code):
    """Return full browser state for one category in the 3-panel UI."""
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    state = _serialize_category_browser_state(form_type, category_code)
    if not state:
        return _json_error("Category not found.", 404)
    return jsonify(state)


@admin.post("/api/form-types/<form_type_code>/categories/<category_code>/fields/reorder")
@role_required("admin")
def admin_category_fields_reorder(form_type_code, category_code):
    """Persist ordered field_ids for a category browser selection."""
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes, MasFieldDisplayConfig

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    data = request.get_json(silent=True) or {}
    field_ids = data.get("field_ids") or []
    if not isinstance(field_ids, list) or not field_ids:
        return _json_error("field_ids must be a non-empty list.", 400)

    fields = db.session.scalars(
        sa_select(MasFieldDisplayConfig).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.field_id.in_(field_ids),
        )
    ).all()
    field_by_id = {field.field_id: field for field in fields}
    if len(field_by_id) != len(set(field_ids)):
        return _json_error("One or more field_ids were not found.", 404)

    for index, field_id in enumerate(field_ids, start=1):
        field = field_by_id[field_id]
        if field.category_code != category_code:
            return _json_error("All field_ids must belong to the selected category.", 400)
        field.display_order = Decimal(index * 10)

    db.session.commit()

    from app.services.field_mapping_service import get_mapping_service
    get_mapping_service().clear_cache()

    state = _serialize_category_browser_state(form_type, category_code)
    return jsonify(state)


@admin.post("/api/form-types/<form_type_code>/fields/<field_id>/move")
@role_required("admin")
def admin_field_move_to_subcategory(form_type_code, field_id):
    """Move a field to a category/subcategory and append it to that target bucket."""
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes, MasFieldDisplayConfig
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    field = db.session.scalar(
        sa_select(MasFieldDisplayConfig).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.field_id == field_id,
        )
    )
    if not field:
        return _json_error("Field not found.", 404)

    data = request.get_json(silent=True) or {}
    category_code = (data.get("category_code") or "").strip()
    subcategory_code = data.get("subcategory_code")
    if isinstance(subcategory_code, str):
        subcategory_code = subcategory_code.strip() or None

    if not category_code:
        return _json_error("category_code is required.", 400)

    category = db.session.scalar(
        sa_select(MasCategoryDisplayConfig).where(
            MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
            MasCategoryDisplayConfig.category_code == category_code,
            MasCategoryDisplayConfig.is_active == True,
        )
    )
    if not category:
        return _json_error("Category not found.", 404)

    if subcategory_code:
        subcategory = db.session.scalar(
            sa_select(MasSubcategoryOrder).where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == category_code,
                MasSubcategoryOrder.subcategory_code == subcategory_code,
            )
        )
        if not subcategory:
            return _json_error("Subcategory not found.", 404)

    max_order = db.session.scalar(
        sa.select(sa.func.max(MasFieldDisplayConfig.display_order)).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.category_code == category_code,
            MasFieldDisplayConfig.subcategory_code == subcategory_code,
        )
    )

    field.category_code = category_code
    field.subcategory_code = subcategory_code
    field.display_order = Decimal(max_order or 0) + Decimal("10")
    db.session.commit()

    from app.services.field_mapping_service import get_mapping_service
    get_mapping_service().clear_cache()

    state = _serialize_category_browser_state(form_type, category_code)
    return jsonify(state)


@admin.get("/api/form-types/<form_type_code>/fields/search")
@role_required("admin")
def admin_form_type_fields_search(form_type_code):
    """Search available fields for assignment into the category browser."""
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes, MasFieldDisplayConfig

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    search = request.args.get("q", "").strip()
    if len(search) < 2:
        return jsonify({"fields": []})

    fields = db.session.scalars(
        sa_select(MasFieldDisplayConfig)
        .where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.is_active == True,
            sa.or_(
                MasFieldDisplayConfig.field_id.ilike(f"%{search}%"),
                MasFieldDisplayConfig.short_label.ilike(f"%{search}%"),
            ),
        )
        .order_by(MasFieldDisplayConfig.field_id)
        .limit(25)
    ).all()

    return jsonify({
        "fields": [
            {
                "field_id": field.field_id,
                "label": field.short_label or field.field_id,
                "category_code": field.category_code,
                "subcategory_code": field.subcategory_code,
            }
            for field in fields
        ]
    })


# --- Category CRUD ---

@admin.post("/api/form-types/<form_type_code>/categories")
@role_required("admin")
def admin_category_create(form_type_code):
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasCategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    data = request.get_json(silent=True) or {}
    code = (data.get("category_code") or "").strip()
    name = (data.get("category_name") or "").strip() or None
    order = data.get("display_order")
    render_mode = (data.get("render_mode") or "default").strip() or "default"

    if not code:
        return _json_error("category_code is required.", 400)

    existing = db.session.scalar(
        sa_select(MasCategoryDisplayConfig).where(
            MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
            MasCategoryDisplayConfig.category_code == code,
        )
    )
    if existing:
        return _json_error("Category code already exists for this form type.", 409)

    if order is None:
        max_row = db.session.scalar(
            sa.select(sa.func.max(MasCategoryDisplayConfig.display_order)).where(
                MasCategoryDisplayConfig.form_type_id == form_type.form_type_id
            )
        )
        order = (max_row or 0) + 10

    cat = MasCategoryOrder(
        form_type_id=form_type.form_type_id,
        category_code=code,
        category_name=name,
        display_order=int(order),
    )
    db.session.add(cat)
    db.session.add(
        MasCategoryDisplayConfig(
            form_type_id=form_type.form_type_id,
            category_code=code,
            display_label=name or code,
            nav_label=name or code,
            display_order=int(order),
            render_mode=render_mode if render_mode != "default" else "table_sections",
        )
    )
    db.session.commit()
    return jsonify({
        "category": {
            "category_code": cat.category_code,
            "category_name": cat.category_name,
            "display_order": cat.display_order,
        }
    }), 201


@admin.put("/api/form-types/<form_type_code>/categories/<category_code>")
@role_required("admin")
def admin_category_update(form_type_code, category_code):
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasCategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    display_cfg = db.session.scalar(
        sa_select(MasCategoryDisplayConfig).where(
            MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
            MasCategoryDisplayConfig.category_code == category_code,
        )
    )
    if not display_cfg:
        return _json_error("Category not found.", 404)

    cat = db.session.scalar(
        sa_select(MasCategoryOrder).where(
            MasCategoryOrder.form_type_id == form_type.form_type_id,
            MasCategoryOrder.category_code == category_code,
        )
    )

    data = request.get_json(silent=True) or {}
    old_name = display_cfg.display_label
    if "category_name" in data:
        new_name = (data["category_name"] or "").strip() or None
        if cat:
            cat.category_name = new_name
        new_label = new_name or category_code
        if not display_cfg.display_label or display_cfg.display_label in {old_name, category_code}:
            display_cfg.display_label = new_label
        if not display_cfg.nav_label or display_cfg.nav_label in {old_name, category_code}:
            display_cfg.nav_label = new_label
    if "display_order" in data:
        try:
            new_order = int(data["display_order"])
        except (TypeError, ValueError):
            return _json_error("display_order must be an integer.", 400)
        display_cfg.display_order = new_order
        if cat:
            cat.display_order = new_order

    db.session.commit()
    return jsonify({
        "category": {
            "category_code": display_cfg.category_code,
            "category_name": display_cfg.display_label,
            "display_order": display_cfg.display_order,
        }
    })


@admin.delete("/api/form-types/<form_type_code>/categories/<category_code>")
@role_required("admin")
def admin_category_delete(form_type_code, category_code):
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasCategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    display_cfg = db.session.scalar(
        sa_select(MasCategoryDisplayConfig).where(
            MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
            MasCategoryDisplayConfig.category_code == category_code,
        )
    )
    if not display_cfg:
        return _json_error("Category not found.", 404)

    cat = db.session.scalar(
        sa_select(MasCategoryOrder).where(
            MasCategoryOrder.form_type_id == form_type.form_type_id,
            MasCategoryOrder.category_code == category_code,
        )
    )

    db.session.delete(display_cfg)
    if cat:
        db.session.delete(cat)
    db.session.commit()
    return jsonify({"deleted": True})


# --- Subcategory CRUD ---

@admin.post("/api/form-types/<form_type_code>/categories/<category_code>/subcategories")
@role_required("admin")
def admin_subcategory_create(form_type_code, category_code):
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    cat = db.session.scalar(
        sa_select(MasCategoryDisplayConfig).where(
            MasCategoryDisplayConfig.form_type_id == form_type.form_type_id,
            MasCategoryDisplayConfig.category_code == category_code,
            MasCategoryDisplayConfig.is_active == True,
        )
    )
    if not cat:
        return _json_error("Category not found.", 404)

    data = request.get_json(silent=True) or {}
    code = (data.get("subcategory_code") or "").strip()
    name = (data.get("subcategory_name") or "").strip() or None
    order = data.get("display_order")

    if not code:
        return _json_error("subcategory_code is required.", 400)

    existing = db.session.scalar(
        sa_select(MasSubcategoryOrder).where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id,
            MasSubcategoryOrder.category_code == category_code,
            MasSubcategoryOrder.subcategory_code == code,
        )
    )
    if existing:
        return _json_error("Subcategory code already exists.", 409)

    if order is None:
        max_row = db.session.scalar(
            sa.select(sa.func.max(MasSubcategoryOrder.display_order)).where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == category_code,
            )
        )
        order = (max_row or 0) + 10

    sub = MasSubcategoryOrder(
        form_type_id=form_type.form_type_id,
        category_code=category_code,
        subcategory_code=code,
        subcategory_name=name,
        display_order=int(order),
        render_mode=render_mode,
    )
    db.session.add(sub)
    db.session.commit()
    return jsonify({
        "subcategory": {
            "subcategory_code": sub.subcategory_code,
            "subcategory_name": sub.subcategory_name,
            "display_order": sub.display_order,
            "render_mode": sub.render_mode,
        }
    }), 201


@admin.put("/api/form-types/<form_type_code>/categories/<category_code>/subcategories/<subcategory_code>")
@role_required("admin")
def admin_subcategory_update(form_type_code, category_code, subcategory_code):
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    sub = db.session.scalar(
        sa_select(MasSubcategoryOrder).where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id,
            MasSubcategoryOrder.category_code == category_code,
            MasSubcategoryOrder.subcategory_code == subcategory_code,
        )
    )
    if not sub:
        return _json_error("Subcategory not found.", 404)

    data = request.get_json(silent=True) or {}
    if "subcategory_name" in data:
        sub.subcategory_name = (data["subcategory_name"] or "").strip() or None
    if "display_order" in data:
        try:
            sub.display_order = int(data["display_order"])
        except (TypeError, ValueError):
            return _json_error("display_order must be an integer.", 400)
    if "render_mode" in data:
        sub.render_mode = (data["render_mode"] or "default").strip() or "default"

    db.session.commit()
    return jsonify({
        "subcategory": {
            "subcategory_code": sub.subcategory_code,
            "subcategory_name": sub.subcategory_name,
            "display_order": sub.display_order,
            "render_mode": sub.render_mode,
        }
    })


@admin.delete("/api/form-types/<form_type_code>/categories/<category_code>/subcategories/<subcategory_code>")
@role_required("admin")
def admin_subcategory_delete(form_type_code, category_code, subcategory_code):
    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    from app.models.va_field_mapping import MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return _json_error("Form type not found.", 404)

    sub = db.session.scalar(
        sa_select(MasSubcategoryOrder).where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id,
            MasSubcategoryOrder.category_code == category_code,
            MasSubcategoryOrder.subcategory_code == subcategory_code,
        )
    )
    if not sub:
        return _json_error("Subcategory not found.", 404)

    db.session.delete(sub)
    db.session.commit()
    return jsonify({"deleted": True})


@admin.get("/api/form-types")
@role_required("admin")
def admin_form_types_list():
    """Return all active form types (code + name)."""
    from app.services.form_type_service import get_form_type_service
    svc = get_form_type_service()
    return jsonify({
        "form_types": [
            {
                "form_type_id": str(ft.form_type_id),
                "form_type_code": ft.form_type_code,
                "form_type_name": ft.form_type_name,
            }
            for ft in svc.list_form_types()
        ]
    })


@admin.post("/api/form-types")
@role_required("admin")
def admin_form_types_create():
    """Create a new blank form type."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.services.form_type_service import get_form_type_service
    data = request.get_json(silent=True) or {}
    code = (data.get("form_type_code") or "").strip().upper()
    name = (data.get("form_type_name") or "").strip()
    description = (data.get("description") or "").strip() or None

    if not code or not name:
        return _json_error("form_type_code and form_type_name are required.", 400)

    try:
        ft = get_form_type_service().register_form_type(code, name, description)
        return jsonify({"form_type_code": ft.form_type_code, "form_type_name": ft.form_type_name}), 201
    except ValueError as e:
        return _json_error(str(e), 409)


@admin.patch("/api/form-types/<form_type_code>")
@role_required("admin")
def admin_form_types_update(form_type_code):
    """Update a form type's name and description."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.models import MasFormTypes
    ft = db.session.scalar(
        sa.select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not ft:
        return _json_error("Form type not found.", 404)

    data = request.get_json(silent=True) or {}
    name = (data.get("form_type_name") or "").strip()
    description = (data.get("description") or "").strip() or None

    if not name:
        return _json_error("form_type_name is required.", 400)

    ft.form_type_name = name
    ft.form_type_description = description
    db.session.commit()
    return jsonify({"form_type_code": ft.form_type_code, "form_type_name": ft.form_type_name})


@admin.post("/api/form-types/<source_code>/duplicate")
@role_required("admin")
def admin_form_types_duplicate(source_code):
    """Duplicate a form type — copies all fields, categories, and choices."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.services.form_type_service import get_form_type_service
    data = request.get_json(silent=True) or {}
    new_code = (data.get("new_code") or "").strip().upper()
    new_name = (data.get("new_name") or "").strip()
    description = (data.get("description") or "").strip() or None

    if not new_code or not new_name:
        return _json_error("new_code and new_name are required.", 400)

    try:
        ft = get_form_type_service().duplicate_form_type(
            source_code.upper(), new_code, new_name, description
        )
        return jsonify({"form_type_code": ft.form_type_code, "form_type_name": ft.form_type_name}), 201
    except ValueError as e:
        return _json_error(str(e), 409)


@admin.get("/api/form-types/<form_type_code>/export")
@role_required("admin")
def admin_form_types_export(form_type_code):
    """Download a form type configuration as a JSON file."""
    from flask import Response
    from app.services.form_type_service import get_form_type_service
    import json

    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    try:
        data = get_form_type_service().export_form_type(form_type_code.upper())
    except ValueError as e:
        return _json_error(str(e), 404)

    from decimal import Decimal

    class _Encoder(json.JSONEncoder):
        def default(self, o):
            if isinstance(o, Decimal):
                return int(o) if o == o.to_integral_value() else float(o)
            return super().default(o)

    filename = f"form_type_{form_type_code.lower()}.json"
    return Response(
        json.dumps(data, indent=2, ensure_ascii=False, cls=_Encoder),
        mimetype="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@admin.post("/api/form-types/import")
@role_required("admin")
def admin_form_types_import():
    """Import a form type from an uploaded JSON file."""
    import json

    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    uploaded = request.files.get("file")
    if not uploaded:
        return _json_error("No file uploaded.", 400)

    try:
        raw = uploaded.read()
        if len(raw) > 10 * 1024 * 1024:  # 10 MB safety cap
            return _json_error("File too large (max 10 MB).", 400)
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return _json_error("Invalid JSON file.", 400)

    override_code = (request.form.get("override_code") or "").strip().upper() or None
    override_name = (request.form.get("override_name") or "").strip() or None
    override_description = request.form.get("override_description")
    if override_description is not None:
        override_description = override_description.strip() or None

    from app.services.form_type_service import get_form_type_service
    try:
        ft, stats = get_form_type_service().import_form_type(
            data,
            override_code=override_code,
            override_name=override_name,
            override_description=override_description,
        )
    except ValueError as e:
        return _json_error(str(e), 409)

    return jsonify({
        "form_type_code": ft.form_type_code,
        "form_type_name": ft.form_type_name,
        **stats,
    }), 201


@admin.get("/panels/field-mapping")
@role_required("admin")
def admin_panel_field_mapping():
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from app.services.form_type_service import get_form_type_service
    svc = get_form_type_service()
    form_types = svc.list_form_types()
    stats = [svc.get_form_type_stats(ft.form_type_code) for ft in form_types]
    return render_template(
        "admin/panels/field_mapping.html",
        form_types=form_types,
        stats=stats,
    )


@admin.get("/panels/field-mapping/fields")
@role_required("admin")
def admin_panel_field_mapping_fields():
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from sqlalchemy import select as sa_select
    from sqlalchemy.orm import aliased
    from app.models import MasFieldDisplayConfig, MasFormTypes
    from app.models.va_field_mapping import MasCategoryDisplayConfig, MasSubcategoryOrder

    form_type_code = request.args.get("form_type", "WHO_2022_VA")
    category_filter = request.args.get("category", "")
    subcategory_filter = request.args.get("subcategory", "")
    search = request.args.get("search", "").strip()
    flag_filters = set(request.args.getlist("flag")) & {"flip", "info", "summary", "pii"}
    no_category = request.args.get("no_category", "") == "1"

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    # Load ordered categories and subcategories for filter dropdowns
    cats = _get_ordered_category_configs_for_form_type(form_type.form_type_id)

    subcats_for_filter = []
    if category_filter:
        subcats_for_filter = db.session.scalars(
            sa_select(MasSubcategoryOrder)
            .where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == category_filter,
                MasSubcategoryOrder.is_active == True,
            )
            .order_by(MasSubcategoryOrder.display_order)
        ).all()

    # Build lookup maps for display in table
    cat_name_map = {c.category_code: c.display_label or c.category_code for c in cats}
    all_subcats = db.session.scalars(
        sa_select(MasSubcategoryOrder)
        .where(
            MasSubcategoryOrder.form_type_id == form_type.form_type_id,
            MasSubcategoryOrder.is_active == True,
        )
    ).all()
    subcat_name_map = {
        (s.category_code, s.subcategory_code): s.subcategory_name or s.subcategory_code
        for s in all_subcats
    }

    cat_order = aliased(MasCategoryDisplayConfig)
    subcat_order = aliased(MasSubcategoryOrder)

    query = (
        sa_select(MasFieldDisplayConfig)
        .outerjoin(
            cat_order,
            sa.and_(
                cat_order.form_type_id == MasFieldDisplayConfig.form_type_id,
                cat_order.category_code == MasFieldDisplayConfig.category_code,
                cat_order.is_active == True,
            )
        )
        .outerjoin(
            subcat_order,
            sa.and_(
                subcat_order.form_type_id == MasFieldDisplayConfig.form_type_id,
                subcat_order.category_code == MasFieldDisplayConfig.category_code,
                subcat_order.subcategory_code == MasFieldDisplayConfig.subcategory_code,
                subcat_order.is_active == True,
            )
        )
        .where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.is_active == True,
        )
        .order_by(
            cat_order.display_order.is_(None),
            cat_order.display_order,
            MasFieldDisplayConfig.category_code,
            subcat_order.display_order.is_(None),
            subcat_order.display_order,
            MasFieldDisplayConfig.subcategory_code,
            MasFieldDisplayConfig.display_order,
            MasFieldDisplayConfig.field_id,
        )
    )
    if no_category:
        query = query.where(MasFieldDisplayConfig.category_code == None)
    elif category_filter:
        query = query.where(MasFieldDisplayConfig.category_code == category_filter)
    if subcategory_filter:
        query = query.where(MasFieldDisplayConfig.subcategory_code == subcategory_filter)
    _FLAG_FILTERS = {
        "flip":    MasFieldDisplayConfig.flip_color == True,
        "info":    MasFieldDisplayConfig.is_info == True,
        "summary": MasFieldDisplayConfig.summary_include == True,
        "pii":     MasFieldDisplayConfig.is_pii == True,
    }
    for f in flag_filters:
        query = query.where(_FLAG_FILTERS[f])
    if search:
        query = query.where(
            sa.or_(
                MasFieldDisplayConfig.field_id.ilike(f"%{search}%"),
                MasFieldDisplayConfig.short_label.ilike(f"%{search}%"),
            )
        )

    fields = db.session.scalars(query).all()

    # Group subcategories by category_code for inline selects
    subcats_by_cat = {}
    for s in all_subcats:
        subcats_by_cat.setdefault(s.category_code, []).append(s)

    return render_template(
        "admin/panels/field_mapping_fields.html",
        form_type_code=form_type_code,
        fields=fields,
        category_filter=category_filter,
        subcategory_filter=subcategory_filter,
        search=search,
        flag_filters=flag_filters,
        no_category=no_category,
        categories=cats,
        subcategories_for_filter=subcats_for_filter,
        cat_name_map=cat_name_map,
        subcat_name_map=subcat_name_map,
        subcats_by_cat=subcats_by_cat,
    )


@admin.route("/panels/field-mapping/field/<form_type_code>/<field_id>",
             methods=["GET", "POST"])
@role_required("admin")
def admin_panel_field_mapping_field_edit(form_type_code, field_id):
    from sqlalchemy import select as sa_select
    from app.models import MasFieldDisplayConfig, MasFormTypes
    from app.models.va_field_mapping import MasSubcategoryOrder
    from app.models.va_field_mapping import MasChoiceMappings

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    field = db.session.scalar(
        sa_select(MasFieldDisplayConfig).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.field_id == field_id,
        )
    )
    if not field:
        return "Field not found", 404

    origin = (request.args.get("origin") or request.form.get("origin") or "").strip()

    # Load categories for this form type
    categories = _get_ordered_category_configs_for_form_type(form_type.form_type_id)

    # Load subcategories for the field's current category (if any)
    subcategories = []
    if field.category_code:
        subcategories = db.session.scalars(
            sa_select(MasSubcategoryOrder)
            .where(
                MasSubcategoryOrder.form_type_id == form_type.form_type_id,
                MasSubcategoryOrder.category_code == field.category_code,
            )
            .order_by(MasSubcategoryOrder.display_order)
        ).all()

    choices = db.session.scalars(
        sa_select(MasChoiceMappings)
        .where(
            MasChoiceMappings.form_type_id == form_type.form_type_id,
            MasChoiceMappings.field_id == field.field_id,
            MasChoiceMappings.is_active == True,
        )
        .order_by(MasChoiceMappings.display_order, MasChoiceMappings.choice_label)
    ).all()

    if request.method == "POST":
        field.short_label = request.form.get("short_label") or field.short_label
        field.full_label = request.form.get("full_label") or None
        field.category_code = request.form.get("category_code") or None
        field.subcategory_code = request.form.get("subcategory_code") or None
        raw_order = (request.form.get("display_order") or "").strip()
        if raw_order:
            try:
                field.display_order = Decimal(raw_order)
            except InvalidOperation:
                return "display_order must be a number.", 400
        field.flip_color = request.form.get("flip_color") == "on"
        field.is_info = request.form.get("is_info") == "on"
        field.summary_include = request.form.get("summary_include") == "on"
        field.is_pii = request.form.get("is_pii") == "on"
        field.pii_type = request.form.get("pii_type") or None
        for choice in choices:
            label_key = f"choice_label__{choice.choice_id}"
            raw_label = request.form.get(label_key)
            if raw_label is not None:
                choice.choice_label = raw_label.strip()
        db.session.commit()

        # Clear service cache so updated label is reflected immediately
        from app.services.field_mapping_service import get_mapping_service
        get_mapping_service().clear_cache()

        # Return updated table row for hx-swap="outerHTML"
        all_subcats_row = db.session.scalars(
            sa_select(MasSubcategoryOrder)
            .where(MasSubcategoryOrder.form_type_id == form_type.form_type_id)
        ).all()
        cat_name_map_row = {c.category_code: c.display_label or c.category_code for c in categories}
        subcat_name_map_row = {
            (s.category_code, s.subcategory_code): s.subcategory_name or s.subcategory_code
            for s in all_subcats_row
        }
        subcats_by_cat_row = {}
        for s in all_subcats_row:
            subcats_by_cat_row.setdefault(s.category_code, []).append(s)
        return render_template(
            "admin/panels/field_mapping_field_row.html",
            form_type_code=form_type_code,
            field=field,
            categories=categories,
            cat_name_map=cat_name_map_row,
            subcat_name_map=subcat_name_map_row,
            subcats_by_cat=subcats_by_cat_row,
        )

    return render_template(
        "admin/panels/field_mapping_field_edit.html",
        form_type_code=form_type_code,
        field=field,
        categories=categories,
        subcategories=subcategories,
        choices=choices,
        origin=origin,
    )


@admin.patch("/panels/field-mapping/field/<form_type_code>/<field_id>/category")
@role_required("admin")
def admin_panel_field_mapping_field_quick_category(form_type_code, field_id):
    """Quick inline update of category/subcategory only. Returns updated table row HTML."""
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from sqlalchemy import select as sa_select
    from app.models import MasFieldDisplayConfig, MasFormTypes
    from app.models.va_field_mapping import MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    field = db.session.scalar(
        sa_select(MasFieldDisplayConfig).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.field_id == field_id,
        )
    )
    if not field:
        return "Field not found", 404

    new_cat = request.form.get("category_code") or None
    new_sub = request.form.get("subcategory_code") or None

    # Clear subcategory if category changed
    if new_cat != field.category_code:
        new_sub = None

    field.category_code = new_cat
    field.subcategory_code = new_sub
    db.session.commit()

    from app.services.field_mapping_service import get_mapping_service
    get_mapping_service().clear_cache()

    # Build context needed to render the row with inline selects
    cats = _get_ordered_category_configs_for_form_type(form_type.form_type_id)
    all_subcats = db.session.scalars(
        sa_select(MasSubcategoryOrder)
        .where(MasSubcategoryOrder.form_type_id == form_type.form_type_id)
    ).all()
    cat_name_map = {c.category_code: c.display_label or c.category_code for c in cats}
    subcat_name_map = {
        (s.category_code, s.subcategory_code): s.subcategory_name or s.subcategory_code
        for s in all_subcats
    }
    subcats_by_cat = {}
    for s in all_subcats:
        subcats_by_cat.setdefault(s.category_code, []).append(s)

    return render_template(
        "admin/panels/field_mapping_field_row.html",
        form_type_code=form_type_code,
        field=field,
        categories=cats,
        cat_name_map=cat_name_map,
        subcat_name_map=subcat_name_map,
        subcats_by_cat=subcats_by_cat,
    )


@admin.patch("/panels/field-mapping/field/<form_type_code>/<field_id>/order")
@role_required("admin")
def admin_panel_field_mapping_field_quick_order(form_type_code, field_id):
    """Quick inline update of field display_order. Returns updated table row HTML."""
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from sqlalchemy import select as sa_select
    from app.models import MasFieldDisplayConfig, MasFormTypes
    from app.models.va_field_mapping import MasSubcategoryOrder

    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    field = db.session.scalar(
        sa_select(MasFieldDisplayConfig).where(
            MasFieldDisplayConfig.form_type_id == form_type.form_type_id,
            MasFieldDisplayConfig.field_id == field_id,
        )
    )
    if not field:
        return "Field not found", 404

    raw_order = (request.form.get("display_order") or "").strip()
    try:
        field.display_order = Decimal(raw_order)
    except InvalidOperation:
        return "display_order must be a number.", 400

    db.session.commit()

    from app.services.field_mapping_service import get_mapping_service
    get_mapping_service().clear_cache()

    cats = _get_ordered_category_configs_for_form_type(form_type.form_type_id)
    all_subcats = db.session.scalars(
        sa_select(MasSubcategoryOrder)
        .where(MasSubcategoryOrder.form_type_id == form_type.form_type_id)
    ).all()
    cat_name_map = {c.category_code: c.display_label or c.category_code for c in cats}
    subcat_name_map = {
        (s.category_code, s.subcategory_code): s.subcategory_name or s.subcategory_code
        for s in all_subcats
    }
    subcats_by_cat = {}
    for s in all_subcats:
        subcats_by_cat.setdefault(s.category_code, []).append(s)

    return render_template(
        "admin/panels/field_mapping_field_row.html",
        form_type_code=form_type_code,
        field=field,
        categories=cats,
        cat_name_map=cat_name_map,
        subcat_name_map=subcat_name_map,
        subcats_by_cat=subcats_by_cat,
    )


@admin.get("/panels/field-mapping/categories")
@role_required("admin")
def admin_panel_field_mapping_categories():
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes
    form_type_code = request.args.get("form_type", "").strip()
    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    fields_by_category, _ = _ordered_field_lists_for_form_type(form_type.form_type_id)

    categories = _get_ordered_category_configs_for_form_type(form_type.form_type_id)

    categories_json = [
        {
            "category_code": c.category_code,
            "category_name": c.display_label,
            "display_order": c.display_order,
            "ordered_fields": fields_by_category.get(c.category_code, []),
        }
        for c in categories
    ]

    return render_template(
        "admin/panels/field_mapping_categories.html",
        form_type_code=form_type_code,
        form_type_name=form_type.form_type_name,
        categories_json=categories_json,
    )


@admin.get("/panels/field-mapping/choices")
@role_required("admin")
def admin_panel_field_mapping_choices():
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    from sqlalchemy import select as sa_select
    from app.models import MasFormTypes, MasFieldDisplayConfig
    from app.models.va_field_mapping import MasChoiceMappings

    form_type_code = request.args.get("form_type", "WHO_2022_VA")
    form_type = db.session.scalar(
        sa_select(MasFormTypes).where(MasFormTypes.form_type_code == form_type_code)
    )
    if not form_type:
        return "Form type not found", 404

    rows = db.session.execute(
        sa_select(
            MasChoiceMappings.field_id,
            MasChoiceMappings.choice_value,
            MasChoiceMappings.choice_label,
            MasChoiceMappings.display_order,
            MasFieldDisplayConfig.short_label,
            MasFieldDisplayConfig.field_type,
        )
        .outerjoin(
            MasFieldDisplayConfig,
            sa.and_(
                MasFieldDisplayConfig.form_type_id == MasChoiceMappings.form_type_id,
                MasFieldDisplayConfig.field_id == MasChoiceMappings.field_id,
            ),
        )
        .where(
            MasChoiceMappings.form_type_id == form_type.form_type_id,
            MasChoiceMappings.is_active == True,
        )
        .order_by(
            MasChoiceMappings.field_id,
            MasChoiceMappings.display_order,
            MasChoiceMappings.choice_value,
        )
    ).all()

    return render_template(
        "admin/panels/field_mapping_choices.html",
        form_type_code=form_type_code,
        form_type_name=form_type.form_type_name,
        rows=rows,
    )


@admin.get("/panels/field-mapping/sync")
@role_required("admin")
def admin_panel_field_mapping_sync():
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    form_type_code = request.args.get("form_type", "WHO_2022_VA")
    return render_template(
        "admin/panels/field_mapping_sync.html",
        form_type_code=form_type_code,
    )


@admin.post("/panels/field-mapping/sync/preview")
@role_required("admin")
def admin_panel_field_mapping_sync_preview():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.services.odk_schema_sync_service import get_sync_service
    data = request.get_json(force=True)
    form_type_code = data.get("form_type_code")
    odk_project_id = data.get("odk_project_id")
    odk_form_id = data.get("odk_form_id")
    connection_id_str = data.get("connection_id")

    if not all([form_type_code, odk_project_id, odk_form_id, connection_id_str]):
        return _json_error("Missing required fields.", 400)

    try:
        conn_uuid = uuid.UUID(connection_id_str)
    except (ValueError, AttributeError):
        return _json_error("Invalid connection_id.", 400)

    conn = db.session.get(MasOdkConnections, conn_uuid)
    if not conn:
        return _json_error("ODK connection not found.", 404)
    if conn.status.value != "active":
        return _json_error(f"ODK connection '{conn.connection_name}' is not active.", 400)

    client = _get_odk_client_for_connection(conn)
    result = get_sync_service().preview_sync(
        form_type_code, int(odk_project_id), odk_form_id, client=client
    )
    return jsonify(result)


@admin.post("/panels/field-mapping/sync/apply")
@role_required("admin")
def admin_panel_field_mapping_sync_apply():
    """Apply a user-selected subset of previewed sync changes."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.services.odk_schema_sync_service import get_sync_service
    data = request.get_json(force=True)
    form_type_code = data.get("form_type_code")
    selected = data.get("selected") or {}

    if not form_type_code:
        return _json_error("form_type_code is required.", 400)

    stats = get_sync_service().sync_selected(form_type_code, selected)
    return jsonify(stats)


@admin.post("/panels/field-mapping/sync")
@role_required("admin")
def admin_panel_field_mapping_sync_run():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.services.odk_schema_sync_service import get_sync_service
    data = request.get_json(force=True)
    form_type_code = data.get("form_type_code")
    odk_project_id = data.get("odk_project_id")
    odk_form_id = data.get("odk_form_id")
    connection_id_str = data.get("connection_id")

    if not all([form_type_code, odk_project_id, odk_form_id, connection_id_str]):
        return _json_error("Missing form_type_code, connection_id, odk_project_id, or odk_form_id.", 400)

    try:
        conn_uuid = uuid.UUID(connection_id_str)
    except (ValueError, AttributeError):
        return _json_error("Invalid connection_id.", 400)

    conn = db.session.get(MasOdkConnections, conn_uuid)
    if not conn:
        return _json_error("ODK connection not found.", 404)
    if conn.status.value != "active":
        return _json_error(f"ODK connection '{conn.connection_name}' is not active.", 400)

    client = _get_odk_client_for_connection(conn)
    stats = get_sync_service().sync_form_choices(
        form_type_code, int(odk_project_id), odk_form_id, client=client
    )
    return jsonify(stats)


# ---------------------------------------------------------------------------
# ODK Connections API  (admin-only)
# ---------------------------------------------------------------------------

def _serialize_odk_connection(conn, project_ids: list[str]) -> dict:
    """Serialize an ODK connection — never include encrypted fields."""
    return {
        "connection_id": str(conn.connection_id),
        "connection_name": conn.connection_name,
        "base_url": conn.base_url,
        "status": conn.status.value,
        "notes": conn.notes or "",
        "project_ids": project_ids,
        "created_at": conn.created_at.isoformat(),
        "updated_at": conn.updated_at.isoformat(),
        "guard": serialize_connection_guard_state(conn),
    }


def _get_connection_project_ids(connection_id: uuid.UUID) -> list[str]:
    rows = db.session.scalars(
        sa.select(MapProjectOdk.project_id).where(
            MapProjectOdk.connection_id == connection_id
        )
    ).all()
    return sorted(rows)


def _odk_connection_alerts() -> list[dict]:
    """Return active ODK connection alerts for operator-facing admin panels."""
    now = datetime.now(timezone.utc)
    conns = db.session.scalars(
        sa.select(MasOdkConnections)
        .where(MasOdkConnections.status == VaStatuses.active)
        .order_by(MasOdkConnections.connection_name)
    ).all()

    alerts = []
    for conn in conns:
        guard = serialize_connection_guard_state(conn)
        if not (guard["cooldown_active"] or guard["consecutive_failure_count"] > 0):
            continue
        alerts.append(
            {
                "connection_id": str(conn.connection_id),
                "connection_name": conn.connection_name,
                "base_url": conn.base_url,
                "guard": guard,
                "cooldown_remaining_seconds": (
                    max(0, int((conn.cooldown_until - now).total_seconds()))
                    if conn.cooldown_until and conn.cooldown_until > now
                    else 0
                ),
            }
        )
    return alerts


@admin.get("/api/odk-connections")
@role_required("admin")
def admin_odk_connections_list():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conns = db.session.scalars(
        sa.select(MasOdkConnections).order_by(MasOdkConnections.connection_name)
    ).all()
    result = [
        _serialize_odk_connection(c, _get_connection_project_ids(c.connection_id))
        for c in conns
    ]
    return jsonify({"connections": result})


@admin.post("/api/odk-connections")
@role_required("admin")
def admin_odk_connections_create():
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    payload = request.get_json(silent=True) or {}
    connection_name = (payload.get("connection_name") or "").strip()
    base_url = (payload.get("base_url") or "").strip().rstrip("/")
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""

    if not connection_name:
        return _json_error("connection_name is required.", 400)
    if not base_url:
        return _json_error("base_url is required.", 400)
    if not username:
        return _json_error("username is required.", 400)
    if not password:
        return _json_error("password is required.", 400)

    existing = db.session.scalar(
        sa.select(MasOdkConnections).where(
            MasOdkConnections.connection_name == connection_name
        )
    )
    if existing:
        return _json_error("A connection with that name already exists.", 400)

    from app.utils.credential_crypto import encrypt_credential, get_odk_pepper
    try:
        pepper = get_odk_pepper()
    except RuntimeError as exc:
        return _json_error(str(exc), 500)

    username_enc, username_salt = encrypt_credential(username, pepper)
    password_enc, password_salt = encrypt_credential(password, pepper)

    conn = MasOdkConnections(
        connection_name=connection_name,
        base_url=base_url,
        username_enc=username_enc,
        username_salt=username_salt,
        password_enc=password_enc,
        password_salt=password_salt,
        status=VaStatuses.active,
        notes=(payload.get("notes") or "").strip() or None,
    )
    db.session.add(conn)
    db.session.commit()
    return jsonify(
        {"connection": _serialize_odk_connection(conn, [])}
    ), 201


@admin.put("/api/odk-connections/<uuid:connection_id>")
@role_required("admin")
def admin_odk_connections_update(connection_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    payload = request.get_json(silent=True) or {}

    if "connection_name" in payload:
        name = (payload["connection_name"] or "").strip()
        if not name:
            return _json_error("connection_name cannot be empty.", 400)
        dup = db.session.scalar(
            sa.select(MasOdkConnections).where(
                MasOdkConnections.connection_name == name,
                MasOdkConnections.connection_id != connection_id,
            )
        )
        if dup:
            return _json_error("A connection with that name already exists.", 400)
        conn.connection_name = name

    if "base_url" in payload:
        base_url = (payload["base_url"] or "").strip().rstrip("/")
        if not base_url:
            return _json_error("base_url cannot be empty.", 400)
        conn.base_url = base_url

    if "notes" in payload:
        conn.notes = (payload["notes"] or "").strip() or None

    # Re-encrypt credentials only if new values are provided
    if payload.get("username") or payload.get("password"):
        from app.utils.credential_crypto import encrypt_credential, decrypt_credential, get_odk_pepper
        try:
            pepper = get_odk_pepper()
        except RuntimeError as exc:
            return _json_error(str(exc), 500)

        if payload.get("username"):
            username = (payload["username"] or "").strip()
            if not username:
                return _json_error("username cannot be empty.", 400)
            conn.username_enc, conn.username_salt = encrypt_credential(username, pepper)

        if payload.get("password"):
            conn.password_enc, conn.password_salt = encrypt_credential(
                payload["password"], pepper
            )

    if "status" in payload:
        try:
            conn.status = VaStatuses(payload["status"])
        except ValueError:
            return _json_error("Invalid status.", 400)

    db.session.commit()
    project_ids = _get_connection_project_ids(connection_id)
    return jsonify({"connection": _serialize_odk_connection(conn, project_ids)})


@admin.post("/api/odk-connections/<uuid:connection_id>/toggle")
@role_required("admin")
def admin_odk_connections_toggle(connection_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    conn.status = (
        VaStatuses.deactive if conn.status == VaStatuses.active else VaStatuses.active
    )
    db.session.commit()
    return jsonify(
        {"connection_id": str(conn.connection_id), "status": conn.status.value}
    )


@admin.post("/api/odk-connections/<uuid:connection_id>/test")
@role_required("admin")
def admin_odk_connections_test(connection_id):
    """Attempt a live authentication check against the ODK server."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    from app.utils.credential_crypto import decrypt_credential, get_odk_pepper
    try:
        pepper = get_odk_pepper()
        username = decrypt_credential(conn.username_enc, conn.username_salt, pepper)
        password = decrypt_credential(conn.password_enc, conn.password_salt, pepper)
    except (RuntimeError, ValueError) as exc:
        return _json_error(f"Credential decryption failed: {exc}", 500)

    try:
        import requests as http
        resp = guarded_odk_call(
            lambda: http.post(
                f"{conn.base_url}/v1/sessions",
                json={"email": username, "password": password},
                timeout=current_app.config.get(
                    "ODK_CONNECTION_TEST_TIMEOUT_SECONDS", 10
                ),
            ),
            connection_id=conn.connection_id,
        )
        if resp.status_code == 200:
            return jsonify({"ok": True, "message": "Authentication successful."})
        return jsonify(
            {"ok": False, "message": f"ODK returned HTTP {resp.status_code}."}
        ), 200
    except OdkConnectionCooldownError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 200
    except Exception as exc:
        return jsonify({"ok": False, "message": f"Connection error: {exc}"}), 200


# ---------------------------------------------------------------------------
# Project ↔ ODK connection mapping API
# ---------------------------------------------------------------------------

@admin.get("/api/odk-connections/<uuid:connection_id>/projects")
@role_required("admin")
def admin_odk_connection_projects(connection_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    return jsonify({"project_ids": _get_connection_project_ids(connection_id)})


@admin.post("/api/odk-connections/<uuid:connection_id>/assign-project")
@role_required("admin")
def admin_odk_assign_project(connection_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    payload = request.get_json(silent=True) or {}
    project_id = (payload.get("project_id") or "").strip().upper()
    if not project_id:
        return _json_error("project_id is required.", 400)

    project = db.session.get(VaProjectMaster, project_id)
    if not project:
        return _json_error("Project not found.", 404)

    existing = db.session.scalar(
        sa.select(MapProjectOdk).where(MapProjectOdk.project_id == project_id)
    )
    if existing:
        if existing.connection_id == connection_id:
            return jsonify({"message": "Already assigned.", "project_id": project_id})
        # Re-point to new connection
        existing.connection_id = connection_id
    else:
        db.session.add(MapProjectOdk(project_id=project_id, connection_id=connection_id))

    db.session.commit()
    return jsonify({"project_id": project_id, "connection_id": str(connection_id)}), 201


@admin.delete("/api/odk-connections/<uuid:connection_id>/assign-project/<project_id>")
@role_required("admin")
def admin_odk_unassign_project(connection_id, project_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    mapping = db.session.scalar(
        sa.select(MapProjectOdk).where(
            MapProjectOdk.connection_id == connection_id,
            MapProjectOdk.project_id == project_id.upper(),
        )
    )
    if not mapping:
        return _json_error("Mapping not found.", 404)

    db.session.delete(mapping)
    db.session.commit()
    return jsonify({"message": "Project unassigned."})


# ---------------------------------------------------------------------------
# ODK Central live data (projects / forms) fetched via pyODK
# ---------------------------------------------------------------------------

def _get_odk_client_for_connection(conn: MasOdkConnections):
    """Return a ready pyODK Client for the given connection row."""
    import os
    from flask import current_app
    from app.utils.va_odk.va_odk_01_clientsetup import client_from_connection
    pyodk_dir = os.path.join(current_app.config.get("APP_RESOURCE"), "pyodk")
    return client_from_connection(conn, pyodk_dir)


@admin.get("/api/odk-connections/<uuid:connection_id>/odk-projects")
@role_required("admin")
def admin_odk_list_odk_projects(connection_id):
    """List ODK Central projects available on the connection."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    try:
        client = _get_odk_client_for_connection(conn)
        projects = guarded_odk_call(
            lambda: client.projects.list(),
            client=client,
        )
        return jsonify({
            "odk_projects": [
                {"id": p.id, "name": p.name} for p in projects
            ]
        })
    except Exception as exc:
        return _json_error(f"Failed to fetch ODK projects: {exc}", 502)


@admin.get("/api/odk-connections/<uuid:connection_id>/odk-projects/<int:odk_project_id>/forms")
@role_required("admin")
def admin_odk_list_forms(connection_id, odk_project_id):
    """List forms in a specific ODK Central project."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    try:
        client = _get_odk_client_for_connection(conn)
        forms = guarded_odk_call(
            lambda: client.forms.list(project_id=odk_project_id),
            client=client,
        )
        return jsonify({
            "forms": [
                {"xmlFormId": f.xmlFormId, "name": f.name, "version": f.version}
                for f in forms
            ]
        })
    except Exception as exc:
        return _json_error(f"Failed to fetch ODK forms: {exc}", 502)


# ---------------------------------------------------------------------------
# Project-site → ODK form mappings
# ---------------------------------------------------------------------------

@admin.get("/api/projects/<project_id>/odk-connection")
@role_required("admin")
def admin_project_odk_connection(project_id):
    """Return the ODK connection linked to this project, or null."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    mapping = db.session.scalar(
        sa.select(MapProjectOdk).where(
            MapProjectOdk.project_id == project_id.upper()
        )
    )
    if not mapping:
        return jsonify({"connection": None})

    conn = db.session.get(MasOdkConnections, mapping.connection_id)
    if not conn:
        return jsonify({"connection": None})

    return jsonify({
        "connection": {
            "connection_id": str(conn.connection_id),
            "connection_name": conn.connection_name,
            "base_url": conn.base_url,
            "status": conn.status.value,
            "guard": serialize_connection_guard_state(conn),
        }
    })

@admin.get("/api/projects/<project_id>/odk-site-mappings")
@role_required("admin")
def admin_odk_site_mappings_list(project_id):
    """Return ODK form mappings for all sites in a project."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    project_id = project_id.upper()
    rows = db.session.scalars(
        sa.select(MapProjectSiteOdk).where(
            MapProjectSiteOdk.project_id == project_id
        )
    ).all()
    forms_by_site = {
        form.site_id: form
        for form in db.session.scalars(
            sa.select(VaForms).where(VaForms.project_id == project_id)
        ).all()
    }
    return jsonify({
        "mappings": [
            {
                "site_id": r.site_id,
                "odk_project_id": r.odk_project_id,
                "odk_form_id": r.odk_form_id,
                "form_type_id": str(r.form_type_id) if r.form_type_id else None,
                "form_type_code": r.form_type.form_type_code if r.form_type else None,
                "form_id": forms_by_site.get(r.site_id).form_id if forms_by_site.get(r.site_id) else None,
                "form_smartvahiv": (
                    forms_by_site.get(r.site_id).form_smartvahiv
                    if forms_by_site.get(r.site_id)
                    else "False"
                ),
                "form_smartvamalaria": (
                    forms_by_site.get(r.site_id).form_smartvamalaria
                    if forms_by_site.get(r.site_id)
                    else "False"
                ),
                "form_smartvahce": (
                    forms_by_site.get(r.site_id).form_smartvahce
                    if forms_by_site.get(r.site_id)
                    else "True"
                ),
                "form_smartvafreetext": (
                    forms_by_site.get(r.site_id).form_smartvafreetext
                    if forms_by_site.get(r.site_id)
                    else "True"
                ),
                "form_smartvacountry": (
                    forms_by_site.get(r.site_id).form_smartvacountry
                    if forms_by_site.get(r.site_id)
                    else "IND"
                ),
            }
            for r in rows
        ]
    })


@admin.post("/api/projects/<project_id>/odk-site-mappings")
@role_required("admin")
def admin_odk_site_mappings_save(project_id):
    """Upsert the ODK form mapping for a single project-site.

    Body: { "site_id": "XX01", "odk_project_id": 3, "odk_form_id": "va_form",
            "form_type_id": "<uuid>" }
    form_type_id is optional but strongly recommended.
    """
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    from app.models.va_field_mapping import MasFormTypes
    from app.services.runtime_form_sync_service import ensure_runtime_form_for_mapping
    from app.utils import validate_boolean_string, validate_smartva_country
    import uuid as _uuid

    data = request.get_json(silent=True) or {}
    project_id = project_id.upper()
    site_id = (data.get("site_id") or "").upper()
    odk_project_id = data.get("odk_project_id")
    odk_form_id = (data.get("odk_form_id") or "").strip()
    form_type_id_raw = (data.get("form_type_id") or "").strip()
    form_smartvahiv = (data.get("form_smartvahiv") or "False").strip()
    form_smartvamalaria = (data.get("form_smartvamalaria") or "False").strip()
    form_smartvahce = (data.get("form_smartvahce") or "True").strip()
    form_smartvafreetext = (data.get("form_smartvafreetext") or "True").strip()
    form_smartvacountry = (data.get("form_smartvacountry") or "IND").strip().upper()

    if not site_id or odk_project_id is None or not odk_form_id:
        return _json_error("site_id, odk_project_id, and odk_form_id are required.", 400)

    try:
        odk_project_id = int(odk_project_id)
    except (TypeError, ValueError):
        return _json_error("odk_project_id must be an integer.", 400)

    # Resolve form_type_id if provided
    form_type_id = None
    if form_type_id_raw:
        try:
            parsed_uuid = _uuid.UUID(form_type_id_raw)
        except ValueError:
            return _json_error("form_type_id must be a valid UUID.", 400)
        ft = db.session.get(MasFormTypes, parsed_uuid)
        if not ft:
            return _json_error("form_type_id not found.", 404)
        form_type_id = parsed_uuid

    for value in (
        form_smartvahiv,
        form_smartvamalaria,
        form_smartvahce,
        form_smartvafreetext,
    ):
        if not validate_boolean_string(value):
            return _json_error("SmartVA boolean settings must be 'True' or 'False'.", 400)
    if not validate_smartva_country(form_smartvacountry):
        return _json_error("form_smartvacountry is invalid.", 400)

    project = db.session.get(VaProjectMaster, project_id)
    if not project:
        return _json_error("Project not found.", 404)

    site = db.session.get(VaSiteMaster, site_id)
    if not site:
        return _json_error("Site not found.", 404)

    existing = db.session.scalar(
        sa.select(MapProjectSiteOdk).where(
            MapProjectSiteOdk.project_id == project_id,
            MapProjectSiteOdk.site_id == site_id,
        )
    )
    if existing:
        existing.odk_project_id = odk_project_id
        existing.odk_form_id = odk_form_id
        existing.form_type_id = form_type_id
        status_code = 200
    else:
        existing = MapProjectSiteOdk(
            project_id=project_id,
            site_id=site_id,
            odk_project_id=odk_project_id,
            odk_form_id=odk_form_id,
            form_type_id=form_type_id,
        )
        db.session.add(existing)
        status_code = 201

    runtime_form = ensure_runtime_form_for_mapping(existing)
    runtime_form.form_smartvahiv = form_smartvahiv
    runtime_form.form_smartvamalaria = form_smartvamalaria
    runtime_form.form_smartvahce = form_smartvahce
    runtime_form.form_smartvafreetext = form_smartvafreetext
    runtime_form.form_smartvacountry = form_smartvacountry

    db.session.commit()
    db.session.refresh(existing)
    db.session.refresh(runtime_form)
    return jsonify({
        "mapping": {
            "site_id": existing.site_id,
            "odk_project_id": existing.odk_project_id,
            "odk_form_id": existing.odk_form_id,
            "form_type_id": str(existing.form_type_id) if existing.form_type_id else None,
            "form_type_code": existing.form_type.form_type_code if existing.form_type else None,
            "form_id": runtime_form.form_id,
            "form_smartvahiv": runtime_form.form_smartvahiv,
            "form_smartvamalaria": runtime_form.form_smartvamalaria,
            "form_smartvahce": runtime_form.form_smartvahce,
            "form_smartvafreetext": runtime_form.form_smartvafreetext,
            "form_smartvacountry": runtime_form.form_smartvacountry,
        }
    }), status_code


@admin.delete("/api/projects/<project_id>/odk-site-mappings/<site_id>")
@role_required("admin")
def admin_odk_site_mappings_delete(project_id, site_id):
    """Remove the ODK form mapping for a project-site."""
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    project_id = project_id.upper()
    site_id = site_id.upper()
    
    project = db.session.get(VaProjectMaster, project_id)
    if not project:
        return _json_error("Project not found.", 404)

    mapping = db.session.scalar(
        sa.select(MapProjectSiteOdk).where(
            MapProjectSiteOdk.project_id == project_id,
            MapProjectSiteOdk.site_id == site_id,
        )
    )
    if not mapping:
        return _json_error("Mapping not found.", 404)

    db.session.delete(mapping)
    db.session.commit()
    return jsonify({"message": "Mapping removed."})


# ---------------------------------------------------------------------------
# Sync Dashboard  (admin-only)
# ---------------------------------------------------------------------------

@admin.get("/panels/sync")
@role_required("admin")
def admin_panel_sync():
    sync_forms = [
        {
            "form_id": row.form_id,
            "project_id": row.project_id,
            "site_id": row.site_id,
            "site_name": row.site_name or row.site_id,
        }
        for row in db.session.execute(
            sa.select(
                VaForms.form_id,
                VaForms.project_id,
                VaForms.site_id,
                VaSiteMaster.site_name,
            )
            .select_from(VaForms)
            .outerjoin(VaSiteMaster, VaSiteMaster.site_id == VaForms.site_id)
            .order_by(VaForms.project_id, VaForms.site_id, VaForms.form_id)
        ).mappings().all()
    ]
    return render_template("admin/panels/sync_dashboard.html", sync_forms=sync_forms)


@admin.get("/panels/activity")
@role_required("admin")
def admin_panel_activity():
    sid = (request.args.get("sid") or "").strip()
    project_id = (request.args.get("project_id") or "").strip().upper()
    site_id = (request.args.get("site_id") or "").strip().upper()
    user_id = (request.args.get("user_id") or "").strip()
    action = (request.args.get("action") or "").strip()
    try:
        limit = min(max(int(request.args.get("limit", 100)), 1), 300)
    except (TypeError, ValueError):
        limit = 100
    try:
        page = max(int(request.args.get("page", 1)), 1)
    except (TypeError, ValueError):
        page = 1

    activity_rows, total_count = _build_activity_rows(
        limit=limit,
        page=page,
        sid=sid or None,
        project_id=project_id or None,
        site_id=site_id or None,
        user_id=user_id or None,
        action=action or None,
    )
    project_options = db.session.scalars(
        sa.select(VaForms.project_id).distinct().order_by(VaForms.project_id)
    ).all()
    site_options = db.session.scalars(
        sa.select(VaForms.site_id).distinct().order_by(VaForms.site_id)
    ).all()
    from app.models import VaSubmissionsAuditlog
    raw_action_options = db.session.scalars(
        sa.select(VaSubmissionsAuditlog.va_audit_action)
        .distinct()
        .order_by(VaSubmissionsAuditlog.va_audit_action)
    ).all()
    # Build labeled options: (raw_value, display_label)
    action_options = [
        (opt, _AUDIT_ACTION_DISPLAY.get(opt, opt))
        for opt in raw_action_options
    ]

    return render_template(
        "admin/panels/activity_log.html",
        activity_rows=activity_rows,
        sid=sid,
        project_id=project_id,
        site_id=site_id,
        user_id=user_id,
        action=action,
        limit=limit,
        page=page,
        total_count=total_count,
        total_pages=max((total_count + limit - 1) // limit, 1),
        project_options=project_options,
        site_options=site_options,
        action_options=action_options,
        action_explanations=_AUDIT_ACTION_EXPLANATIONS,
    )


def _sync_task_names() -> set[str]:
    return {
        "app.tasks.sync_tasks.run_odk_sync",
        "app.tasks.sync_tasks.run_smartva_pending",
        "app.tasks.sync_tasks.run_single_form_sync",
        "app.tasks.sync_tasks.run_single_form_backfill",
        "app.tasks.sync_tasks.run_single_submission_sync",
        "app.tasks.sync_tasks.run_attachment_cache_backfill",
    }


def _sync_run_last_progress_at(run) -> datetime | None:
    progress_log = run.progress_log
    if not progress_log:
        return None
    try:
        entries = json.loads(progress_log)
    except Exception:
        return None
    if not isinstance(entries, list) or not entries:
        return None
    for entry in reversed(entries):
        if not isinstance(entry, dict):
            continue
        ts = entry.get("ts")
        if not ts:
            continue
        try:
            return parser.isoparse(ts)
        except Exception:
            continue
    return None


def _reconcile_orphaned_running_sync_rows() -> None:
    """Mark running sync rows stale when Celery has no active sync tasks."""
    from datetime import datetime, timezone, timedelta
    from flask import current_app
    from app.models.va_sync_runs import VaSyncRun

    running_rows = db.session.scalars(
        sa.select(VaSyncRun)
        .where(VaSyncRun.status == "running")
        .order_by(VaSyncRun.started_at.desc())
    ).all()
    if not running_rows:
        return

    celery_app = current_app.extensions.get("celery")
    if celery_app is None:
        return

    inspect = celery_app.control.inspect(timeout=2)
    active_by_worker = inspect.active() or {}
    active_sync_task_found = any(
        task.get("name") in _sync_task_names()
        for tasks in active_by_worker.values()
        for task in (tasks or [])
    )
    if active_sync_task_found and not running_rows:
        recent_row = db.session.scalar(
            sa.select(VaSyncRun)
            .where(VaSyncRun.status == "error")
            .order_by(VaSyncRun.started_at.desc())
            .limit(1)
        )
        if recent_row is not None:
            last_progress_at = _sync_run_last_progress_at(recent_row)
            now = datetime.now(timezone.utc)
            if (
                recent_row.started_at
                and recent_row.started_at > now - timedelta(minutes=10)
                and last_progress_at
                and last_progress_at > now - timedelta(minutes=3)
                and recent_row.error_message
                and "no active Celery sync/backfill task was found" in recent_row.error_message
            ):
                recent_row.status = "running"
                recent_row.finished_at = None
                recent_row.error_message = None
                db.session.commit()
        return
    if active_sync_task_found:
        return

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(minutes=5)
    quiet_cutoff = now - timedelta(minutes=3)
    reconciled = 0
    for row in running_rows:
        last_progress_at = _sync_run_last_progress_at(row)
        if row.started_at and row.started_at > stale_cutoff:
            continue
        if last_progress_at and last_progress_at > quiet_cutoff:
            continue
        row.status = "error"
        row.finished_at = now
        row.error_message = (
            "Stale run — no active Celery sync/backfill task was found and no recent progress was recorded."
        )
        reconciled += 1
    if reconciled:
        db.session.commit()
        log.warning(
            "Reconciled %d orphaned running sync row(s) with no active Celery task.",
            reconciled,
        )
    else:
        db.session.rollback()


@admin.get("/api/sync/status")
@limiter.exempt
@role_required("admin")
def admin_sync_status():
    try:
        from app.models.va_sync_runs import VaSyncRun

        _reconcile_orphaned_running_sync_rows()
        running = db.session.scalar(
            sa.select(VaSyncRun)
            .where(VaSyncRun.status == "running")
            .order_by(VaSyncRun.started_at.desc())
            .limit(1)
        )

        # Flag runs that have been "running" for over 10 minutes with no
        # progress entries — likely orphaned by a worker crash.
        possibly_stale = False
        if running:
            from datetime import datetime, timezone
            age_seconds = (datetime.now(timezone.utc) - running.started_at).total_seconds()
            has_progress = bool(running.progress_log and running.progress_log.strip() not in ("", "[]"))
            if age_seconds > 600 and not has_progress:
                possibly_stale = True

        last_completed = db.session.scalar(
            sa.select(VaSyncRun)
            .where(VaSyncRun.status.in_(["success", "partial", "error", "cancelled"]))
            .order_by(VaSyncRun.started_at.desc())
            .limit(1)
        )
        schedule_hours = _get_sync_schedule_hours()

        return jsonify({
            "is_running": running is not None,
            "possibly_stale": possibly_stale,
            "current_run": _sync_run_dict(running) if running else None,
            "last_completed": _sync_run_dict(last_completed) if last_completed else None,
            "schedule_hours": schedule_hours,
            "odk_connection_alerts": _odk_connection_alerts(),
        })
    except Exception as e:
        log.error("admin_sync_status failed", exc_info=True)
        return _json_error(f"Failed to load sync status: {str(e)}", 500)


@admin.get("/api/sync/history")
@limiter.exempt
@role_required("admin")
def admin_sync_history():
    try:
        from app.models.va_sync_runs import VaSyncRun

        try:
            limit = min(int(request.args.get("limit", 20)), 100)
        except (TypeError, ValueError):
            limit = 20

        runs = db.session.scalars(
            sa.select(VaSyncRun)
            .order_by(VaSyncRun.started_at.desc())
            .limit(limit)
        ).all()

        return jsonify({"runs": [_sync_run_dict(r) for r in runs]})
    except Exception as e:
        log.error("admin_sync_history failed", exc_info=True)
        return _json_error(f"Failed to load sync history: {str(e)}", 500)


@admin.post("/api/sync/trigger")
@role_required("admin")
def admin_sync_trigger():
    try:
        from app.tasks.sync_tasks import run_odk_sync

        _reconcile_orphaned_running_sync_rows()
        running = db.session.scalar(
            sa.select(VaSyncRun)
            .where(VaSyncRun.status == "running")
            .limit(1)
        )
        if running:
            return _json_error(
                "A Sync, Force-resync, or Backfill run is already in progress.",
                409,
            )

            log.info("Manual sync triggered by user %s", current_user.user_id)
        task = run_odk_sync.delay(
            triggered_by="manual",
            user_id=str(current_user.user_id),
        )
        return jsonify({"message": "Sync started.", "task_id": task.id}), 202
    except Exception as e:
        log.error("admin_sync_trigger failed", exc_info=True)
        return _json_error(f"Failed to trigger sync: {str(e)}", 500)


@admin.post("/api/sync/attachment-backfill")
@role_required("admin")
def admin_attachment_backfill_trigger():
    try:
        from app.tasks.sync_tasks import run_attachment_cache_backfill

        _reconcile_orphaned_running_sync_rows()
        running = db.session.scalar(
            sa.select(VaSyncRun.sync_run_id)
            .where(VaSyncRun.status == "running")
            .limit(1)
        )
        if running:
            return _json_error("A sync or backfill task is already in progress.", 409)

        data = request.get_json(silent=True) or {}
        project_id = (data.get("project_id") or "").strip().upper() or None
        site_id = (data.get("site_id") or "").strip().upper() or None
        form_id = (data.get("form_id") or "").strip().upper() or None

        if form_id:
            form_row = db.session.get(VaForms, form_id)
            if form_row is None:
                return _json_error("Selected form was not found.", 404)
            project_id = form_row.project_id
            site_id = form_row.site_id

            task = run_attachment_cache_backfill.delay(
            project_id=project_id,
            site_id=site_id,
            form_id=form_id,
            triggered_by="attach_backfill",
            user_id=str(current_user.user_id),
        )
        return jsonify(
            {
                "message": "Attachment cache backfill started.",
                "task_id": task.id,
            }
        ), 202
    except Exception as e:
        log.error("admin_attachment_backfill_trigger failed", exc_info=True)
        return _json_error(f"Failed to trigger attachment backfill: {str(e)}", 500)


@admin.post("/api/sync/stop")
@role_required("admin")
def admin_sync_stop():
    try:
        from datetime import datetime, timezone
        from flask import current_app
        from app.models.va_sync_runs import VaSyncRun

        celery_app = current_app.extensions.get("celery")
        if celery_app is None:
            return _json_error("Celery is not configured.", 503)

        inspect = celery_app.control.inspect(timeout=2)
        active_by_worker = inspect.active() or {}
        sync_task_names = {
            "app.tasks.sync_tasks.run_odk_sync",
            "app.tasks.sync_tasks.run_smartva_pending",
            "app.tasks.sync_tasks.run_single_form_sync",
            "app.tasks.sync_tasks.run_single_form_backfill",
            "app.tasks.sync_tasks.run_single_submission_sync",
            "app.tasks.sync_tasks.run_attachment_cache_backfill",
        }
        active_task_ids = []
        for tasks in active_by_worker.values():
            for task in tasks or []:
                if task.get("name") in sync_task_names and task.get("id"):
                    active_task_ids.append(task["id"])

        running_rows = db.session.scalars(
            sa.select(VaSyncRun)
            .where(VaSyncRun.status == "running")
            .order_by(VaSyncRun.started_at.desc())
        ).all()

        if not active_task_ids and not running_rows:
            return _json_error("No sync task is currently running.", 409)

        for task_id in active_task_ids:
            celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")

        now = datetime.now(timezone.utc)
        for row in running_rows:
            row.status = "cancelled"
            row.finished_at = now
            row.error_message = "Cancelled by admin."
        db.session.commit()

        return jsonify(
            {
                "message": "Stop signal sent to running sync task(s).",
                "task_ids": active_task_ids,
                "runs_cancelled": len(running_rows),
            }
        )
    except Exception as e:
        log.error("admin_sync_stop failed", exc_info=True)
        return _json_error(f"Failed to stop sync: {str(e)}", 500)


@admin.post("/api/sync/schedule")
@role_required("admin")
def admin_sync_schedule():
    import json as _json

    data = request.get_json(silent=True) or {}
    try:
        hours = int(data.get("interval_hours", 0))
    except (TypeError, ValueError):
        return _json_error("interval_hours must be an integer.", 400)
    if not (1 <= hours <= 168):
        return _json_error("interval_hours must be between 1 and 168.", 400)

    try:
        with db.engine.begin() as conn:
            tables_ready = conn.execute(sa.text("""
                SELECT
                    to_regclass('public.celery_periodictask') IS NOT NULL
                    AND to_regclass('public.celery_intervalschedule') IS NOT NULL
                    AND to_regclass('public.celery_periodictaskchanged') IS NOT NULL
            """)).scalar()
            if not tables_ready:
                return _json_error(
                    "Celery Beat schedule tables are not initialized yet.",
                    503,
                )
            interval_id = conn.execute(sa.text(
                "SELECT id FROM public.celery_intervalschedule "
                "WHERE every = :h AND period = 'hours' LIMIT 1"
            ), {"h": hours}).scalar()
            if interval_id is None:
                interval_id = conn.execute(sa.text(
                    "INSERT INTO public.celery_intervalschedule (every, period) "
                    "VALUES (:h, 'hours') RETURNING id"
                ), {"h": hours}).scalar()

            conn.execute(sa.text("""
                UPDATE public.celery_periodictask
                SET schedule_id = :sid,
                    discriminator = 'intervalschedule',
                    date_changed = NOW()
                WHERE name = :name
            """), {"sid": interval_id, "name": "ODK Sync — every 6 hours"})

            conn.execute(sa.text(
                "INSERT INTO public.celery_periodictaskchanged (last_update) "
                "VALUES (NOW()) ON CONFLICT DO NOTHING"
            ))

        log.info("Sync schedule updated to every %sh", hours)
        return jsonify({"interval_hours": hours})
    except Exception as e:
        log.error("admin_sync_schedule failed (hours=%s)", hours, exc_info=True)
        return _json_error(f"Could not update schedule: {str(e)}", 503)


@admin.get("/api/sync/coverage")
@role_required("admin")
def admin_sync_coverage():
    try:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from app.models.va_submissions import VaSubmissions
        from app.models.va_forms import VaForms
        from app.utils.va_odk.va_odk_04_submissioncount import va_odk_submissioncount

        mappings = db.session.scalars(sa.select(MapProjectSiteOdk)).all()
        log.info("admin_sync_coverage: checking %d mappings", len(mappings))

        # Resolve local counts (fast, DB-only) first
        local_data = {}
        for mapping in mappings:
            form = db.session.scalar(
                sa.select(VaForms).where(
                    VaForms.project_id == mapping.project_id,
                    VaForms.site_id == mapping.site_id,
                )
            )
            local_count = 0
            if form:
                local_count = db.session.scalar(
                    sa.select(sa.func.count()).where(
                        VaSubmissions.va_form_id == form.form_id
                    )
                ) or 0
            local_data[(mapping.project_id, mapping.site_id)] = {
                "form": form,
                "local_count": local_count,
            }

        # Fetch ODK counts in parallel — one thread per mapping.
        # ThreadPoolExecutor threads don't inherit Flask's app context, so
        # we capture the real app object and push a context inside each thread.
        from flask import current_app as _current_app
        flask_app = _current_app._get_current_object()

        def fetch_odk_count(mapping):
            with flask_app.app_context():
                try:
                    count = va_odk_submissioncount(
                        mapping.odk_project_id,
                        mapping.odk_form_id,
                        app_project_id=mapping.project_id,
                    )
                    log.info(
                        "coverage %s/%s: odk=%d",
                        mapping.project_id, mapping.site_id, count,
                    )
                    return mapping, count, None
                except Exception as e:
                    log.warning(
                        "coverage ODK count failed for %s/%s: %s",
                        mapping.project_id, mapping.site_id, e,
                    )
                    return mapping, None, str(e)

        odk_results = {}
        with ThreadPoolExecutor(max_workers=len(mappings) or 1) as ex:
            futures = {ex.submit(fetch_odk_count, m): m for m in mappings}
            for future in as_completed(futures):
                mapping, odk_count, odk_error = future.result()
                odk_results[(mapping.project_id, mapping.site_id)] = (odk_count, odk_error)

        # Assemble response
        rows = []
        odk_total = 0
        local_total = 0
        for mapping in mappings:
            key = (mapping.project_id, mapping.site_id)
            ld = local_data[key]
            odk_count, odk_error = odk_results.get(key, (None, "No result"))
            local_count = ld["local_count"]
            form = ld["form"]

            rows.append({
                "project_id": mapping.project_id,
                "site_id": mapping.site_id,
                "odk_project_id": mapping.odk_project_id,
                "odk_form_id": mapping.odk_form_id,
                "form_id": form.form_id if form else None,
                "can_site_sync": True,
                "odk_total": odk_count,
                "local_total": local_count,
                "missing": (odk_count - local_count) if odk_count is not None else None,
                "error": odk_error,
                "last_synced_at": mapping.last_synced_at.isoformat() if mapping.last_synced_at else None,
            })
            if odk_count is not None:
                odk_total += odk_count
            local_total += local_count

        log.info(
            "admin_sync_coverage complete: odk_total=%d local_total=%d",
            odk_total, local_total,
        )
        return jsonify({
            "mappings": rows,
            "totals": {"odk_total": odk_total, "local_total": local_total},
        })
    except Exception as e:
        log.error("admin_sync_coverage failed", exc_info=True)
        return _json_error(f"Failed to load coverage data: {str(e)}", 500)


@admin.get("/api/sync/backfill-stats")
@limiter.exempt
@role_required("admin")
def admin_sync_backfill_stats():
    """Return local per-form data, metadata, attachment, and SmartVA completeness counts."""
    try:
        from app.models.va_forms import VaForms
        from app.models.va_project_master import VaProjectMaster
        from app.models.va_sites import VaSites
        from app.models.va_submissions import VaSubmissions
        from app.models.va_submission_attachments import VaSubmissionAttachments
        from app.services.submission_analytics_mv import DEMOGRAPHICS_MV_NAME

        forms = db.session.scalars(
            sa.select(VaForms)
            .where(VaForms.form_status == VaStatuses.active)
            .order_by(VaForms.project_id, VaForms.site_id, VaForms.form_id)
        ).all()
        if not forms:
            return jsonify({
                "projects": [],
                "totals": {
                    "local_total": 0,
                    "metadata_complete": 0,
                    "attachments_complete": 0,
                    "smartva_complete": 0,
                },
            })

        attachment_counts_sq = (
            sa.select(
                VaSubmissionAttachments.va_sid.label("va_sid"),
                sa.func.count().label("attachment_count"),
            )
            .where(VaSubmissionAttachments.exists_on_odk.is_(True))
            .group_by(VaSubmissionAttachments.va_sid)
            .subquery()
        )

        metadata_complete_expr = sa.case(
            (
                sa.and_(
                    VaSubmissions.va_summary.is_not(None),
                    VaSubmissions.va_category_list.is_not(None),
                    VaSubmissionPayloadVersion.has_required_metadata.is_(True),
                ),
                1,
            ),
            else_=0,
        )
        attachment_present_expr = sa.func.coalesce(attachment_counts_sq.c.attachment_count, 0)
        attachment_expected_expr = sa.func.coalesce(VaSubmissionPayloadVersion.attachments_expected, 0)
        attachments_complete_expr = sa.case(
            (attachment_present_expr >= attachment_expected_expr, 1),
            else_=0,
        )
        # Use the demographics MV for has_smartva — avoids a full scan + group-by
        # on va_smartva_results. The MV is refreshed after every sync so it is
        # current enough for this dashboard.
        demographics_mv = sa.table(
            DEMOGRAPHICS_MV_NAME,
            sa.column("va_sid"),
            sa.column("has_smartva"),
        )
        smartva_complete_expr = sa.case(
            (demographics_mv.c.has_smartva.is_(True), 1),
            else_=0,
        )

        local_counts = {
            row["va_form_id"]: row
            for row in db.session.execute(
                sa.select(
                    VaSubmissions.va_form_id.label("va_form_id"),
                    sa.func.count(VaSubmissions.va_sid).label("local_total"),
                    sa.func.coalesce(sa.func.sum(metadata_complete_expr), 0).label("metadata_complete"),
                    sa.func.coalesce(sa.func.sum(attachments_complete_expr), 0).label("attachments_complete"),
                    sa.func.coalesce(sa.func.sum(attachment_expected_expr), 0).label("attachments_files_total"),
                    sa.func.coalesce(sa.func.sum(attachment_present_expr), 0).label("attachments_files_present"),
                    sa.func.coalesce(sa.func.sum(smartva_complete_expr), 0).label("smartva_complete"),
                )
                .select_from(VaSubmissions)
                .outerjoin(
                    VaSubmissionPayloadVersion,
                    VaSubmissionPayloadVersion.payload_version_id == VaSubmissions.active_payload_version_id,
                )
                .outerjoin(
                    attachment_counts_sq,
                    attachment_counts_sq.c.va_sid == VaSubmissions.va_sid,
                )
                .outerjoin(
                    demographics_mv,
                    demographics_mv.c.va_sid == VaSubmissions.va_sid,
                )
                .group_by(VaSubmissions.va_form_id)
            ).mappings().all()
        }

        projects_map = {}
        total_local = 0
        total_metadata = 0
        total_attachments = 0
        total_att_files_total = 0
        total_att_files_present = 0
        total_smartva = 0

        for form in forms:
            counts = local_counts.get(form.form_id, {})
            local_total = int(counts.get("local_total") or 0)
            metadata_complete = int(counts.get("metadata_complete") or 0)
            attachments_complete = int(counts.get("attachments_complete") or 0)
            att_files_total = int(counts.get("attachments_files_total") or 0)
            att_files_present = int(counts.get("attachments_files_present") or 0)
            smartva_complete = int(counts.get("smartva_complete") or 0)

            total_local += local_total
            total_metadata += metadata_complete
            total_attachments += attachments_complete
            total_att_files_total += att_files_total
            total_att_files_present += att_files_present
            total_smartva += smartva_complete

            project = projects_map.setdefault(form.project_id, {
                "project_id": form.project_id,
                "project_name": None,
                "sites": {},
                "local_total": 0,
                "metadata_complete": 0,
                "attachments_complete": 0,
                "attachments_files_total": 0,
                "attachments_files_present": 0,
                "smartva_complete": 0,
            })
            project["local_total"] += local_total
            project["metadata_complete"] += metadata_complete
            project["attachments_complete"] += attachments_complete
            project["attachments_files_total"] += att_files_total
            project["attachments_files_present"] += att_files_present
            project["smartva_complete"] += smartva_complete

            site = project["sites"].setdefault(form.site_id, {
                "site_id": form.site_id,
                "site_name": None,
                "forms": [],
                "local_total": 0,
                "metadata_complete": 0,
                "attachments_complete": 0,
                "attachments_files_total": 0,
                "attachments_files_present": 0,
                "smartva_complete": 0,
            })
            site["local_total"] += local_total
            site["metadata_complete"] += metadata_complete
            site["attachments_complete"] += attachments_complete
            site["attachments_files_total"] += att_files_total
            site["attachments_files_present"] += att_files_present
            site["smartva_complete"] += smartva_complete
            site["forms"].append({
                "form_id": form.form_id,
                "local_total": local_total,
                "metadata_complete": metadata_complete,
                "metadata_missing": max(local_total - metadata_complete, 0),
                "attachments_complete": attachments_complete,
                "attachments_missing": max(local_total - attachments_complete, 0),
                "attachments_files_total": att_files_total,
                "attachments_files_present": att_files_present,
                "attachments_files_missing": max(att_files_total - att_files_present, 0),
                "smartva_complete": smartva_complete,
                "smartva_missing": max(local_total - smartva_complete, 0),
            })

        project_names = {
            r.project_id: r.project_name
            for r in db.session.scalars(sa.select(VaProjectMaster)).all()
        }
        site_names = {
            r.site_id: r.site_name
            for r in db.session.scalars(sa.select(VaSites)).all()
        }
        for pid, project in projects_map.items():
            project["project_name"] = project_names.get(pid, pid)
            for sid, site in project["sites"].items():
                site["site_name"] = site_names.get(sid, sid)
                site["forms"] = sorted(site["forms"], key=lambda item: item["form_id"])
            project["sites"] = sorted(project["sites"].values(), key=lambda item: item["site_id"])

        return jsonify({
            "projects": sorted(projects_map.values(), key=lambda item: item["project_id"]),
            "totals": {
                "local_total": total_local,
                "metadata_complete": total_metadata,
                "attachments_complete": total_attachments,
                "attachments_files_total": total_att_files_total,
                "attachments_files_present": total_att_files_present,
                "attachments_files_missing": max(total_att_files_total - total_att_files_present, 0),
                "smartva_complete": total_smartva,
            },
        })
    except Exception as e:
        log.error("admin_sync_backfill_stats failed", exc_info=True)
        return _json_error(f"Failed to load backfill stats: {str(e)}", 500)


@admin.post("/api/sync/backfill/form/<form_id>")
@role_required("admin")
def admin_sync_backfill_form(form_id: str):
    """Repair local sync gaps for a single form without force-resyncing it."""
    try:
        from app.models.va_forms import VaForms
        from app.tasks.sync_tasks import run_single_form_backfill

        va_form = db.session.get(VaForms, form_id)
        if va_form is None:
            return _json_error(f"Form '{form_id}' not found.", 404)

        _reconcile_orphaned_running_sync_rows()
        running = db.session.scalar(
            sa.select(VaSyncRun)
            .where(VaSyncRun.status == "running")
            .limit(1)
        )
        if running:
            return _json_error("A sync is already in progress.", 409)

            log.info(
            "Backfill of %s triggered by user %s",
            form_id,
            current_user.user_id,
        )
        task = run_single_form_backfill.delay(
            form_id=form_id,
            triggered_by="backfill",
            user_id=str(current_user.user_id),
        )
        return jsonify({
            "message": f"Backfill started for form {form_id}.",
            "task_id": task.id,
            "form_id": form_id,
        }), 202
    except Exception as e:
        log.error("admin_sync_backfill_form failed for %s", form_id, exc_info=True)
        return _json_error(f"Failed to trigger backfill for form {form_id}: {str(e)}", 500)


@admin.post("/api/sync/trigger-smartva")
@role_required("admin")
def admin_sync_trigger_smartva():
    try:
        from app.models.va_sync_runs import VaSyncRun
        from app.tasks.sync_tasks import run_smartva_pending

        _reconcile_orphaned_running_sync_rows()
        running = db.session.scalar(
            sa.select(VaSyncRun)
            .where(VaSyncRun.status == "running")
            .limit(1)
        )
        if running:
            return _json_error("A sync is already in progress.", 409)

            log.info("SmartVA-only run triggered by user %s", current_user.user_id)
        task = run_smartva_pending.delay(
            triggered_by="smartva-only",
            user_id=str(current_user.user_id),
        )
        return jsonify({"message": "SmartVA run started.", "task_id": task.id}), 202
    except Exception as e:
        log.error("admin_sync_trigger_smartva failed", exc_info=True)
        return _json_error(f"Failed to trigger SmartVA run: {str(e)}", 500)


@admin.post("/api/sync/form/<form_id>")
@role_required("admin")
def admin_sync_form(form_id: str):
    """Force-resync a single form, bypassing the delta check."""
    try:
        from app.models.va_forms import VaForms
        from app.tasks.sync_tasks import run_single_form_sync

        va_form = db.session.get(VaForms, form_id)
        if va_form is None:
            return _json_error(f"Form '{form_id}' not found.", 404)

        _reconcile_orphaned_running_sync_rows()
        log.info("Single-form force-resync of %s triggered by user %s", form_id, current_user.user_id)
        task = run_single_form_sync.delay(
            form_id=form_id,
            triggered_by="manual",
            user_id=str(current_user.user_id),
        )
        return jsonify({"message": f"Force-resync started for form {form_id}.", "task_id": task.id}), 202
    except Exception as e:
        log.error("admin_sync_form failed for %s", form_id, exc_info=True)
        return _json_error(f"Failed to trigger Force-resync for form {form_id}: {str(e)}", 500)


@admin.post("/api/sync/project-site/<project_id>/<site_id>")
@role_required("admin")
def admin_sync_project_site(project_id: str, site_id: str):
    """Materialize the runtime form for one mapping and trigger a form sync."""
    try:
        from app.services.runtime_form_sync_service import ensure_runtime_form_for_mapping
        from app.tasks.sync_tasks import run_single_form_sync

        mapping = db.session.scalar(
            sa.select(MapProjectSiteOdk).where(
                MapProjectSiteOdk.project_id == project_id,
                MapProjectSiteOdk.site_id == site_id,
            )
        )
        if mapping is None:
            return _json_error(
                f"ODK mapping not found for project/site '{project_id}/{site_id}'.",
                404,
            )

        va_form = ensure_runtime_form_for_mapping(mapping)
        db.session.commit()

        log.info(
            "Project/site sync of %s/%s (%s) triggered by user %s",
            project_id,
            site_id,
            va_form.form_id,
            current_user.user_id,
        )
        task = run_single_form_sync.delay(
            form_id=va_form.form_id,
            triggered_by="manual",
            user_id=str(current_user.user_id),
        )
        return jsonify(
            {
                "message": (
                    f"Sync started for {project_id}/{site_id} "
                    f"using form {va_form.form_id}."
                ),
                "task_id": task.id,
                "form_id": va_form.form_id,
            }
        ), 202
    except Exception as e:
        log.error("admin_sync_project_site failed for %s/%s", project_id, site_id, exc_info=True)
        return _json_error(
            f"Failed to trigger sync for project/site {project_id}/{site_id}: {str(e)}",
            500,
        )


@admin.get("/api/sync/smartva-stats")
@role_required("admin")
def admin_sync_smartva_stats():
    """Return SmartVA result counts grouped by project → site → form."""
    try:
        from app.models.va_submissions import VaSubmissions
        from app.models.va_smartva_results import VaSmartvaResults
        from app.models.va_forms import VaForms
        from app.models.va_project_master import VaProjectMaster
        from app.models.va_sites import VaSites

        forms = db.session.scalars(sa.select(VaForms)).all()

        # Fetch SmartVA counts in one query: count active results per form
        smartva_by_form = dict(
            db.session.execute(
                sa.select(
                    VaSubmissions.va_form_id,
                    sa.func.count(VaSmartvaResults.va_smartva_id).label("cnt"),
                )
                .join(VaSmartvaResults, VaSmartvaResults.va_sid == VaSubmissions.va_sid)
                .where(VaSmartvaResults.va_smartva_status == VaStatuses.active)
                .group_by(VaSubmissions.va_form_id)
            ).all()
        )

        # Fetch submission counts per form (excluding finalized_upstream_changed — pending SmartVA)
        from app.services.workflow.definition import WORKFLOW_FINALIZED_UPSTREAM_CHANGED
        from app.models.va_submission_workflow import VaSubmissionWorkflow

        sub_by_form = dict(
            db.session.execute(
                sa.select(
                    VaSubmissions.va_form_id,
                    sa.func.count(VaSubmissions.va_sid).label("cnt"),
                )
                .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
                .where(VaSubmissionWorkflow.workflow_state != WORKFLOW_FINALIZED_UPSTREAM_CHANGED)
                .group_by(VaSubmissions.va_form_id)
            ).all()
        )

        # Group by project → site
        projects_map = {}
        total_submissions = total_with_smartva = total_pending = 0

        for form in forms:
            sub_count = sub_by_form.get(form.form_id, 0)
            sva_count = smartva_by_form.get(form.form_id, 0)
            pending = max(sub_count - sva_count, 0)

            total_submissions += sub_count
            total_with_smartva += sva_count
            total_pending += pending

            proj = projects_map.setdefault(form.project_id, {
                "project_id": form.project_id,
                "project_name": None,
                "sites": {},
                "submissions": 0,
                "with_smartva": 0,
                "pending_smartva": 0,
            })
            proj["submissions"] += sub_count
            proj["with_smartva"] += sva_count
            proj["pending_smartva"] += pending

            site = proj["sites"].setdefault(form.site_id, {
                "site_id": form.site_id,
                "site_name": None,
                "form_id": form.form_id,
                "submissions": 0,
                "with_smartva": 0,
                "pending_smartva": 0,
            })
            site["submissions"] += sub_count
            site["with_smartva"] += sva_count
            site["pending_smartva"] += pending

        # Enrich with project/site names
        project_names = {
            r.project_id: r.project_name
            for r in db.session.scalars(sa.select(VaProjectMaster)).all()
        }
        site_names = {
            r.site_id: r.site_name
            for r in db.session.scalars(sa.select(VaSites)).all()
        }
        for pid, proj in projects_map.items():
            proj["project_name"] = project_names.get(pid, pid)
            for sid, site in proj["sites"].items():
                site["site_name"] = site_names.get(sid, sid)
            proj["sites"] = list(proj["sites"].values())

        return jsonify({
            "projects": list(projects_map.values()),
            "totals": {
                "submissions": total_submissions,
                "with_smartva": total_with_smartva,
                "pending_smartva": total_pending,
            },
        })
    except Exception as e:
        log.error("admin_sync_smartva_stats failed", exc_info=True)
        return _json_error(f"Failed to load SmartVA stats: {str(e)}", 500)


@admin.get("/api/sync/revoked-stats")
@limiter.exempt
@role_required("admin")
def admin_sync_revoked_stats():
    """Return counts of submissions in finalized_upstream_changed state.

    These are protected submissions that had upstream ODK data changes
    and are pending data-manager review.
    """
    try:
        from app.models.va_submissions import VaSubmissions
        from app.models.va_submission_workflow import VaSubmissionWorkflow
        from app.models.va_forms import VaForms
        from app.models.va_project_master import VaProjectMaster
        from app.models.va_sites import VaSites
        from app.services.workflow.definition import WORKFLOW_FINALIZED_UPSTREAM_CHANGED

        # Fetch revoked counts per form
        revoked_by_form = dict(
            db.session.execute(
                sa.select(
                    VaSubmissions.va_form_id,
                    sa.func.count(VaSubmissions.va_sid).label("cnt"),
                )
                .join(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
                .where(
                    VaSubmissionWorkflow.workflow_state
                    == WORKFLOW_FINALIZED_UPSTREAM_CHANGED
                )
                .group_by(VaSubmissions.va_form_id)
            ).all()
        )

        if not revoked_by_form:
            return jsonify({
                "projects": [],
                "totals": {"revoked": 0},
            })

        forms = db.session.scalars(
            sa.select(VaForms).where(VaForms.form_id.in_(revoked_by_form.keys()))
        ).all()

        # Group by project → site
        projects_map = {}
        total_revoked = 0

        for form in forms:
            revoked_count = revoked_by_form.get(form.form_id, 0)
            if revoked_count == 0:
                continue

            total_revoked += revoked_count

            proj = projects_map.setdefault(form.project_id, {
                "project_id": form.project_id,
                "project_name": None,
                "sites": {},
                "revoked": 0,
            })
            proj["revoked"] += revoked_count

            site = proj["sites"].setdefault(form.site_id, {
                "site_id": form.site_id,
                "site_name": None,
                "forms": {},
                "revoked": 0,
            })
            site["revoked"] += revoked_count

            site["forms"][form.form_id] = {
                "form_id": form.form_id,
                "revoked": revoked_count,
            }

        # Add names
        project_names = {
            r.project_id: r.project_name
            for r in db.session.scalars(sa.select(VaProjectMaster)).all()
        }
        site_names = {
            r.site_id: r.site_name
            for r in db.session.scalars(sa.select(VaSites)).all()
        }
        for pid, proj in projects_map.items():
            proj["project_name"] = project_names.get(pid, pid)
            for sid, site in proj["sites"].items():
                site["site_name"] = site_names.get(sid, sid)
            proj["sites"] = list(proj["sites"].values())

        return jsonify({
            "projects": list(projects_map.values()),
            "totals": {"revoked": total_revoked},
        })
    except Exception as e:
        log.error("admin_sync_revoked_stats failed", exc_info=True)
        return _json_error(f"Failed to load revoked stats: {str(e)}", 500)


@admin.get("/api/sync/progress")
@limiter.exempt
@role_required("admin")
def admin_sync_progress():
    """Return live progress log for the currently running sync, or the last run."""
    import json as _json
    try:
        from app.models.va_sync_runs import VaSyncRun

        run = db.session.scalar(
            sa.select(VaSyncRun)
            .where(VaSyncRun.status == "running")
            .order_by(VaSyncRun.started_at.desc())
            .limit(1)
        )
        if not run:
            run = db.session.scalar(
                sa.select(VaSyncRun)
                .order_by(VaSyncRun.started_at.desc())
                .limit(1)
            )

        if not run:
            return jsonify({"is_running": False, "entries": []})

        entries = []
        if run.progress_log:
            try:
                entries = _json.loads(run.progress_log)
            except Exception:
                entries = []

        return jsonify({
            "is_running": run.status == "running",
            "run_id": str(run.sync_run_id),
            "triggered_by": run.triggered_by,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "status": run.status,
            "entries": entries,
        })
    except Exception as e:
        log.error("admin_sync_progress failed", exc_info=True)
        return _json_error(f"Failed to load progress: {str(e)}", 500)


def _sync_run_dict(run) -> dict:
    """Serialise a VaSyncRun to a JSON-safe dict."""
    if run is None:
        return None
    duration = None
    if run.finished_at and run.started_at:
        duration = int((run.finished_at - run.started_at).total_seconds())
    return {
        "sync_run_id": str(run.sync_run_id),
        "triggered_by": run.triggered_by,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_seconds": duration,
        "status": run.status,
        "records_added": run.records_added,
        "records_updated": run.records_updated,
        "error_message": run.error_message,
    }


def _get_sync_schedule_hours() -> int | None:
    """Return the configured sync interval in hours, or None if not set."""
    try:
        with db.engine.connect() as conn:
            tables_ready = conn.execute(sa.text("""
                SELECT
                    to_regclass('public.celery_periodictask') IS NOT NULL
                    AND to_regclass('public.celery_intervalschedule') IS NOT NULL
            """)).scalar()
            if not tables_ready:
                return None
            row = conn.execute(sa.text("""
                SELECT i.every
                FROM public.celery_periodictask t
                JOIN public.celery_intervalschedule i ON i.id = t.schedule_id
                WHERE t.name = 'ODK Sync — every 6 hours'
                  AND t.discriminator = 'intervalschedule'
                LIMIT 1
            """)).fetchone()
            return row[0] if row else None
    except Exception:
        return None


# ── Language Management API ──────────────────────────────────────────────────


@admin.get("/api/languages")
@role_required("admin")
def admin_languages_list():
    from app.models.mas_languages import MasLanguages, MapLanguageAliases

    include_inactive = request.args.get("include_inactive") == "1"
    include_unmapped = request.args.get("include_unmapped") == "1"

    stmt = sa.select(MasLanguages).order_by(MasLanguages.language_name)
    if not include_inactive:
        stmt = stmt.where(MasLanguages.is_active == True)
    langs = db.session.scalars(stmt).all()

    # Count submissions per language
    sub_counts = dict(
        db.session.execute(
            sa.text("""
                SELECT va_narration_language, COUNT(*)
                FROM va_submissions
                GROUP BY va_narration_language
            """)
        ).all()
    )

    result = []
    for lang in langs:
        aliases = db.session.scalars(
            sa.select(MapLanguageAliases.alias).where(
                MapLanguageAliases.language_code == lang.language_code
            ).order_by(MapLanguageAliases.alias)
        ).all()
        result.append({
            "language_code": lang.language_code,
            "language_name": lang.language_name,
            "is_active": lang.is_active,
            "aliases": aliases,
            "submission_count": sub_counts.get(lang.language_code, 0),
        })

    response = {"languages": result}

    if include_unmapped:
        # Find language values in submissions that don't match any alias
        all_aliases = set(
            db.session.scalars(
                sa.select(sa.func.lower(MapLanguageAliases.alias))
            ).all()
        )
        all_codes = set(
            db.session.scalars(sa.select(MasLanguages.language_code)).all()
        )
        known = all_aliases | all_codes

        unmapped_rows = db.session.execute(
            sa.text("""
                SELECT va_narration_language, COUNT(*) as cnt
                FROM va_submissions
                WHERE va_narration_language IS NOT NULL
                  AND va_narration_language != ''
                GROUP BY va_narration_language
                ORDER BY cnt DESC
            """)
        ).all()
        unmapped = [
            {"value": row[0], "count": row[1]}
            for row in unmapped_rows
            if row[0].lower() not in known
        ]
        response["unmapped"] = unmapped

    return jsonify(response)


@admin.post("/api/languages")
@role_required("admin")
def admin_languages_create():
    from app.models.mas_languages import MasLanguages, MapLanguageAliases

    payload = request.get_json(silent=True) or {}
    code = (payload.get("language_code") or "").strip().lower()
    name = (payload.get("language_name") or "").strip()
    aliases = payload.get("aliases", [])

    if not code or not name:
        return _json_error("language_code and language_name are required.", 400)

    if db.session.get(MasLanguages, code):
        return _json_error(f"Language code '{code}' already exists.", 400)

    lang = MasLanguages(language_code=code, language_name=name, is_active=True)
    db.session.add(lang)

    # Always add the code itself as an alias
    alias_values = {code}
    for a in aliases:
        a = a.strip().lower()
        if a:
            alias_values.add(a)

    for a in alias_values:
        existing_alias = db.session.get(MapLanguageAliases, a)
        if existing_alias:
            return _json_error(
                f"Alias '{a}' is already mapped to '{existing_alias.language_code}'.", 400
            )
        db.session.add(MapLanguageAliases(alias=a, language_code=code))

    db.session.commit()
    return jsonify({"language_code": code, "language_name": name}), 201


@admin.put("/api/languages/<language_code>")
@role_required("admin")
def admin_languages_update(language_code):
    from app.models.mas_languages import MasLanguages, MapLanguageAliases

    lang = db.session.get(MasLanguages, language_code)
    if not lang:
        return _json_error("Language not found.", 404)

    payload = request.get_json(silent=True) or {}

    if "language_name" in payload:
        name = (payload["language_name"] or "").strip()
        if not name:
            return _json_error("language_name cannot be empty.", 400)
        lang.language_name = name

    if "aliases" in payload:
        new_aliases = set()
        for a in payload["aliases"]:
            a = a.strip().lower()
            if a:
                new_aliases.add(a)
        # Always keep the code itself as an alias
        new_aliases.add(language_code)

        # Check for conflicts with other languages
        for a in new_aliases:
            existing = db.session.get(MapLanguageAliases, a)
            if existing and existing.language_code != language_code:
                return _json_error(
                    f"Alias '{a}' is already mapped to '{existing.language_code}'.", 400
                )

        # Remove old aliases not in new set
        current_aliases = db.session.scalars(
            sa.select(MapLanguageAliases).where(
                MapLanguageAliases.language_code == language_code
            )
        ).all()
        for alias_obj in current_aliases:
            if alias_obj.alias.lower() not in new_aliases:
                db.session.delete(alias_obj)

        # Add new aliases not currently present
        current_alias_set = {a.alias.lower() for a in current_aliases}
        for a in new_aliases:
            if a not in current_alias_set:
                db.session.add(MapLanguageAliases(alias=a, language_code=language_code))

    db.session.commit()
    return jsonify({"language_code": lang.language_code, "language_name": lang.language_name})


@admin.post("/api/languages/<language_code>/toggle")
@role_required("admin")
def admin_languages_toggle(language_code):
    from app.models.mas_languages import MasLanguages

    lang = db.session.get(MasLanguages, language_code)
    if not lang:
        return _json_error("Language not found.", 404)

    lang.is_active = not lang.is_active
    db.session.commit()
    return jsonify({
        "language_code": lang.language_code,
        "is_active": lang.is_active,
    })


@admin.delete("/api/languages/<language_code>/aliases/<alias>")
@role_required("admin")
def admin_languages_delete_alias(language_code, alias):
    from app.models.mas_languages import MapLanguageAliases

    # Don't allow removing the code-matching alias
    if alias.lower() == language_code.lower():
        return _json_error("Cannot remove the primary alias (matches language code).", 400)

    alias_obj = db.session.get(MapLanguageAliases, alias)
    if not alias_obj:
        return _json_error("Alias not found.", 404)
    if alias_obj.language_code != language_code:
        return _json_error("Alias does not belong to this language.", 400)

    db.session.delete(alias_obj)
    db.session.commit()
    return jsonify({"deleted": alias})
