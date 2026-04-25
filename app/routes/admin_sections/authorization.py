from flask import request
from flask_login import current_user

from app.authz.request_context import request_user_has_role
from app.http.responses import json_error
from app.routes.admin import admin

MASTER_QUERY_ENDPOINTS = {"/admin/api/projects", "/admin/api/sites"}


@admin.before_request
def enforce_admin_only_master_queries():
    if not current_user or not getattr(current_user, "is_authenticated", False):
        return None

    if request.path not in MASTER_QUERY_ENDPOINTS:
        return None

    if request.args.get("master") != "1":
        return None

    if request_user_has_role("admin"):
        return None

    return json_error("Admin access required.", 403)
