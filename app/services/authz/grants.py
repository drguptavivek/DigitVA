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

import dataclasses
import hashlib
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field

import sqlalchemy as sa
from flask import g, has_request_context, request

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
_BYPASS_KEY = "digitva.authz.bypass_cache"

_P = VaAccessScopeTypes.project
_PS = VaAccessScopeTypes.project_site
_U = VaAccessScopeTypes.org_unit

# Roles whose gate opens on a project or pair grant only once it reaches a form.
_NEEDS_FORM_ON_ACTIVE_PAIR = frozenset({VaAccessRoles.coder, VaAccessRoles.coding_tester})
_NEEDS_FORM = frozenset({VaAccessRoles.reviewer, VaAccessRoles.interviewer})

# A device bearer credential is a collection/coding credential.  Keeping this
# projection here means every authz predicate, including the admin bypasses,
# sees the same credential-scoped grants.  Browser sessions continue to use
# the complete resolved set.
NATIVE_DEVICE_ROLES = frozenset({
    VaAccessRoles.interviewer,
    VaAccessRoles.death_reporter,
    VaAccessRoles.coder,
    VaAccessRoles.coding_tester,
    VaAccessRoles.reviewer,
})


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
    # Opens its role gate (effective_roles). False only for a project or pair
    # grant of a form-resolved role that reaches no active form yet: coder and
    # coding_tester need one on an active pair, reviewer and interviewer any
    # (the legacy VaUsers._get_granted_va_forms rule, digitva-5hmc). Scope is
    # never read from it.
    opens_gate: bool = True
    # Where the grant comes from: "assigned" (a grant row) or "self_coding" (the
    # interviewer grant implied by a coder grant on a self-coding project).
    source: str = "assigned"

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
    web_intake_mode: str = "off"
    scope_level_code: str | None = None   # level_code of coding_scope_level_id
    # Self-coding is on and web intake is not off: a coder here also interviews
    # (policy: web-intake.md, "Self-coding projects").
    self_coding: bool = False


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

    def unit_grant_ids(self, roles, *, coding: bool) -> frozenset[uuid.UUID]:
        return frozenset(
            g.org_unit_id for g in self.of(roles, scope_types=(_U,))
            if not coding or self.codes(g)
        )

    # -- data-manager shaped grants ----------------------------------------

    def oversees(self, grant: Grant) -> bool:
        """site_pi at a unit (the In-charge) or project_pi on a tree project:
        the grants that count as data_manager and interview_supervisor."""
        if grant.role == VaAccessRoles.site_pi:
            return grant.scope_type == _U
        if grant.role == VaAccessRoles.project_pi:
            return self.has_tree(grant.project_id)
        return False

    def is_dm_grant(self, grant: Grant) -> bool:
        """data_manager at any scope, or an overseeing grant
        (access-control-model.md)."""
        return grant.role == VaAccessRoles.data_manager or self.oversees(grant)

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
    form = sa.orm.aliased(VaForms, name="authz_gate_form")
    pair = sa.orm.aliased(VaProjectSites, name="authz_gate_pair")
    form_in_reach = sa.and_(
        form.project_id == project_id,
        form.form_status == VaStatuses.active,
        sa.or_(grant.scope_type != VaAccessScopeTypes.project_site, form.site_id == site.site_id),
    )
    any_form = sa.exists(sa.select(1).where(form_in_reach))
    form_on_active_pair = sa.exists(sa.select(1).where(form_in_reach, sa.exists(sa.select(1).where(
        pair.project_id == form.project_id,
        pair.site_id == form.site_id,
        pair.project_site_status == VaStatuses.active,
    ))))
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
            any_form.label("any_form"),
            form_on_active_pair.label("form_on_active_pair"),
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
            opens_gate=_opens_gate(row),
        ))
    return is_admin, grants


def _opens_gate(row) -> bool:
    if row.scope_type == _U:
        return True
    if row.role in _NEEDS_FORM_ON_ACTIVE_PAIR:
        return bool(row.form_on_active_pair)
    if row.role in _NEEDS_FORM:
        return bool(row.any_form)
    return True


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
            level.level_code,
            project.web_intake_mode,
            project.above_scope_coding_mode,
            sa.and_(demo, has_active_form).label("demo_training"),
            sa.and_(
                project.self_coding_enabled.is_(True), project.web_intake_mode != "off"
            ).label("self_coding"),
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
            self_coding=bool(row.self_coding),
            web_intake_mode=row.web_intake_mode or "off",
            scope_level_code=row.level_code,
        )
        for row in rows
    }


def _implied_interviewer_grants(
    user_id: uuid.UUID, grants: list[Grant], projects: dict[str, ProjectSettings]
) -> list[Grant]:
    """An interviewer grant for each coder grant that codes (coding scope rule;
    a view-only above-scope coder gets none) on a self-coding project, at
    the same scope: derived here, never written (access-control-model.md,
    "Implied roles"). A mentoring institute member's coder grant implies
    nothing; that lookup is one query, run only when a candidate exists.
    """
    scope = ResolvedGrants(user_id=user_id, is_admin=False, grants=(), projects=projects)
    coders = [
        g for g in grants
        if g.role == VaAccessRoles.coder
        and (settings := projects.get(g.project_id)) is not None
        and settings.self_coding
        and scope.codes(g)
    ]
    if not coders:
        return []
    from app.services.mentor_institute_service import member_user_ids

    if user_id in member_user_ids([user_id]):
        return []
    explicit = {
        (g.scope_type, g.project_id, g.project_site_id, g.org_unit_id)
        for g in grants if g.role == VaAccessRoles.interviewer
    }
    return [
        dataclasses.replace(g, role=VaAccessRoles.interviewer, source="self_coding")
        for g in coders
        if (g.scope_type, g.project_id, g.project_site_id, g.org_unit_id) not in explicit
    ]


def _resolve(user_id: uuid.UUID) -> ResolvedGrants:
    is_admin, grants = _load_grants(user_id)
    projects = _load_projects({g.project_id for g in grants})
    # Demo coding and reviewing only for people who code or review somewhere
    # (owner 2026-10-03): an interviewer, ASHA or viewer never sees coding.
    grants.extend(_implied_interviewer_grants(user_id, grants, projects))
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


def _device_projection(resolved: ResolvedGrants) -> ResolvedGrants:
    """Restrict a resolved account to roles supported by a device token.

    The Redis/request memo stores the full account result.  Return a fresh
    immutable result so a bearer request cannot mutate the browser result or
    leak admin/data-manager projects through the shared cache.
    """
    explicit_native = tuple(
        g for g in resolved.grants
        if not g.virtual and g.role in NATIVE_DEVICE_ROLES
    )
    demo_eligible = any(g.role in DEMO_VIRTUAL_ROLES for g in explicit_native)
    grants = tuple(
        g for g in resolved.grants
        if g.role in NATIVE_DEVICE_ROLES and (not g.virtual or demo_eligible)
    )
    project_ids = {grant.project_id for grant in grants}
    projects = {
        project_id: settings
        for project_id, settings in resolved.projects.items()
        if project_id in project_ids
    }
    return dataclasses.replace(
        resolved,
        is_admin=False,
        grants=grants,
        projects=projects,
    )


def resolve_grants(user, *, native: bool | None = None) -> ResolvedGrants:
    """The user's ``ResolvedGrants``, memoised for the current request.

    Kept in the WSGI environ, not ``flask.g``: the app context (and so ``g``)
    can outlive a request and would hand one user's grants to the next
    (same reason as dm_kpi_scope.dm_scope). Outside a request (Celery, CLI,
    direct service calls) it resolves fresh every time.

    Across requests the resolution is cached in Redis (``grant_cache``,
    digitva-5hmc; this reverses the earlier "no cross-request cache" design,
    .tasks/digitva-0wc-design.md section 9): versioned keys bumped after every
    commit that changes grants or the reach they resolve to, a 5-minute TTL
    behind them, and the database whenever Redis cannot answer.
    """
    from app.services.authz import grant_cache

    if native is None:
        native = bool(has_request_context() and g.get("bearer_auth"))

    user_id = user.user_id
    if not has_request_context():
        resolved = _resolve(user_id)
        return _device_projection(resolved) if native else resolved
    memo = request.environ.setdefault(_ENVIRON_KEY, {})
    resolved = memo.get(user_id)
    if resolved is None:
        # After invalidate() in this request the cache still holds the old
        # version until commit: read the database instead.
        bypass = request.environ.get(_BYPASS_KEY, set())
        if "*" in bypass or user_id in bypass:
            resolved = memo[user_id] = _resolve(user_id)
        else:
            resolved = memo[user_id] = grant_cache.load(user_id, _resolve)
    return _device_projection(resolved) if native else resolved


def invalidate(user_id: uuid.UUID) -> None:
    """Forget *user_id*'s grants: the request memo now, the Redis cache when
    the session next commits. Every grant write calls it so a grant written
    and used in one request is seen; ORM writes bump the cache anyway
    (``grant_cache``), Core statements depend on this call."""
    from app.services.authz import grant_cache

    grant_cache.defer_user_bump(db.session(), user_id)
    if has_request_context():
        request.environ.get(_ENVIRON_KEY, {}).pop(user_id, None)
        request.environ.setdefault(_BYPASS_KEY, set()).add(user_id)


def invalidate_all() -> None:
    """Every user's cached grants, when the session next commits: for a Core
    statement that changes many users' reach (an org-unit path rewrite or
    subtree deactivation) and so escapes the ORM hooks."""
    from app.services.authz import grant_cache

    grant_cache.defer_global_bump(db.session())
    if has_request_context():
        request.environ.pop(_ENVIRON_KEY, None)
        request.environ.setdefault(_BYPASS_KEY, set()).add("*")
