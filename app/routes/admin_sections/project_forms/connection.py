"""Connection lookup routes for admin project-form mapping."""

import sqlalchemy as sa
from flask import jsonify
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import MapProjectOdk, MasOdkConnections
from app.http.responses import json_error as _json_error
from app.routes.admin import admin
from app.services.odk_connection_guard_service import serialize_connection_guard_state


@admin.get("/api/projects/<project_id>/odk-connection")
@role_required("admin")
def admin_project_odk_connection(project_id):
    if not current_user.is_admin():
        return _json_error("Admin access required.", 403)

    mapping = db.session.scalar(
        sa.select(MapProjectOdk).where(MapProjectOdk.project_id == project_id.upper())
    )
    if not mapping:
        return jsonify({"connection": None})

    conn = db.session.get(MasOdkConnections, mapping.connection_id)
    if not conn:
        return jsonify({"connection": None})

    return jsonify(
        {
            "connection": {
                "connection_id": str(conn.connection_id),
                "connection_name": conn.connection_name,
                "base_url": conn.base_url,
                "status": conn.status.value,
                "guard": serialize_connection_guard_state(conn),
            }
        }
    )
