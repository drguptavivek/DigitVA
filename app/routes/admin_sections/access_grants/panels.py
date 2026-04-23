from flask import render_template, request

from app.decorators import role_required
from app.routes.admin import admin


@admin.get("/panels/access-grants")
@role_required("admin")
def admin_panel_access_grants():
    project_id = request.args.get("project_id") or ""
    return render_template("admin/panels/access_grants.html", project_id=project_id)
