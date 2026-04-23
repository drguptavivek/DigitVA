"""Project-assignment routes for ODK connections."""

import sqlalchemy as sa
from flask import jsonify, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import MapProjectOdk, MasOdkConnections, VaProjectMaster
from app.http.responses import json_error as _json_error
from app.routes.admin import admin
from app.routes.admin_sections import odk_connections as odk_routes


@admin.get("/api/odk-connections/<uuid:connection_id>/projects")
@role_required("admin")
def admin_odk_connection_projects(connection_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    conn = db.session.get(MasOdkConnections, connection_id)
    if not conn:
        return _json_error("Connection not found.", 404)

    return jsonify({"project_ids": odk_routes._get_connection_project_ids(connection_id)})


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
