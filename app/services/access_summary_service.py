"""The signed-in user's whole access in one body (digitva-339w).

Served by ``GET /api/v1/me/access`` for either credential. Built from
``resolve_grants`` (closed projects and inactive grants, pairs and units are
already absent from it) plus a fixed number of queries per project: names,
sites, granted-unit names, and one tree load per tree project. Pure reads.

The body is the complete statement of the user's access (digitva-ntct.3):
every value is the output of the predicate the server enforces, no second
copy. ``grants[]`` lists every resolved grant with ``active``; every other
list (``roles``, ``sites[].roles``, ``units[].roles``, ``actions``) counts
active grants only.

Explicit grants only: demo-training virtual grants are never listed in
``grants`` or ``roles``; ``demo_coding`` says where they open coding practice.
Admin is reflected as ``is_admin`` and gets no implicit project.

Policy: docs/policy/api-v1.md; shape: docs/current-state/api-v1.md.
"""

from __future__ import annotations

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
)
from app.services import mentor_institute_service, totp_service
from app.services.authz import action_reach, resolve_grants, role_flags
from app.services.authz.actions import ADMIN_BYPASS
from app.services.authz.consulted import mark_consulted
from app.services.viewer_pii_service import should_redact_pii

_PS = VaAccessScopeTypes.project_site
_U = VaAccessScopeTypes.org_unit
_DM = VaAccessRoles.data_manager
_IS = VaAccessRoles.interview_supervisor
_CODING_ROLES = frozenset(
    {VaAccessRoles.coder, VaAccessRoles.coding_tester, VaAccessRoles.reviewer})


def build_access_summary(user) -> dict:
    """The access summary of *user*; see docs/current-state/api-v1.md."""
    # Imported here: these import this package or route modules at load.
    from app.services.device_auth_service import has_device_access
    from app.services.web_intake_service import interviewer_context, self_coding_project_ids

    mark_consulted()
    resolved = resolve_grants(user)
    # Once per call: the intake routes' check, shared with has_device_access.
    context = interviewer_context(user)
    interviewing: dict[str, list[dict]] = {}
    for entry in context:
        interviewing.setdefault(entry["project_id"], []).append(entry)
    self_coding = self_coding_project_ids(user)
    explicit = [g for g in resolved.grants if not g.virtual]
    by_project: dict[str, list] = {}
    for grant in explicit:
        by_project.setdefault(grant.project_id, []).append(grant)

    names = {}
    sites: dict[str, list] = {}
    unit_names = {}
    if by_project:
        project_ids = sorted(by_project)
        names = dict(db.session.execute(
            sa.select(VaProjectMaster.project_id, VaProjectMaster.project_name)
            .where(VaProjectMaster.project_id.in_(project_ids))
        ).all())
        for row in db.session.execute(
            sa.select(VaProjectSites.project_id, VaProjectSites.site_id, VaSiteMaster.site_name)
            .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
            .where(
                VaProjectSites.project_id.in_(project_ids),
                VaProjectSites.project_site_status == VaStatuses.active,
            )
            .order_by(VaProjectSites.project_id, VaProjectSites.site_id)
        ):
            sites.setdefault(row.project_id, []).append(row)
        unit_ids = {g.org_unit_id for g in explicit if g.scope_type == _U}
        if unit_ids:
            unit_names = dict(db.session.execute(
                sa.select(MasOrgUnit.org_unit_id, MasOrgUnit.unit_name)
                .where(MasOrgUnit.org_unit_id.in_(unit_ids))
            ).all())

    projects = [
        _project(project_id, grants, resolved, names.get(project_id),
                 sites.get(project_id, []), unit_names, interviewing.get(project_id, []),
                 project_id in self_coding)
        for project_id, grants in sorted(by_project.items())
    ]
    demo_projects = sorted({g.project_id for g in resolved.grants if g.virtual})
    return {
        "user": {
            "user_id": str(user.user_id),
            "name": user.name,
            "landing_page": user.landing_page,
            "coding_languages": list(user.vacode_language or []),
        },
        "is_admin": resolved.is_admin,
        "account": {
            "privileged": totp_service.is_privileged(user),
            "second_factor": {
                "required": totp_service.needs_second_factor(user),
                "configured": totp_service.has_any_factor(user.user_id),
            },
            "pii_visible": not should_redact_pii(user),
            "device_access": has_device_access(user, context),
            "mentor": {
                "member": user.user_id in mentor_institute_service.member_user_ids([user.user_id]),
                "admin_of": [
                    {"institute_code": i.institute_code, "institute_name": i.institute_name}
                    for i in mentor_institute_service.administered_institutes(user.user_id)
                ],
            },
        },
        "roles": sorted(role_flags(user, virtual=False)),
        "admin_actions": sorted(a.value for a in ADMIN_BYPASS) if resolved.is_admin else [],
        "projects": projects,
        "demo_coding": {"available": bool(demo_projects), "project_ids": demo_projects},
    }


def _roles(grant, resolved) -> set:
    """The roles one grant holds: its own, plus data_manager and
    interview_supervisor where ``role_flags`` derives them (``oversees``)."""
    roles = {grant.role}
    if resolved.oversees(grant):
        roles |= {_DM, _IS}
    return roles


def _project(project_id, grants, resolved, name, site_rows, unit_names, interview,
             code_now) -> dict:
    has_tree = resolved.has_tree(project_id)
    grants = sorted(grants, key=lambda g: (
        g.role.value, g.scope_type.value, g.site_id or "", str(g.org_unit_id or "")))
    # Every list below counts active grants only (``grants`` itself shows all).
    active = [g for g in grants if g.opens_gate]
    # A project or unit grant reaches every active site; a site grant its own.
    roles_all_sites = set().union(*(_roles(g, resolved) for g in active if g.scope_type != _PS))
    site_grants: dict[str, set] = {}
    for g in active:
        if g.scope_type == _PS:
            site_grants.setdefault(g.site_id, set()).update(_roles(g, resolved))
    # Interviewer only where the intake routes list the site (interviewer_context).
    interviewing = {entry["site_id"] for entry in interview}
    site_list = []
    for row in site_rows:
        roles = (roles_all_sites | site_grants.get(row.site_id, set())) - {VaAccessRoles.interviewer}
        if row.site_id in interviewing:
            roles.add(VaAccessRoles.interviewer)
        if roles:
            site_list.append({
                "site_id": row.site_id,
                "site_name": row.site_name,
                "roles": sorted(r.value for r in roles),
            })
    settings = resolved.projects[project_id]
    actions = action_reach(resolved, project_id)
    actions["interview"] = [
        {k: entry[k] for k in ("site_id", "site_name", "web_intake_mode", "org_units")}
        for entry in interview
    ]
    body = {
        "project_id": project_id,
        "project_name": name,
        "has_tree": has_tree,
        "settings": {
            "web_intake_mode": settings.web_intake_mode,
            "coding_scope": None if settings.scope_depth is None else {
                "level_code": settings.scope_level_code, "above_mode": settings.above_mode},
        },
        "self_coding": {"enabled": settings.self_coding, "code_now": code_now},
        "grants": [_grant(g, unit_names, resolved) for g in grants],
        "actions": actions,
        "sites": site_list,
    }
    if has_tree:
        # A unit interviewer grant always opens its gate, but with no site the
        # intake routes accept (web intake off) it reaches no unit either.
        tree_grants = active if interview else [g for g in active if g.role != VaAccessRoles.interviewer]
        body.update(_tree(project_id, tree_grants, resolved))
    return body


def _codes(grant, resolved) -> bool:
    """The server's coding scope rule for one grant: coding_tester is exempt
    from the scope level (predicates.py, CODE_CODER), coder and reviewer are not."""
    return grant.role == VaAccessRoles.coding_tester or resolved.codes(grant)


def _grant(grant, unit_names, resolved) -> dict:
    body = {
        "role": grant.role.value,
        "scope": grant.scope_type.value,
        "active": grant.opens_gate,
        "source": grant.source,
    }
    if grant.role in _CODING_ROLES:
        body["codes"] = _codes(grant, resolved)
    if grant.scope_type == _PS:
        body["site_id"] = grant.site_id
    elif grant.scope_type == _U:
        body["org_unit_id"] = str(grant.org_unit_id)
        body["unit_name"] = unit_names.get(grant.org_unit_id)
    return body


def _tree(project_id, grants, resolved) -> dict:
    """Levels and units with the roles that reach each (*grants*: the active ones).

    ``roles`` is tree reach (picker/browse, the same answer as
    ``/organization/<p>/units?role=...``), not action capability: actions are
    decided per request. Per role the reach is the whole tree for a project
    or project_site grant (a site grant reaches that site's cases in any
    unit); a project_pi holds every one of their roles on the whole tree (as
    ``reachable_unit_ids`` has it); else the subtrees of that role's unit
    grants. data_manager and interview_supervisor are derived from an
    In-charge's unit grant (its subtree) and a project_pi (everywhere), as
    ``role_flags`` has it. ``can_code`` mirrors the coding scope rule: some coder or
    coding_tester grant covering the unit codes there. Ancestors of reached
    units come as context: ``roles: []``, ``selectable: false``.
    """
    # Imported here so this service does not import a route module at load.
    from app.routes.api.organization import units_payload

    tree = units_payload(project_id, None)
    if any(g.role == VaAccessRoles.project_pi for g in grants):
        # Web intake has no project_pi bypass (web_intake_service.reachable_unit_ids):
        # a unit interviewer grant stays its subtree.
        whole = set().union(*(
            _roles(g, resolved) for g in grants
            if not (g.scope_type == _U and g.role == VaAccessRoles.interviewer)))
    else:
        whole = set().union(*(_roles(g, resolved) for g in grants if g.scope_type != _U))
    coders = [
        g for g in grants
        if g.role in (VaAccessRoles.coder, VaAccessRoles.coding_tester) and _codes(g, resolved)
    ]
    subtrees: dict = {}
    for g in grants:
        if g.scope_type == _U:
            for role in _roles(g, resolved) - whole:
                subtrees.setdefault(role, []).append(g)

    units = []
    reached_paths = set()
    for unit in tree["units"]:
        roles = set(whole)
        roles.update(
            role for role, unit_grants in subtrees.items()
            if any(g.covers_unit(project_id, unit["path"]) for g in unit_grants)
        )
        can_code = any(g.is_wide or g.covers_unit(project_id, unit["path"]) for g in coders)
        unit = dict(unit, roles=sorted(r.value for r in roles), selectable=bool(roles),
                    can_code=can_code)
        if roles:
            reached_paths.add(unit["path"])
        units.append(unit)
    # ltree paths are dotted unit codes, so a prefix of a reached path is an ancestor's.
    context_paths = {
        ".".join(path.split(".")[:i])
        for path in reached_paths
        for i in range(1, len(path.split(".")))
    }
    units = [u for u in units if u["selectable"] or u["path"] in context_paths]
    return {
        "levels": [
            {"level_code": lv["level_code"], "level_name": lv["level_name"], "depth": lv["depth"]}
            for lv in tree["levels"]
        ],
        "units": units,
    }
