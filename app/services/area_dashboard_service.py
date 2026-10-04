"""Area dashboard: collection and coding counts for the part of a project a
user holds a grant for.

Scope is viewing scope, never coding scope, resolved per project as a union
over all of the user's roles:

* a tree project: ``authz.reachable_unit_ids`` -- the whole tree
  for an admin, the project's PI, or any project- or site-scoped grant;
  otherwise the subtrees of the user's unit grants;
* a project with no tree (sites mode): every active site for an admin, PI or
  project-scoped grant, else the user's granted sites.

Counts only: no case lists and no subject data. Staff names appear only in
the optional per-staff view (``area_staff``), and only for a viewer
``should_redact_pii`` lets see staff identity. Each level is one query per
section (units, snapshot counts, live drafts), with subtree rollups on ltree
containment. A unit or site outside scope is reported as
not found, never as forbidden, so its existence does not leak.

Policy: docs/policy/area-dashboard.md.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import (
    MapCaseContactAttempt,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflowEvent,
    VaSyncRun,
    VaUserAccessGrants,
    VaUsers,
    VaWebIntakeDraft,
)
from app.services import authz, org_grant_service
from app.services.duplicate_exclusion import (
    DUPLICATE_CASE_STATUS,
    not_confirmed_duplicate_condition,
)
from app.services.odk_retirement_service import submission_is_in_odk
from app.services.sitepi_reporting_service import get_project_workflow_kpis
from app.services.submission_analytics_mv import (
    AREA_BREAKDOWN_KEYS,
    get_area_site_stats_from_mv,
    get_area_unrouted_stats_from_mv,
    get_dm_org_unit_stats_from_mv,
)
from app.services.viewer_pii_service import should_redact_pii
from app.services.workflow.definition import (
    TRANSITION_CODER_FINALIZED,
    TRANSITION_CODER_NOT_CODEABLE,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
)

DRAFT_STATUS_IN_PROGRESS = "draft"
UNROUTED_KEY = "unrouted"


class AreaNotFound(Exception):
    """The project, unit or site is not in this user's area (or does not exist)."""


@dataclass(frozen=True)
class AreaScope:
    project_id: str
    project_name: str
    has_tree: bool
    # Tree projects: None = the whole tree, else the covered unit ids.
    unit_ids: frozenset | None = None
    # Sites-mode projects: None = every active site, else the granted sites.
    site_ids: frozenset | None = None

    @property
    def project_wide(self) -> bool:
        if self.has_tree:
            return self.unit_ids is None
        return self.site_ids is None


# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------


def _granted_project_rows(user):
    """Subquery of (project_id, role) for each active non-global grant of *user*.

    Unit grants carry no project_id, so the project comes from the grant, its
    project-site or its unit, whichever the scope has.
    """
    grant_project = sa.func.coalesce(
        VaUserAccessGrants.project_id, VaProjectSites.project_id, MasOrgUnit.project_id
    )
    return (
        sa.select(grant_project.label("project_id"), VaUserAccessGrants.role)
        .select_from(VaUserAccessGrants)
        .outerjoin(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        )
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id)
        .where(
            VaUserAccessGrants.user_id == user.user_id,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaUserAccessGrants.scope_type != VaAccessScopeTypes.global_scope,
        )
        .subquery()
    )


def candidate_projects(user) -> list[tuple[str, str]]:
    """(project_id, project_name) of every active project the user holds any grant on.

    One query. Admins get every active project.
    """
    active = VaProjectMaster.project_status == VaStatuses.active
    if user.is_admin():
        stmt = sa.select(VaProjectMaster.project_id, VaProjectMaster.project_name).where(active)
    else:
        granted = _granted_project_rows(user)
        stmt = sa.select(VaProjectMaster.project_id, VaProjectMaster.project_name).where(
            active, VaProjectMaster.project_id.in_(sa.select(granted.c.project_id))
        )
    return [tuple(row) for row in db.session.execute(stmt.order_by(VaProjectMaster.project_id))]


def _project_roles(user, project_id: str) -> set[VaAccessRoles]:
    """Roles the user holds on *project_id* through any active grant, in one query."""
    granted = _granted_project_rows(user)
    return set(
        db.session.scalars(
            sa.select(granted.c.role).where(granted.c.project_id == project_id).distinct()
        )
    )


def _sites_mode_site_ids(user, project_id: str) -> frozenset | None:
    """Sites a no-tree project shows this user: None = all, empty = none.

    One query over the user's project- and project-site-scoped grants on the
    project, any role. Inactive grants, inactive project-sites and closed
    projects never count, as in every other grant resolver.
    """
    if user.is_admin() or user.can_manage_project(project_id):
        return None
    rows = db.session.execute(
        sa.select(VaUserAccessGrants.scope_type, VaProjectSites.site_id)
        .select_from(VaUserAccessGrants)
        .outerjoin(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        )
        .where(
            VaUserAccessGrants.user_id == user.user_id,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            org_grant_service.active_project_condition(project_id),
            sa.or_(
                sa.and_(
                    VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
                    VaUserAccessGrants.project_id == project_id,
                ),
                sa.and_(
                    VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
                    VaProjectSites.project_id == project_id,
                    VaProjectSites.project_site_status == VaStatuses.active,
                ),
            ),
        )
    ).all()
    if any(row.scope_type == VaAccessScopeTypes.project for row in rows):
        return None
    return frozenset(row.site_id for row in rows)


def resolve_area_scope(user, project_id: str, project_name: str | None = None) -> AreaScope | None:
    """The user's area in *project_id*, or None when they have none there.

    A project is a tree project when it has an active organization level
    (``projects_with_org_tree``), the same test the coding scope enforcement
    and the data manager's unit rollup use.

    No grant of any role (``authz.effective_roles`` empty) is no area
    anywhere, decided before the project is even looked up.
    """
    if not authz.effective_roles(user):
        return None
    if project_name is None:
        project_name = db.session.scalar(
            sa.select(VaProjectMaster.project_name).where(
                VaProjectMaster.project_id == project_id,
                VaProjectMaster.project_status == VaStatuses.active,
            )
        )
        if project_name is None:
            return None

    if project_id in org_grant_service.projects_with_org_tree({project_id}):
        reachable = authz.reachable_unit_ids(
            user, project_id, org_grant_service.ROLES_ALLOWING_ORG_UNIT
        )
        if reachable is not None and not reachable:
            return None
        return AreaScope(
            project_id=project_id,
            project_name=project_name,
            has_tree=True,
            unit_ids=None if reachable is None else frozenset(reachable),
        )

    site_ids = _sites_mode_site_ids(user, project_id)
    if site_ids is not None and not site_ids:
        return None
    return AreaScope(
        project_id=project_id, project_name=project_name, has_tree=False, site_ids=site_ids
    )


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------


def _unit_rows(where) -> list:
    """Active units matching *where*, each with whether it has active children."""
    child = sa.orm.aliased(MasOrgUnit, name="child_unit")
    has_children = sa.exists(
        sa.select(1).where(
            child.parent_org_unit_id == MasOrgUnit.org_unit_id, child.is_active.is_(True)
        )
    ).label("has_children")
    return db.session.execute(
        sa.select(
            MasOrgUnit.org_unit_id,
            MasOrgUnit.parent_org_unit_id,
            MasOrgUnit.unit_code,
            MasOrgUnit.unit_name,
            has_children,
        )
        .where(MasOrgUnit.is_active.is_(True), *where)
        .order_by(MasOrgUnit.unit_code)
    ).all()


def grant_root_units(scope: AreaScope) -> list:
    """The top units a user may open in a tree project.

    Project-wide: the project's top-level units (a parentless unit, placed or
    not). Otherwise the covered units whose parent is not itself covered, so
    a district grant plus a PHC grant inside it yields one root.
    """
    if scope.unit_ids is None:
        return _unit_rows(
            [
                MasOrgUnit.project_id == scope.project_id,
                MasOrgUnit.parent_org_unit_id.is_(None),
            ]
        )
    covered = _unit_rows([MasOrgUnit.org_unit_id.in_(sorted(scope.unit_ids))])
    return [row for row in covered if row.parent_org_unit_id not in scope.unit_ids]


def _parse_unit_id(raw) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except (TypeError, ValueError, AttributeError):
        raise AreaNotFound() from None


def _selected_unit(scope: AreaScope, raw_unit_id) -> MasOrgUnit:
    """The requested unit, only if it is an active unit inside the user's area."""
    unit_id = _parse_unit_id(raw_unit_id)
    if scope.unit_ids is not None and unit_id not in scope.unit_ids:
        raise AreaNotFound()
    unit = db.session.get(MasOrgUnit, unit_id)
    if unit is None or unit.project_id != scope.project_id or not unit.is_active:
        raise AreaNotFound()
    return unit


def _breadcrumb(scope: AreaScope, unit: MasOrgUnit) -> list[dict]:
    """In-scope ancestors of *unit*, top down, ending with the unit itself."""
    where = [
        MasOrgUnit.project_id == scope.project_id,
        MasOrgUnit.path.op("@>")(unit.path),
    ]
    if scope.unit_ids is not None:
        where.append(MasOrgUnit.org_unit_id.in_(sorted(scope.unit_ids)))
    rows = db.session.execute(
        sa.select(MasOrgUnit.org_unit_id, MasOrgUnit.unit_code, MasOrgUnit.unit_name)
        .where(*where)
        .order_by(sa.func.nlevel(MasOrgUnit.path))
    ).all()
    return [
        {"org_unit_id": str(row.org_unit_id), "code": row.unit_code, "name": row.unit_name}
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------


def _open_drafts(project_id: str):
    return sa.and_(
        VaWebIntakeDraft.project_id == project_id,
        VaWebIntakeDraft.status == DRAFT_STATUS_IN_PROGRESS,
    )


def _drafts_by_unit(project_id: str, unit_ids: list) -> dict:
    """Open web-intake drafts in each unit's subtree, live, in one query."""
    if not unit_ids:
        return {}
    draft_unit = sa.orm.aliased(MasOrgUnit, name="draft_unit")
    rows = db.session.execute(
        sa.select(MasOrgUnit.org_unit_id, sa.func.count(VaWebIntakeDraft.draft_id))
        .select_from(MasOrgUnit)
        .join(draft_unit, draft_unit.path.op("<@")(MasOrgUnit.path))
        .join(VaWebIntakeDraft, VaWebIntakeDraft.org_unit_id == draft_unit.org_unit_id)
        .where(
            MasOrgUnit.org_unit_id.in_(sorted(unit_ids)),
            draft_unit.project_id == project_id,
            _open_drafts(project_id),
        )
        .group_by(MasOrgUnit.org_unit_id)
    ).all()
    return dict(rows)


def _unrouted_drafts(project_id: str) -> int:
    return db.session.scalar(
        sa.select(sa.func.count(VaWebIntakeDraft.draft_id)).where(
            _open_drafts(project_id), VaWebIntakeDraft.org_unit_id.is_(None)
        )
    ) or 0


def _drafts_by_site(project_id: str, site_ids: list) -> dict:
    rows = db.session.execute(
        sa.select(VaWebIntakeDraft.site_id, sa.func.count(VaWebIntakeDraft.draft_id))
        .where(_open_drafts(project_id), VaWebIntakeDraft.site_id.in_(sorted(site_ids)))
        .group_by(VaWebIntakeDraft.site_id)
    ).all()
    return dict(rows)


def _counts(stats: dict | None, drafts: int) -> dict:
    stats = stats or {}
    counts = {"total_submissions": stats.get("total_submissions", 0)}
    counts.update({key: stats.get(key, 0) for key in AREA_BREAKDOWN_KEYS})
    counts["drafts_in_progress"] = drafts
    return counts


def _unit_summary_rows(scope: AreaScope, units: list) -> list[dict]:
    unit_ids = [row.org_unit_id for row in units]
    stats = {}
    if unit_ids:
        stats = {
            row["org_unit_id"]: row
            for row in get_dm_org_unit_stats_from_mv(
                project_id=scope.project_id,
                project_ids=[scope.project_id],
                project_site_pairs=[],
                unit_ids=unit_ids,
                include_breakdown=True,
            )
        }
    drafts = _drafts_by_unit(scope.project_id, unit_ids)
    return [
        {
            "kind": "unit",
            "key": str(row.org_unit_id),
            "code": row.unit_code,
            "name": row.unit_name,
            "has_children": bool(row.has_children),
            "counts": _counts(stats.get(str(row.org_unit_id)), drafts.get(row.org_unit_id, 0)),
        }
        for row in units
    ]


def _unrouted_row(scope: AreaScope) -> dict:
    return {
        "kind": UNROUTED_KEY,
        "key": UNROUTED_KEY,
        "code": None,
        "name": "Unrouted",
        "has_children": False,
        "counts": _counts(
            get_area_unrouted_stats_from_mv(project_id=scope.project_id),
            _unrouted_drafts(scope.project_id),
        ),
    }


def _site_rows(scope: AreaScope, site_id: str | None, dm_links: bool) -> list[dict]:
    """Per-site rows for a sites-mode project: every in-scope active site.

    With *dm_links*, each row's submitted count links to the data manager
    dashboard filtered to that project and site.
    """
    where = [
        VaProjectSites.project_id == scope.project_id,
        VaProjectSites.project_site_status == VaStatuses.active,
    ]
    if scope.site_ids is not None:
        where.append(VaProjectSites.site_id.in_(sorted(scope.site_ids)))
    if site_id:
        where.append(VaProjectSites.site_id == site_id)
    sites = db.session.execute(
        sa.select(VaProjectSites.site_id, VaSiteMaster.site_name)
        .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
        .where(*where)
        .order_by(VaProjectSites.site_id)
    ).all()
    if site_id and not sites:
        raise AreaNotFound()
    if not sites:
        return []

    site_ids = [row.site_id for row in sites]
    stats = {
        row["site_id"]: row
        for row in get_area_site_stats_from_mv(
            project_ids=[],
            project_site_pairs=[(scope.project_id, s) for s in site_ids],
        )
    }
    drafts = _drafts_by_site(scope.project_id, site_ids)
    return [
        {
            "kind": "site",
            "key": row.site_id,
            "code": row.site_id,
            "name": row.site_name,
            "has_children": False,
            "counts": _counts(stats.get(row.site_id), drafts.get(row.site_id, 0)),
            "links": (
                {"total_submissions": _dm_link(project=scope.project_id, site=row.site_id)}
                if dm_links
                else {}
            ),
        }
        for row in sites
    ]


# ---------------------------------------------------------------------------
# Project card and links
# ---------------------------------------------------------------------------

SCREEN_DATA_MANAGEMENT = "data_management.dashboard"
SCREEN_CODING = "coding.dashboard"
SCREEN_INTAKE = "intake.dashboard"

# Every filter the data manager page reads from its URL
# (loadStateFromUrl in app/static/js/data_manager_dashboard.js). A link sends
# them all, blank unless set, because the page overlays URL values on the
# filters it saved in the browser; a stale saved filter would otherwise make
# the landing count disagree with the count that was clicked.
DM_URL_FILTERS = (
    "search", "project", "site", "date_from", "date_to", "odk_status",
    "smartva", "age_group", "gender", "odk_sync", "workflow",
)

# Card counts that equal one data manager workflow filter exactly. The DM
# groups (pending_coding, coded) do not match the card's pending or coded
# definitions, so those counts get no data manager link.
_DM_WORKFLOW_FILTERS = {
    "reviewer_eligible": WORKFLOW_REVIEWER_ELIGIBLE,
    "reviewer_finalized": WORKFLOW_REVIEWER_FINALIZED,
    "upstream_changed": WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
}


def _dm_link(**filters) -> dict:
    return {
        "endpoint": SCREEN_DATA_MANAGEMENT,
        "params": {key: filters.get(key, "") for key in DM_URL_FILTERS},
    }


def link_screens(user, project_id: str) -> set[str]:
    """Screens a count on *project_id* may link to for this user.

    A screen is offered only when the user holds the role that does that
    work on this project, and passes the target route's own role gate, so a
    link never leads to a 403: data managers (and admin) the data manager
    dashboard, coders the coding dashboard, interviewers web intake. The
    target screens still enforce their own scope on every request.
    """
    roles = _project_roles(user, project_id)
    screens = set()
    if user.is_admin() or (VaAccessRoles.data_manager in roles and user.is_data_manager()):
        screens.add(SCREEN_DATA_MANAGEMENT)
    if VaAccessRoles.coder in roles and user.is_coder():
        screens.add(SCREEN_CODING)
    if VaAccessRoles.interviewer in roles and user.is_interviewer():
        screens.add(SCREEN_INTAKE)
    return screens


def project_card(scope: AreaScope, screens: set[str]) -> dict:
    """The project-wide operational card: the Site PI KPIs over the whole project.

    Counts only. The coder names and per-submission rows the Site PI page
    also shows never reach it. ``links`` maps a count key to
    ``{"endpoint", "params"}`` for the caller to turn into a URL.
    """
    kpis = get_project_workflow_kpis(scope.project_id)
    links = {}
    if SCREEN_DATA_MANAGEMENT in screens:
        links["total_submissions"] = _dm_link(project=scope.project_id)
        for key, state in _DM_WORKFLOW_FILTERS.items():
            links[key] = _dm_link(project=scope.project_id, workflow=state)
    elif SCREEN_INTAKE in screens:
        links["total_submissions"] = {"endpoint": SCREEN_INTAKE, "params": {}}
    if SCREEN_CODING in screens:
        links["pending_or_active"] = {"endpoint": SCREEN_CODING, "params": {}}
    return {
        "total_submissions": kpis["total_submissions"],
        "total_coded": kpis["total_coded"],
        "total_not_codeable": kpis["total_not_codeable"],
        "current_state_kpis": kpis["current_state_kpis"],
        "authority_kpis": kpis["authority_kpis"],
        "links": links,
    }


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def snapshot_refreshed_at():
    """When the scheduled analytics snapshot refresh last succeeded, or None.

    Only the hourly beat task records a run; an ad-hoc refresh from the data
    manager or analytics screens does not, so this is a lower bound on
    freshness.
    """
    from app.tasks.sync_tasks import ANALYTICS_MV_TRIGGER

    return db.session.scalar(
        sa.select(VaSyncRun.finished_at)
        .where(VaSyncRun.triggered_by == ANALYTICS_MV_TRIGGER, VaSyncRun.status == "success")
        .order_by(VaSyncRun.started_at.desc())
        .limit(1)
    )


def area_projects(user) -> list[dict]:
    """Projects the user has an area in, each with the roots they may open.

    ponytail: resolves scope per project (a few queries each); bounded by the
    user's own project count, not by data. Batch the resolvers if users come
    to hold grants on many projects.
    """
    projects = []
    if not authz.effective_roles(user):
        return projects
    for project_id, project_name in candidate_projects(user):
        scope = resolve_area_scope(user, project_id, project_name)
        if scope is None:
            continue
        if scope.has_tree:
            roots = [
                {"key": str(row.org_unit_id), "code": row.unit_code, "name": row.unit_name}
                for row in grant_root_units(scope)
            ]
        else:
            roots = []
        projects.append(
            {
                "project_id": project_id,
                "project_name": project_name,
                "mode": "organization" if scope.has_tree else "sites",
                "project_wide": scope.project_wide,
                "roots": roots,
            }
        )
    return projects


def area_summary(user, project_id: str, unit_id=None, site_id: str | None = None) -> dict:
    """Summary rows for one level of the user's area in *project_id*.

    Tree project, no unit: the grant roots, plus an Unrouted row when the
    scope is project-wide. With a unit: that unit's direct children. Each row
    is the row's whole subtree, counted once. Sites-mode project: one row per
    in-scope site (just *site_id* when given).

    At the project root (no unit, no site) a project-wide scope also gets
    ``project_card``; it is None otherwise.

    Raises AreaNotFound for a project, unit or site outside the user's area.
    """
    scope = resolve_area_scope(user, project_id)
    if scope is None:
        raise AreaNotFound()
    result = {
        "project_id": scope.project_id,
        "project_name": scope.project_name,
        "mode": "organization" if scope.has_tree else "sites",
        "project_wide": scope.project_wide,
        "unit": None,
        "breadcrumb": [],
        "project_card": None,
    }
    at_root = not unit_id and not site_id
    screens = link_screens(user, project_id) if at_root or not scope.has_tree else set()
    if at_root and scope.project_wide:
        result["project_card"] = project_card(scope, screens)

    if not scope.has_tree:
        if unit_id:
            raise AreaNotFound()
        result["rows"] = _site_rows(
            scope, site_id or None, dm_links=SCREEN_DATA_MANAGEMENT in screens
        )
        return result

    if site_id:
        raise AreaNotFound()
    if unit_id:
        unit = _selected_unit(scope, unit_id)
        result["unit"] = {
            "org_unit_id": str(unit.org_unit_id),
            "code": unit.unit_code,
            "name": unit.unit_name,
        }
        result["breadcrumb"] = _breadcrumb(scope, unit)
        units = _unit_rows(
            [
                MasOrgUnit.project_id == scope.project_id,
                MasOrgUnit.parent_org_unit_id == unit.org_unit_id,
            ]
        )
        result["rows"] = _unit_summary_rows(scope, units)
        return result

    rows = _unit_summary_rows(scope, grant_root_units(scope))
    if scope.project_wide:
        rows.append(_unrouted_row(scope))
    result["rows"] = rows
    return result


# ---------------------------------------------------------------------------
# Staff breakdown
# ---------------------------------------------------------------------------

#: Most rows one staff query returns; one more sets ``truncated``.
STAFF_ROW_LIMIT = 500
CONTACT_WINDOW_DAYS = 30


def _staff_area(scope: AreaScope, unit_id, site_id: str | None):
    """The area the staff view counts, as ``in_area(project_col, site_col, unit_col)``.

    The same area as the summary at that level, so the per-staff numbers
    cover exactly the rows above them: a selected unit's whole subtree
    (inactive descendants included, as the unit rollup counts them), a
    selected site of a sites-mode project, or the whole project at its root
    for a project-wide scope (unrouted cases included). A root that is not
    project-wide has no single area and, like anything outside scope,
    raises AreaNotFound.
    """
    project_id = scope.project_id
    if (scope.has_tree and site_id) or (not scope.has_tree and unit_id):
        raise AreaNotFound()

    if unit_id:
        unit = _selected_unit(scope, unit_id)
        subtree = sa.select(MasOrgUnit.org_unit_id).where(
            MasOrgUnit.project_id == project_id, MasOrgUnit.path.op("<@")(unit.path)
        )

        def in_area(project_col, site_col, unit_col):
            return sa.and_(project_col == project_id, unit_col.in_(subtree))

        return in_area

    if site_id:
        in_scope = scope.site_ids is None or site_id in scope.site_ids
        if not in_scope or not db.session.scalar(
            sa.select(
                sa.exists().where(
                    VaProjectSites.project_id == project_id,
                    VaProjectSites.site_id == site_id,
                    VaProjectSites.project_site_status == VaStatuses.active,
                )
            )
        ):
            raise AreaNotFound()

        def in_area(project_col, site_col, unit_col):
            return sa.and_(project_col == project_id, site_col == site_id)

        return in_area

    if not scope.project_wide:
        raise AreaNotFound()

    def in_area(project_col, site_col, unit_col):
        return project_col == project_id

    return in_area


def _case_not_duplicate(case=VaDeathRegister):
    """*case* (outer-joined or not) is not a confirmed duplicate."""
    return sa.or_(case.status.is_(None), case.status != DUPLICATE_CASE_STATUS)


def _interviewer_rows(in_area) -> tuple[list[dict], bool]:
    """Per-interviewer web intake counts in the area: one grouped query per table.

    Cases registered (``registered_by`` on register-first cases) and
    interviews started (``started_by_user_id``) come from the case register,
    submitted and in-progress interviews from the drafts' owner, contact
    attempts in the last 30 days from who logged them. Confirmed duplicate
    cases count nowhere.
    """
    case_area = in_area(
        VaDeathRegister.project_id, VaDeathRegister.site_id, VaDeathRegister.org_unit_id
    )
    case_where = [case_area, VaDeathRegister.status != DUPLICATE_CASE_STATUS]
    attributions = sa.union_all(
        sa.select(
            VaDeathRegister.registered_by.label("user_id"), sa.literal("registered").label("kind")
        ).where(*case_where, VaDeathRegister.source == "register"),
        sa.select(
            VaDeathRegister.started_by_user_id.label("user_id"), sa.literal("started").label("kind")
        ).where(*case_where, VaDeathRegister.started_by_user_id.is_not(None)),
    ).subquery("case_attributions")
    counted = sa.func.count()
    cases = (
        sa.select(
            attributions.c.user_id,
            VaUsers.name,
            counted.filter(attributions.c.kind == "registered").label("cases_registered"),
            counted.filter(attributions.c.kind == "started").label("interviews_started"),
        )
        .join(VaUsers, VaUsers.user_id == attributions.c.user_id)
        .group_by(attributions.c.user_id, VaUsers.name)
    )

    # Aliased so the duplicate predicate's own register subquery is not
    # auto-correlated to this join.
    draft_case = sa.orm.aliased(VaDeathRegister, name="draft_case")
    drafts = (
        sa.select(
            VaWebIntakeDraft.user_id,
            VaUsers.name,
            counted.filter(VaWebIntakeDraft.status == "submitted").label("submitted"),
            counted.filter(VaWebIntakeDraft.status == DRAFT_STATUS_IN_PROGRESS).label(
                "in_progress"
            ),
        )
        .join(VaUsers, VaUsers.user_id == VaWebIntakeDraft.user_id)
        .outerjoin(draft_case, draft_case.death_id == VaWebIntakeDraft.death_id)
        .where(
            in_area(
                VaWebIntakeDraft.project_id, VaWebIntakeDraft.site_id, VaWebIntakeDraft.org_unit_id
            ),
            VaWebIntakeDraft.status.in_(("submitted", DRAFT_STATUS_IN_PROGRESS)),
            _case_not_duplicate(draft_case),
            # An in-progress draft has no va_sid yet; the case status covers it.
            not_confirmed_duplicate_condition(VaWebIntakeDraft.va_sid),
        )
        .group_by(VaWebIntakeDraft.user_id, VaUsers.name)
    )

    since = datetime.now(UTC) - timedelta(days=CONTACT_WINDOW_DAYS)
    attempts = (
        sa.select(
            MapCaseContactAttempt.by_user_id,
            VaUsers.name,
            counted.label("contact_attempts_30_days"),
        )
        .join(VaDeathRegister, VaDeathRegister.death_id == MapCaseContactAttempt.death_id)
        .join(VaUsers, VaUsers.user_id == MapCaseContactAttempt.by_user_id)
        .where(case_area, _case_not_duplicate(), MapCaseContactAttempt.attempted_at >= since)
        .group_by(MapCaseContactAttempt.by_user_id, VaUsers.name)
    )

    keys = (
        "cases_registered", "interviews_started", "submitted", "in_progress",
        "contact_attempts_30_days",
    )
    by_user: dict = {}
    truncated = False
    for stmt in (cases, drafts, attempts):
        result = db.session.execute(
            stmt.order_by(counted.desc(), VaUsers.name).limit(STAFF_ROW_LIMIT + 1)
        ).all()
        truncated = truncated or len(result) > STAFF_ROW_LIMIT
        for record in result[:STAFF_ROW_LIMIT]:
            row = by_user.setdefault(
                record[0], {"name": record.name or "Unknown", **dict.fromkeys(keys, 0)}
            )
            row.update({key: value for key, value in record._mapping.items() if key in keys})
    return _sorted_staff(by_user.values(), keys), truncated


def _coder_rows(in_area) -> tuple[list[dict], bool]:
    """Per-coder first-pass outcomes in the area over the last 7 and 30 days.

    The attribution ``dm_coder_daily_statistics`` uses: the actor of a
    ``coder_finalized`` (coded) or ``coder_not_codeable`` workflow event.
    Retired submissions, inactive project-sites and confirmed duplicates are
    left out, as in the coding columns of the table.
    """
    now = datetime.now(UTC)
    event = VaSubmissionWorkflowEvent
    coded = event.transition_id == TRANSITION_CODER_FINALIZED
    not_codeable = event.transition_id == TRANSITION_CODER_NOT_CODEABLE
    last_7 = event.event_created_at >= now - timedelta(days=7)
    counted = sa.func.count()
    stmt = (
        sa.select(
            event.actor_user_id,
            VaUsers.name,
            counted.filter(coded, last_7).label("coded_7_days"),
            counted.filter(coded).label("coded_30_days"),
            counted.filter(not_codeable, last_7).label("not_codeable_7_days"),
            counted.filter(not_codeable).label("not_codeable_30_days"),
        )
        .join(VaSubmissions, VaSubmissions.va_sid == event.va_sid)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(
            VaProjectSites,
            sa.and_(
                VaProjectSites.project_id == VaForms.project_id,
                VaProjectSites.site_id == VaForms.site_id,
                VaProjectSites.project_site_status == VaStatuses.active,
            ),
        )
        .join(VaUsers, VaUsers.user_id == event.actor_user_id)
        .where(
            event.transition_id.in_((TRANSITION_CODER_FINALIZED, TRANSITION_CODER_NOT_CODEABLE)),
            event.event_created_at >= now - timedelta(days=30),
            in_area(VaForms.project_id, VaForms.site_id, VaSubmissions.org_unit_id),
            submission_is_in_odk(VaSubmissions),
            not_confirmed_duplicate_condition(VaSubmissions.va_sid),
        )
        .group_by(event.actor_user_id, VaUsers.name)
        .order_by(counted.desc(), VaUsers.name)
        .limit(STAFF_ROW_LIMIT + 1)
    )
    keys = ("coded_7_days", "coded_30_days", "not_codeable_7_days", "not_codeable_30_days")
    result = db.session.execute(stmt).all()
    rows = [
        {"name": record.name or "Unknown", **{key: getattr(record, key) for key in keys}}
        for record in result[:STAFF_ROW_LIMIT]
    ]
    return _sorted_staff(rows, keys), len(result) > STAFF_ROW_LIMIT


def _sorted_staff(rows, keys) -> list[dict]:
    return sorted(rows, key=lambda row: (-sum(row[key] for key in keys), row["name"].lower()))


def area_staff(user, project_id: str, unit_id=None, site_id: str | None = None) -> dict:
    """Per-interviewer and per-coder counts for one area of the dashboard.

    The area is the selected unit's subtree or sites-mode site, or the whole
    project at its root for a project-wide scope (``_staff_area``). Every row
    names a person, so a viewer ``should_redact_pii`` hides staff identity
    from gets no rows and ``staff_identity_redacted``, not pseudonyms: a
    "Coder 1" with its own throughput still singles out one person, which is
    why ``dm_coder_daily_statistics`` does the same (docs/policy/area-dashboard.md,
    "Staff identity"). The staff queries do not run for such a viewer.

    Raises AreaNotFound for a project, unit or site outside the user's area,
    before the identity decision, so a redacted viewer learns no more.
    """
    scope = resolve_area_scope(user, project_id)
    if scope is None:
        raise AreaNotFound()
    in_area = _staff_area(scope, unit_id, site_id)
    result = {
        "project_id": scope.project_id,
        "staff_identity_redacted": should_redact_pii(user),
        "interviewers": [],
        "coders": [],
        "truncated": False,
    }
    if result["staff_identity_redacted"]:
        return result
    result["interviewers"], interviewers_truncated = _interviewer_rows(in_area)
    result["coders"], coders_truncated = _coder_rows(in_area)
    result["truncated"] = interviewers_truncated or coders_truncated
    return result
