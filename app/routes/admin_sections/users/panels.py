from flask import render_template

from app.decorators import role_required
from app.routes.admin import admin

from .helpers import _available_languages


@admin.get("/panels/users")
@role_required("admin")
def admin_panel_users():
    return render_template(
        "admin/panels/users.html",
        available_languages=_available_languages(),
    )
