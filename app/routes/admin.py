from flask import Blueprint, request
from flask_login import current_user

from app.services.odk_connection_guard_service import serialize_connection_guard_state
from app.routes.admin_support.activity import (
    AUDIT_ACTION_DISPLAY as _AUDIT_ACTION_DISPLAY,
    AUDIT_ACTION_EXPLANATIONS as _AUDIT_ACTION_EXPLANATIONS,
    build_activity_rows as _build_activity_rows,
)
from app.routes.admin_support.auth import (
    request_user_from_session as _request_user_from_session,
    request_user_has_role,
    request_user_has_role as _request_user_has_role,
)
from app.routes.admin_support.field_mapping import (
    get_ordered_category_configs_for_form_type as _get_ordered_category_configs_for_form_type,
    ordered_field_lists_for_form_type as _ordered_field_lists_for_form_type,
    serialize_category_browser_state as _serialize_category_browser_state,
)
from app.routes.admin_support.grants import (
    current_user_can_manage_project as _current_user_can_manage_project,
    get_active_project_site as _get_active_project_site,
    grant_project_id_expression as _grant_project_id_expression,
    grant_site_id_expression as _grant_site_id_expression,
    resolve_scope_from_payload as _resolve_scope_from_payload,
)
from app.routes.admin_support.http import (
    json_error,
    json_error as _json_error,
    validate_entity_id as _validate_entity_id,
)
from app.routes.admin_support.odk import (
    get_connection_project_ids as _get_connection_project_ids,
    get_odk_client_for_connection as _get_odk_client_for_connection,
    odk_connection_alerts as _odk_connection_alerts,
    validate_odk_base_url as _validate_odk_base_url,
)
from app.routes.admin_support.serializers import (
    serialize_grant as _serialize_grant,
    serialize_project as _serialize_project,
    serialize_project_site as _serialize_project_site,
    serialize_site as _serialize_site,
    serialize_user as _serialize_user,
    serialize_odk_connection,
)


admin = Blueprint("admin", __name__)


def _serialize_odk_connection(conn, project_ids):
    return serialize_odk_connection(conn, project_ids, serialize_connection_guard_state(conn))


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
