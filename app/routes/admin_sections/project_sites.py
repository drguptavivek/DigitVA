import sqlalchemy as sa
from flask import jsonify, render_template, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import VaProjectMaster, VaProjectSites, VaSiteMaster, VaStatuses
from app.routes.admin import admin
from app.routes.admin_support.grants import (
    current_user_can_manage_project as _current_user_can_manage_project,
)
from app.routes.admin_support.http import json_error as _json_error
from app.routes.admin_support.serializers import (
    serialize_project_site as _serialize_project_site,
)


def _get_active_project_site(project_id: str, site_id: str):
    return db.session.scalar(
        sa.select(VaProjectSites)
        .join(VaProjectMaster, VaProjectMaster.project_id == VaProjectSites.project_id)
        .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
        .where(
            VaProjectSites.project_id == project_id,
            VaProjectSites.site_id == site_id,
            VaProjectSites.project_site_status == VaStatuses.active,
            VaProjectMaster.project_status == VaStatuses.active,
            VaSiteMaster.site_status == VaStatuses.active,
        )
    )


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
            VaProjectSites.coding_enabled,
            VaProjectSites.coding_start_date,
            VaProjectSites.coding_end_date,
            VaProjectSites.daily_coder_limit,
            VaProjectMaster.project_name,
            VaSiteMaster.site_name,
        )
        .join(VaProjectMaster, VaProjectMaster.project_id == VaProjectSites.project_id)
        .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
    )
    stmt = stmt.where(
        VaProjectMaster.project_status == VaStatuses.active,
        VaSiteMaster.site_status == VaStatuses.active,
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
            VaProjectSites.coding_enabled,
            VaProjectSites.coding_start_date,
            VaProjectSites.coding_end_date,
            VaProjectSites.daily_coder_limit,
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


@admin.put("/api/project-sites/<project_id>/<site_id>/coding-settings")
@role_required("admin")
def admin_update_project_site_coding_settings(project_id, site_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    from datetime import date as _date

    project_id = project_id.upper()
    site_id = site_id.upper()

    data = request.get_json(silent=True) or {}

    coding_enabled = data.get("coding_enabled")
    coding_start_raw = data.get("coding_start_date")
    coding_end_raw = data.get("coding_end_date")
    daily_coder_limit_raw = data.get("daily_coder_limit")

    if not isinstance(coding_enabled, bool):
        return _json_error("coding_enabled must be a boolean.", 400)

    coding_start = None
    coding_end = None
    try:
        if coding_start_raw:
            coding_start = _date.fromisoformat(coding_start_raw)
        if coding_end_raw:
            coding_end = _date.fromisoformat(coding_end_raw)
    except (ValueError, TypeError):
        return _json_error(
            "coding_start_date and coding_end_date must be ISO date strings (YYYY-MM-DD).",
            400,
        )

    if coding_start and coding_end and coding_end < coding_start:
        return _json_error("coding_end_date must be on or after coding_start_date.", 400)

    if daily_coder_limit_raw is None:
        daily_coder_limit = 100
    else:
        try:
            daily_coder_limit = int(daily_coder_limit_raw)
        except (ValueError, TypeError):
            return _json_error("daily_coder_limit must be an integer.", 400)
        if daily_coder_limit < 1:
            return _json_error("daily_coder_limit must be at least 1.", 400)

    project_site = _get_active_project_site(project_id, site_id)
    if not project_site:
        return _json_error("Active project-site mapping not found.", 404)

    project_site.coding_enabled = coding_enabled
    project_site.coding_start_date = coding_start
    project_site.coding_end_date = coding_end
    project_site.daily_coder_limit = daily_coder_limit
    db.session.commit()

    return jsonify({
        "project_site_id": str(project_site.project_site_id),
        "project_id": project_site.project_id,
        "site_id": project_site.site_id,
        "coding_enabled": project_site.coding_enabled,
        "coding_start_date": (
            project_site.coding_start_date.isoformat()
            if project_site.coding_start_date
            else None
        ),
        "coding_end_date": (
            project_site.coding_end_date.isoformat()
            if project_site.coding_end_date
            else None
        ),
        "daily_coder_limit": project_site.daily_coder_limit,
    })


@admin.get("/panels/project-sites")
@role_required("admin", "project_pi")
def admin_panel_project_sites():
    project_id = request.args.get("project_id") or ""
    return render_template("admin/panels/project_sites.html", project_id=project_id)
