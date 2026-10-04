"""Unit-scoped access grants: validation and resolution.

A grant with ``scope_type = 'org_unit'`` points at one node of a project's
organization tree (``mas_org_unit``) and covers that node's own subtree. The
cadre on the grant is descriptive, but it is validated when the grant is
created: the cadre must be defined at the unit's level, a ``coder`` grant
requires a cadre that may code at that level, and an ``interview_supervisor``
grant (unit scope only) a cadre that may supervise interviews there.

Authorization decisions are ``app.services.authz``'s; this module keeps the
write-time validation and the unit-set resolvers web intake and the unit
pickers build on.

Policy: docs/policy/organization-model.md, docs/policy/access-control-model.md.
Plan: docs/planning/health-system-organization-model-plan.md (phase 2).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import sqlalchemy as sa

from app import db
from app.models import (
    MapOrgUnitCodingGate,
    MapOrgUnitVaPresets,
    MasCadre,
    MasOrgLevel,
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
# project_pi project-scoped. site_pi at a unit is the In-charge
# (access-control-model.md, "In-charge"), in a tree project only.
ROLES_ALLOWING_ORG_UNIT = frozenset(
    {
        VaAccessRoles.site_pi,
        VaAccessRoles.collaborator,
        VaAccessRoles.collaborator_pii,
        VaAccessRoles.coder,
        VaAccessRoles.coding_tester,
        VaAccessRoles.reviewer,
        VaAccessRoles.data_manager,
        VaAccessRoles.interviewer,
        VaAccessRoles.interview_supervisor,
    }
)

# Roles whose cadre must be permitted to code at the unit's level. The cadre is
# mandatory for these roles for that reason.
ROLES_REQUIRING_CODING_CADRE = frozenset({VaAccessRoles.coder})

# Role -> (level x cadre flag its cadre must carry, what the flag permits).
# A grant of one of these roles on a unit requires a cadre with that flag at the
# unit's level (decision 12 of .tasks/2026-09-28-interviewer-worklist.md for
# interview_supervisor). Checked when the grant is written, never at runtime.
CADRE_FLAG_BY_ROLE = {
    VaAccessRoles.coder: ("can_code_va_form", "code VA forms"),
    VaAccessRoles.interview_supervisor: ("can_supervise_interviews", "supervise interviews"),
}


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
    user_id: uuid.UUID | None = None,
) -> tuple[MasOrgUnit, MasCadre | None]:
    """Check a unit-scoped grant before it is written.

    Returns the resolved (unit, cadre). Raises OrganizationError with a message
    meant for the operator when the combination is not allowed. Pass *user_id*
    (the grantee) to apply the mentoring-institute guard.
    """
    if role not in ROLES_ALLOWING_ORG_UNIT:
        raise OrganizationError(f"Role {role.value!r} cannot use org_unit scope.")

    unit = get_active_unit(org_unit_id)
    if role == VaAccessRoles.site_pi and not db.session.scalar(sa.select(sa.exists().where(
        MasOrgLevel.project_id == unit.project_id, MasOrgLevel.is_active.is_(True),
    ))):
        # The In-charge belongs to a tree (organization) project; a site
        # project keeps site_pi on its (project, site) pairs.
        raise OrganizationError("An In-charge (site_pi at a unit) needs an organization project.")
    if user_id is not None:
        from app.services.mentor_institute_service import check_mentor_grant

        check_mentor_grant(user_id, role, unit)

    cadre = None
    if cadre_id is not None and str(cadre_id).strip():
        cadre = db.session.get(MasCadre, _as_uuid(cadre_id, what="cadre id"))
        if cadre is None or cadre.project_id != unit.project_id:
            raise OrganizationError("Cadre not found in this unit's project.")
        if not cadre.is_active:
            raise OrganizationError(f"Cadre {cadre.cadre_code!r} is inactive.")

    if role in CADRE_FLAG_BY_ROLE:
        flag, permits = CADRE_FLAG_BY_ROLE[role]
        if cadre is None:
            raise OrganizationError(
                f"A {role.value} grant on a unit requires a cadre that may {permits} "
                "at that unit's level."
            )
        permission = get_level_cadre_permission(unit.org_level_id, cadre.cadre_id)
        if permission is None:
            raise OrganizationError(
                f"Cadre {cadre.cadre_code!r} is not defined at level "
                f"{unit.level.level_code!r}; add it in the level permissions grid first."
            )
        if not getattr(permission, flag):
            raise OrganizationError(
                f"Cadre {cadre.cadre_code!r} may not {permits} at level "
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


def active_project_condition(project_id_expr):
    """SQL predicate: *project_id_expr* names a project that is still active.

    The single expression of the rule that a project whose ``project_status``
    is not ``active`` resolves **no** grant of any scope for any non-admin
    role (docs/policy/access-control-model.md, "Closed projects"). Grants on
    such a project stay on the row, untouched, and resolve again the moment
    the project is reopened.

    Every resolver that turns grants into access ANDs this into its own
    query, as a correlated EXISTS against the primary key, so the rule costs
    one indexed lookup inside the same round trip -- never a per-grant
    lookup -- and cannot drift between mechanisms. Admin grants are global
    scope and are never resolved through any of those resolvers, so admin
    bypass is unaffected.
    """
    from app.models import VaProjectMaster

    return sa.exists(
        sa.select(1).where(
            VaProjectMaster.project_id == project_id_expr,
            VaProjectMaster.project_status == VaStatuses.active,
        )
    )


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
            active_project_condition(MasOrgUnit.project_id),
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
            active_project_condition(granted.project_id),
        )
    )
    return set(db.session.scalars(stmt).all())


def scope_unit_ids_for_roles(
    user_id: uuid.UUID, roles: Iterable[VaAccessRoles]
) -> set[uuid.UUID]:
    """Every active unit reachable by any of *roles*, in one query.

    Same shaped join as ``scope_unit_ids``, but with the role filter widened
    to ``role IN (...)`` so a caller that used to need one query per role
    (e.g. the organization API's read-only unit picker, which unions across
    every role that may hold an org_unit grant) gets it in one round trip.
    """
    roles = list(roles)
    if not roles:
        return set()
    return set(db.session.scalars(scope_unit_ids_select(user_id, roles)).all())


def scope_unit_ids_select(user_id: uuid.UUID, roles: Iterable[VaAccessRoles]):
    """The ``scope_unit_ids_for_roles`` query as a SELECT of unit ids, unexecuted.

    For callers that embed the subtree in their own statement
    (``col.in_(scope_unit_ids_select(...))``) instead of shipping the id set
    back as bind parameters. *roles* must not be empty.
    """
    granted = sa.orm.aliased(MasOrgUnit, name="granted_unit_roles")
    covered = sa.orm.aliased(MasOrgUnit, name="covered_unit_roles")
    return (
        sa.select(covered.org_unit_id)
        .select_from(VaUserAccessGrants)
        .join(granted, granted.org_unit_id == VaUserAccessGrants.org_unit_id)
        .join(
            covered,
            sa.and_(
                covered.project_id == granted.project_id,
                sa.text("covered_unit_roles.path <@ granted_unit_roles.path"),
            ),
        )
        .where(
            VaUserAccessGrants.user_id == user_id,
            VaUserAccessGrants.role.in_(list(roles)),
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            granted.is_active.is_(True),
            covered.is_active.is_(True),
            active_project_condition(granted.project_id),
        )
        # Never correlate with an enclosing query that also reads grants.
        .correlate(None)
    )


def granted_project_ids(user_id: uuid.UUID, role: VaAccessRoles) -> set[str]:
    """Projects the user holds *role* in through a unit-scoped grant."""
    stmt = _grant_units_stmt(user_id, role).with_only_columns(MasOrgUnit.project_id)
    return set(db.session.scalars(stmt).all())


# ---------------------------------------------------------------------------
# Coding scope modes (mas_project.above_scope_coding_mode). The rule that
# applies them is ``authz.ResolvedGrants.codes``.
# ---------------------------------------------------------------------------

ABOVE_SCOPE_CODE_ANY = "code_any"
ABOVE_SCOPE_VIEW_ONLY = "view_only"


def projects_with_org_tree(project_ids: set[str] | None = None) -> set[str]:
    """Projects that have at least one active organization level."""
    from app.models import MasOrgLevel

    stmt = sa.select(MasOrgLevel.project_id).where(MasOrgLevel.is_active.is_(True))
    if project_ids:
        stmt = stmt.where(MasOrgLevel.project_id.in_(sorted(project_ids)))
    return set(db.session.scalars(stmt.distinct()).all())


def resolve_unit_coding_gates(
    unit_ids: Iterable[uuid.UUID],
) -> dict[uuid.UUID, MapOrgUnitCodingGate]:
    """Nearest gated ancestor (inclusive) for each of *unit_ids*.

    A ``map_org_unit_coding_gate`` row on a unit applies to that unit and to
    every descendant that does not carry its own row -- the nearest gated
    ancestor wins. Resolved with one ltree containment query across all
    requested units (never a per-row walk up the tree): each target unit is
    joined to every ancestor-or-self unit carrying a gate row, then the
    deepest match per target is kept.

    Returns a mapping from a requested unit id to the ``MapOrgUnitCodingGate``
    that governs it. A unit id absent from the result has no gate at all --
    neither its own nor an inherited one -- and callers must treat that as
    "not gated", never as closed.
    """
    unit_id_set = set(unit_ids)
    if not unit_id_set:
        return {}

    target = sa.orm.aliased(MasOrgUnit, name="gate_target_unit")
    ancestor = sa.orm.aliased(MasOrgUnit, name="gate_ancestor_unit")
    rows = db.session.execute(
        sa.select(target.org_unit_id, MapOrgUnitCodingGate)
        .select_from(target)
        .join(
            ancestor,
            sa.and_(
                ancestor.project_id == target.project_id,
                sa.text("gate_target_unit.path <@ gate_ancestor_unit.path"),
            ),
        )
        .join(MapOrgUnitCodingGate, MapOrgUnitCodingGate.org_unit_id == ancestor.org_unit_id)
        .where(target.org_unit_id.in_(unit_id_set))
        .order_by(target.org_unit_id, sa.func.nlevel(ancestor.path).desc())
    ).all()

    resolved: dict[uuid.UUID, MapOrgUnitCodingGate] = {}
    for target_unit_id, gate in rows:
        # Rows are grouped by target and ordered deepest-ancestor-first within
        # each group, so the first row seen per target is its nearest gate.
        resolved.setdefault(target_unit_id, gate)
    return resolved


# Model column -> WHO 2022 questionnaire field name each preset fills.
VA_PRESET_QUESTION_NAMES = {
    "hiv_mortality": "Id10002",
    "malaria_mortality": "Id10003",
}


def resolve_unit_va_presets(unit_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, dict[str, dict]]:
    """Nearest ancestor value for each VA preset field, independently, per unit.

    ``hiv_mortality`` and ``malaria_mortality`` are resolved separately: a
    unit can inherit one from its parent and the other from a grandparent
    (or set neither). Resolved with one ltree containment query across all
    requested units, never a per-row walk up the tree -- same shape as
    ``resolve_unit_coding_gates``.

    Returns ``{unit_id: {"hiv_mortality": {"value": ..., "source_unit_id":
    ..., "source_unit_name": ...}, "malaria_mortality": {...}}}``. A field
    absent from a unit's dict has no value at all, on that unit or any
    ancestor -- callers must treat that as "not preset", never as a default.
    """
    unit_id_set = set(unit_ids)
    if not unit_id_set:
        return {}

    target = sa.orm.aliased(MasOrgUnit, name="preset_target_unit")
    ancestor = sa.orm.aliased(MasOrgUnit, name="preset_ancestor_unit")
    rows = db.session.execute(
        sa.select(
            target.org_unit_id,
            ancestor.org_unit_id,
            ancestor.unit_name,
            MapOrgUnitVaPresets.hiv_mortality,
            MapOrgUnitVaPresets.malaria_mortality,
        )
        .select_from(target)
        .join(
            ancestor,
            sa.and_(
                ancestor.project_id == target.project_id,
                sa.text("preset_target_unit.path <@ preset_ancestor_unit.path"),
            ),
        )
        .join(MapOrgUnitVaPresets, MapOrgUnitVaPresets.org_unit_id == ancestor.org_unit_id)
        .where(target.org_unit_id.in_(unit_id_set))
        .order_by(target.org_unit_id, sa.func.nlevel(ancestor.path).desc())
    ).all()

    resolved: dict[uuid.UUID, dict[str, dict]] = {}
    for target_unit_id, source_unit_id, source_unit_name, hiv, malaria in rows:
        fields = resolved.setdefault(target_unit_id, {})
        # Rows are grouped by target and ordered deepest-ancestor-first, so
        # the first non-null value seen per field is its nearest preset --
        # independently for each field, since one ancestor may set hiv only.
        if hiv is not None and "hiv_mortality" not in fields:
            fields["hiv_mortality"] = {
                "value": hiv,
                "source_unit_id": source_unit_id,
                "source_unit_name": source_unit_name,
            }
        if malaria is not None and "malaria_mortality" not in fields:
            fields["malaria_mortality"] = {
                "value": malaria,
                "source_unit_id": source_unit_id,
                "source_unit_name": source_unit_name,
            }
    return resolved


def resolve_va_presets(org_unit_id: uuid.UUID) -> dict[str, str]:
    """Resolved Id10002/Id10003 answers for one unit, keyed by field name.

    Convenience wrapper over ``resolve_unit_va_presets`` for the one-unit case
    (web intake prefill). Only keys that resolve are present; no configured
    value on the unit or any ancestor means the question stays asked.
    """
    fields = resolve_unit_va_presets([org_unit_id]).get(org_unit_id, {})
    return {
        VA_PRESET_QUESTION_NAMES[column]: entry["value"]
        for column, entry in fields.items()
    }
