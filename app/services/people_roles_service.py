"""People and roles: who holds which role where in one project, and the
project's access audit view (docs/policy/people-and-roles-page.md, bead
digitva-nk1).

Read-only. One bounded select reads the project's grants joined to users,
units, levels, cadres, sites and the granter; the grid is one more select and
everything else (cells, flags, audience, filters, counts) is computed in
Python from ``ResolvedGrants`` and ``Grant``, the same pure rule objects the
authz layer uses, so the page never decides access itself.

Three viewer tiers (policy "Who may open it"):
  * identity: admin, project PI, data manager, site PI (In-charge), interview
    supervisor, reviewer. Emails, deactivated users/grants, global admins.
  * names: any other grant holder. Names, no emails, active people only.
  * initials: a viewer ``should_redact_pii`` redacts and who is not in the
    identity tier (a plain collaborator).
Audit columns and flags: admin, project PI and project-scope DM-shaped
viewers see every row; a DM-shaped unit grant sees rows inside its subtree.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    MasCadre,
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import organization_service as org
from app.services.access_summary_service import _codes, _roles
from app.services.authz import reachable_unit_ids, resolve_grants
from app.services.authz.actions import DEATH_REGISTERING_ROLES
from app.services.authz.grants import Grant, ResolvedGrants, _load_projects
from app.services.org_grant_service import CADRE_FLAG_BY_ROLE, ROLES_ALLOWING_ORG_UNIT
from app.services.viewer_pii_service import (
    _PII_GRANTING_ROLES,
    pii_visible_user_ids,
    should_redact_pii,
)

R = VaAccessRoles
_P = VaAccessScopeTypes.project
_PS = VaAccessScopeTypes.project_site
_U = VaAccessScopeTypes.org_unit
_G = VaAccessScopeTypes.global_scope

# No sign-in for this long flags an account (owner 2026-10-01, confirmed
# 2026-10-06). A code constant; a per-project setting is deferred.
DORMANT_DAYS = 90
# Grant rows read per request. A district of a few thousand staff fits; past
# it the response says ``truncated`` instead of growing without bound.
MAX_GRANTS = 10000
DEFAULT_LIMIT = 200
MAX_LIMIT = 500
_MAX_TEXT = 64

# THE capability mapping: column key -> roles that give it. Roles are the
# derived set (access_summary_service._roles), so an In-charge (site_pi at a
# unit) and a project PI on a tree project also count as data_manager and
# interview_supervisor. ``view_pii`` is per person, not per row: it is read
# from ``pii_visible_user_ids`` (the same ``_PII_GRANTING_ROLES`` set, across
# every project the person holds) and the roles here only name which of the
# row's own grants contribute. "report_deaths" is every role that registers a
# death (authz DEATH_REGISTERING_ROLES).
CAPABILITY_ROLES: dict[str, frozenset[VaAccessRoles]] = {
    "report_deaths": DEATH_REGISTERING_ROLES,
    "interview": frozenset({R.interviewer}),
    "supervise": frozenset({R.interview_supervisor, R.data_manager}),
    "code": frozenset({R.coder}),
    "review": frozenset({R.reviewer}),
    "test_code": frozenset({R.coding_tester}),
    "manage_data": frozenset({R.data_manager}),
    "view_pii": _PII_GRANTING_ROLES,
    "read_only": frozenset({R.collaborator, R.collaborator_pii}),
    "site_lead": frozenset({R.site_pi}),
    "manage_grants": frozenset({R.admin, R.project_pi, R.data_manager}),
}
CAPABILITY_LABELS = {
    "report_deaths": "Report deaths",
    "interview": "Interview",
    "supervise": "Supervise",
    "code": "Code",
    "review": "Review",
    "test_code": "Test code",
    "manage_data": "Manage data",
    "view_pii": "View PII",
    "read_only": "Read-only",
    "site_lead": "Site lead",
    "manage_grants": "Manage grants",
}
# Capabilities a grant gives only at project_site scope. A site_pi at a unit is
# the In-charge, whose duties are Supervise, Manage data and Manage grants.
SITE_SCOPE_ONLY = frozenset({"site_lead"})
# Hollow (red) cells: the level x cadre grid flag that says "may be given".
HOLLOW_FLAGS = {
    "report_deaths": "can_report_deaths",
    "interview": "can_fill_va_form",
    "code": "can_code_va_form",
    "supervise": "can_supervise_interviews",
}
# Roles that see emails, deactivated rows and global admins.
IDENTITY_ROLES = frozenset({
    R.project_pi, R.data_manager, R.site_pi, R.interview_supervisor, R.reviewer,
})
MODES = ("granted_here", "can_act_here")
STATUSES = ("active", "deactivated", "all")
_KIND_ORDER = {"project": 0, "site": 1, "unit": 2, "platform": 3}


class PeopleRolesError(Exception):
    """A refusal that maps to an HTTP status; the message is safe to return."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _not_found() -> PeopleRolesError:
    return PeopleRolesError("Not found.", 404)


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------

def _parse(args: Mapping[str, str], *, paged: bool) -> dict:
    def text(name):
        value = (args.get(name) or "").strip()
        if len(value) > _MAX_TEXT:
            raise PeopleRolesError(f"{name} is too long.")
        return value

    def choice(name, allowed, default):
        value = text(name) or default
        if value not in allowed:
            raise PeopleRolesError(f"Unknown {name} {value!r}.")
        return value

    def number(name, default, low, high):
        raw = text(name)
        if not raw:
            return default
        try:
            return min(max(int(raw), low), high)
        except ValueError:
            raise PeopleRolesError(f"{name} must be a whole number.") from None

    unit = text("unit")
    if unit:
        try:
            unit = uuid.UUID(unit)
        except ValueError:
            raise PeopleRolesError("unit must be a unit id.") from None
    capability = text("capability")
    if capability and capability not in CAPABILITY_ROLES:
        raise PeopleRolesError(f"Unknown capability {capability!r}.")
    return {
        "level": text("level").lower(),
        "unit": unit or None,
        "cadre": text("cadre").lower(),
        "capability": capability or None,
        "status": choice("status", STATUSES, "active"),
        "q": text("q").lower(),
        "mode": choice("mode", MODES, "granted_here"),
        "limit": number("limit", DEFAULT_LIMIT, 1, MAX_LIMIT) if paged else None,
        "offset": number("offset", 0, 0, 10**9) if paged else 0,
    }


# ---------------------------------------------------------------------------
# The one grants query
# ---------------------------------------------------------------------------

def _project_scope(project_id: str):
    """Grants of *project_id* by scope. Per-scope IN subqueries, not a project
    test on joined rows: the planner can then use the grant table's indexes."""
    grant = VaUserAccessGrants
    return sa.or_(
        grant.project_id == project_id,
        grant.project_site_id.in_(
            sa.select(VaProjectSites.project_site_id).where(VaProjectSites.project_id == project_id)
        ),
        grant.org_unit_id.in_(
            sa.select(MasOrgUnit.org_unit_id).where(MasOrgUnit.project_id == project_id)
        ),
    )


def _users_with_active_grant(project_id: str) -> set:
    """People holding any active grant in the project: its own aggregate, so
    the row cap cannot make the ``no_active_grant`` flag wrong."""
    grant = VaUserAccessGrants
    return set(db.session.scalars(
        sa.select(grant.user_id).distinct()
        .where(grant.grant_status == VaStatuses.active, _project_scope(project_id))
    ))


def _load_grant_rows(project_id: str, *, include_deactivated: bool, include_platform: bool):
    """Grants of *project_id* (and, for the identity tier, the global admin
    grants) with everything a row shows. Unit and pair activity are columns,
    not filters, so a grant on a deactivated unit still lists and flags."""
    grant = VaUserAccessGrants
    user = sa.orm.aliased(VaUsers, name="pr_user")
    granter = sa.orm.aliased(VaUsers, name="pr_granter")
    site = sa.orm.aliased(VaProjectSites, name="pr_site")
    site_master = sa.orm.aliased(VaSiteMaster, name="pr_site_master")
    unit = sa.orm.aliased(MasOrgUnit, name="pr_unit")
    level = sa.orm.aliased(MasOrgLevel, name="pr_level")
    cadre = sa.orm.aliased(MasCadre, name="pr_cadre")

    scope = _project_scope(project_id)
    if include_platform:
        scope = sa.or_(scope, sa.and_(grant.scope_type == _G, grant.role == R.admin))
    statuses = [VaStatuses.active, VaStatuses.deactive] if include_deactivated else [VaStatuses.active]
    rows = db.session.execute(
        sa.select(
            grant.grant_id,
            grant.role,
            grant.scope_type,
            grant.grant_status,
            grant.grant_created_at,
            grant.cadre_id,
            grant.org_unit_id,
            grant.project_site_id,
            user.user_id,
            user.name.label("user_name"),
            user.email,
            user.job_title,
            user.user_status,
            user.last_signed_in_at,
            granter.name.label("granted_by"),
            site.site_id,
            site.project_site_status,
            site_master.site_name,
            unit.unit_code,
            unit.unit_name,
            unit.is_active.label("unit_active"),
            sa.cast(unit.path, sa.Text).label("unit_path"),
            level.depth,
            level.level_code,
            level.level_name,
            cadre.cadre_code,
            cadre.cadre_name,
        )
        .select_from(grant)
        .join(user, user.user_id == grant.user_id)
        .outerjoin(granter, granter.user_id == grant.created_by_user_id)
        .outerjoin(site, site.project_site_id == grant.project_site_id)
        .outerjoin(site_master, site_master.site_id == site.site_id)
        .outerjoin(unit, unit.org_unit_id == grant.org_unit_id)
        .outerjoin(level, level.org_level_id == unit.org_level_id)
        .outerjoin(cadre, cadre.cadre_id == grant.cadre_id)
        .where(grant.grant_status.in_(statuses), scope)
        .order_by(grant.grant_created_at, grant.grant_id)
        .limit(MAX_GRANTS + 1)
    ).all()
    return rows[:MAX_GRANTS], len(rows) > MAX_GRANTS


# ---------------------------------------------------------------------------
# Viewer
# ---------------------------------------------------------------------------

def _viewer_facts(viewer, resolved, scope: ResolvedGrants, project_id: str) -> dict:
    mine = [
        g for g in resolved.grants
        if g.project_id == project_id and not g.virtual and g.source == "assigned"
    ]
    is_admin = resolved.is_admin
    identity = is_admin or any(g.role in IDENTITY_ROLES for g in mine)
    audit_all = is_admin or any(
        g.role == R.project_pi or (g.scope_type == _P and scope.is_dm_grant(g)) for g in mine
    )
    dm_grants = [g for g in mine if scope.is_dm_grant(g)]
    return {
        "mine": mine,
        # Whole project: a project-scope grant (a PI's included) or admin.
        # reachable_unit_ids says None for a site grant too, so it cannot tell.
        "whole_project": is_admin or any(g.scope_type == _P for g in mine),
        "sites": {g.project_site_id for g in mine if g.scope_type == _PS},
        "identity": identity,
        "initials": not identity and should_redact_pii(viewer),
        "audit_all": audit_all,
        "dm_units": [g for g in dm_grants if g.scope_type == _U],
        "dm_sites": {g.project_site_id for g in dm_grants if g.scope_type == _PS},
    }


def _initials(name: str) -> str:
    return " ".join(f"{part[0].upper()}." for part in (name or "").split()[:3]) or "?"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)  # grant_created_at is stored naive UTC
    return value.isoformat()


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def _location(r) -> tuple[str, str, dict]:
    """(kind, key, JSON) of where one grant sits."""
    if r.scope_type == _G:
        return "platform", "", {"kind": "platform", "active": True}
    if r.scope_type == _U:
        return "unit", str(r.org_unit_id), {
            "kind": "unit",
            "org_unit_id": str(r.org_unit_id),
            "unit_code": r.unit_code,
            "unit_name": r.unit_name,
            "level_code": r.level_code,
            "level_name": r.level_name,
            "depth": r.depth,
            "path": r.unit_path,
            "active": bool(r.unit_active),
        }
    if r.scope_type == _PS:
        return "site", str(r.project_site_id), {
            "kind": "site",
            "project_site_id": str(r.project_site_id),
            "site_id": r.site_id,
            "site_name": r.site_name,
            "active": r.project_site_status == VaStatuses.active,
        }
    return "project", "", {"kind": "project", "active": True}


def _grant_object(r, project_id: str) -> Grant | None:
    if r.scope_type == _G:
        return None
    return Grant(
        role=r.role,
        scope_type=r.scope_type,
        project_id=project_id,
        site_id=r.site_id if r.scope_type == _PS else None,
        project_site_id=r.project_site_id,
        org_unit_id=r.org_unit_id,
        unit_depth=r.depth,
        unit_path=r.unit_path,
    )


def _role_names(entries) -> list[str]:
    return sorted({e["role"].value for e in entries})


def _cells(entries, *, live: bool, sees_pii: bool, scope, loc: dict, cadre_id, grid) -> dict:
    """One state per capability: granted | view_only | inactive | hollow |
    blank. ``live``: the user and the location are active. An entry counts
    for a green cell only when its grant is active and the row is live."""
    cells = {}
    for key, roles in CAPABILITY_ROLES.items():
        if key == "view_pii":
            mine = sorted({e["role"].value for e in entries if e["active"] and e["role"] in roles})
            state = "blank"
            if sees_pii:
                state = "granted" if live and any(e["active"] for e in entries) else "inactive"
            cells[key] = {"state": state, "roles": mine}
            continue
        giving = [
            e for e in entries
            if roles & e["derived"]
            and (key not in SITE_SCOPE_ONLY or (e["grant"] and e["grant"].scope_type == _PS))
        ]
        counting = [e for e in giving if e["active"] and live]
        effective = counting
        if key == "code":
            effective = [e for e in counting if _codes(e["grant"], scope)]
        if effective:
            cells[key] = {"state": "granted", "roles": _role_names(effective)}
        elif counting:
            cells[key] = {"state": "view_only", "roles": _role_names(counting)}
        elif giving:
            cells[key] = {"state": "inactive", "roles": _role_names(giving)}
        else:
            cells[key] = {"state": "blank", "roles": []}
            flag = HOLLOW_FLAGS.get(key)
            if flag and live and cadre_id and loc["kind"] == "unit" and any(e["active"] for e in entries):
                cell = grid.get((loc["level_code"], str(cadre_id)))
                if cell and cell["is_active"] and cell[flag]:
                    cells[key]["state"] = "hollow"
    return cells


def _flags(entries, *, user_active: bool, loc: dict, cadre_id, grid, has_active_elsewhere: bool,
           last_sign_in, now: datetime) -> list[str]:
    flags = []
    active = [e for e in entries if e["active"]]
    if loc["kind"] == "platform":
        return flags
    if active and loc["kind"] == "unit":
        if cadre_id is None:
            flags.append("no_cadre")
        for e in active:
            spec = CADRE_FLAG_BY_ROLE.get(e["role"])
            if spec and cadre_id is not None:
                cell = grid.get((loc["level_code"], str(cadre_id)))
                if not (cell and cell["is_active"] and cell[spec[0]]):
                    flags.append("exceeds_grid")
                    break
    if active and not user_active:
        flags.append("inactive_user")
    if active and not loc["active"]:
        flags.append("inactive_unit")
    if not has_active_elsewhere:
        flags.append("no_active_grant")
    if active and user_active and last_sign_in is not None:
        if last_sign_in.tzinfo is None:
            last_sign_in = last_sign_in.replace(tzinfo=UTC)
        if now - last_sign_in > timedelta(days=DORMANT_DAYS):
            flags.append("dormant")
    return flags


def _load_units(project_id: str) -> list[dict]:
    """Every unit of the project (deactivated too), only the columns the page
    reads. Filtered to the viewer's audience by the caller."""
    unit, level = MasOrgUnit, MasOrgLevel
    return [
        {
            "org_unit_id": str(r.org_unit_id),
            "unit_code": r.unit_code,
            "unit_name": r.unit_name,
            "level_code": r.level_code,
            "depth": r.depth,
            "parent_org_unit_id": str(r.parent_org_unit_id) if r.parent_org_unit_id else None,
            "path": r.path,
            "is_active": r.is_active,
        }
        for r in db.session.execute(
            sa.select(
                unit.org_unit_id, unit.unit_code, unit.unit_name, level.level_code, level.depth,
                unit.parent_org_unit_id, sa.cast(unit.path, sa.Text).label("path"), unit.is_active,
            )
            .join(level, level.org_level_id == unit.org_level_id)
            .where(unit.project_id == project_id)
            .order_by(unit.path)
        )
    ]


def _below_counts(units: list[dict]) -> dict[str, int]:
    """Active units strictly below each unit path, from the paths alone
    (same prefix rule as ``Grant.covers_unit``, but one pass, not rows x units)."""
    counts: dict[str, int] = {}
    for unit in units:
        if not unit["is_active"]:
            continue
        parts = str(unit["path"]).split(".")
        for i in range(1, len(parts)):
            prefix = ".".join(parts[:i])
            counts[prefix] = counts.get(prefix, 0) + 1
    return counts


def people_roles(viewer, project_id: str, args: Mapping[str, str], *, paged: bool = True) -> dict:
    """The people-and-roles body for *project_id*, as seen by *viewer*.

    Raises ``PeopleRolesError``: 404 for a project the viewer has no grant in
    (or that is closed), alike whether it exists or not; 400 for a bad
    parameter (parsed only after that gate). ``paged=False`` (CSV) returns
    every filtered row.
    """
    project_id = (project_id or "").strip().upper()
    # The authz decision comes first: it marks the request decided, and an
    # unreachable project answers 404 before any parameter is looked at.
    reachable = reachable_unit_ids(viewer, project_id, ROLES_ALLOWING_ORG_UNIT)
    resolved = resolve_grants(viewer)
    projects = _load_projects({project_id})
    scope = ResolvedGrants(user_id=viewer.user_id, is_admin=False, grants=(), projects=projects)
    facts = _viewer_facts(viewer, resolved, scope, project_id)
    project = db.session.get(VaProjectMaster, project_id)
    if (not resolved.is_admin and not facts["mine"]) or project is None \
            or project.project_status != VaStatuses.active:
        raise _not_found()
    filters = _parse(args, paged=paged)

    identity = facts["identity"]
    vgs = [g for g in facts["mine"] if g.scope_type == _U]

    def unit_visible(path: str | None) -> bool:
        if reachable is None:
            return True
        return path is not None and any(
            g.covers_unit(project_id, path) or (g.unit_path or "").startswith(path + ".")
            for g in vgs
        )

    units = [
        u for u in _load_units(project_id)
        if unit_visible(u["path"]) and (identity or u["is_active"])
    ]
    selected = None
    if filters["unit"] is not None:
        selected = next((u for u in units if u["org_unit_id"] == str(filters["unit"])), None)
        if selected is None:
            raise _not_found()
    grid = {(lc["level_code"], lc["cadre_id"]): lc for lc in org.list_level_cadres(project_id)}
    below = _below_counts(units)  # visible units only: no count of what the viewer cannot see

    include_deactivated = identity and filters["status"] != "active"
    grant_rows, truncated = _load_grant_rows(
        project_id, include_deactivated=include_deactivated, include_platform=identity
    )
    # Only a deactivated row can carry the flag, and those load only here.
    users_with_active = _users_with_active_grant(project_id) if include_deactivated else None

    # -- group grants into person x location x cadre rows ---------------------
    grouped: dict[tuple, dict] = {}
    for r in grant_rows:
        active = r.grant_status == VaStatuses.active
        if filters["status"] != "all" and active != (filters["status"] == "active"):
            continue
        user_active = r.user_status == VaStatuses.active
        kind, loc_key, loc = _location(r)
        if kind == "unit" and not unit_visible(r.unit_path):
            continue
        if kind == "site" and not facts["whole_project"] and r.project_site_id not in facts["sites"]:
            continue
        if not identity and not (user_active and loc["active"] and active):
            continue
        key = (r.user_id, kind, loc_key, r.cadre_id)
        row = grouped.get(key)
        if row is None:
            row = grouped[key] = {"r": r, "loc": loc, "entries": []}
        grant = _grant_object(r, project_id)
        row["entries"].append({
            "grant": grant,
            "role": r.role,
            "active": active,
            "derived": _roles(grant, scope) if grant else {r.role},
            "created_at": r.grant_created_at,
            "granted_by": r.granted_by,
            "grant_id": str(r.grant_id),
        })

    sees_pii = pii_visible_user_ids({k[0] for k in grouped}, project_id=project_id)
    now = datetime.now(UTC)

    def audit_allowed(row) -> bool:
        if facts["audit_all"]:
            return True
        loc, r = row["loc"], row["r"]
        if loc["kind"] == "unit":
            return any(g.covers_unit(project_id, loc["path"]) for g in facts["dm_units"])
        return loc["kind"] == "site" and r.project_site_id in facts["dm_sites"]

    rows = []
    for row in grouped.values():
        r, loc, entries = row["r"], row["loc"], row["entries"]
        user_active = r.user_status == VaStatuses.active
        live = user_active and loc["active"]
        name = _initials(r.user_name) if facts["initials"] else r.user_name
        cadre = {"cadre_id": str(r.cadre_id), "code": r.cadre_code, "name": r.cadre_name} if r.cadre_id else None
        out = {
            "row_id": f"{r.user_id}|{loc['kind']}|{loc.get('org_unit_id') or loc.get('project_site_id') or ''}|{r.cadre_id or ''}",
            "person": {
                "user_id": str(r.user_id),
                "name": name,
                "initials_only": facts["initials"],
                "email": r.email if identity else None,
                "job_title": r.job_title,
                "active": user_active,
                "sees_pii": r.user_id in sees_pii,
            },
            "cadre": cadre,
            "location": loc,
            "covered_below": below.get(loc["path"], 0) if loc["kind"] == "unit" else None,
            "grants": [
                {"role": e["role"].value, "status": "active" if e["active"] else "deactive"}
                for e in sorted(entries, key=lambda e: e["role"].value)
            ],
            "cells": _cells(
                entries, live=live, sees_pii=r.user_id in sees_pii, scope=scope,
                loc=loc, cadre_id=r.cadre_id, grid=grid,
            ),
            "audit": None,
        }
        if audit_allowed(row):
            first = min(entries, key=lambda e: e["created_at"])
            out["audit"] = {
                "granted_at": _iso(first["created_at"]),
                "granted_by": first["granted_by"],
                "last_sign_in_at": _iso(r.last_signed_in_at),
                "flags": _flags(
                    entries, user_active=user_active, loc=loc, cadre_id=r.cadre_id, grid=grid,
                    has_active_elsewhere=users_with_active is None or r.user_id in users_with_active
                    or loc["kind"] == "platform",
                    last_sign_in=r.last_signed_in_at, now=now,
                ),
                "grants": [
                    {
                        "role": e["role"].value,
                        "status": "active" if e["active"] else "deactive",
                        "granted_at": _iso(e["created_at"]),
                        "granted_by": e["granted_by"],
                    }
                    for e in sorted(entries, key=lambda e: (e["created_at"], e["role"].value))
                ],
            }
        out["_entries"] = entries
        out["_haystack"] = " ".join(
            filter(None, (name, out["person"]["email"], r.job_title))
        ).lower()
        rows.append(out)

    # The cadre picker lists the audience's cadres, not the filtered page's.
    cadres = sorted(
        {r["cadre"]["cadre_id"]: r["cadre"] for r in rows if r["cadre"]}.values(),
        key=lambda c: (c["name"] or "").lower(),
    )
    rows = [row for row in rows if _keep(row, filters, selected, project_id)]
    rows.sort(key=lambda row: (
        _KIND_ORDER[row["location"]["kind"]],
        row["location"].get("path") or row["location"].get("site_id") or "",
        row["person"]["name"].lower(),
        (row["cadre"] or {}).get("code") or "",
    ))

    columns = []
    for key in CAPABILITY_ROLES:
        columns.append({
            "key": key,
            "label": CAPABILITY_LABELS[key],
            "people": len({row["person"]["user_id"] for row in rows if row["cells"][key]["state"] == "granted"}),
            "hollow": len({row["person"]["user_id"] for row in rows if row["cells"][key]["state"] == "hollow"}),
        })
    total = len(rows)
    if paged:
        rows = rows[filters["offset"]:filters["offset"] + filters["limit"]]
    for row in rows:
        row.pop("_entries")
        row.pop("_haystack")

    body = {
        "project_id": project_id,
        "viewer": {
            "identity": identity,
            "names": "initials" if facts["initials"] else "full",
            "audit": "all" if facts["audit_all"] else ("scoped" if facts["dm_units"] or facts["dm_sites"] else "none"),
        },
        "filters": {
            "level": filters["level"] or None,
            "unit": str(filters["unit"]) if filters["unit"] else None,
            "cadre": filters["cadre"] or None,
            "capability": filters["capability"],
            "status": filters["status"],
            "q": filters["q"] or None,
            "mode": filters["mode"],
        },
        "dormant_days": DORMANT_DAYS,
        "total": total,
        "limit": filters["limit"],
        "offset": filters["offset"],
        "truncated": truncated,
        "columns": columns,
        "rows": rows,
    }
    # The picker trees ride on the first page only; the CSV never needs it.
    if paged and filters["offset"] == 0:
        level = MasOrgLevel
        levels = db.session.execute(
            sa.select(level.level_code, level.level_name, level.depth)
            .where(level.project_id == project_id, *([] if identity else [level.is_active.is_(True)]))
            .order_by(level.depth)
        )
        body["units"] = {"levels": [dict(r._mapping) for r in levels], "units": units}
        body["cadres"] = cadres
    return body


def _keep(row: dict, f: dict, selected: dict | None, project_id: str) -> bool:
    loc = row["location"]
    if f["level"] and (loc["kind"] != "unit" or loc["level_code"].lower() != f["level"]):
        return False
    if f["cadre"] and ((row["cadre"] or {}).get("code") or "").lower() != f["cadre"]:
        return False
    if f["capability"] and row["cells"][f["capability"]]["state"] != "granted":
        return False
    if f["q"] and f["q"] not in row["_haystack"]:
        return False
    if selected is None:
        return True
    if f["mode"] == "granted_here":
        return loc["kind"] == "unit" and loc["org_unit_id"] == selected["org_unit_id"]
    # can_act_here: a grant on the unit or above it, and every project, site
    # and global-admin grant (they reach every unit).
    if loc["kind"] != "unit":
        return True
    return any(
        e["grant"].covers_unit(project_id, selected["path"]) for e in row["_entries"][:1]
    )


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def csv_table(result: dict) -> Iterator[list[str]]:
    """The header, then one list of cells per row, of a ``people_roles``
    result, formula-neutralised. The same rows and redaction as the JSON."""
    audit = result["viewer"]["audit"] != "none"
    header = ["person", "email", "job_title", "person_status", "cadre", "location", "level", "path",
              "units_below"]
    header += [CAPABILITY_LABELS[c["key"]] for c in result["columns"]]
    if audit:
        header += ["granted_at", "granted_by", "last_sign_in_at", "flags"]
    yield header
    for row in result["rows"]:
        loc = row["location"]
        place = {
            "unit": loc.get("unit_name"), "site": loc.get("site_name"),
            "project": "Whole project", "platform": "All projects",
        }[loc["kind"]]
        line = [
            row["person"]["name"], row["person"]["email"], row["person"]["job_title"],
            "active" if row["person"]["active"] else "deactive",
            (row["cadre"] or {}).get("code"), place, loc.get("level_code"), loc.get("path"),
            row["covered_below"],
        ]
        line += [
            "" if row["cells"][c["key"]]["state"] == "blank" else row["cells"][c["key"]]["state"]
            for c in result["columns"]
        ]
        if audit:
            a = row["audit"] or {}
            line += [a.get("granted_at"), a.get("granted_by"), a.get("last_sign_in_at"),
                     " ".join(a.get("flags", ()))]
        yield ["" if v is None else org._spreadsheet_safe(v) if isinstance(v, str) else v for v in line]
