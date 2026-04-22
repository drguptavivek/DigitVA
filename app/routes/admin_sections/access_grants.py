import uuid

import sqlalchemy as sa
from flask import jsonify, render_template, request
from flask_login import current_user

from app import db
from app.decorators import role_required
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.routes.admin import admin
from app.routes.admin_support.grants import (
    current_user_can_manage_project as _current_user_can_manage_project,
    grant_project_id_expression as _grant_project_id_expression,
    grant_site_id_expression as _grant_site_id_expression,
    resolve_scope_from_payload as _resolve_scope_from_payload,
)
from app.routes.admin_support.http import json_error as _json_error
from app.routes.admin_support.serializers import serialize_grant as _serialize_grant


def _project_access_filter(project_id_expression):
    if current_user.is_authenticated and current_user.is_admin():
        return sa.true()
    if current_user.is_authenticated:
        return project_id_expression.in_(list(current_user.get_project_pi_projects()))
    return sa.false()


@admin.get("/api/access-grants")
@role_required("admin")
def admin_access_grants():
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
            _project_access_filter(project_id_expression),
        )
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
        stmt.order_by(project_id_expression, site_id_expression, VaUsers.email)
    ).all()
    return jsonify({"grants": [_serialize_grant(row) for row in rows]})


@admin.get("/api/access-grants/orphaned")
@role_required("admin")
def admin_orphaned_grants():
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
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
            sa.or_(
                VaProjectSites.project_site_id == None,
                VaProjectSites.project_site_status == VaStatuses.deactive,
            ),
            _project_access_filter(project_id_expression),
        )
    )

    project_id = request.args.get("project_id")
    if project_id:
        if not _current_user_can_manage_project(project_id):
            return _json_error("You do not have access to that project.", 403)
        stmt = stmt.where(project_id_expression == project_id)

    rows = db.session.execute(
        stmt.order_by(project_id_expression, site_id_expression, VaUsers.email)
    ).all()
    return jsonify({"grants": [_serialize_grant(row) for row in rows]})


@admin.post("/api/access-grants")
@role_required("admin")
def admin_create_access_grant():
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

    try:
        role, scope_type, resolved_project_id, project_site_id = _resolve_scope_from_payload(
            payload
        )
    except ValueError as exc:
        return _json_error(str(exc), 400)

    if scope_type == VaAccessScopeTypes.project:
        project = db.session.get(VaProjectMaster, resolved_project_id)
        if not project or project.project_status != VaStatuses.active:
            return _json_error("Active project not found.", 404)

    if not current_user.is_admin():
        if role in {VaAccessRoles.admin, VaAccessRoles.project_pi}:
            return _json_error("Project PI may not manage admin or project_pi grants.", 403)
        if not _current_user_can_manage_project(resolved_project_id):
            return _json_error("You do not have access to that project.", 403)

    status_code = 201
    existing = None
    if scope_type == VaAccessScopeTypes.global_scope:
        existing = db.session.scalar(
            sa.select(VaUserAccessGrants).where(
                VaUserAccessGrants.user_id == user_id,
                VaUserAccessGrants.role == role,
                VaUserAccessGrants.scope_type == scope_type,
            )
        )
    elif scope_type == VaAccessScopeTypes.project:
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
        action="grant_reactivated" if (status_code == 200) else "grant_created",
        actor_user_id=current_user.user_id,
        actor_role="admin",
        target_user_id=user_id,
        grant_id=grant.grant_id,
        role=role.value,
        scope_type=scope_type.value,
        project_id=resolved_project_id,
        project_site_id=project_site_id,
        request_ip=request.remote_addr,
    )

    row = db.session.execute(
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
            _grant_project_id_expression().label("resolved_project_id"),
            _grant_site_id_expression().label("resolved_site_id"),
        )
        .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
        .outerjoin(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        )
        .where(VaUserAccessGrants.grant_id == grant.grant_id)
    ).one()
    return jsonify({"grant": _serialize_grant(row)}), status_code


@admin.post("/api/access-grants/<uuid:grant_id>/toggle")
@role_required("admin")
def admin_toggle_access_grant(grant_id):
    grant = db.session.get(VaUserAccessGrants, grant_id)
    if not grant:
        return _json_error("Grant not found.", 404)

    if grant.scope_type == VaAccessScopeTypes.project:
        resolved_project_id = grant.project_id
    elif grant.scope_type == VaAccessScopeTypes.project_site:
        project_site = db.session.get(VaProjectSites, grant.project_site_id)
        resolved_project_id = project_site.project_id if project_site else None
    else:
        resolved_project_id = None

    if not current_user.is_admin():
        if grant.role in {VaAccessRoles.admin, VaAccessRoles.project_pi}:
            return _json_error("Project PI may not manage admin or project_pi grants.", 403)
        if not resolved_project_id or not _current_user_can_manage_project(
            resolved_project_id
        ):
            return _json_error("This operation is not permitted for this resource.", 403)

    new_status = (
        VaStatuses.deactive if grant.grant_status == VaStatuses.active else VaStatuses.active
    )
    grant.grant_status = new_status
    db.session.commit()

    from app.logging.va_logger import log_grant_action

    log_grant_action(
        action="grant_toggled_inactive"
        if new_status == VaStatuses.deactive
        else "grant_toggled_active",
        actor_user_id=current_user.user_id,
        actor_role="admin",
        target_user_id=grant.user_id,
        grant_id=grant.grant_id,
        role=grant.role.value,
        scope_type=grant.scope_type.value,
        project_id=resolved_project_id,
        project_site_id=grant.project_site_id,
        request_ip=request.remote_addr,
    )

    return jsonify({"grant_id": str(grant.grant_id), "status": grant.grant_status.value})


@admin.get("/panels/access-grants")
@role_required("admin")
def admin_panel_access_grants():
    project_id = request.args.get("project_id") or ""
    return render_template("admin/panels/access_grants.html", project_id=project_id)
