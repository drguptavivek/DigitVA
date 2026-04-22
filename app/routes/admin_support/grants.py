import uuid

import sqlalchemy as sa
from flask_login import current_user

from app import db
from app.models import (
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
)


def current_user_can_manage_project(project_id):
    return current_user.is_admin() or current_user.can_manage_project(project_id)


def grant_project_id_expression():
    return sa.case(
        (
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
            VaUserAccessGrants.project_id,
        ),
        else_=VaProjectSites.project_id,
    )


def grant_site_id_expression():
    return sa.case(
        (
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
            VaProjectSites.site_id,
        ),
        else_=sa.null(),
    )


def get_active_project_site(project_id: str, site_id: str):
    return db.session.scalar(
        sa.select(VaProjectSites)
        .join(VaProjectMaster, VaProjectMaster.project_id == VaProjectSites.project_id)
        .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
        .where(
            VaProjectSites.project_id == project_id,
            VaProjectSites.site_id == site_id,
            VaProjectSites.project_site_status == VaStatuses.active,
            VaProjectMaster.project_status == VaStatuses.active,
            VaSiteMaster.site_status == VaStatuses.active,
        )
    )


def resolve_scope_from_payload(payload):
    role_value = payload.get("role")
    scope_value = payload.get("scope_type")
    if role_value not in {role.value for role in VaAccessRoles}:
        raise ValueError("Invalid role.")
    if scope_value not in {scope.value for scope in VaAccessScopeTypes}:
        raise ValueError("Invalid scope_type.")

    role = VaAccessRoles(role_value)
    scope_type = VaAccessScopeTypes(scope_value)
    project_id = payload.get("project_id")
    project_site_id_value = payload.get("project_site_id")

    if scope_type == VaAccessScopeTypes.global_scope:
        if role != VaAccessRoles.admin:
            raise ValueError("Only admin may use global scope.")
        if project_id or project_site_id_value:
            raise ValueError("Global scope must not include project_id or project_site_id.")
        return role, scope_type, None, None

    if scope_type == VaAccessScopeTypes.project:
        if role not in {
            VaAccessRoles.project_pi,
            VaAccessRoles.collaborator,
            VaAccessRoles.coder,
            VaAccessRoles.coding_tester,
            VaAccessRoles.reviewer,
            VaAccessRoles.data_manager,
        }:
            raise ValueError("This role cannot use project scope.")
        if not project_id or project_site_id_value:
            raise ValueError("Project scope requires project_id only.")
        return role, scope_type, project_id, None

    if role not in {
        VaAccessRoles.site_pi,
        VaAccessRoles.collaborator,
        VaAccessRoles.coder,
        VaAccessRoles.coding_tester,
        VaAccessRoles.reviewer,
        VaAccessRoles.data_manager,
    }:
        raise ValueError("This role cannot use project_site scope.")
    if payload.get("project_id"):
        raise ValueError("Project-site scope must not include project_id.")
    if not project_site_id_value:
        raise ValueError("Project-site scope requires project_site_id.")

    try:
        project_site_id = uuid.UUID(project_site_id_value)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid project_site_id.") from exc

    project_site = db.session.get(VaProjectSites, project_site_id)
    if not project_site or project_site.project_site_status != VaStatuses.active:
        raise ValueError("Active project-site mapping not found.")
    return role, scope_type, project_site.project_id, project_site.project_site_id
