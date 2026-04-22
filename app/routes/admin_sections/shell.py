from secrets import token_hex

import sqlalchemy as sa
from flask import jsonify, render_template, session
from flask_login import current_user, login_required
from flask_wtf.csrf import generate_csrf

from app import db
from app.decorators import role_required
from app.models import VaProjectMaster, VaStatuses
from app.routes.admin import admin
from app.routes.admin_support.auth import request_user_has_role
from app.routes.admin_support.http import json_error as _json_error


@admin.get("/api/bootstrap")
@login_required
def admin_bootstrap():
    if not (request_user_has_role("admin") or request_user_has_role("project_pi")):
        return _json_error("Admin API access is not allowed for this user.", 403)
    if "csrf_token" not in session:
        session["csrf_token"] = token_hex(32)
    accessible_projects = sorted(current_user.get_project_pi_projects())
    if request_user_has_role("admin"):
        accessible_projects = sorted(
            db.session.scalars(
                sa.select(VaProjectMaster.project_id).where(
                    VaProjectMaster.project_status == VaStatuses.active
                )
            ).all()
        )
    return jsonify(
        {
            "csrf_header_name": "X-CSRFToken",
            "csrf_token": generate_csrf(),
            "user": {
                "user_id": str(current_user.user_id),
                "email": current_user.email,
                "name": current_user.name,
                "is_admin": request_user_has_role("admin"),
                "project_pi_projects": sorted(current_user.get_project_pi_projects()),
            },
            "accessible_projects": sorted(accessible_projects),
        }
    )


@admin.get("/", strict_slashes=False)
@role_required("admin", "project_pi")
def admin_index():
    return render_template("admin/admin_index.html")
