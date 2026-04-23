import sqlalchemy as sa
from flask import jsonify, render_template, request
from flask_login import current_user

from app import db
from app.authz.scope import user_has_role
from app.decorators import role_required
from app.models import VaProjectSites, VaSiteMaster, VaStatuses
from app.routes.admin import admin
from app.authz.grants import (
    current_user_can_manage_project as _current_user_can_manage_project,
)
from app.http.responses import (
    json_error as _json_error,
    validate_entity_id as _validate_entity_id,
)
from app.serializers import serialize_site as _serialize_site


@admin.get("/api/sites")
@role_required("admin", "project_pi")
def admin_sites():
    master = "master=1" in request.query_string.decode()

    if master:
        if not user_has_role(current_user, "admin"):
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
        elif not user_has_role(current_user, "admin"):
            stmt = stmt.where(
                VaProjectSites.project_id.in_(list(current_user.get_project_pi_projects()))
            )

    sites = db.session.scalars(stmt.distinct().order_by(VaSiteMaster.site_id)).all()
    return jsonify({"sites": [_serialize_site(site) for site in sites]})


@admin.post("/api/sites")
@role_required("admin")
def admin_create_site():
    if not user_has_role(current_user, "admin"):
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
        site_status=VaStatuses.active,
    )
    db.session.add(site)
    db.session.commit()
    return jsonify({"site": _serialize_site(site)}), 201


@admin.put("/api/sites/<site_id>")
@role_required("admin")
def admin_update_site(site_id):
    if not user_has_role(current_user, "admin"):
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
    if not user_has_role(current_user, "admin"):
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


@admin.get("/panels/sites")
@role_required("admin")
def admin_panel_sites():
    return render_template("admin/panels/sites.html")
