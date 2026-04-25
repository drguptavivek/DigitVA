"""Panel routes for COD bucket management."""

from flask import render_template
from flask_login import current_user

from app.decorators import role_required
from app.routes.admin import admin
from app.services.cod_buckets.management import list_cod_bucket_scheme_cards


@admin.get("/panels/cod-buckets")
@role_required("admin")
def admin_panel_cod_buckets():
    if not current_user.is_admin():
        return render_template("va_errors/va_403.html"), 403

    return render_template(
        "admin/panels/cod_buckets.html",
        cod_bucket_schemes=list_cod_bucket_scheme_cards(),
    )
