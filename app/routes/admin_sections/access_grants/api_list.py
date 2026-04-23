import uuid

import sqlalchemy as sa
from flask import jsonify, request

from app import db
from app.decorators import role_required
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
)
from app.routes.admin import admin
from app.authz.grants import (
    current_user_can_manage_project as _current_user_can_manage_project,
)
from app.http.responses import json_error as _json_error
from app.serializers import serialize_grant as _serialize_grant

from .common import _base_grants_select, _project_access_filter


@admin.get("/api/access-grants")
@role_required("admin")
def admin_access_grants():
    stmt, project_id_expression, site_id_expression = _base_grants_select()
    stmt = stmt.where(
        VaUserAccessGrants.grant_status == VaStatuses.active,
        _project_access_filter(project_id_expression),
    )

    project_id = request.args.get("project_id")
    if project_id:
        if not _current_user_can_manage_project(project_id):
            return _json_error("You do not have access to that project.", 403)
        stmt = stmt.where(project_id_expression == project_id)

    role = request.args.get("role")
    if role:
        if role not in {member.value for member in VaAccessRoles}:
            return _json_error("Invalid role.", 400)
        stmt = stmt.where(VaUserAccessGrants.role == VaAccessRoles(role))

    user_id = request.args.get("user_id")
    if user_id:
        try:
            stmt = stmt.where(VaUserAccessGrants.user_id == uuid.UUID(user_id))
        except (ValueError, TypeError):
            return _json_error("Invalid user_id.", 400)

    rows = db.session.execute(
        stmt.order_by(project_id_expression, site_id_expression, sa.column("email"))
    ).all()
    return jsonify({"grants": [_serialize_grant(row) for row in rows]})


@admin.get("/api/access-grants/orphaned")
@role_required("admin")
def admin_orphaned_grants():
    stmt, project_id_expression, site_id_expression = _base_grants_select()
    stmt = stmt.where(
        VaUserAccessGrants.grant_status == VaStatuses.active,
        VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
        sa.or_(
            VaProjectSites.project_site_id.is_(None),
            VaProjectSites.project_site_status == VaStatuses.deactive,
        ),
        _project_access_filter(project_id_expression),
    )

    project_id = request.args.get("project_id")
    if project_id:
        if not _current_user_can_manage_project(project_id):
            return _json_error("You do not have access to that project.", 403)
        stmt = stmt.where(project_id_expression == project_id)

    rows = db.session.execute(
        stmt.order_by(project_id_expression, site_id_expression, sa.column("email"))
    ).all()
    return jsonify({"grants": [_serialize_grant(row) for row in rows]})
