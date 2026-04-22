from flask import render_template

from app.decorators import role_required
from app.routes.admin import admin


@admin.get("/panels/project-pi")
@role_required("admin")
def admin_panel_project_pi():
    return render_template("admin/panels/project_pi.html")
