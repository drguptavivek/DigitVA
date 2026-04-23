"""Panel route for admin language management."""

from flask import render_template

from app.decorators import role_required
from app.routes.admin import admin


@admin.get("/panels/languages")
@role_required("admin")
def admin_panel_languages():
    return render_template("admin/panels/languages.html")
