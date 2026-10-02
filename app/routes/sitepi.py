from flask_login import current_user
from flask import Blueprint, render_template, request
from app.decorators import role_required
from app.services.sitepi_reporting_service import get_sitepi_dashboard_data
from app.utils.va_permission.va_permission_01_abortwithflash import va_permission_abortwithflash

sitepi = Blueprint("sitepi", __name__)


def _site_key(project_id: str, site_id: str) -> str:
    """The dropdown value for one (project, site) pair: a site_id alone is
    shared across projects (digitva-d5s)."""
    return f"{project_id}:{site_id}"


def _site_label(project_id: str, site_id: str) -> str:
    return f"{project_id} / {site_id}"


@sitepi.get("/")
@role_required("site_pi")
def dashboard():
    pairs = sorted(current_user.get_site_pi_project_site_pairs())
    if not pairs:
        va_permission_abortwithflash("No sites assigned for supervision.", 403)

    sitepi_sites = [(_site_key(p, s), _site_label(p, s)) for p, s in pairs]
    default_project_id, default_site_id = pairs[0]

    return render_template(
        "va_frontpages/va_sitepi.html",
        sitepi_sites=sitepi_sites,
        default_site=_site_label(default_project_id, default_site_id),
        default_site_data=get_sitepi_dashboard_data(default_project_id, default_site_id),
    )


@sitepi.get("/data")
@role_required("site_pi")
def sitepi_data():
    selected = request.args.get("siteSelect")
    if not selected:
        return "<div class='text-center py-5'><p class='text-muted'>No site selected.</p></div>"

    project_id, _, site_id = selected.partition(":")
    # The user's own grants are the allowlist; anything else is refused.
    if (project_id, site_id) not in current_user.get_site_pi_project_site_pairs():
        va_permission_abortwithflash("Access denied for this site.", 403)

    site_data = get_sitepi_dashboard_data(project_id, site_id)

    return render_template(
        "va_intermediate_partials/sitepi_dashboard_content.html",
        site_data=site_data,
        site_label=_site_label(project_id, site_id),
    )
