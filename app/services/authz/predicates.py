"""scope_filter, can, require, effective_roles and reachable_unit_ids.

``scope_filter(user, action)`` is a SQL predicate on ``VaSubmissions``; a
list embeds it. ``can(user, action, va_sid)`` is ``EXISTS`` of the same
predicate for one submission, so a list can never offer what ``can``
refuses: there is no second implementation of the rules.

Predicate hygiene (load-bearing). The returned expression references
``VaSubmissions`` columns only. ``VaForms`` and ``MasOrgUnit`` are reached
through uncorrelated ``IN (SELECT ...)`` subqueries carrying
``.correlate(None)``. The reviewing dashboard joins ``VaForms`` itself and
the coder pool does not; a correlated ``EXISTS`` on ``VaForms`` silently
adds a cartesian product in one of them.
tests/authz/test_single_source.py runs the predicate both ways.
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
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaStatuses,
    VaSubmissions,
)
from app.services.authz.actions import (
    ADMIN_BYPASS,
    RULES,
    SUBMISSION_ACTIONS,
    Action,
    Lens,
    Reason,
)
from app.services.authz.grants import Grant, ResolvedGrants, resolve_grants

_R = VaAccessRoles
_P = VaAccessScopeTypes.project
_PS = VaAccessScopeTypes.project_site
_U = VaAccessScopeTypes.org_unit

_MESSAGES = {
    Reason.ALLOWED: "",
    Reason.NOT_FOUND: "Submission not found.",
    Reason.NO_ROLE: "You do not have access to view this submission.",
    Reason.PROJECT_CLOSED: "This project is closed.",
    Reason.OUT_OF_SCOPE: "This submission belongs to a unit outside your area.",
    Reason.VIEW_ONLY: "This submission belongs to a unit outside your coding scope.",
    Reason.UNROUTED: "This submission has not been routed to a unit yet.",
}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: Reason
    message: str  # operator-facing, the strings the routes flash today

    def __bool__(self) -> bool:
        return self.allowed


_ALLOWED = Decision(True, Reason.ALLOWED, "")


def _deny(reason: Reason) -> Decision:
    return Decision(False, reason, _MESSAGES[reason])


class AuthzError(Exception):
    """A refused ``require``: 404 when the target does not exist, else 403."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# ---------------------------------------------------------------------------
# Building blocks
# ---------------------------------------------------------------------------

def _subtree_select(unit_ids):
    """SELECT of every active unit in the subtree of *unit_ids*, unexecuted.

    Anchored on the already-resolved grant units (a handful of ids), joined
    to their descendants through the ltree path (GiST, ix_mas_org_unit_path),
    never materialised: a district subtree stays in Postgres.
    """
    granted = sa.orm.aliased(MasOrgUnit, name="authz_granted_unit")
    covered = sa.orm.aliased(MasOrgUnit, name="authz_covered_unit")
    return (
        sa.select(covered.org_unit_id)
        .select_from(granted)
        .join(covered, sa.and_(
            covered.project_id == granted.project_id,
            covered.path.op("<@", is_comparison=True)(granted.path),
        ))
        .where(granted.org_unit_id.in_(sorted(unit_ids)), covered.is_active.is_(True))
        .correlate(None)
    )


def _routed_into(unit_ids):
    return VaSubmissions.org_unit_id.in_(_subtree_select(unit_ids))


# The form's project has an active org level (a tree project; design 0.2).
_HAS_TREE = sa.exists(sa.select(1).where(
    MasOrgLevel.project_id == VaForms.project_id,
    MasOrgLevel.is_active.is_(True),
))


def _active_pair(project_id, site_id):
    """EXISTS an active ``va_project_sites`` row for (*project_id*, *site_id*).

    The active-pair rule of the data-manager and viewer lenses, for any
    surface whose rows carry the form's project and site (an analytics MV,
    say). Correlates to the enclosing query; one probe of
    ``uq_va_project_sites_project_site``.
    """
    return sa.exists(sa.select(1).where(
        VaProjectSites.project_id == project_id,
        VaProjectSites.site_id == site_id,
        VaProjectSites.project_site_status == VaStatuses.active,
    ))


def _form_ids(condition, *, active_form: bool, active_pair: bool):
    """SELECT of form ids matching *condition* (on VaForms), uncorrelated.

    *active_form*: the form is active (the form-resolved roles: coder,
    coding_tester, reviewer, site_pi; va_users._get_granted_va_forms).
    *active_pair*: the form's (project, site) is an active project-site
    (coder, data manager, viewer: their lists never reached a site moved
    out of the project).
    """
    stmt = sa.select(VaForms.form_id)
    if condition is not None:
        stmt = stmt.where(condition)
    if active_form:
        stmt = stmt.where(VaForms.form_status == VaStatuses.active)
    if active_pair:
        stmt = stmt.where(_active_pair(VaForms.project_id, VaForms.site_id))
    return stmt.correlate(None)


def _wide_form_condition(grants):
    """VaForms condition for the project and pair grants among *grants*, or None."""
    projects = sorted({g.project_id for g in grants if g.scope_type == _P})
    pairs = sorted({(g.project_id, g.site_id) for g in grants if g.scope_type == _PS})
    clauses = []
    if projects:
        clauses.append(VaForms.project_id.in_(projects))
    if pairs:
        clauses.append(sa.tuple_(VaForms.project_id, VaForms.site_id).in_(pairs))
    return sa.or_(*clauses) if clauses else None


def _forms_in(grants, *, active_form: bool, active_pair: bool):
    """VaSubmissions predicate: the form is under a project/pair grant of *grants*."""
    condition = _wide_form_condition(grants)
    if condition is None:
        return None
    return VaSubmissions.va_form_id.in_(
        _form_ids(condition, active_form=active_form, active_pair=active_pair)
    )


def _group_predicate(grants, *, active_form: bool, active_pair: bool):
    """Wide grants through their forms (routed or not), unit grants through
    the routed unit; an unrouted submission is reached by wide grants only."""
    clauses = []
    wide = _forms_in(grants, active_form=active_form, active_pair=active_pair)
    if wide is not None:
        clauses.append(wide)
    units = {g.org_unit_id for g in grants if g.scope_type == _U}
    if units:
        routed = _routed_into(units)
        if active_form or active_pair:
            routed = sa.and_(routed, VaSubmissions.va_form_id.in_(
                _form_ids(None, active_form=active_form, active_pair=active_pair)
            ))
        clauses.append(routed)
    return clauses


# ---------------------------------------------------------------------------
# Lenses
# ---------------------------------------------------------------------------

def _lens_groups(g: ResolvedGrants, lens: Lens, *, coding: bool = True):
    """[(grants, active_form, active_pair)] a lens counts.

    *coding* applies the coding scope rule (``ResolvedGrants.codes``) where
    the lens has it; ``coding=False`` gives the grants before that rule
    (denial reasons only).
    """
    def coded(grants):
        return [x for x in grants if not coding or g.codes(x)]

    virtual_coders = list(g.of((_R.coder, _R.coding_tester), virtual=True))
    if lens is Lens.CODE_CODER:
        return [
            (coded(g.of((_R.coder,), virtual=False)), True, True),
            # coding_tester is exempt from the coding scope level; the
            # demo-training virtual grants carry no active-site rule.
            (list(g.of((_R.coding_tester,), virtual=False)) + virtual_coders, True, False),
        ]
    if lens is Lens.CODE_REVIEWER:
        # Demo-training grants are exempt from the coding scope level, as
        # for coders: demo practice never depends on a project's tree.
        return [(
            coded(g.of((_R.reviewer,), virtual=False))
            + list(g.of((_R.reviewer,), virtual=True)),
            True,
            False,
        )]
    if lens is Lens.VIEW_CODER:
        return [
            (list(g.of((_R.coder,), virtual=False)), True, True),
            (list(g.of((_R.coding_tester,), virtual=False)) + virtual_coders, True, False),
        ]
    if lens is Lens.VIEW_REVIEWER:
        return [(list(g.of((_R.reviewer,))), True, False)]
    # Data-manager and viewer reach stops at a deactivated (project, site)
    # pair, as their grid, exports and KPI cards always have
    # (_expand_project_ids_to_active_pairs): a site moved to another
    # project leaves its old forms behind.
    if lens is Lens.DM:
        return [(list(g.dm_grants()), False, True)]
    if lens is Lens.VIEWER:
        return [(list(g.of((_R.collaborator, _R.collaborator_pii))), False, True)]
    if lens is Lens.SITE_PI_PAIR:
        return [(list(g.of((_R.site_pi,), scope_types=(_PS,))), True, False)]
    if lens is Lens.PROJECT_PI_SITE:
        return [(
            [x for x in g.of((_R.project_pi,)) if not g.has_tree(x.project_id)],
            False,
            False,
        )]
    if lens is Lens.DM_DIRECT:
        # A form spans units, so a unit grant never covers a whole form.
        return [([x for x in g.dm_grants() if x.is_wide], False, True)]
    if lens is Lens.DM_PROJECT_UNROUTED:
        return [(list(g.dm_grants()), False, False)]
    raise ValueError(f"unknown lens {lens!r}")


def _lens_predicate(g: ResolvedGrants, lens: Lens):
    if lens is Lens.DM_PROJECT_UNROUTED:
        projects = sorted(g.dm_projects())
        if not projects:
            return []
        return [sa.and_(
            VaSubmissions.org_unit_id.is_(None),
            VaSubmissions.va_form_id.in_(
                _form_ids(VaForms.project_id.in_(projects), active_form=False, active_pair=True)
            ),
        )]
    clauses = []
    for grants, active_form, active_pair in _lens_groups(g, lens):
        if grants:
            clauses.extend(_group_predicate(grants, active_form=active_form, active_pair=active_pair))
    return clauses


def reaches(user, lens: Lens, va_sid, *, _grants: ResolvedGrants | None = None) -> bool:
    """Whether *va_sid* lies in the reach of one lens of *user*'s grants.

    For a rendering that must belong to one role (the reviewer view): VIEW
    answers whether the user may see the case at all, this whether they see
    it as that role. A role flag such as ``VaUsers.is_reviewer()`` is not
    enough, because the demo-training grants make it true for everyone.
    """
    g = _grants if _grants is not None else resolve_grants(user)
    clauses = _lens_predicate(g, lens)
    if not clauses:
        return False
    return bool(db.session.scalar(sa.select(sa.exists().where(
        VaSubmissions.va_sid == va_sid, sa.or_(*clauses),
    ))))


def reachable_unit_ids(
    user, project_id: str, roles, *, _grants: ResolvedGrants | None = None
) -> set[uuid.UUID] | None:
    """Unit ids of *project_id* that *user*'s grants in *roles* reach, for
    browsing the tree (the organization API's unit picker, the device unit
    list, the area dashboard).

    ``None`` means the whole tree: an admin, a project_pi of the project, or
    a project or pair grant in *roles* there. Otherwise the subtrees of the
    user's unit grants in *roles* on this project; an empty set reaches
    nothing. Demo-training grants never count: they open coding practice,
    not a project's tree. Web intake keeps its own grant-only variant with
    no admin bypass (``web_intake_service._reachable_unit_ids``).
    """
    g = _grants if _grants is not None else resolve_grants(user)
    if g.is_admin:
        return None
    roles = frozenset(roles)
    for grant in g.grants:
        if grant.virtual or grant.project_id != project_id:
            continue
        if grant.role == _R.project_pi or (grant.role in roles and grant.is_wide):
            return None
    units = {
        grant.org_unit_id
        for grant in g.of(roles, scope_types=(_U,), virtual=False)
        if grant.project_id == project_id
    }
    if not units:
        return set()
    return set(db.session.scalars(_subtree_select(units)))


def scope_filter(user, action: Action, *, _grants: ResolvedGrants | None = None):
    """SQL predicate on ``VaSubmissions``: the submissions *user* may *action*.

    ``sa.true()`` for an admin on a bypassed action, ``sa.false()`` when no
    lens applies. ``_grants`` is a test seam: a hand-built ``ResolvedGrants``.
    """
    if action not in RULES:
        raise ValueError(f"{action!r} has no submission predicate")
    g = _grants if _grants is not None else resolve_grants(user)
    if g.is_admin and action is Action.LIST_UNROUTED:
        # The queue is the unrouted cases of tree projects only, admin
        # included: the bypass lifts the project limit, never the queue's
        # own shape. A site project's case is unrouted by construction and
        # has nowhere to be routed to.
        return sa.and_(
            VaSubmissions.org_unit_id.is_(None),
            VaSubmissions.va_form_id.in_(
                _form_ids(_HAS_TREE, active_form=False, active_pair=False)
            ),
        )
    if g.is_admin and action in ADMIN_BYPASS:
        return sa.true()
    clauses = [c for lens in RULES[action] for c in _lens_predicate(g, lens)]
    return sa.or_(*clauses) if clauses else sa.false()


# ---------------------------------------------------------------------------
# can / require
# ---------------------------------------------------------------------------

def can(user, action: Action, target, *, _grants: ResolvedGrants | None = None) -> Decision:
    """May *user* perform *action* on *target*?

    Targets: a ``va_sid`` for the submission actions (``ROUTE_PIN`` also
    takes ``("unit", org_unit_id)``, the pin target); a ``form_id`` for
    ``SYNC_FORM``; a ``project_id`` for ``LIST_UNROUTED``;
    ``("pair", project_id, site_id)`` or ``("unit", org_unit_id)`` for
    ``SITE_PI_REPORT``; a ``VaDeathRegister`` row for ``SUPERVISE_INTAKE``.
    ``LIST_DATA`` has no target: use ``scope_filter``.
    """
    g = _grants if _grants is not None else resolve_grants(user)
    if action is Action.ROUTE_PIN and isinstance(target, tuple):
        return _can_pin_to(g, target)
    if action in SUBMISSION_ACTIONS:
        return _can_submission(user, g, action, target)
    if action is Action.SYNC_FORM:
        return _can_sync_form(g, target)
    if action is Action.LIST_UNROUTED:
        return _can_list_unrouted(g, target)
    if action is Action.SITE_PI_REPORT:
        return _can_site_pi_report(g, target)
    if action is Action.SUPERVISE_INTAKE:
        return _can_supervise(g, target)
    raise ValueError(f"{action!r} has no single target; use scope_filter")


def require(user, action: Action, target, *, _grants: ResolvedGrants | None = None) -> None:
    """``can``, raising ``AuthzError`` (404 for a missing target, else 403)."""
    decision = can(user, action, target, _grants=_grants)
    if not decision:
        raise AuthzError(404 if decision.reason is Reason.NOT_FOUND else 403, decision.message)


def _can_submission(user, g: ResolvedGrants, action: Action, va_sid) -> Decision:
    predicate = scope_filter(user, action, _grants=g)
    if db.session.scalar(sa.select(sa.exists().where(VaSubmissions.va_sid == va_sid, predicate))):
        return _ALLOWED
    row = db.session.execute(
        sa.select(
            VaForms.project_id,
            VaForms.site_id,
            VaSubmissions.org_unit_id,
            sa.cast(MasOrgUnit.path, sa.Text).label("unit_path"),
            VaProjectMaster.project_status,
        )
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(VaProjectMaster, VaProjectMaster.project_id == VaForms.project_id)
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == VaSubmissions.org_unit_id)
        .where(VaSubmissions.va_sid == va_sid)
    ).first()
    if row is None:
        return _deny(Reason.NOT_FOUND)
    return _deny(_submission_reason(g, action, row))


def _reaches(grant: Grant, row) -> bool:
    if grant.project_id != row.project_id:
        return False
    if grant.scope_type == _P:
        return True
    if grant.scope_type == _PS:
        return grant.site_id == row.site_id
    return grant.covers_unit(row.project_id, row.unit_path)


def _submission_reason(g: ResolvedGrants, action: Action, row) -> Reason:
    """Why a submission action was refused. Changes only the message; the
    decision itself is always the predicate's."""
    relevant = [
        grant
        for lens in RULES[action]
        for grants, _, _ in _lens_groups(g, lens, coding=False)
        for grant in grants
        if not grant.virtual
    ]
    if not relevant:
        return Reason.NO_ROLE
    if row.project_status != VaStatuses.active:
        return Reason.PROJECT_CLOSED
    reachers = [grant for grant in relevant if _reaches(grant, row)]
    if action in (Action.CODE, Action.RECODE, Action.REVIEW):
        if any(not g.codes(grant) for grant in reachers):
            return Reason.VIEW_ONLY
    if row.org_unit_id is None and not reachers and any(
        grant.scope_type == _U and grant.project_id == row.project_id for grant in relevant
    ):
        return Reason.UNROUTED
    return Reason.OUT_OF_SCOPE


def _can_sync_form(g: ResolvedGrants, form_id) -> Decision:
    if g.is_admin:
        condition = sa.true()
    else:
        condition = _wide_form_condition(_lens_groups(g, Lens.DM_DIRECT)[0][0])
    if condition is not None and db.session.scalar(sa.select(sa.exists().where(
        VaForms.form_id == form_id, condition,
        VaForms.form_id.in_(_form_ids(None, active_form=False, active_pair=True)),
    ))):
        return _ALLOWED
    if db.session.get(VaForms, form_id) is None:
        return _deny(Reason.NOT_FOUND)
    if not any(g.dm_grants()):
        return _deny(Reason.NO_ROLE)
    return _deny(Reason.OUT_OF_SCOPE)


def _can_list_unrouted(g: ResolvedGrants, project_id) -> Decision:
    if project_id in g.dm_projects():
        return _ALLOWED
    if g.is_admin:
        # Admin's queue is tree projects only, as in scope_filter.
        if db.session.scalar(sa.select(sa.exists().where(
            MasOrgLevel.project_id == project_id, MasOrgLevel.is_active.is_(True),
        ))):
            return _ALLOWED
        return _deny(Reason.OUT_OF_SCOPE)
    return _deny(Reason.NO_ROLE if not g.dm_grants() else Reason.OUT_OF_SCOPE)


def _unit_row(org_unit_id):
    try:
        org_unit_id = uuid.UUID(str(org_unit_id))
    except (TypeError, ValueError):
        return None
    return db.session.execute(
        sa.select(MasOrgUnit.project_id, sa.cast(MasOrgUnit.path, sa.Text).label("path"))
        .where(MasOrgUnit.org_unit_id == org_unit_id, MasOrgUnit.is_active.is_(True))
    ).first()


def _can_pin_to(g: ResolvedGrants, target) -> Decision:
    """The pin's target unit: a wide DM-shaped grant on the unit's project
    reaches any unit of it; a unit DM or In-charge only its own subtree."""
    kind, org_unit_id = target
    if kind != "unit":
        raise ValueError(f"unknown pin target {target!r}")
    unit = _unit_row(org_unit_id)
    if unit is None:
        return _deny(Reason.NOT_FOUND)
    if g.is_admin:
        return _ALLOWED
    for grant in g.dm_grants():
        if grant.is_wide and grant.project_id == unit.project_id:
            return _ALLOWED
        if grant.covers_unit(unit.project_id, unit.path):
            return _ALLOWED
    return _deny(Reason.NO_ROLE if not g.dm_grants() else Reason.OUT_OF_SCOPE)


def _can_site_pi_report(g: ResolvedGrants, target) -> Decision:
    """site_pi on the pair, or at a unit whose subtree holds the target unit;
    project_pi on the target's project (access-control-model.md:72)."""
    pi_projects = {x.project_id for x in g.of((_R.project_pi,))}
    holders = list(g.of((_R.site_pi, _R.project_pi)))
    if target[0] == "pair":
        _, project_id, site_id = target
        if g.is_admin or project_id in pi_projects or any(
            x.project_id == project_id and x.site_id == site_id
            for x in g.of((_R.site_pi,), scope_types=(_PS,))
        ):
            return _ALLOWED
        return _deny(Reason.NO_ROLE if not holders else Reason.OUT_OF_SCOPE)
    if target[0] == "unit":
        unit = _unit_row(target[1])
        if unit is None:
            return _deny(Reason.NOT_FOUND)
        if g.is_admin or unit.project_id in pi_projects or any(
            x.covers_unit(unit.project_id, unit.path)
            for x in g.of((_R.site_pi,), scope_types=(_U,))
        ):
            return _ALLOWED
        return _deny(Reason.NO_ROLE if not holders else Reason.OUT_OF_SCOPE)
    raise ValueError(f"unknown site PI report target {target!r}")


def _can_supervise(g: ResolvedGrants, case) -> Decision:
    """interview_supervisor, data_manager or In-charge at a unit whose
    subtree holds the case; data_manager on its pair or project; project_pi
    on a tree project. No admin bypass (case_transition_service)."""
    unit_holders = list(g.of(
        (_R.interview_supervisor, _R.data_manager, _R.site_pi), scope_types=(_U,)
    ))
    wide_dm = list(g.of((_R.data_manager,), scope_types=(_P, _PS)))
    tree_pi = [x for x in g.of((_R.project_pi,)) if g.has_tree(x.project_id)]
    if not (unit_holders or wide_dm or tree_pi):
        return _deny(Reason.NO_ROLE)
    project_id, site_id = case.project_id, case.site_id
    if any(x.project_id == project_id for x in tree_pi):
        return _ALLOWED
    for x in wide_dm:
        if x.project_id == project_id and (x.scope_type == _P or x.site_id == site_id):
            return _ALLOWED
    if case.org_unit_id is not None and unit_holders:
        unit = _unit_row(case.org_unit_id)
        if unit is not None and any(x.covers_unit(project_id, unit.path) for x in unit_holders):
            return _ALLOWED
    return _deny(Reason.OUT_OF_SCOPE)


# ---------------------------------------------------------------------------
# Effective roles
# ---------------------------------------------------------------------------

def effective_roles(user, *, _grants: ResolvedGrants | None = None) -> frozenset[str]:
    """The ``role_required._ROLE_METHODS`` keys whose gate *user* opens.

    The single place that says: ``site_pi`` at a unit (the In-charge) and
    ``project_pi`` on a tree project count as ``data_manager`` and
    ``interview_supervisor``; an active demo-training project counts as
    every role in ``DEMO_VIRTUAL_ROLES``. ``mentor_institute_admin`` is a
    membership flag, not a grant, and is not answered here.
    """
    g = _grants if _grants is not None else resolve_grants(user)
    roles = {grant.role.value for grant in g.grants}
    if g.is_admin:
        roles.add(_R.admin.value)
    oversees = any(
        (x.role == _R.site_pi and x.scope_type == _U)
        or (x.role == _R.project_pi and g.has_tree(x.project_id))
        for x in g.grants
    )
    if oversees:
        roles |= {_R.data_manager.value, _R.interview_supervisor.value}
    if roles & {_R.collaborator.value, _R.collaborator_pii.value}:
        roles |= {_R.collaborator.value, _R.collaborator_pii.value}
    return frozenset(roles)
