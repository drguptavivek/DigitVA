from flask import render_template

from app.decorators import role_required
from app.routes.admin import admin


@admin.get("/panels/sync")
@role_required("admin")
def admin_panel_sync():
    return render_template("admin/panels/sync_dashboard.html")
