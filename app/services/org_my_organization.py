"""My organization page (digitva-e7sz). Read-only; names and cadres only.

Policy: docs/policy/organization-model.md, "Who sees worker names"."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

import sqlalchemy as sa

from app import db
from app.models import (
    MasCadre,
    MasOrgLevel,
    MasOrgUnit,
    MasOrgUnitWorker,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
)
from app.models.va_selectives import ROLE_LABELS
from app.services import authz
from app.services.authz.consulted import mark_consulted
from app.services.org_common import (
    OrganizationError,
    _uuid,
)
from app.services.org_levels_units import (
    list_units_by_codes,
)

#: Most people returned for one unit. Bounds the response, not the roster.
MY_ORG_PEOPLE_CAP = 500


def _granted_project_ids(user) -> set[str]:
    """Active projects in which the user holds any live grant, from authz's
    resolved grants (closed projects and inactive grants are already out).

    Not gated on ``effective_roles``: a grant whose role gate is still closed
    (an interviewer on a project with no form yet) still lists its project.
    Demo-training grants are virtual and do not count. ``resolve_grants`` does
    not mark the request consulted itself, so this does it, as the other
    services that read resolved grants do.
    """
    return set(_granted(user)[0])


def _granted(user) -> tuple[dict[str, list], authz.ResolvedGrants]:
    """The user's live explicit grants grouped by project, and the resolved
    grants they came from (see ``_granted_project_ids``)."""
    mark_consulted()
    resolved = authz.resolve_grants(user)
    by_project: dict[str, list] = {}
    for grant in resolved.grants:
        if not grant.virtual:
            by_project.setdefault(grant.project_id, []).append(grant)
    return by_project, resolved


def _my_units(user_id: uuid.UUID, project_id: str) -> dict[str, dict]:
    """Units the user is placed at in *project_id*: its unit grants and its own
    worker rows. Keyed by unit id; one query whatever the unit count. Each
    entry carries ``roles``: ``{role value: cadre name or None}`` from the unit
    grants (a worker row adds a cadre, no role).
    """
    grant_stmt = (
        sa.select(
            MasOrgUnit.org_unit_id.label("org_unit_id"),
            MasCadre.cadre_name.label("cadre_name"),
            sa.cast(VaUserAccessGrants.role, sa.Text).label("role"),
        )
        .select_from(VaUserAccessGrants)
        .join(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
        .outerjoin(MasCadre, MasCadre.cadre_id == VaUserAccessGrants.cadre_id)
        .where(
            VaUserAccessGrants.user_id == user_id,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
            MasOrgUnit.project_id == project_id,
            MasOrgUnit.is_active.is_(True),
        )
    )
    worker_stmt = (
        sa.select(
            MasOrgUnit.org_unit_id.label("org_unit_id"),
            MasCadre.cadre_name.label("cadre_name"),
            sa.cast(sa.null(), sa.Text).label("role"),
        )
        .select_from(MasOrgUnitWorker)
        .join(MasOrgUnit, MasOrgUnit.org_unit_id == MasOrgUnitWorker.org_unit_id)
        .join(MasCadre, MasCadre.cadre_id == MasOrgUnitWorker.cadre_id)
        .where(
            MasOrgUnitWorker.user_id == user_id,
            MasOrgUnitWorker.is_active.is_(True),
            MasOrgUnit.project_id == project_id,
            MasOrgUnit.is_active.is_(True),
        )
    )
    combined = sa.union(grant_stmt, worker_stmt).subquery("my_units_placement")
    rows = db.session.execute(
        sa.select(MasOrgUnit, MasOrgLevel, combined.c.cadre_name, combined.c.role)
        .select_from(combined)
        .join(MasOrgUnit, MasOrgUnit.org_unit_id == combined.c.org_unit_id)
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
    ).all()
    mine: dict[str, dict] = {}
    for unit, level, cadre_name, role in rows:
        entry = mine.setdefault(
            str(unit.org_unit_id), {"unit": unit, "level": level, "cadres": set(), "roles": {}})
        if cadre_name:
            entry["cadres"].add(cadre_name)
        if role:
            # Two grants of one role at one unit: keep a cadre over none.
            entry["roles"][role] = entry["roles"].get(role) or cadre_name
    return mine


def _ancestor_units(project_id: str, mine: dict[str, dict]) -> list[dict]:
    """Active units above any of *mine*, root first, in one query.

    The ancestors are named by the codes in each unit's ltree path (the path
    is the chain of unit codes). Units of *mine* are left out: they are shown
    as the user's own level, not as context above it.
    """
    codes = {
        code
        for entry in mine.values()
        for code in str(entry["unit"].path).split(".")[:-1]
    }
    if not codes:
        return []
    return [
        unit
        for unit in list_units_by_codes(project_id, codes)
        if unit["org_unit_id"] not in mine
    ]


def _people_by_unit(unit_ids: Iterable[str]) -> dict[str, list[dict]]:
    """Active workers of *unit_ids*, as ``{name, cadre, roles}``, one query.

    Name, cadre and role labels only: never phone, email, worker code or user
    id (docs/policy/organization-model.md, "Who sees worker names"). ``roles``
    are the labels of the linked user's active grants in the unit's own
    project (closed projects resolve none), gathered by one correlated
    aggregate in the same query; empty without a linked user. Each unit is
    capped at ``MY_ORG_PEOPLE_CAP`` by a window over the same query.
    """
    from app.services.org_grant_service import active_project_condition

    ids = [uuid.UUID(unit_id) for unit_id in unit_ids]
    if not ids:
        return {}
    roles = (
        sa.select(sa.func.array_agg(sa.distinct(sa.cast(VaUserAccessGrants.role, sa.Text))))
        .where(
            VaUserAccessGrants.user_id == MasOrgUnitWorker.user_id,
            VaUserAccessGrants.project_id == MasOrgUnit.project_id,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            active_project_condition(VaUserAccessGrants.project_id),
        )
        .correlate(MasOrgUnitWorker, MasOrgUnit)
        .scalar_subquery()
    )
    ranked = (
        sa.select(
            MasOrgUnitWorker.org_unit_id.label("org_unit_id"),
            MasOrgUnitWorker.worker_name.label("name"),
            MasCadre.cadre_name.label("cadre"),
            roles.label("roles"),
            sa.func.row_number()
            .over(
                partition_by=MasOrgUnitWorker.org_unit_id,
                order_by=(MasOrgUnitWorker.worker_name, MasOrgUnitWorker.worker_id),
            )
            .label("rank"),
        )
        .select_from(MasOrgUnitWorker)
        .join(MasCadre, MasCadre.cadre_id == MasOrgUnitWorker.cadre_id)
        .join(MasOrgUnit, MasOrgUnit.org_unit_id == MasOrgUnitWorker.org_unit_id)
        .where(MasOrgUnitWorker.org_unit_id.in_(ids), MasOrgUnitWorker.is_active.is_(True))
        .subquery()
    )
    rows = db.session.execute(
        sa.select(ranked.c.org_unit_id, ranked.c.name, ranked.c.cadre, ranked.c.roles)
        .where(ranked.c.rank <= MY_ORG_PEOPLE_CAP)
        .order_by(ranked.c.rank)
    ).all()
    people: dict[str, list[dict]] = {}
    for org_unit_id, name, cadre, role_values in rows:
        labels = sorted({ROLE_LABELS[r] for r in role_values or () if r in ROLE_LABELS})
        people.setdefault(str(org_unit_id), []).append({"name": name, "cadre": cadre, "roles": labels})
    return people


def _unit_summaries(project_id: str, *conditions) -> list[dict]:
    """Active units of *project_id* matching *conditions*, with their worker
    count and whether they have child units. One query: both are correlated
    scalars on the unit row, so the cost does not grow per unit in Python.
    """
    child = sa.orm.aliased(MasOrgUnit, name="child_unit")
    people_count = (
        sa.select(sa.func.count(MasOrgUnitWorker.worker_id))
        .where(
            MasOrgUnitWorker.org_unit_id == MasOrgUnit.org_unit_id,
            MasOrgUnitWorker.is_active.is_(True),
        )
        .correlate(MasOrgUnit)
        .scalar_subquery()
    )
    has_children = sa.exists().where(
        child.parent_org_unit_id == MasOrgUnit.org_unit_id,
        child.is_active.is_(True),
    )
    rows = db.session.execute(
        sa.select(
            MasOrgUnit,
            MasOrgLevel.level_name,
            people_count.label("people_count"),
            has_children.label("has_children"),
        )
        .select_from(MasOrgUnit)
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
        .where(MasOrgUnit.project_id == project_id, MasOrgUnit.is_active.is_(True), *conditions)
        .order_by(MasOrgUnit.unit_name, MasOrgUnit.unit_code)
    ).all()
    return [
        {
            "org_unit_id": str(unit.org_unit_id),
            "unit_name": unit.unit_name,
            "level_name": level_name,
            "parent_org_unit_id": str(unit.parent_org_unit_id) if unit.parent_org_unit_id else None,
            "people_count": people_count_value,
            "has_children": bool(has_children_value),
        }
        for unit, level_name, people_count_value, has_children_value in rows
    ]


def _my_project(user_id: uuid.UUID, project_id: str, project_name: str) -> dict:
    """One project's block of the My organization page.

    The user's own units, the units above them (with their people), their
    level, and the units one level below. A user with no unit placement (a
    project- or site-scoped grant) gets no ``my_units``; ``below`` is then the
    tree's root units, which sit above every grant.
    """
    mine = _my_units(user_id, project_id)
    ancestors = _ancestor_units(project_id, mine)
    if mine:
        mine_ids = [uuid.UUID(unit_id) for unit_id in mine]
        below = _unit_summaries(
            project_id,
            MasOrgUnit.parent_org_unit_id.in_(mine_ids),
            # A unit the user is placed at is shown as their own level, not as a
            # child below it.
            MasOrgUnit.org_unit_id.not_in(mine_ids),
        )
    else:
        req_min = (
            sa.select(sa.func.min(MasOrgLevel.depth))
            .where(
                MasOrgLevel.project_id == project_id,
                MasOrgLevel.is_active.is_(True),
                MasOrgLevel.is_optional.is_(False),
            )
            .scalar_subquery()
        )
        all_min = (
            sa.select(sa.func.min(MasOrgLevel.depth))
            .where(MasOrgLevel.project_id == project_id, MasOrgLevel.is_active.is_(True))
            .scalar_subquery()
        )
        below = _unit_summaries(
            project_id,
            MasOrgUnit.parent_org_unit_id.is_(None),
            MasOrgLevel.depth <= sa.func.coalesce(req_min, all_min),
        )
    people = _people_by_unit([*mine, *(unit["org_unit_id"] for unit in ancestors)])
    ordered = sorted(mine.items(), key=lambda item: str(item[1]["unit"].path))
    return {
        "project_id": project_id,
        "project_name": project_name,
        "my_units": [
            {
                "org_unit_id": unit_id,
                "unit_name": entry["unit"].unit_name,
                "level_name": entry["level"].level_name,
                "cadres": sorted(entry["cadres"]),
                "roles": [
                    {"role": role, "cadre": cadre}
                    for role, cadre in sorted(entry["roles"].items())
                ],
            }
            for unit_id, entry in ordered
        ],
        "above": [
            {
                "org_unit_id": unit["org_unit_id"],
                "unit_name": unit["unit_name"],
                "level_name": unit["level_name"],
                "parent_org_unit_id": unit["parent_org_unit_id"],
                "people": people.get(unit["org_unit_id"], []),
            }
            for unit in ancestors
        ],
        "my_level": [
            {
                "org_unit_id": unit_id,
                "unit_name": entry["unit"].unit_name,
                "parent_org_unit_id": (
                    str(entry["unit"].parent_org_unit_id) if entry["unit"].parent_org_unit_id else None
                ),
                "people": people.get(unit_id, []),
            }
            for unit_id, entry in ordered
        ],
        "below": below,
    }


def _granted_site_names(grants_by_project: dict[str, list]) -> dict[tuple[str, str], str]:
    """``{(project_id, site_id): site_name}`` for the active project sites the
    user holds a project_site grant at, all projects in one query."""
    pairs = sorted({
        (grant.project_id, grant.site_id)
        for grants in grants_by_project.values()
        for grant in grants
        if grant.scope_type == VaAccessScopeTypes.project_site and grant.site_id
    })
    if not pairs:
        return {}
    rows = db.session.execute(
        sa.select(VaProjectSites.project_id, VaProjectSites.site_id, VaSiteMaster.site_name)
        .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
        .where(
            sa.tuple_(VaProjectSites.project_id, VaProjectSites.site_id).in_(pairs),
            VaProjectSites.project_site_status == VaStatuses.active,
        )
    ).all()
    return {(row.project_id, row.site_id): row.site_name for row in rows}


def _my_positions(project_id: str, grants: list, site_names: dict) -> dict:
    """The user's own project- and site-scope roles in one project (unit roles
    ride on ``my_units``). Grant roles as granted, sorted; no derived roles."""
    project_roles = sorted({
        grant.role.value for grant in grants if grant.scope_type == VaAccessScopeTypes.project
    })
    site_roles: dict[str, set[str]] = {}
    for grant in grants:
        if grant.scope_type == VaAccessScopeTypes.project_site and (project_id, grant.site_id) in site_names:
            site_roles.setdefault(grant.site_id, set()).add(grant.role.value)
    return {
        "project_roles": project_roles,
        "sites": [
            {"site_id": site_id, "site_name": site_names[(project_id, site_id)], "roles": sorted(roles)}
            for site_id, roles in sorted(site_roles.items())
        ],
    }


def my_organization(user, *, project_ids=None, people=True) -> dict:
    """The My organization page's data: every project the user holds a live
    grant in, with ``has_tree`` and ``my_positions`` (their own roles). The
    tree lists (``my_units``, ``above``, ``my_level``, ``below``) are filled for
    org-tree projects and empty for sites-mode projects.

    *user* may be another person (the Users page): *project_ids* then limits the
    projects to the viewer's own, and ``people=False`` empties every people list
    and count, so the reply names no other worker.
    """
    grants_by_project, resolved = _granted(user)
    if project_ids is not None:
        grants_by_project = {p: g for p, g in grants_by_project.items() if p in project_ids}
    if not grants_by_project:
        return {"projects": []}
    project_ids = sorted(grants_by_project)
    names = dict(
        db.session.execute(
            sa.select(VaProjectMaster.project_id, VaProjectMaster.project_name).where(
                VaProjectMaster.project_id.in_(project_ids)
            )
        ).all()
    )
    site_names = _granted_site_names(grants_by_project)
    projects = []
    for pid in project_ids:
        has_tree = resolved.has_tree(pid)
        block = (
            _my_project(user.user_id, pid, names[pid])
            if has_tree
            else {"project_id": pid, "project_name": names[pid],
                  "my_units": [], "above": [], "my_level": [], "below": []}
        )
        block["has_tree"] = has_tree
        if not people or getattr(user, "is_public_demo", False):
            for unit in (*block["above"], *block["my_level"]):
                unit["people"] = []
            for unit in block["below"]:
                unit["people_count"] = 0
        block["my_positions"] = _my_positions(pid, grants_by_project[pid], site_names)
        projects.append(block)
    return {"projects": projects}


def unit_people(user, org_unit_id: object) -> dict | None:
    """One unit's people and its child units, for opening a unit on the page.

    Allowed to any user holding an active grant in the unit's project. Returns
    ``None`` (the route answers 404) for a bad id, an unknown or inactive unit,
    or a project the user holds no grant in: the same answer in every case, so
    the reply does not reveal that a unit exists elsewhere.
    """
    # Decided first, so a bad id also consults authz (the reach is the same).
    granted = _granted_project_ids(user)
    # A public-demo account sees no roster (docs/policy/public-demo.md section 3).
    if getattr(user, "is_public_demo", False):
        return None
    try:
        unit_uuid = _uuid(org_unit_id, what="Unit")
    except OrganizationError:
        return None
    row = db.session.execute(
        sa.select(MasOrgUnit, MasOrgLevel.level_name)
        .join(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
        .where(MasOrgUnit.org_unit_id == unit_uuid, MasOrgUnit.is_active.is_(True))
    ).first()
    if row is None:
        return None
    unit, level_name = row
    if unit.project_id not in granted:
        return None
    unit_id = str(unit.org_unit_id)
    return {
        "unit": {"org_unit_id": unit_id, "unit_name": unit.unit_name, "level_name": level_name},
        "people": _people_by_unit([unit_id]).get(unit_id, []),
        "children": _unit_summaries(unit.project_id, MasOrgUnit.parent_org_unit_id == unit.org_unit_id),
    }
