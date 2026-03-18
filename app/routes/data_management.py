"""Data management blueprint — /data-management/

Page routes only. JSON API routes live in app/routes/api/data_management.py.
Shared helpers live in app/services/data_management_service.py.
"""

import logging

import sqlalchemy as sa
from flask import Blueprint, render_template, redirect
from flask_login import login_required, current_user

from app import db
from app.models import (
    VaSubmissions,
    VaSubmissionAttachments,
    VaSmartvaResults,
    VaStatuses,
    VaDataManagerReview,
    VaForms,
    VaSubmissionWorkflow,
)
from app.services.submission_analytics_mv import get_dm_kpi_from_mv
from app.services.data_management_service import (
    dm_scope_filter,
    dm_scoped_forms,
    dm_odk_edit_url,
    audit_dm_submission_action,
)
from app.utils import va_render_serialisedates
from app.utils.va_permission.va_permission_01_abortwithflash import (
    va_permission_abortwithflash,
)

data_management = Blueprint("data_management", __name__)
log = logging.getLogger(__name__)


@data_management.get("/")
@login_required
def dashboard():
    if not current_user.is_data_manager():
        va_permission_abortwithflash("Data-manager access is required.", 403)

    project_ids = sorted(current_user.get_data_manager_projects())
    project_site_pairs = current_user.get_data_manager_project_sites()
    if not project_ids and not project_site_pairs:
        va_permission_abortwithflash("No data-manager scope has been assigned.", 403)

    scope_filter = dm_scope_filter(current_user)
    kpi = get_dm_kpi_from_mv(
        project_ids=project_ids,
        project_site_pairs=project_site_pairs,
    )
    total_submissions = kpi["total_submissions"]
    flagged_submissions = kpi["flagged_submissions"]
    odk_has_issues_submissions = kpi["odk_has_issues_submissions"]
    smartva_missing_submissions = kpi["smartva_missing_submissions"]
    attachment_counts = (
        sa.select(
            VaSubmissionAttachments.va_sid.label("va_sid"),
            sa.func.count().label("attachment_count"),
        )
        .where(VaSubmissionAttachments.exists_on_odk.is_(True))
        .group_by(VaSubmissionAttachments.va_sid)
        .subquery()
    )
    smartva_active_results = (
        sa.select(VaSmartvaResults.va_sid.label("va_sid"))
        .where(VaSmartvaResults.va_smartva_status == VaStatuses.active)
        .group_by(VaSmartvaResults.va_sid)
        .subquery()
    )
    _mv_ref = sa.table(
        "va_submission_analytics_mv",
        sa.column("va_sid"),
        sa.column("analytics_age_band"),
    )
    submission_rows = [
        va_render_serialisedates(
            row,
            ["va_submission_date", "va_dmreview_createdat"],
        )
        for row in db.session.execute(
            sa.select(
                VaSubmissions.va_sid,
                VaSubmissions.va_uniqueid_masked,
                VaForms.project_id,
                VaForms.site_id,
                sa.func.date(VaSubmissions.va_submission_date).label(
                    "va_submission_date"
                ),
                VaSubmissions.va_data_collector,
                sa.func.coalesce(
                    attachment_counts.c.attachment_count, 0
                ).label("attachment_count"),
                smartva_active_results.c.va_sid.label("smartva_result_sid"),
                VaSubmissions.va_odk_reviewstate,
                VaSubmissions.va_odk_reviewcomments,
                VaSubmissions.va_sync_issue_code,
                VaSubmissions.va_sync_issue_updated_at,
                VaSubmissionWorkflow.workflow_state,
                VaDataManagerReview.va_dmreview_createdat,
                _mv_ref.c.analytics_age_band,
                VaSubmissions.va_deceased_gender,
            )
            .select_from(VaSubmissions)
            .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
            .join(
                VaSubmissionWorkflow,
                VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid,
            )
            .outerjoin(
                attachment_counts,
                attachment_counts.c.va_sid == VaSubmissions.va_sid,
            )
            .outerjoin(
                smartva_active_results,
                smartva_active_results.c.va_sid == VaSubmissions.va_sid,
            )
            .outerjoin(
                VaDataManagerReview,
                sa.and_(
                    VaDataManagerReview.va_sid == VaSubmissions.va_sid,
                    VaDataManagerReview.va_dmreview_status == VaStatuses.active,
                ),
            )
            .outerjoin(
                _mv_ref,
                _mv_ref.c.va_sid == VaSubmissions.va_sid,
            )
            .where(scope_filter)
            .order_by(
                VaForms.project_id,
                VaForms.site_id,
                VaSubmissions.va_submission_date.desc(),
            )
        ).mappings().all()
    ]
    scoped_forms = dm_scoped_forms(current_user)
    return render_template(
        "va_frontpages/va_data_manager.html",
        total_submissions=total_submissions,
        flagged_submissions=flagged_submissions,
        odk_has_issues_submissions=odk_has_issues_submissions,
        smartva_missing_submissions=smartva_missing_submissions,
        submission_rows=submission_rows,
        scoped_forms=scoped_forms,
    )


@data_management.get("/submissions/<path:va_sid>/odk-edit")
@login_required
def submission_odk_edit(va_sid):
    odk_edit_url = dm_odk_edit_url(current_user, va_sid)
    if not odk_edit_url:
        va_permission_abortwithflash(
            "ODK edit link is not available for this submission.", 404
        )
    audit_dm_submission_action(va_sid, "data_manager_opened_odk_edit_link")
    return redirect(odk_edit_url)
