import sqlalchemy as sa
from flask import jsonify, render_template, request
from flask_login import current_user

from app import db
from app.authz.scope import user_has_role
from app.decorators import role_required
from app.models import VaProjectMaster, VaStatuses
from app.routes.admin import admin
from app.http.responses import (
    json_error as _json_error,
    validate_entity_id as _validate_entity_id,
)
from app.serializers import serialize_project as _serialize_project


@admin.get("/api/projects")
@role_required("admin", "project_pi")
def admin_projects():
    master = "master=1" in request.query_string.decode()

    if master:
        if not user_has_role(current_user, "admin"):
            return _json_error("Admin access required.", 403)
        stmt = sa.select(VaProjectMaster)
        if request.args.get("include_inactive") != "1":
            stmt = stmt.where(VaProjectMaster.project_status == VaStatuses.active)
    else:
        stmt = sa.select(VaProjectMaster).where(
            VaProjectMaster.project_status == VaStatuses.active
        )
        if not user_has_role(current_user, "admin"):
            stmt = stmt.where(
                VaProjectMaster.project_id.in_(list(current_user.get_project_pi_projects()))
            )
    projects = db.session.scalars(stmt.order_by(VaProjectMaster.project_id)).all()
    return jsonify({"projects": [_serialize_project(project) for project in projects]})


@admin.post("/api/projects")
@role_required("admin")
def admin_create_project():
    if not user_has_role(current_user, "admin"):
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
    if not user_has_role(current_user, "admin"):
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
    if not user_has_role(current_user, "admin"):
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


@admin.get("/panels/projects")
@role_required("admin")
def admin_panel_projects():
    return render_template("admin/panels/projects.html")
