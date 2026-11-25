"""Grant query expressions, grant serialization and grant-scope parsing.

Shared by the admin panel (``app.routes.admin``), the data-manager user
interface (``app.routes.data_management``) and ``user_admin_tools_service``,
so services never import a route module for them (digitva-r8nh.13).
"""

import uuid
from dataclasses import dataclass

import sqlalchemy as sa

from app import db
from app.models import (
    MasCadre,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
)


def _grant_unit_column(column):
    """Correlated lookup of one mas_org_unit column for a unit-scoped grant.

    A subquery rather than a join so every grant query resolves the unit
    without having to remember an extra outerjoin; a missing join would
    otherwise silently drop unit grants out of a project filter.
    """
    return (
        sa.select(column)
        .where(MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
        .scalar_subquery()
    )


def _grant_project_id_expression():
    return sa.case(
        (
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
            VaUserAccessGrants.project_id,
        ),
        (
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
            _grant_unit_column(MasOrgUnit.project_id),
        ),
        else_=VaProjectSites.project_id,
    )


def _grant_org_unit_columns():
    """Labelled columns describing a grant's unit and cadre, for _serialize_grant."""
    return (
        _grant_unit_column(MasOrgUnit.unit_code).label("resolved_unit_code"),
        _grant_unit_column(MasOrgUnit.unit_name).label("resolved_unit_name"),
        sa.cast(_grant_unit_column(MasOrgUnit.path), sa.Text).label("resolved_unit_path"),
        sa.select(MasCadre.cadre_code)
        .where(MasCadre.cadre_id == VaUserAccessGrants.cadre_id)
        .scalar_subquery()
        .label("resolved_cadre_code"),
    )


def _grant_site_id_expression():
    return sa.case(
        (
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
            VaProjectSites.site_id,
        ),
        else_=sa.null(),
    )


def _serialize_grant(row):
    org_unit_id = getattr(row, "org_unit_id", None)
    return {
        "grant_id": str(row.grant_id),
        "user_id": str(row.user_id),
        "user_email": row.email,
        "user_name": row.name,
        "user_job_title": getattr(row, "job_title", None),
        "role": row.role.value,
        "scope_type": row.scope_type.value,
        "project_id": row.resolved_project_id,
        "site_id": row.resolved_site_id,
        "project_site_id": str(row.project_site_id) if row.project_site_id else None,
        "org_unit_id": str(org_unit_id) if org_unit_id else None,
        "unit_code": getattr(row, "resolved_unit_code", None),
        "unit_name": getattr(row, "resolved_unit_name", None),
        "unit_path": getattr(row, "resolved_unit_path", None),
        "cadre_code": getattr(row, "resolved_cadre_code", None),
        "status": row.grant_status.value,
        "notes": row.notes,
    }


@dataclass(frozen=True)
class ResolvedGrantScope:
    """One validated grant scope, as parsed from a request payload."""

    role: VaAccessRoles
    scope_type: VaAccessScopeTypes
    project_id: str | None
    project_site_id: uuid.UUID | None
    org_unit_id: uuid.UUID | None = None
    cadre_id: uuid.UUID | None = None


def _refuse_mentor_member(user_id, role):
    """A mentoring institute member holds unit-scope grants only (guard)."""
    if user_id is None:
        return
    from app.services.mentor_institute_service import check_mentor_grant
    from app.services.organization_service import OrganizationError

    try:
        check_mentor_grant(user_id, role, None)
    except OrganizationError as exc:
        raise ValueError(str(exc)) from exc


def _resolve_scope_from_payload(payload, user_id=None):
    """Parse and validate a grant scope; *user_id* (the grantee) enables the
    mentoring-institute guard."""
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
    org_unit_id_value = payload.get("org_unit_id")
    project_site_id = None
    project_site = None

    if scope_type == VaAccessScopeTypes.global_scope:
        if role != VaAccessRoles.admin:
            raise ValueError("Only admin may use global scope.")
        if project_id or project_site_id_value or org_unit_id_value:
            raise ValueError(
                "Global scope must not include project_id, project_site_id or org_unit_id."
            )
        _refuse_mentor_member(user_id, role)
        return ResolvedGrantScope(role, scope_type, None, None)

    if scope_type == VaAccessScopeTypes.project:
        if role not in {
            VaAccessRoles.project_pi,
            VaAccessRoles.collaborator,
            VaAccessRoles.collaborator_pii,
            VaAccessRoles.coder,
            VaAccessRoles.coding_tester,
            VaAccessRoles.reviewer,
            VaAccessRoles.data_manager,
            VaAccessRoles.interviewer,
        }:
            raise ValueError("This role cannot use project scope.")
        if not project_id or project_site_id_value or org_unit_id_value:
            raise ValueError("Project scope requires project_id only.")
        _refuse_mentor_member(user_id, role)
        return ResolvedGrantScope(role, scope_type, project_id, None)

    if scope_type == VaAccessScopeTypes.org_unit:
        from app.services.org_grant_service import validate_org_unit_grant
        from app.services.organization_service import OrganizationError

        if project_id or project_site_id_value:
            raise ValueError(
                "Unit scope must not include project_id or project_site_id."
            )
        if not org_unit_id_value:
            raise ValueError("Unit scope requires org_unit_id.")
        try:
            unit, cadre = validate_org_unit_grant(
                role=role,
                org_unit_id=org_unit_id_value,
                cadre_id=payload.get("cadre_id"),
                user_id=user_id,
            )
        except OrganizationError as exc:
            raise ValueError(str(exc)) from exc
        return ResolvedGrantScope(
            role,
            scope_type,
            unit.project_id,
            None,
            org_unit_id=unit.org_unit_id,
            cadre_id=cadre.cadre_id if cadre else None,
        )

    if role not in {
        VaAccessRoles.site_pi,
        VaAccessRoles.collaborator,
        VaAccessRoles.collaborator_pii,
        VaAccessRoles.coder,
        VaAccessRoles.coding_tester,
        VaAccessRoles.reviewer,
        VaAccessRoles.data_manager,
        VaAccessRoles.interviewer,
    }:
        raise ValueError("This role cannot use project_site scope.")
    if payload.get("project_id"):
        raise ValueError("Project-site scope must not include project_id.")
    if org_unit_id_value:
        raise ValueError("Project-site scope must not include org_unit_id.")
    if not project_site_id_value:
        raise ValueError("Project-site scope requires project_site_id.")
    try:
        project_site_id = uuid.UUID(project_site_id_value)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid project_site_id.") from exc

    project_site = db.session.get(VaProjectSites, project_site_id)
    if not project_site or project_site.project_site_status != VaStatuses.active:
        raise ValueError("Active project-site mapping not found.")
    _refuse_mentor_member(user_id, role)
    return ResolvedGrantScope(
        role, scope_type, project_site.project_id, project_site.project_site_id
    )


def _payload_grant_target(payload):
    """The grant a create payload names, before any validation, or None.

    For asking ``authz.can_grant`` first (digitva-xd1q): the cadre and
    unit checks in ``_resolve_scope_from_payload`` say whether a unit
    exists, is active or takes the cadre, which a caller who may not write
    there must not learn. None when the payload names no well-formed target
    (bad role or scope_type, missing or malformed id); its shape errors
    disclose nothing and ``_resolve_scope_from_payload`` reports them.
    """
    from app.services import authz

    try:
        role = VaAccessRoles(payload.get("role"))
        scope_type = VaAccessScopeTypes(payload.get("scope_type"))
    except ValueError:
        return None
    if scope_type == VaAccessScopeTypes.project:
        project_id = payload.get("project_id")
        if not project_id or not isinstance(project_id, str):
            return None
        return authz.GrantTarget(role=role, scope_type=scope_type, project_id=project_id)
    key = {
        VaAccessScopeTypes.project_site: "project_site_id",
        VaAccessScopeTypes.org_unit: "org_unit_id",
    }.get(scope_type)
    if key is None:
        return None
    try:
        target_id = uuid.UUID(str(payload.get(key)))
    except ValueError:
        return None
    return authz.GrantTarget(role=role, scope_type=scope_type, **{key: target_id})
