"""Grant routes for data-management user management."""

import uuid

import sqlalchemy as sa
from flask import g, jsonify, request
from flask_login import current_user

from app import db
from app.authz.access import action_authorized
from app.authz.resources import grant_from_kwarg
from app.authz.scope import user_has_role
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.authz.grants import (
    grant_project_id_expression as _grant_project_id_expression,
    grant_site_id_expression as _grant_site_id_expression,
)
from app.http.responses import json_error as _json_error
from app.serializers import serialize_grant as _serialize_grant

from ..base import data_management
from ..helpers import dm_grant_filter, require_dm_scope
from .helpers import _grant_detail_row, _managed_roles


@data_management.get("/api/access-grants")
@action_authorized("dm_manage_grants_view")
def manage_access_grants():
    """List coder/coding_tester/data_manager grants within the DM's scope."""
    project_id_expression = _grant_project_id_expression()
    site_id_expression = _grant_site_id_expression()

    stmt = (
        sa.select(
            VaUserAccessGrants.grant_id,
            VaUserAccessGrants.user_id,
            VaUserAccessGrants.role,
            VaUserAccessGrants.scope_type,
            VaUserAccessGrants.project_site_id,
            VaUserAccessGrants.grant_status,
            VaUserAccessGrants.notes,
            VaUsers.email,
            VaUsers.name,
            project_id_expression.label("resolved_project_id"),
            site_id_expression.label("resolved_site_id"),
        )
        .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
        .outerjoin(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        )
        .where(
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaUserAccessGrants.role.in_(_managed_roles()),
            dm_grant_filter(project_id_expression),
        )
    )

    project_id = request.args.get("project_id")
    if project_id:
        stmt = stmt.where(project_id_expression == project_id)

    role = request.args.get("role")
    if role:
        if role not in {member.value for member in VaAccessRoles}:
            return _json_error("Invalid role.", 400)
        stmt = stmt.where(VaUserAccessGrants.role == VaAccessRoles(role))

    rows = db.session.execute(
        stmt.order_by(project_id_expression, site_id_expression, VaUsers.email)
    ).all()
    return jsonify({"grants": [_serialize_grant(row) for row in rows]})


@data_management.post("/api/access-grants")
@action_authorized("dm_manage_grants_create")
@require_dm_scope
def manage_create_access_grant():
    """Create a coder/coding_tester/data_manager grant within the DM's scope."""
    role, scope_type, resolved_project_id, project_site_id = g.dm_scope

    payload = request.get_json(silent=True) or {}
    user_id_value = payload.get("user_id")
    if not user_id_value:
        return _json_error("user_id is required.", 400)
    try:
        user_id = uuid.UUID(user_id_value)
    except (ValueError, TypeError):
        return _json_error("Invalid user_id.", 400)

    target_user = db.session.get(VaUsers, user_id)
    if not target_user or target_user.user_status != VaStatuses.active:
        return _json_error("Active user not found.", 404)

    if scope_type == VaAccessScopeTypes.project:
        project = db.session.get(VaProjectMaster, resolved_project_id)
        if not project or project.project_status != VaStatuses.active:
            return _json_error("Active project not found.", 404)

    existing = None
    if scope_type == VaAccessScopeTypes.project:
        existing = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == user_id,
                VaUserAccessGrants.role == role,
                VaUserAccessGrants.scope_type == scope_type,
                VaUserAccessGrants.project_id == resolved_project_id,
            )
        )
    else:
        existing = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == user_id,
                VaUserAccessGrants.role == role,
                VaUserAccessGrants.scope_type == scope_type,
                VaUserAccessGrants.project_site_id == project_site_id,
            )
        )

    status_code = 201
    if existing:
        existing.grant_status = VaStatuses.active
        existing.notes = payload.get("notes") or existing.notes
        grant = existing
        status_code = 200
    else:
        grant = VaUserAccessGrants(
            user_id=user_id,
            role=role,
            scope_type=scope_type,
            project_id=resolved_project_id
            if scope_type == VaAccessScopeTypes.project
            else None,
            project_site_id=project_site_id,
            notes=payload.get("notes"),
            grant_status=VaStatuses.active,
        )
        db.session.add(grant)

    db.session.commit()

    from app.logging.va_logger import log_grant_action

    log_grant_action(
        action="grant_reactivated" if status_code == 200 else "grant_created",
        actor_user_id=current_user.user_id,
        actor_role="data_manager",
        target_user_id=user_id,
        grant_id=grant.grant_id,
        role=role.value,
        scope_type=scope_type.value,
        project_id=resolved_project_id,
        project_site_id=project_site_id,
        request_ip=request.remote_addr,
    )

    return jsonify({"grant": _serialize_grant(_grant_detail_row(grant.grant_id))}), status_code


@data_management.post("/api/access-grants/<uuid:grant_id>/toggle")
@action_authorized(
    "dm_manage_grants_toggle",
    resource_resolver=grant_from_kwarg("grant_id"),
)
@require_dm_scope
def manage_toggle_access_grant(grant_id):
    """Toggle (activate/deactivate) a coder/coding_tester/data_manager grant."""
    grant = db.session.get(VaUserAccessGrants, grant_id)
    if not grant:
        return _json_error("Grant not found.", 404)
    if (
        not user_has_role(current_user, "admin")
        and grant.role == VaAccessRoles.data_manager
        and grant.user_id == current_user.user_id
    ):
        return _json_error(
            "You cannot revoke your own data_manager grant from this interface.",
            400,
        )

    new_status = (
        VaStatuses.deactive
        if grant.grant_status == VaStatuses.active
        else VaStatuses.active
    )
    grant.grant_status = new_status
    db.session.commit()

    from app.logging.va_logger import log_grant_action

    log_grant_action(
        action=(
            "grant_toggled_inactive"
            if new_status == VaStatuses.deactive
            else "grant_toggled_active"
        ),
        actor_user_id=current_user.user_id,
        actor_role="data_manager",
        target_user_id=grant.user_id,
        grant_id=grant.grant_id,
        role=grant.role.value,
        scope_type=grant.scope_type.value,
        request_ip=request.remote_addr,
    )

    return jsonify({"grant_id": str(grant.grant_id), "status": grant.grant_status.value})
