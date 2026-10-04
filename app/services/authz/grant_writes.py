"""Who may write which grant where (digitva-0wc, design 2.5).

``can_grant`` answers whether an actor may create, reactivate or revoke a
grant of a role at a scope; ``grant_list_filter`` is the same rule as a
predicate over ``VaUserAccessGrants`` (the grants the actor may manage), so
the grant list shows exactly what ``can_grant`` allows. The write-time
checks that follow a True decision are unchanged and not repeated here:
``org_grant_service.validate_org_unit_grant`` (cadre, role-at-unit) and
``mentor_institute_service.check_mentor_grant``.

Policy: access-control-model.md, "Who creates which grants";
dm-user-grant-management.md, "Scope Rules" and "Toggle".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaProjectSites,
    VaUserAccessGrants,
)
from app.services.authz.actions import (
    DM_SITE_ASSIGNABLE,
    DM_TREE_ASSIGNABLE,
    PI_NEVER_ASSIGNS,
    Reason,
)
from app.services.authz.consulted import mark_consulted
from app.services.authz.grants import Grant, ResolvedGrants, resolve_grants
from app.services.authz.predicates import _ALLOWED, Decision, _deny, _subtree_select

_R = VaAccessRoles
_P = VaAccessScopeTypes.project
_PS = VaAccessScopeTypes.project_site
_U = VaAccessScopeTypes.org_unit


@dataclass(frozen=True)
class GrantTarget:
    role: VaAccessRoles
    scope_type: VaAccessScopeTypes
    project_id: str | None = None          # project scope
    project_site_id: uuid.UUID | None = None
    org_unit_id: uuid.UUID | None = None


@dataclass(frozen=True)
class _Where:
    """Where a target grant sits: its project, pair or unit, and the project's kind."""

    project_id: str
    site_id: str | None
    project_site_id: uuid.UUID | None
    org_unit_id: uuid.UUID | None
    path: str | None
    has_tree: bool


def _has_tree(project_id_expr):
    return sa.exists(sa.select(1).where(
        MasOrgLevel.project_id == project_id_expr,
        MasOrgLevel.is_active.is_(True),
    ))


def _locate(target: GrantTarget) -> _Where | None:
    """One query: the target's project (and pair or unit) and its kind."""
    if target.scope_type == _P and target.project_id:
        has_tree = db.session.scalar(sa.select(_has_tree(target.project_id)))
        return _Where(target.project_id, None, None, None, None, bool(has_tree))
    if target.scope_type == _PS and target.project_site_id:
        row = db.session.execute(
            sa.select(VaProjectSites.project_id, VaProjectSites.site_id,
                      _has_tree(VaProjectSites.project_id).label("has_tree"))
            .where(VaProjectSites.project_site_id == target.project_site_id)
        ).first()
        if row is None:
            return None
        return _Where(row.project_id, row.site_id, target.project_site_id, None, None,
                      bool(row.has_tree))
    if target.scope_type == _U and target.org_unit_id:
        row = db.session.execute(
            sa.select(MasOrgUnit.project_id, sa.cast(MasOrgUnit.path, sa.Text).label("path"),
                      _has_tree(MasOrgUnit.project_id).label("has_tree"))
            .where(MasOrgUnit.org_unit_id == target.org_unit_id,
                   MasOrgUnit.is_active.is_(True))
        ).first()
        if row is None:
            return None
        return _Where(row.project_id, None, None, target.org_unit_id, row.path,
                      bool(row.has_tree))
    return None


def writer_grants(g: ResolvedGrants) -> list[Grant]:
    """The actor's grants that confer any grant-writing power: project_pi,
    data_manager at any scope, site_pi at a unit (the In-charge)."""
    return [
        x for x in g.grants
        if not x.virtual and (
            x.role in (_R.project_pi, _R.data_manager)
            or (x.role == _R.site_pi and x.scope_type == _U)
        )
    ]


def _allows(actor: Grant, role: VaAccessRoles, scope: VaAccessScopeTypes, where: _Where) -> bool:
    """Whether one actor grant lets them write *role* at *where*."""
    if actor.project_id != where.project_id:
        return False
    if actor.role == _R.project_pi:
        # Any role except admin and project_pi, anywhere in the project.
        return role not in PI_NEVER_ASSIGNS
    in_subtree = scope == _U and actor.covers_unit(where.project_id, where.path)
    strictly_below = in_subtree and where.path != actor.unit_path
    if actor.role == _R.site_pi:
        # In-charge (site_pi at a unit), district projects: data_manager on
        # their own unit and below, the DM role list anywhere in the subtree.
        return actor.scope_type == _U and in_subtree and (
            role == _R.data_manager or role in DM_TREE_ASSIGNABLE
        )
    if actor.role != _R.data_manager:
        return False
    if not where.has_tree:
        # Site projects: today's rule (coder, coding_tester, data_manager at
        # the DM's own scope; a pair DM on that pair only).
        if role not in DM_SITE_ASSIGNABLE:
            return False
        if actor.scope_type == _P:
            return scope in (_P, _PS)
        return actor.scope_type == _PS and scope == _PS and where.site_id == actor.site_id
    # District projects: data_manager strictly below the DM's own grant, the
    # DM role list anywhere in the subtree, own level included.
    if actor.scope_type == _P:
        if role == _R.data_manager:
            return scope in (_PS, _U)
        return role in DM_TREE_ASSIGNABLE and scope in (_P, _PS, _U)
    if actor.scope_type == _PS:
        # Nothing lies below a pair.
        return role in DM_TREE_ASSIGNABLE and scope == _PS and where.site_id == actor.site_id
    if role == _R.data_manager:
        return strictly_below
    return role in DM_TREE_ASSIGNABLE and in_subtree


def can_grant(
    actor,
    target: GrantTarget,
    *,
    grantee_id: uuid.UUID | None = None,
    _grants: ResolvedGrants | None = None,
) -> Decision:
    """May *actor* create, reactivate or revoke a grant matching *target*?

    *grantee_id*: a non-admin never writes a ``data_manager`` grant for
    themselves (a data manager may not revoke their own data_manager grant,
    dm-user-grant-management.md, "Toggle").
    """
    mark_consulted()
    g = _grants if _grants is not None else resolve_grants(actor)
    if g.is_admin:
        return _ALLOWED
    writers = writer_grants(g)
    if not writers:
        return _deny(Reason.NO_ROLE)
    if target.role in PI_NEVER_ASSIGNS or target.scope_type == VaAccessScopeTypes.global_scope:
        return _deny(Reason.OUT_OF_SCOPE)
    if grantee_id is not None and grantee_id == g.user_id and target.role == _R.data_manager:
        return _deny(Reason.OUT_OF_SCOPE)
    where = _locate(target)
    if where is None:
        return _deny(Reason.NOT_FOUND)
    if any(_allows(x, target.role, target.scope_type, where) for x in writers):
        return _ALLOWED
    return _deny(Reason.OUT_OF_SCOPE)


# ---------------------------------------------------------------------------
# The same rule over the grants table
# ---------------------------------------------------------------------------

_G = VaUserAccessGrants


def _at_project(project_id: str, scopes) -> sa.ColumnElement:
    """Grant rows of *project_id* at any of *scopes*."""
    clauses = []
    if _P in scopes:
        clauses.append(sa.and_(_G.scope_type == _P, _G.project_id == project_id))
    if _PS in scopes:
        clauses.append(sa.and_(_G.scope_type == _PS, _G.project_site_id.in_(
            sa.select(VaProjectSites.project_site_id)
            .where(VaProjectSites.project_id == project_id).correlate(None)
        )))
    if _U in scopes:
        clauses.append(sa.and_(_G.scope_type == _U, _G.org_unit_id.in_(
            sa.select(MasOrgUnit.org_unit_id)
            .where(MasOrgUnit.project_id == project_id, MasOrgUnit.is_active.is_(True))
            .correlate(None)
        )))
    return sa.or_(*clauses)


def _in_subtree(actor: Grant, *, strict: bool) -> sa.ColumnElement:
    clause = sa.and_(_G.scope_type == _U, _G.org_unit_id.in_(_subtree_select([actor.org_unit_id])))
    return sa.and_(clause, _G.org_unit_id != actor.org_unit_id) if strict else clause


def _roles(roles) -> sa.ColumnElement:
    return _G.role.in_(sorted(roles, key=lambda r: r.value))


def _list_clause(g: ResolvedGrants, actor: Grant) -> sa.ColumnElement:
    pid = actor.project_id
    if actor.role == _R.project_pi:
        return sa.and_(sa.not_(_roles(PI_NEVER_ASSIGNS)), _at_project(pid, (_P, _PS, _U)))
    if actor.role == _R.site_pi:
        return sa.and_(
            _roles(DM_TREE_ASSIGNABLE | {_R.data_manager}), _in_subtree(actor, strict=False)
        )
    own_pair = sa.and_(_G.scope_type == _PS, _G.project_site_id == actor.project_site_id)
    if not g.has_tree(pid):
        if actor.scope_type == _P:
            return sa.and_(_roles(DM_SITE_ASSIGNABLE), _at_project(pid, (_P, _PS)))
        return sa.and_(_roles(DM_SITE_ASSIGNABLE), own_pair)
    six = _roles(DM_TREE_ASSIGNABLE)
    dm = _G.role == _R.data_manager
    if actor.scope_type == _P:
        return sa.or_(
            sa.and_(dm, _at_project(pid, (_PS, _U))),
            sa.and_(six, _at_project(pid, (_P, _PS, _U))),
        )
    if actor.scope_type == _PS:
        return sa.and_(six, own_pair)
    return sa.or_(
        sa.and_(dm, _in_subtree(actor, strict=True)),
        sa.and_(six, _in_subtree(actor, strict=False)),
    )


def grant_list_filter(actor, *, _grants: ResolvedGrants | None = None) -> sa.ColumnElement:
    """Predicate over ``VaUserAccessGrants``: the grants *actor* may manage."""
    mark_consulted()
    g = _grants if _grants is not None else resolve_grants(actor)
    if g.is_admin:
        return sa.true()
    clauses = [_list_clause(g, x) for x in writer_grants(g)]
    if not clauses:
        return sa.false()
    not_own_dm = sa.not_(sa.and_(_G.role == _R.data_manager, _G.user_id == g.user_id))
    return sa.and_(sa.or_(*clauses), not_own_dm)
