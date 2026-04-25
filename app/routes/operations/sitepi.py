import uuid

import sqlalchemy as sa
from flask import Blueprint, render_template, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import VaProjectSites, VaStatuses
from app.services.analytics.sitepi_reporting import get_sitepi_dashboard_data
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash

sitepi = Blueprint("sitepi", __name__)


def _sitepi_scope_options():
    granted_pairs = sorted(current_user.get_site_pi_project_sites())
    if not granted_pairs:
        return []

    rows = db.session.execute(
        sa.select(
            VaProjectSites.project_site_id,
            VaProjectSites.project_id,
            VaProjectSites.site_id,
        )
        .where(
            VaProjectSites.project_site_status == VaStatuses.active,
            sa.tuple_(VaProjectSites.project_id, VaProjectSites.site_id).in_(
                granted_pairs
            ),
        )
        .order_by(VaProjectSites.project_id, VaProjectSites.site_id)
    ).all()
    return [
        {
            "project_site_id": str(row.project_site_id),
            "project_id": row.project_id,
            "site_id": row.site_id,
            "label": f"{row.project_id} / {row.site_id}",
        }
        for row in rows
    ]


@sitepi.get("/")
@role_required("site_pi")
def dashboard():
    sitepi_scopes = _sitepi_scope_options()
    if not sitepi_scopes:
        va_permission_abortwithflash("No sites assigned for supervision.", 403)

    default_scope = sitepi_scopes[0] if sitepi_scopes else None
    default_site_data = None

    if default_scope:
        default_site_data = get_sitepi_dashboard_data(default_scope["project_site_id"])

    return render_template(
        "va_frontpages/va_sitepi.html",
        sitepi_sites=sitepi_scopes,
        default_site=default_scope,
        default_site_data=default_site_data
    )


@sitepi.get("/data")
@role_required("site_pi")
def sitepi_data():
    project_site_id_raw = request.args.get("siteSelect")
    if not project_site_id_raw:
        return "<div class='text-center py-5'><p class='text-muted'>No site selected.</p></div>"

    try:
        project_site_id = uuid.UUID(project_site_id_raw)
    except (TypeError, ValueError):
        va_permission_abortwithflash("Access denied for this site.", 403)

    scope = next(
        (
            scope_entry
            for scope_entry in _sitepi_scope_options()
            if scope_entry["project_site_id"] == str(project_site_id)
        ),
        None,
    )
    if scope is None:
        va_permission_abortwithflash("Access denied for this site.", 403)

    site_data = get_sitepi_dashboard_data(project_site_id)

    return render_template(
        "va_intermediate_partials/sitepi_dashboard_content.html",
        site_data=site_data,
        site_label=scope["label"],
    )
