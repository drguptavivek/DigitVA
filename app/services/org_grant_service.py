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
from collections.abc import Iterable

import sqlalchemy as sa

from app import db
from app.models import (
    MapOrgUnitCodingGate,
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
        VaAccessRoles.collaborator_pii,
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
    granted = sa.orm.aliased(MasOrgUnit, name="granted_unit_roles")
    covered = sa.orm.aliased(MasOrgUnit, name="covered_unit_roles")
    stmt = (
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
            VaUserAccessGrants.role.in_(roles),
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


# ---------------------------------------------------------------------------
# Coding scope (phase 4)
#
# A project may fix the level within which a death may be coded. A coder
# granted at or below that level codes inside their own unit's subtree; one
# granted above it is governed by the project's above_scope_coding_mode:
# 'code_any' lets them code their whole subtree, 'view_only' lets them code
# nothing. A project with no scope level set has no unit-based restriction.
# ---------------------------------------------------------------------------

ABOVE_SCOPE_CODE_ANY = "code_any"
ABOVE_SCOPE_VIEW_ONLY = "view_only"


def _project_scope_settings(project_ids: set[str]) -> dict[str, tuple[int | None, str]]:
    """(scope level depth, above-scope mode) per project, in one query."""
    if not project_ids:
        return {}
    from app.models import MasOrgLevel, VaProjectMaster

    level = sa.orm.aliased(MasOrgLevel)
    rows = db.session.execute(
        sa.select(
            VaProjectMaster.project_id,
            level.depth,
            VaProjectMaster.above_scope_coding_mode,
        )
        .outerjoin(level, level.org_level_id == VaProjectMaster.coding_scope_level_id)
        .where(VaProjectMaster.project_id.in_(sorted(project_ids)))
    ).all()
    return {
        row.project_id: (row.depth, row.above_scope_coding_mode or ABOVE_SCOPE_VIEW_ONLY)
        for row in rows
    }


def codeable_unit_ids(user_id: uuid.UUID, role: VaAccessRoles) -> set[uuid.UUID]:
    """Units whose submissions this user may code (or review) through unit grants.

    Starts from each active *role* grant, applies the grant's project coding
    scope, and expands the surviving grants to their subtrees. A grant above
    the project's scope level survives only when the project says
    ``above_scope_coding_mode = 'code_any'``.
    """
    from app.models import MasOrgLevel, MasOrgUnit

    granted = sa.orm.aliased(MasOrgUnit, name="granted_unit")
    level = sa.orm.aliased(MasOrgLevel, name="granted_level")
    rows = db.session.execute(
        sa.select(granted.org_unit_id, granted.project_id, level.depth)
        .select_from(VaUserAccessGrants)
        .join(granted, granted.org_unit_id == VaUserAccessGrants.org_unit_id)
        .join(level, level.org_level_id == granted.org_level_id)
        .where(
            VaUserAccessGrants.user_id == user_id,
            VaUserAccessGrants.role == role,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            granted.is_active.is_(True),
        )
    ).all()
    if not rows:
        return set()

    settings = _project_scope_settings({row.project_id for row in rows})
    eligible_unit_ids = []
    for row in rows:
        scope_depth, above_mode = settings.get(row.project_id, (None, ABOVE_SCOPE_VIEW_ONLY))
        if scope_depth is None:
            # No coding scope level set: the grant's own subtree, as always.
            eligible_unit_ids.append(row.org_unit_id)
            continue
        if row.depth >= scope_depth or above_mode == ABOVE_SCOPE_CODE_ANY:
            eligible_unit_ids.append(row.org_unit_id)
    if not eligible_unit_ids:
        return set()

    covered = sa.orm.aliased(MasOrgUnit, name="covered_unit")
    anchor = sa.orm.aliased(MasOrgUnit, name="anchor_unit")
    stmt = (
        sa.select(covered.org_unit_id)
        .select_from(anchor)
        .join(
            covered,
            sa.and_(
                covered.project_id == anchor.project_id,
                sa.text("covered_unit.path <@ anchor_unit.path"),
            ),
        )
        .where(anchor.org_unit_id.in_(eligible_unit_ids), covered.is_active.is_(True))
    )
    return set(db.session.scalars(stmt).all())


def project_wide_grant_exists(
    user_id: uuid.UUID, project_id: str, roles: frozenset[VaAccessRoles]
) -> bool:
    """Whether *user_id* holds a project- or site-scoped grant in *roles* on
    *project_id*.

    Such a grant reaches the project's *whole* organization tree, not one
    subtree, so it can't be answered by expanding org_unit-scoped grants
    (``scope_unit_ids``) — it needs its own existence check.

    Shared by the organization API's unit picker
    (``app/routes/api/organization.py::_reachable_unit_ids``) and the web
    intake service's create-time scope check
    (``app/services/web_intake_service.py::_reachable_unit_ids``). Both must
    apply the same reachability rule, or the picker an interviewer sees and
    the check their submission is held to would disagree about which units
    they reach.

    Exact promises, because callers outside this module depend on them:

    * **Inactive grants never count.** Both branches require
      ``grant_status == active``.
    * **Inactive project-sites never count.** The site-scoped branch joins
      ``VaProjectSites`` and requires ``project_site_status == active``.
    * **An admin or project-manager bypass is NOT applied here.** This
      function answers one narrow question — does an *explicit* project- or
      site-scoped grant in *roles* exist — and nothing else. A caller that
      wants admins to reach the whole tree must check that itself, before
      calling (the organization API does; web intake deliberately does not,
      because intake access is strictly grant-based).
    * **An org_unit-scoped grant never counts**, by construction: that is
      what ``scope_unit_ids`` expands.
    * **Asymmetry, inherited and codebase-wide:** the site-scoped branch
      checks the *site's* status, but the project-scoped branch does not
      check the *project's* status. A project-scoped grant on a closed
      project therefore still returns True here.

      Do not read this as a quirk of this function with a mitigating caller.
      The same gap exists independently on the data-management path, which
      never calls this function at all:
      ``VaUsers._get_granted_project_ids`` (app/models/va_users.py) filters
      grant status, scope type and role but not project status, and
      ``submission_analytics_mv._expand_project_ids_to_active_pairs``
      expands those ids filtering only ``project_site_status``. A
      data_manager grant on a closed project resolves to active pairs today.

      So: two known instances, two independent mechanisms, one shared
      assumption that a closed project's grants are already gone. Nothing
      here relies on a caller to be safe — the organization API happens to
      404 on a non-active project before reaching this, but that is a
      property of that caller only, and a new caller inherits the gap.
      Closing it means deciding what a closed project means for *every*
      grant scope, which is why it has not been done piecemeal.
    """
    from app.models import VaProjectSites

    project_scope = sa.select(sa.literal(1)).where(
        sa.exists(
            sa.select(1).where(
                VaUserAccessGrants.user_id == user_id,
                VaUserAccessGrants.grant_status == VaStatuses.active,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
                VaUserAccessGrants.project_id == project_id,
                VaUserAccessGrants.role.in_(roles),
            )
        )
    )
    if db.session.scalar(project_scope):
        return True
    site_scope = sa.select(sa.literal(1)).where(
        sa.exists(
            sa.select(1)
            .select_from(VaUserAccessGrants)
            .join(
                VaProjectSites,
                VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
            )
            .where(
                VaUserAccessGrants.user_id == user_id,
                VaUserAccessGrants.grant_status == VaStatuses.active,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
                VaUserAccessGrants.role.in_(roles),
                VaProjectSites.project_id == project_id,
                VaProjectSites.project_site_status == VaStatuses.active,
            )
        )
    )
    return bool(db.session.scalar(site_scope))


def projects_with_org_tree(project_ids: set[str] | None = None) -> set[str]:
    """Projects that have at least one active organization level."""
    from app.models import MasOrgLevel

    stmt = sa.select(MasOrgLevel.project_id).where(MasOrgLevel.is_active.is_(True))
    if project_ids:
        stmt = stmt.where(MasOrgLevel.project_id.in_(sorted(project_ids)))
    return set(db.session.scalars(stmt.distinct()).all())


def submission_within_org_scope(user, va_sid: str, role: VaAccessRoles) -> bool:
    """Whether one submission is inside the user's unit scope for *role*.

    True for any submission of a project with no organization tree: those keep
    the form-and-site model untouched. For a tree project the submission must
    be routed to a unit inside the user's coding scope, so an unrouted one is
    reachable by nobody until a data manager routes it.

    This is the per-submission counterpart of the list filter in
    ``coder_workflow_service._org_unit_scope_filter``: the list decides what is
    offered, this decides what may be opened directly.
    """
    from app.models import MasOrgLevel, VaForms, VaSubmissions

    row = db.session.execute(
        sa.select(VaSubmissions.org_unit_id, VaForms.project_id)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .where(VaSubmissions.va_sid == va_sid)
    ).first()
    if row is None:
        return False

    has_tree = db.session.scalar(
        sa.select(sa.literal(True)).where(
            sa.exists(
                sa.select(1).where(
                    MasOrgLevel.project_id == row.project_id,
                    MasOrgLevel.is_active.is_(True),
                )
            )
        )
    )
    if not has_tree:
        return True
    if row.org_unit_id is None:
        return False
    return row.org_unit_id in codeable_unit_ids(user.user_id, role)


# ---------------------------------------------------------------------------
# Viewing scope
#
# Deliberately separate from the coding scope above. A grant above the
# project's coding scope level codes nothing, but its holder still oversees
# their subtree: they see the cause of death and the submission data,
# read-only. Keeping the two sets apart is what stops a viewer becoming a
# coder — never substitute one for the other.
# ---------------------------------------------------------------------------


def viewable_unit_ids(user_id: uuid.UUID, role: VaAccessRoles) -> set[uuid.UUID]:
    """Units whose submissions this user may *see* through unit grants.

    The whole subtree of every active grant, regardless of the project's
    coding scope level — oversight does not shrink because coding does.
    """
    return scope_unit_ids(user_id, role)


def submission_within_org_view_scope(user, va_sid: str, role: VaAccessRoles) -> bool:
    """Whether one submission is inside the user's *viewing* scope for *role*.

    Same shape as ``submission_within_org_scope``, against the viewable set.
    True for any submission of a project with no organization tree.
    """
    from app.models import MasOrgLevel, VaForms, VaSubmissions

    row = db.session.execute(
        sa.select(VaSubmissions.org_unit_id, VaForms.project_id)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .where(VaSubmissions.va_sid == va_sid)
    ).first()
    if row is None:
        return False

    has_tree = db.session.scalar(
        sa.select(sa.literal(True)).where(
            sa.exists(
                sa.select(1).where(
                    MasOrgLevel.project_id == row.project_id,
                    MasOrgLevel.is_active.is_(True),
                )
            )
        )
    )
    if not has_tree:
        return True
    if row.org_unit_id is None:
        return False
    return row.org_unit_id in viewable_unit_ids(user.user_id, role)


def has_view_only_scope(user_id: uuid.UUID, role: VaAccessRoles) -> bool:
    """Whether this user oversees units they may not code in.

    True when the viewable set is strictly larger than the codeable one, which
    is exactly the case the oversight surface exists for.
    """
    viewable = viewable_unit_ids(user_id, role)
    if not viewable:
        return False
    return bool(viewable - codeable_unit_ids(user_id, role))


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
