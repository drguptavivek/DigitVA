from flask import Blueprint, request
from flask_login import current_user

from app.admin_support.auth import request_user_has_role
from app.http.responses import json_error

admin = Blueprint("admin", __name__)


@admin.before_request
def _enforce_admin_only_master_queries():
    if not current_user or not getattr(current_user, "is_authenticated", False):
        return None

    if request.path not in {"/admin/api/projects", "/admin/api/sites"}:
        return None

    if request.args.get("master") != "1":
        return None

    if request_user_has_role("admin"):
        return None

    return json_error("Admin access required.", 403)


from app.routes.admin_sections import (  # noqa: E402,F401
    access_grants,
    activity,
    cod_buckets,
    data_sync,
    field_mapping,
    icd10_browser,
    languages,
    odk_connections,
    project_forms,
    project_pis,
    project_sites,
    projects,
    shell,
    sites,
    users,
)
