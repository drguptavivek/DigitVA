"""Panel routes for ODK connection management."""

from flask import render_template

from app.decorators import role_required
from app.routes.admin import admin


@admin.get("/panels/odk-connections")
@role_required("admin")
def admin_panel_odk_connections():
    return render_template("admin/panels/odk_connections.html")
