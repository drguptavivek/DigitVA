from flask_login import current_user, login_required
from flask import Blueprint, render_template, request
from app.services.sitepi_reporting_service import get_sitepi_dashboard_data
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash

sitepi = Blueprint("sitepi", __name__)


@sitepi.get("/")
@login_required
def dashboard():
    if not current_user.is_site_pi():
        va_permission_abortwithflash("No sites assigned for supervision.", 403)

    sitepi_sites = sorted(current_user.get_site_pi_sites())
    if not sitepi_sites:
        va_permission_abortwithflash("No sites assigned for supervision.", 403)

    default_site = sitepi_sites[0] if sitepi_sites else None
    default_site_data = None

    if default_site:
        default_site_data = get_sitepi_dashboard_data(default_site)

    return render_template(
        "va_frontpages/va_sitepi.html",
        sitepi_sites=sitepi_sites,
        default_site=default_site,
        default_site_data=default_site_data
    )


@sitepi.get("/data")
@login_required
def sitepi_data():
    site_id = request.args.get("siteSelect")
    if not site_id:
        return "<div class='text-center py-5'><p class='text-muted'>No site selected.</p></div>"

    sitepi_sites = sorted(current_user.get_site_pi_sites())
    if site_id not in sitepi_sites:
        return "<div class='text-center py-5'><p class='text-danger'>Access denied for this site.</p></div>"

    site_data = get_sitepi_dashboard_data(site_id)

    return render_template(
        "va_intermediate_partials/sitepi_dashboard_content.html",
        site_data=site_data,
        site_label=site_id,
    )
