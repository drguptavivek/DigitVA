"""One user's grants, resolved once per request (digitva-0wc, design 1.3).

``resolve_grants`` runs two queries: the user's live grants (each resolved to
its project, and for a unit grant to its depth and ltree path), then the
settings of the projects involved plus every active demo-training project.
Everything else in ``app.services.authz`` is computed from the result.

Closed projects resolve nothing: ``active_project_condition`` is ANDed once
here, so a grant on a non-active project is simply absent
(docs/policy/access-control-model.md, "Closed Projects"). Admin is the
global grant and is never project-resolved.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

import sqlalchemy as sa
from flask import has_request_context, request

from app import db
from app.models import (
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services.authz.actions import DEMO_VIRTUAL_ROLES
from app.services.org_grant_service import (
    ABOVE_SCOPE_CODE_ANY,
    ABOVE_SCOPE_VIEW_ONLY,
    active_project_condition,
)

_ENVIRON_KEY = "digitva.authz"

_P = VaAccessScopeTypes.project
_PS = VaAccessScopeTypes.project_site
_U = VaAccessScopeTypes.org_unit


@dataclass(frozen=True)
class Grant:
    role: VaAccessRoles
    scope_type: VaAccessScopeTypes
    project_id: str                       # resolved for every scope (pair, unit -> project)
    site_id: str | None = None            # project_site scope only
    project_site_id: uuid.UUID | None = None
    org_unit_id: uuid.UUID | None = None  # org_unit scope only
    unit_depth: int | None = None         # the unit's level depth
    unit_path: str | None = None          # the unit's ltree path, for subtree tests in Python
    virtual: bool = False                 # demo-training grant (design 2.6)

    @property
    def is_wide(self) -> bool:
        """A project or project_site grant: the top of any tree."""
        return self.scope_type in (_P, _PS)

    def covers_unit(self, project_id: str | None, path: str | None) -> bool:
        """Whether this unit grant's subtree holds the unit at *path* of
        *project_id*. Paths are built from unit codes, unique within one
        project only, so the project is part of the test."""
        if self.unit_path is None or path is None or project_id != self.project_id:
            return False
        return path == self.unit_path or path.startswith(self.unit_path + ".")


@dataclass(frozen=True)
class ProjectSettings:
    project_id: str
    has_tree: bool
    scope_depth: int | None   # depth of coding_scope_level_id; None = no coding scope
    above_mode: str           # 'code_any' | 'view_only'
    demo_training: bool


@dataclass(frozen=True)
class ResolvedGrants:
    """A user's live grants on active projects, plus the projects' settings.

    Pure: no method runs SQL.
    """

    user_id: uuid.UUID
    is_admin: bool
    grants: tuple[Grant, ...]
    projects: dict[str, ProjectSettings] = field(default_factory=dict)

    # -- selection ---------------------------------------------------------

    def of(
        self,
        roles: Iterable[VaAccessRoles],
        *,
        scope_types: Iterable[VaAccessScopeTypes] | None = None,
        virtual: bool | None = None,
    ) -> Iterator[Grant]:
        roles = frozenset(roles)
        scope_types = frozenset(scope_types) if scope_types is not None else None
        for grant in self.grants:
            if grant.role not in roles:
                continue
            if scope_types is not None and grant.scope_type not in scope_types:
                continue
            if virtual is not None and grant.virtual != virtual:
                continue
            yield grant

    def holds(self, role: VaAccessRoles, scope_type: VaAccessScopeTypes | None = None) -> bool:
        return any(self.of((role,), scope_types=None if scope_type is None else (scope_type,)))

    def has_tree(self, project_id: str) -> bool:
        settings = self.projects.get(project_id)
        return bool(settings and settings.has_tree)

    # -- the coding scope rule (organization-model.md, "Coding scope") ------

    def codes(self, grant: Grant) -> bool:
        """Whether *grant* codes under its project's coding scope level.

        A project or pair grant is above any level, so it codes only when no
        level is set or the project says ``code_any``; a unit grant codes when
        its unit is at or below the level, or under ``code_any``.
        """
        settings = self.projects.get(grant.project_id)
        if settings is None or settings.scope_depth is None:
            return True
        if settings.above_mode == ABOVE_SCOPE_CODE_ANY:
            return True
        if grant.is_wide:
            return False
        return grant.unit_depth is not None and grant.unit_depth >= settings.scope_depth

    def wide_projects(self, roles, *, coding: bool) -> frozenset[str]:
        return frozenset(
            g.project_id for g in self.of(roles, scope_types=(_P,))
            if not coding or self.codes(g)
        )

    def wide_pairs(self, roles, *, coding: bool) -> frozenset[tuple[str, str]]:
        return frozenset(
            (g.project_id, g.site_id) for g in self.of(roles, scope_types=(_PS,))
            if not coding or self.codes(g)
        )

    def unit_grant_ids(self, roles, *, coding: bool) -> frozenset[uuid.UUID]:
        return frozenset(
            g.org_unit_id for g in self.of(roles, scope_types=(_U,))
            if not coding or self.codes(g)
        )

    # -- data-manager shaped grants ----------------------------------------

    def is_dm_grant(self, grant: Grant) -> bool:
        """data_manager at any scope; site_pi at a unit (the In-charge);
        project_pi on a tree project (access-control-model.md)."""
        if grant.role == VaAccessRoles.data_manager:
            return True
        if grant.role == VaAccessRoles.site_pi:
            return grant.scope_type == _U
        if grant.role == VaAccessRoles.project_pi:
            return self.has_tree(grant.project_id)
        return False

    def dm_grants(self) -> tuple[Grant, ...]:
        return tuple(g for g in self.grants if self.is_dm_grant(g))

    def dm_projects(self) -> frozenset[str]:
        """Tree projects where the user holds any DM-shaped grant: the
        projects whose unrouted queue they see (decision 2026-10-02)."""
        return frozenset(
            g.project_id for g in self.dm_grants() if self.has_tree(g.project_id)
        )

    def digest(self) -> str:
        """Short stable hash of the grants, for cache keys."""
        raw = "|".join(sorted(
            f"{g.role.value}:{g.scope_type.value}:{g.project_id}:{g.site_id}:{g.org_unit_id}"
            f":{int(g.virtual)}"
            for g in self.grants
        ))
        return hashlib.sha1(f"{int(self.is_admin)}#{raw}".encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------

def _load_grants(user_id: uuid.UUID) -> tuple[bool, list[Grant]]:
    grant = VaUserAccessGrants
    site = sa.orm.aliased(VaProjectSites, name="authz_grant_site")
    unit = sa.orm.aliased(MasOrgUnit, name="authz_grant_unit")
    level = sa.orm.aliased(MasOrgLevel, name="authz_grant_level")
    project_id = sa.func.coalesce(grant.project_id, site.project_id, unit.project_id)
    rows = db.session.execute(
        sa.select(
            grant.role,
            grant.scope_type,
            project_id.label("project_id"),
            site.site_id,
            grant.project_site_id,
            grant.org_unit_id,
            level.depth,
            sa.cast(unit.path, sa.Text).label("unit_path"),
        )
        .select_from(grant)
        .outerjoin(site, sa.and_(
            site.project_site_id == grant.project_site_id,
            site.project_site_status == VaStatuses.active,
        ))
        .outerjoin(unit, sa.and_(
            unit.org_unit_id == grant.org_unit_id,
            unit.is_active.is_(True),
        ))
        .outerjoin(level, level.org_level_id == unit.org_level_id)
        .where(
            grant.user_id == user_id,
            grant.grant_status == VaStatuses.active,
            sa.or_(
                grant.scope_type == VaAccessScopeTypes.global_scope,
                # An inactive pair or unit leaves the project NULL: no grant.
                sa.and_(project_id.is_not(None), active_project_condition(project_id)),
            ),
        )
    ).all()
    is_admin = False
    grants = []
    for row in rows:
        if row.scope_type == VaAccessScopeTypes.global_scope:
            is_admin = is_admin or row.role == VaAccessRoles.admin
            continue
        grants.append(Grant(
            role=row.role,
            scope_type=row.scope_type,
            project_id=row.project_id,
            site_id=row.site_id if row.scope_type == _PS else None,
            project_site_id=row.project_site_id,
            org_unit_id=row.org_unit_id,
            unit_depth=row.depth,
            unit_path=row.unit_path,
        ))
    return is_admin, grants


def _load_projects(project_ids: set[str]) -> dict[str, ProjectSettings]:
    """Settings of *project_ids*, plus every active demo-training project
    (flagged ``demo_training`` only when it has an active form)."""
    level = sa.orm.aliased(MasOrgLevel, name="authz_scope_level")
    project = VaProjectMaster
    has_tree = sa.exists(sa.select(1).where(
        MasOrgLevel.project_id == project.project_id,
        MasOrgLevel.is_active.is_(True),
    ))
    has_active_form = sa.exists(sa.select(1).where(
        VaForms.project_id == project.project_id,
        VaForms.form_status == VaStatuses.active,
    ))
    demo = sa.and_(
        project.demo_training_enabled.is_(True),
        project.project_status == VaStatuses.active,
    )
    wanted = sa.or_(project.project_id.in_(sorted(project_ids)), demo) if project_ids else demo
    rows = db.session.execute(
        sa.select(
            project.project_id,
            level.depth,
            project.above_scope_coding_mode,
            sa.and_(demo, has_active_form).label("demo_training"),
            has_tree.label("has_tree"),
        )
        .outerjoin(level, level.org_level_id == project.coding_scope_level_id)
        .where(wanted)
    ).all()
    return {
        row.project_id: ProjectSettings(
            project_id=row.project_id,
            has_tree=bool(row.has_tree),
            scope_depth=row.depth,
            above_mode=row.above_scope_coding_mode or ABOVE_SCOPE_VIEW_ONLY,
            demo_training=bool(row.demo_training),
        )
        for row in rows
    }


def _resolve(user_id: uuid.UUID) -> ResolvedGrants:
    is_admin, grants = _load_grants(user_id)
    projects = _load_projects({g.project_id for g in grants})
    # Demo coding and reviewing only for people who code or review somewhere
    # (owner 2026-10-03): an interviewer, ASHA or viewer never sees coding.
    demo_eligible = is_admin or any(g.role in DEMO_VIRTUAL_ROLES for g in grants)
    for settings in projects.values():
        if not settings.demo_training or not demo_eligible:
            continue
        grants.extend(
            Grant(role=role, scope_type=_P, project_id=settings.project_id, virtual=True)
            for role in sorted(DEMO_VIRTUAL_ROLES, key=lambda r: r.value)
        )
    return ResolvedGrants(
        user_id=user_id, is_admin=is_admin, grants=tuple(grants), projects=projects
    )


def resolve_grants(user) -> ResolvedGrants:
    """The user's ``ResolvedGrants``, memoised for the current request.

    Kept in the WSGI environ, not ``flask.g``: the app context (and so ``g``)
    can outlive a request and would hand one user's grants to the next
    (same reason as dm_kpi_scope.dm_scope). Outside a request (Celery, CLI,
    direct service calls) it resolves fresh every time. No cross-request
    cache: a revoked grant bites on the next request.
    """
    user_id = user.user_id
    if not has_request_context():
        return _resolve(user_id)
    memo = request.environ.setdefault(_ENVIRON_KEY, {})
    resolved = memo.get(user_id)
    if resolved is None:
        resolved = memo[user_id] = _resolve(user_id)
    return resolved


def invalidate(user_id: uuid.UUID) -> None:
    """Forget the memoised grants of *user_id*; every grant write calls it so
    a grant written and used in one request is seen."""
    if has_request_context():
        request.environ.get(_ENVIRON_KEY, {}).pop(user_id, None)
