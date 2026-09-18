"""Unit-scoped access grants: validation and resolution.

A grant with ``scope_type = 'org_unit'`` points at one node of a project's
organization tree (``mas_org_unit``) and covers that node's own subtree. The
cadre on the grant is descriptive, but it is validated when the grant is
created: the cadre must be defined at the unit's level, and a ``coder`` grant
requires a cadre that may code at that level.

Runtime coding and reviewer enforcement is phase 4; this module only resolves
grants to unit id sets so those surfaces have one place to ask.

Policy: docs/policy/organization-model.md, docs/policy/access-control-model.md.
Plan: docs/planning/health-system-organization-model-plan.md (phase 2).
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from app import db
from app.models import (
    MasCadre,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services.organization_service import (
    OrganizationError,
    get_level_cadre_permission,
)

# Roles a unit-scoped grant may carry. Mirrors the
# ck_va_user_access_grants_role_scope check constraint; admin stays global and
# project_pi stays project-scoped.
ROLES_ALLOWING_ORG_UNIT = frozenset(
    {
        VaAccessRoles.site_pi,
        VaAccessRoles.collaborator,
        VaAccessRoles.coder,
        VaAccessRoles.coding_tester,
        VaAccessRoles.reviewer,
        VaAccessRoles.data_manager,
        VaAccessRoles.interviewer,
    }
)

# Roles whose cadre must be permitted to code at the unit's level. The cadre is
# mandatory for these roles for that reason.
ROLES_REQUIRING_CODING_CADRE = frozenset({VaAccessRoles.coder})


def _as_uuid(raw: object, *, what: str) -> uuid.UUID:
    if isinstance(raw, uuid.UUID):
        return raw
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError, AttributeError) as exc:
        raise OrganizationError(f"Invalid {what}.") from exc


def get_active_unit(org_unit_id: object) -> MasOrgUnit:
    """Return the active unit, or raise OrganizationError."""
    unit = db.session.get(MasOrgUnit, _as_uuid(org_unit_id, what="unit id"))
    if unit is None:
        raise OrganizationError("Organization unit not found.")
    if not unit.is_active:
        raise OrganizationError("Organization unit is inactive.")
    return unit


def validate_org_unit_grant(
    *,
    role: VaAccessRoles,
    org_unit_id: object,
    cadre_id: object | None = None,
) -> tuple[MasOrgUnit, MasCadre | None]:
    """Check a unit-scoped grant before it is written.

    Returns the resolved (unit, cadre). Raises OrganizationError with a message
    meant for the operator when the combination is not allowed.
    """
    if role not in ROLES_ALLOWING_ORG_UNIT:
        raise OrganizationError(f"Role {role.value!r} cannot use org_unit scope.")

    unit = get_active_unit(org_unit_id)

    cadre = None
    if cadre_id is not None and str(cadre_id).strip():
        cadre = db.session.get(MasCadre, _as_uuid(cadre_id, what="cadre id"))
        if cadre is None or cadre.project_id != unit.project_id:
            raise OrganizationError("Cadre not found in this unit's project.")
        if not cadre.is_active:
            raise OrganizationError(f"Cadre {cadre.cadre_code!r} is inactive.")

    if role in ROLES_REQUIRING_CODING_CADRE:
        if cadre is None:
            raise OrganizationError(
                f"A {role.value} grant on a unit requires a cadre that may code "
                "at that unit's level."
            )
        permission = get_level_cadre_permission(unit.org_level_id, cadre.cadre_id)
        if permission is None:
            raise OrganizationError(
                f"Cadre {cadre.cadre_code!r} is not defined at level "
                f"{unit.level.level_code!r}; add it in the level permissions grid first."
            )
        if not permission.can_code_va_form:
            raise OrganizationError(
                f"Cadre {cadre.cadre_code!r} may not code VA forms at level "
                f"{unit.level.level_code!r}."
            )
    elif cadre is not None:
        # Descriptive cadre on a non-coding role: it must still exist at the level.
        if get_level_cadre_permission(unit.org_level_id, cadre.cadre_id) is None:
            raise OrganizationError(
                f"Cadre {cadre.cadre_code!r} is not defined at level "
                f"{unit.level.level_code!r}; add it in the level permissions grid first."
            )

    return unit, cadre


def _grant_units_stmt(user_id: uuid.UUID, role: VaAccessRoles):
    return (
        sa.select(MasOrgUnit)
        .join(
            VaUserAccessGrants,
            VaUserAccessGrants.org_unit_id == MasOrgUnit.org_unit_id,
        )
        .where(
            VaUserAccessGrants.user_id == user_id,
            VaUserAccessGrants.role == role,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            MasOrgUnit.is_active.is_(True),
        )
    )


def granted_units(user_id: uuid.UUID, role: VaAccessRoles) -> list[MasOrgUnit]:
    """The units a user holds *role* at directly (not their subtrees)."""
    return list(db.session.scalars(_grant_units_stmt(user_id, role)).all())


def scope_unit_ids(user_id: uuid.UUID, role: VaAccessRoles) -> set[uuid.UUID]:
    """Every active unit inside the subtree of any *role* grant of the user.

    One shaped query: the grant units join their own descendants through the
    ltree path (GiST-indexed), so a user with several grants still costs one
    round trip.
    """
    granted = sa.orm.aliased(MasOrgUnit, name="granted_unit")
    covered = sa.orm.aliased(MasOrgUnit, name="covered_unit")
    stmt = (
        sa.select(covered.org_unit_id)
        .select_from(VaUserAccessGrants)
        .join(granted, granted.org_unit_id == VaUserAccessGrants.org_unit_id)
        .join(
            covered,
            sa.and_(
                covered.project_id == granted.project_id,
                sa.text("covered_unit.path <@ granted_unit.path"),
            ),
        )
        .where(
            VaUserAccessGrants.user_id == user_id,
            VaUserAccessGrants.role == role,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            granted.is_active.is_(True),
            covered.is_active.is_(True),
        )
    )
    return set(db.session.scalars(stmt).all())


def granted_project_ids(user_id: uuid.UUID, role: VaAccessRoles) -> set[str]:
    """Projects the user holds *role* in through a unit-scoped grant."""
    stmt = _grant_units_stmt(user_id, role).with_only_columns(MasOrgUnit.project_id)
    return set(db.session.scalars(stmt).all())
