"""Dashboard and submission page routes for data-management."""

import uuid

from flask import g, redirect, render_template
from flask_login import current_user

from app import db
from app.authz.access import action_authorized
from app.authz.resources import submission_from_kwarg
from app.services.cod_buckets.management import (
    SCHEME_CODE_SRS_INDIA,
    list_cod_bucket_schemes,
)
from app.services.data_management.dashboard import (
    audit_dm_submission_action,
    dm_odk_edit_url,
    dm_scoped_forms,
    reporting_scope_pairs,
)
from app.services.analytics.submission_mv import get_dm_kpi_from_mv
from app.utils.va_permission.va_permission_01_abortwithflash import (
    va_permission_abortwithflash,
)

from app.routes.operations import data_management as dm_routes
from .base import data_management


@data_management.get("/")
@action_authorized("dm_dashboard_view")
def dashboard():
    scope_pairs = reporting_scope_pairs(current_user)
    if not scope_pairs:
        va_permission_abortwithflash("No data-manager scope has been assigned.", 403)

    kpi = dm_routes.get_dm_kpi_from_mv(project_ids=[], project_site_pairs=scope_pairs)
    return render_template(
        "va_frontpages/va_data_manager.html",
        total_submissions=kpi["total_submissions"],
        flagged_submissions=kpi["flagged_submissions"],
        odk_has_issues_submissions=kpi["odk_has_issues_submissions"],
        smartva_missing_submissions=kpi["smartva_missing_submissions"],
    )


@data_management.get("/dashboard")
@action_authorized("dm_kpi_dashboard_view")
def kpi_dashboard():
    """Data manager KPI analytics dashboard."""
    if not reporting_scope_pairs(current_user):
        va_permission_abortwithflash("No data-manager scope has been assigned.", 403)

    return render_template("va_frontpages/va_dm_kpi_dashboard.html")


@data_management.get("/cod-buckets")
@action_authorized("cod_dashboard_view")
def cod_bucket_reporting():
    if not reporting_scope_pairs(current_user):
        va_permission_abortwithflash("No reporting scope has been assigned.", 403)

    forms = dm_routes.dm_scoped_forms(current_user)
    schemes = [
        {
            "scheme_code": scheme.scheme_code,
            "scheme_name": scheme.scheme_name,
        }
        for scheme in list_cod_bucket_schemes()
        if scheme.is_active
    ]
    default_scheme_code = (
        SCHEME_CODE_SRS_INDIA
        if any(scheme["scheme_code"] == SCHEME_CODE_SRS_INDIA for scheme in schemes)
        else (schemes[0]["scheme_code"] if schemes else None)
    )
    return render_template(
        "va_frontpages/va_cod_bucket_reporting.html",
        cod_bucket_forms=forms,
        cod_bucket_schemes=schemes,
        cod_bucket_default_scheme_code=default_scheme_code,
    )


@data_management.get("/view/<va_sid>")
@action_authorized("dm_submission_view", resource_resolver=submission_from_kwarg("va_sid"))
def view_submission(va_sid):
    """Data manager read-only view of a submission."""
    from app.models import VaSubmissionsAuditlog
    from app.services.rendering.coding_page import render_va_coding_page

    form = g.authz_resource.obj
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole="data_manager",
            va_audit_by=current_user.user_id,
            va_audit_operation="r",
            va_audit_action="data_manager_viewed_submission_read_only",
            va_audit_entityid=uuid.uuid4(),
        )
    )
    db.session.commit()
    return render_va_coding_page(form, "vadata", "vaview", "data_manager")


@data_management.get("/submissions/<path:va_sid>/odk-edit")
@action_authorized("dm_submission_odk_edit", resource_resolver=submission_from_kwarg("va_sid"))
def submission_odk_edit(va_sid):
    odk_edit_url = dm_odk_edit_url(current_user, va_sid)
    if not odk_edit_url:
        va_permission_abortwithflash(
            "ODK edit link is not available for this submission.",
            404,
        )
    audit_dm_submission_action(va_sid, "data_manager_opened_odk_edit_link")
    return redirect(odk_edit_url)
