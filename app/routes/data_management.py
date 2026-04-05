"""Data management blueprint — /data-management/

Page routes only. JSON API routes live in app/routes/api/data_management.py.
Shared helpers live in app/services/data_management_service.py.
"""

import logging

import sqlalchemy as sa
from flask import Blueprint, render_template, redirect
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import (
    VaSubmissions,
    VaForms,
)
from app.services.submission_analytics_mv import get_dm_kpi_from_mv
from app.services.data_management_service import (
    dm_odk_edit_url,
    audit_dm_submission_action,
)
from app.utils.va_permission.va_permission_01_abortwithflash import (
    va_permission_abortwithflash,
)

data_management = Blueprint("data_management", __name__)
log = logging.getLogger(__name__)


@data_management.get("/")
@role_required("data_manager")
def dashboard():
    project_ids = sorted(current_user.get_data_manager_projects())
    project_site_pairs = current_user.get_data_manager_project_sites()
    if not project_ids and not project_site_pairs:
        va_permission_abortwithflash("No data-manager scope has been assigned.", 403)

    kpi = get_dm_kpi_from_mv(
        project_ids=project_ids,
        project_site_pairs=project_site_pairs,
    )
    return render_template(
        "va_frontpages/va_data_manager.html",
        total_submissions=kpi["total_submissions"],
        flagged_submissions=kpi["flagged_submissions"],
        odk_has_issues_submissions=kpi["odk_has_issues_submissions"],
        smartva_missing_submissions=kpi["smartva_missing_submissions"],
    )


@data_management.get("/view/<va_sid>")
@role_required("data_manager")
def view_submission(va_sid):
    """Data manager read-only view of a submission."""
    import uuid
    from app.models import VaSubmissionsAuditlog
    from app.services.coding_service import render_va_coding_page
    form = db.session.get(VaSubmissions, va_sid)
    if not form:
        va_permission_abortwithflash("Submission not found.", 404)
    # ABAC: verify the DM's grant scope covers this submission's project/site
    form_meta = db.session.execute(
        sa.select(VaForms.project_id, VaForms.site_id).where(VaForms.form_id == form.va_form_id)
    ).mappings().first()
    if not form_meta or not current_user.has_data_manager_submission_access(form_meta["project_id"], form_meta["site_id"]):
        va_permission_abortwithflash("You do not have data-manager access to this submission.", 403)
    # Audit read
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid,
        va_audit_byrole="data_manager",
        va_audit_by=current_user.user_id,
        va_audit_operation="r",
        va_audit_action="data_manager_viewed_submission_read_only",
        va_audit_entityid=uuid.uuid4(),
    ))
    db.session.commit()
    return render_va_coding_page(form, "vadata", "vaview", "data_manager")


@data_management.get("/submissions/<path:va_sid>/odk-edit")
@role_required("data_manager")
def submission_odk_edit(va_sid):
    odk_edit_url = dm_odk_edit_url(current_user, va_sid)
    if not odk_edit_url:
        va_permission_abortwithflash(
            "ODK edit link is not available for this submission.", 404
        )
    audit_dm_submission_action(va_sid, "data_manager_opened_odk_edit_link")
    return redirect(odk_edit_url)
