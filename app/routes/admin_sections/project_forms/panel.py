"""Panel routes for admin project-form mapping."""

from flask import render_template

from app.decorators import role_required
from app.routes.admin import admin


@admin.get("/panels/project-forms")
@role_required("admin")
def admin_panel_project_forms():
    from app.services.smartva.legacy.countries import (
        smartva_allowed_countries,
    )

    return render_template(
        "admin/panels/project_forms.html",
        smartva_countries=smartva_allowed_countries,
    )
