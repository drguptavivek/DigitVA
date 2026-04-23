"""Panel routes for admin project-site management."""

from flask import render_template, request

from app.decorators import role_required
from app.routes.admin import admin


@admin.get("/panels/project-sites")
@role_required("admin", "project_pi")
def admin_panel_project_sites():
    project_id = request.args.get("project_id") or ""
    return render_template("admin/panels/project_sites.html", project_id=project_id)
