"""Intake supervision (``Action.SUPERVISE_INTAKE``): who supervises which case.

The one rule for supervisory reach over a ``VaDeathRegister`` case.
``predicates.can(user, SUPERVISE_INTAKE, case)`` asks it for one case;
``supervised_case_condition`` is the same rule as a SQL condition for the
worklist; ``supervising_grant`` and ``dm_shaped_grant`` name the grant a
supervisor action's audit row relies on (case_transition_service).

Decisions 15-17 (.tasks/2026-09-28-interviewer-worklist.md): an
``interview_supervisor`` unit grant reaches its unit's subtree on its own
(no interviewer grant needed); a ``data_manager`` grant supervises through
its own scope; so does an In-charge (``site_pi`` at a unit) through its
subtree and a ``project_pi`` on a tree project through the whole project
(digitva-0wc). No other role confers supervision, and admin has no bypass.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from flask import g, has_request_context
from sqlalchemy.orm import aliased

from app import db
from app.models import (
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
)
from app.services.authz.actions import SUPERVISING_ROLES
from app.services.org_grant_service import active_project_condition

# SUPERVISING_ROLES (site_pi counts at a unit only: the In-charge), plus
# project_pi on a tree project. Sorted so the SQL is stable.
_SUPERVISING_ROLES = (*sorted(SUPERVISING_ROLES, key=lambda r: r.value), VaAccessRoles.project_pi)
# Every data-manager power, as ResolvedGrants.is_dm_grant: data_manager,
# the In-charge and project_pi on a tree project.
_DM_SHAPED_ROLES = (VaAccessRoles.data_manager, VaAccessRoles.site_pi, VaAccessRoles.project_pi)


def _covering_grants(
    user_id: uuid.UUID, roles: tuple[VaAccessRoles, ...], project_id, site_id, org_unit_id
) -> list[sa.Select]:
    """The one source of supervisory reach: *user_id*'s grants of *roles*
    that cover the case named by *project_id*, *site_id* and *org_unit_id*.

    The three case identifiers are SQL expressions: ``VaDeathRegister``
    columns (the selects correlate with the outer row) or bound values for
    one case. Each select yields ``(grant_id, cadre_id, depth, role_rank)``.
    A unit grant reaches its unit's subtree (same ltree join as
    ``org_grant_service.scope_unit_ids``, on the case's unit and project);
    ``depth`` is its unit's depth, so the deepest unit is the narrowest. A
    ``data_manager`` project-site grant (depth 0) or project grant (depth -1)
    reaches that whole project-site or project, and a ``project_pi`` grant on
    a tree project (depth -1) its whole project. ``site_pi`` reaches only
    through a unit grant (the In-charge) and ranks with
    ``interview_supervisor`` at equal depth. Active grants, units, project
    sites and projects only (closed-project dormancy via
    ``active_project_condition``).
    """
    granted = aliased(MasOrgUnit, name="sup_granted_unit")
    covered = aliased(MasOrgUnit, name="sup_covered_unit")
    role_rank = sa.case(
        (VaUserAccessGrants.role.in_((VaAccessRoles.interview_supervisor, VaAccessRoles.site_pi)), 0),
        else_=1,
    )
    live = (
        VaUserAccessGrants.user_id == user_id,
        VaUserAccessGrants.grant_status == VaStatuses.active,
    )
    selects = [
        sa.select(
            VaUserAccessGrants.grant_id, VaUserAccessGrants.cadre_id,
            sa.func.nlevel(granted.path).label("depth"), role_rank.label("role_rank"),
        )
        .select_from(VaUserAccessGrants)
        .join(granted, granted.org_unit_id == VaUserAccessGrants.org_unit_id)
        .join(
            covered,
            sa.and_(
                covered.project_id == granted.project_id,
                sa.text("sup_covered_unit.path <@ sup_granted_unit.path"),
            ),
        )
        .where(
            *live,
            VaUserAccessGrants.role.in_(roles),
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
            granted.is_active.is_(True),
            covered.is_active.is_(True),
            active_project_condition(granted.project_id),
            covered.org_unit_id == org_unit_id,
            covered.project_id == project_id,
        )
    ]
    if VaAccessRoles.data_manager in roles:
        data_manager = (*live, VaUserAccessGrants.role == VaAccessRoles.data_manager)
        selects.append(
            sa.select(
                VaUserAccessGrants.grant_id, VaUserAccessGrants.cadre_id,
                sa.literal_column("0").label("depth"), role_rank.label("role_rank"),
            )
            .select_from(VaUserAccessGrants)
            .join(VaProjectSites, VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id)
            .where(
                *data_manager,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
                VaProjectSites.project_site_status == VaStatuses.active,
                active_project_condition(VaProjectSites.project_id),
                VaProjectSites.project_id == project_id,
                VaProjectSites.site_id == site_id,
            )
        )
        selects.append(
            sa.select(
                VaUserAccessGrants.grant_id, VaUserAccessGrants.cadre_id,
                sa.literal_column("-1").label("depth"), role_rank.label("role_rank"),
            )
            .where(
                *data_manager,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
                active_project_condition(VaUserAccessGrants.project_id),
                VaUserAccessGrants.project_id == project_id,
            )
        )
    if VaAccessRoles.project_pi in roles:
        selects.append(
            sa.select(
                VaUserAccessGrants.grant_id, VaUserAccessGrants.cadre_id,
                sa.literal_column("-1").label("depth"), role_rank.label("role_rank"),
            )
            .where(
                *live,
                VaUserAccessGrants.role == VaAccessRoles.project_pi,
                VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
                active_project_condition(VaUserAccessGrants.project_id),
                VaUserAccessGrants.project_id == project_id,
                sa.exists().where(
                    MasOrgLevel.project_id == VaUserAccessGrants.project_id,
                    MasOrgLevel.is_active.is_(True),
                ),
            )
        )
    return selects


def supervised_case_condition(user):
    """SQL condition on ``VaDeathRegister``: the cases *user* supervises."""
    if has_request_context() and g.get("bearer_auth"):
        # Native credentials do not carry the browser-only supervisor or
        # data-manager roles, even when the account also has collection work.
        return sa.false()
    return sa.or_(*(
        select.exists()
        for select in _covering_grants(
            user.user_id, _SUPERVISING_ROLES,
            VaDeathRegister.project_id, VaDeathRegister.site_id, VaDeathRegister.org_unit_id,
        )
    ))


def _grant_for(user_id: uuid.UUID, case, roles: tuple[VaAccessRoles, ...]):
    """The narrowest of *user_id*'s *roles* grants covering *case*, or None.

    *case* is anything with ``project_id``, ``site_id`` and ``org_unit_id``.
    Returns a row ``(grant_id, cadre_id)``. Narrowest: the unit grant at the
    deepest unit, then a project-site grant, then a project grant; at equal
    depth ``interview_supervisor`` or ``site_pi`` before ``data_manager`` or
    ``project_pi``, then the lowest grant id, so the choice is deterministic.
    """
    covering = sa.union_all(
        *_covering_grants(user_id, roles, case.project_id, case.site_id, case.org_unit_id)
    ).subquery()
    return db.session.execute(
        sa.select(covering.c.grant_id, covering.c.cadre_id)
        .order_by(covering.c.depth.desc(), covering.c.role_rank, covering.c.grant_id)
        .limit(1)
    ).first()


def supervising_grant(user_id: uuid.UUID, case):
    """The grant *user_id* supervises *case* through, as ``(grant_id,
    cadre_id)``, or None. What a supervisor action's audit row names
    (decision 15); ``can(SUPERVISE_INTAKE)`` allows exactly when it exists."""
    if has_request_context() and g.get("bearer_auth"):
        return None
    return _grant_for(user_id, case, _SUPERVISING_ROLES)


def dm_shaped_grant(user_id: uuid.UUID, case):
    """The narrowest data-manager shaped grant of *user_id* over *case*, or
    None: what confirming an already coded duplicate relies on (decisions
    10, 14). An In-charge and a project_pi on a tree project hold every
    data-manager power (access-control-model.md, "In-charge")."""
    if has_request_context() and g.get("bearer_auth"):
        return None
    return _grant_for(user_id, case, _DM_SHAPED_ROLES)
