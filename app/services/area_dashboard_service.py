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
section (units, snapshot counts, case counts, live counts), with subtree
rollups on ltree containment, plus one each for the area card's medians and
causes; causes are small-cell suppressed here, before any caller sees them.
A unit or site outside scope is reported as not found, never as forbidden,
so its existence does not leak.

Policy: docs/policy/area-dashboard.md.
"""

from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

import sqlalchemy as sa

from app import cache, db
from app.models import (
    AuthDevice,
    AuthStationConfig,
    MapCaseContactAttempt,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaBundleIngest,
    VaDeathRegister,
    VaFinalCodAuthority,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaSmartvaResults,
    VaStatuses,
    VaSubmissions,
    VaSyncRun,
    VaUserAccessGrants,
    VaUsers,
    VaWebIntakeDraft,
)
from app.services import authz, org_grant_service, training_scope
from app.services.authz.consulted import mark_consulted
from app.services.cod_bucket_mapping_service import (
    count_coded_submissions_by_cause,
    default_reporting_scheme_code,
)
from app.services.duplicate_exclusion import (
    DUPLICATE_CASE_STATUS,
    not_confirmed_duplicate_condition,
)
from app.services.odk_retirement_service import submission_is_in_odk
from app.services.submission_analytics_mv import (
    CORE_MV_NAME,
    get_area_site_stats_from_mv,
    get_area_unrouted_stats_from_mv,
    get_dm_org_unit_stats_from_mv,
)
from app.services.user_home_service import OPEN_CASE_STATES
from app.services.viewer_pii_service import should_redact_pii
from app.services.visit_note import has_visit_note_condition

DRAFT_STATUS_IN_PROGRESS = "draft"
# No shared constant exists for a cancelled case (web_intake_service compares
# the literal); duplicates use DUPLICATE_CASE_STATUS from duplicate_exclusion.
CANCELLED_CASE_STATUS = "cancelled"
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
    """(project_id, project_name) of every active project the user holds any grant on,
    the training project excepted.

    One query. Admins get every active project.
    """
    # The training project is never part of anyone's area (docs/policy/training-demo-project.md).
    active = sa.and_(
        VaProjectMaster.project_status == VaStatuses.active,
        VaProjectMaster.project_id.is_distinct_from(training_scope.training_project_id()),
    )
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


def resolve_area_scope(
    user,
    project_id: str,
    project_name: str | None = None,
    *,
    tree_projects: set[str] | None = None,
) -> AreaScope | None:
    """The user's area in *project_id*, or None when they have none there.

    A project is a tree project when it has an active organization level
    (``projects_with_org_tree``), the same test the coding scope enforcement
    and the data manager's unit rollup use.

    No grant of any role (``authz.effective_roles`` empty) is no area
    anywhere, decided before the project is even looked up.

    A public-demo account has no area either: its project-wide staff names
    and aggregates are other demo users' data (docs/policy/public-demo.md
    section 3). Every area endpoint and the home KPIs resolve through here.
    """
    if not authz.effective_roles(user) or getattr(user, "is_public_demo", False):
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

    has_tree = (
        project_id in tree_projects
        if tree_projects is not None
        else project_id in org_grant_service.projects_with_org_tree({project_id})
    )
    if has_tree:
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
# Period
# ---------------------------------------------------------------------------

#: The period filter: days back from today, or None for all time
#: (docs/policy/area-dashboard.md, "Period").
PERIOD_DAYS = {"30d": 30, "90d": 90, "12m": 365, "all": None}
DEFAULT_PERIOD = "all"


def period_start(period: str) -> datetime | None:
    """Start of *period* (a ``PERIOD_DAYS`` key) at UTC midnight, or None for all time.

    Midnight, so a period count equals the data manager's ``date_from``
    filter on the same day. Raises ValueError for any other value.
    """
    if period not in PERIOD_DAYS:
        raise ValueError(f"Unknown period {period!r}.")
    days = PERIOD_DAYS[period]
    if days is None:
        return None
    return datetime.combine(datetime.now(UTC).date() - timedelta(days=days), time.min, UTC)


# ---------------------------------------------------------------------------
# Counts
# ---------------------------------------------------------------------------

#: Every count a table row and the area card carry, in table order.
CASE_COUNT_KEYS = (
    "deaths_reported", "deaths_7_days", "deaths_30_days",
    "interviews_pending", "pending_over_7_days", "pending_over_30_days",
)
LIVE_COUNT_KEYS = ("final_cod", "smartva_failed", "visit_notes")
COUNT_KEYS = (
    *CASE_COUNT_KEYS, "submitted", "awaiting_coding", "not_codeable", *LIVE_COUNT_KEYS
)


def _reported_deaths(project_id: str):
    """Death-register cases of *project_id* that count as reported: every source,
    minus confirmed duplicates and cancelled cases."""
    return sa.and_(
        VaDeathRegister.project_id == project_id,
        VaDeathRegister.status.not_in([DUPLICATE_CASE_STATUS, CANCELLED_CASE_STATUS]),
    )


def _case_count_columns(since) -> list:
    """The death-register counts as labelled ``count FILTER`` columns: cases
    registered in the period (all when *since* is None) and in the last 7 and
    30 days, and open cases waiting for an interview, also those waiting
    over 7 and 30 days since registration."""
    now = datetime.now(UTC)
    counted = sa.func.count(VaDeathRegister.death_id)
    created = VaDeathRegister.created_at
    pending = VaDeathRegister.status.in_(OPEN_CASE_STATES)
    return [
        (counted if since is None else counted.filter(created >= since)).label("deaths_reported"),
        counted.filter(created >= now - timedelta(days=7)).label("deaths_7_days"),
        counted.filter(created >= now - timedelta(days=30)).label("deaths_30_days"),
        counted.filter(pending).label("interviews_pending"),
        counted.filter(pending, created < now - timedelta(days=7)).label("pending_over_7_days"),
        counted.filter(pending, created < now - timedelta(days=30)).label("pending_over_30_days"),
    ]


def _values(row, keys) -> dict:
    return {key: row._mapping[key] or 0 for key in keys}


def _case_counts_by_unit(project_id: str, unit_ids: list, since=None) -> dict:
    """Unit id -> case counts in the unit's subtree, live, in one query."""
    if not unit_ids:
        return {}
    death_unit = sa.orm.aliased(MasOrgUnit, name="death_unit")
    rows = db.session.execute(
        sa.select(MasOrgUnit.org_unit_id, *_case_count_columns(since))
        .select_from(MasOrgUnit)
        .join(death_unit, death_unit.path.op("<@")(MasOrgUnit.path))
        .join(VaDeathRegister, VaDeathRegister.org_unit_id == death_unit.org_unit_id)
        .where(
            MasOrgUnit.org_unit_id.in_(sorted(unit_ids)),
            death_unit.project_id == project_id,
            _reported_deaths(project_id),
        )
        .group_by(MasOrgUnit.org_unit_id)
    ).all()
    return {row.org_unit_id: _values(row, CASE_COUNT_KEYS) for row in rows}


def _case_counts_unrouted(project_id: str, since=None) -> dict:
    row = db.session.execute(
        sa.select(*_case_count_columns(since)).where(
            _reported_deaths(project_id), VaDeathRegister.org_unit_id.is_(None)
        )
    ).one()
    return _values(row, CASE_COUNT_KEYS)


def _case_counts_by_site(project_id: str, site_ids: list, since=None) -> dict:
    rows = db.session.execute(
        sa.select(VaDeathRegister.site_id, *_case_count_columns(since))
        .where(_reported_deaths(project_id), VaDeathRegister.site_id.in_(sorted(site_ids)))
        .group_by(VaDeathRegister.site_id)
    ).all()
    return {row.site_id: _values(row, CASE_COUNT_KEYS) for row in rows}


def _has_final_cod():
    """The submission's final cause of death holds authority
    (``final-cod-authority.md``): an authority row naming a coder or reviewer
    assessment, the Site PI KPIs' definition."""
    return sa.exists().where(
        VaFinalCodAuthority.va_sid == VaSubmissions.va_sid,
        sa.or_(
            VaFinalCodAuthority.authoritative_final_assessment_id.is_not(None),
            VaFinalCodAuthority.authoritative_reviewer_final_assessment_id.is_not(None),
        ),
    )


def _smartva_failed():
    """The submission's active SmartVA result has outcome ``failed``."""
    return sa.exists().where(
        VaSmartvaResults.va_sid == VaSubmissions.va_sid,
        VaSmartvaResults.va_smartva_status == VaStatuses.active,
        VaSmartvaResults.va_smartva_outcome == VaSmartvaResults.OUTCOME_FAILED,
    )


def _live_flags(project_id: str):
    """(org_unit_id, site_id, final_cod, smartva_failed, visit_notes) of the
    project's submissions that carry any of the three, live.

    One subquery serves the three live columns, so a level costs one query
    for them, not three. Retired submissions, confirmed duplicates and
    inactive project-sites are left out, as for every count on the page.
    """
    flags = {
        "final_cod": _has_final_cod(),
        "smartva_failed": _smartva_failed(),
        "visit_notes": has_visit_note_condition(),
    }
    return (
        sa.select(
            VaSubmissions.org_unit_id,
            VaForms.site_id,
            *(condition.label(key) for key, condition in flags.items()),
        )
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .join(
            VaProjectSites,
            sa.and_(
                VaProjectSites.project_id == VaForms.project_id,
                VaProjectSites.site_id == VaForms.site_id,
                VaProjectSites.project_site_status == VaStatuses.active,
            ),
        )
        .where(
            VaForms.project_id == project_id,
            submission_is_in_odk(VaSubmissions),
            not_confirmed_duplicate_condition(VaSubmissions.va_sid),
            sa.or_(*flags.values()),
        )
        .subquery("live_flags")
    )


def _live_count_columns(flags) -> list:
    return [sa.func.count().filter(flags.c[key]).label(key) for key in LIVE_COUNT_KEYS]


def _live_counts_by_unit(project_id: str, unit_ids: list) -> dict:
    """Unit id -> final COD, SmartVA failed and visit notes in the unit's subtree, one query."""
    if not unit_ids:
        return {}
    flags = _live_flags(project_id)
    sub_unit = sa.orm.aliased(MasOrgUnit, name="flag_unit")
    rows = db.session.execute(
        sa.select(MasOrgUnit.org_unit_id, *_live_count_columns(flags))
        .select_from(MasOrgUnit)
        .join(sub_unit, sub_unit.path.op("<@")(MasOrgUnit.path))
        .join(flags, flags.c.org_unit_id == sub_unit.org_unit_id)
        .where(MasOrgUnit.org_unit_id.in_(sorted(unit_ids)), sub_unit.project_id == project_id)
        .group_by(MasOrgUnit.org_unit_id)
    ).all()
    return {row.org_unit_id: _values(row, LIVE_COUNT_KEYS) for row in rows}


def _live_counts_total(project_id: str, unrouted_only: bool = False) -> dict:
    """Live counts over the whole project, or its submissions with no unit."""
    flags = _live_flags(project_id)
    stmt = sa.select(*_live_count_columns(flags)).select_from(flags)
    if unrouted_only:
        stmt = stmt.where(flags.c.org_unit_id.is_(None))
    return _values(db.session.execute(stmt).one(), LIVE_COUNT_KEYS)


def _live_counts_by_site(project_id: str, site_ids: list) -> dict:
    flags = _live_flags(project_id)
    rows = db.session.execute(
        sa.select(flags.c.site_id, *_live_count_columns(flags))
        .where(flags.c.site_id.in_(sorted(site_ids)))
        .group_by(flags.c.site_id)
    ).all()
    return {row.site_id: _values(row, LIVE_COUNT_KEYS) for row in rows}


def _counts(stats: dict | None, cases: dict | None, live: dict | None) -> dict:
    """One row's counts from the snapshot *stats*, the case and the live counts."""
    merged = {**(stats or {}), **(cases or {}), **(live or {})}
    return {key: merged.get(key, 0) for key in COUNT_KEYS}


def _unit_summary_rows(
    scope: AreaScope, units: list, dm_links: bool = False, since=None
) -> list[dict]:
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
                since=since,
            )
        }
    cases = _case_counts_by_unit(scope.project_id, unit_ids, since)
    live = _live_counts_by_unit(scope.project_id, unit_ids)
    return [
        {
            "kind": "unit",
            "key": str(row.org_unit_id),
            "code": row.unit_code,
            "name": row.unit_name,
            "has_children": bool(row.has_children),
            "counts": _counts(
                stats.get(str(row.org_unit_id)),
                cases.get(row.org_unit_id),
                live.get(row.org_unit_id),
            ),
            "links": (
                {
                    "visit_notes": _dm_link(
                        project=scope.project_id, org_unit=str(row.org_unit_id), visit_note="1"
                    )
                }
                if dm_links
                else {}
            ),
        }
        for row in units
    ]


def _unrouted_row(scope: AreaScope, since=None) -> dict:
    return {
        "kind": UNROUTED_KEY,
        "key": UNROUTED_KEY,
        "code": None,
        "name": "Unrouted",
        "has_children": False,
        "counts": _counts(
            get_area_unrouted_stats_from_mv(project_id=scope.project_id, since=since),
            _case_counts_unrouted(scope.project_id, since),
            _live_counts_total(scope.project_id, unrouted_only=True),
        ),
    }


def _site_rows(scope: AreaScope, site_id: str | None, dm_links: bool, since=None) -> list[dict]:
    """Per-site rows for a sites-mode project: every in-scope active site.

    With *dm_links*, each row's submitted count links to the data manager
    dashboard filtered to that project, site and period.
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
            since=since,
        )
    }
    cases = _case_counts_by_site(scope.project_id, site_ids, since)
    live = _live_counts_by_site(scope.project_id, site_ids)
    return [
        {
            "kind": "site",
            "key": row.site_id,
            "code": row.site_id,
            "name": row.site_name,
            "has_children": False,
            "counts": _counts(stats.get(row.site_id), cases.get(row.site_id), live.get(row.site_id)),
            "links": (
                {
                    "submitted": _dm_link(
                        project=scope.project_id, site=row.site_id, date_from=_date_from(since)
                    ),
                    "visit_notes": _dm_link(
                        project=scope.project_id, site=row.site_id, visit_note="1"
                    ),
                }
                if dm_links
                else {}
            ),
        }
        for row in sites
    ]


# ---------------------------------------------------------------------------
# Area card
# ---------------------------------------------------------------------------

#: A cause with fewer deaths than this is folded into OTHER_CAUSES_LABEL.
CAUSE_MIN_COUNT = 5
#: Most causes the card names; the rest are folded too.
TOP_CAUSES = 10
OTHER_CAUSES_LABEL = "Other (suppressed)"


def _in_area(scope: AreaScope, unit: MasOrgUnit | None = None, site_id: str | None = None):
    """The selected area as ``in_area(project_col, site_col, unit_col)``.

    A selected unit's whole subtree (inactive descendants included, as the
    unit rollup counts them), a selected sites-mode site, or at the root the
    user's whole scope: the project for a project-wide scope (unrouted cases
    included), else the covered units or granted sites. Callers have already
    checked *unit* and *site_id* are in scope.
    """
    project_id = scope.project_id
    if unit is not None:
        subtree = sa.select(MasOrgUnit.org_unit_id).where(
            MasOrgUnit.project_id == project_id, MasOrgUnit.path.op("<@")(unit.path)
        )
        return lambda project_col, site_col, unit_col: sa.and_(
            project_col == project_id, unit_col.in_(subtree)
        )
    if site_id:
        return lambda project_col, site_col, unit_col: sa.and_(
            project_col == project_id, site_col == site_id
        )
    if scope.project_wide:
        return lambda project_col, site_col, unit_col: project_col == project_id
    if scope.has_tree:
        unit_ids = sorted(scope.unit_ids)
        return lambda project_col, site_col, unit_col: sa.and_(
            project_col == project_id, unit_col.in_(unit_ids)
        )
    site_ids = sorted(scope.site_ids)
    return lambda project_col, site_col, unit_col: sa.and_(
        project_col == project_id, site_col.in_(site_ids)
    )


def _medians(in_area) -> dict:
    """Median days from death to interview and from interview to final COD
    over the area's submissions, all time, with how many each is over.

    Death to interview: the case register's date of death to the submission
    date, for submissions with a case. Interview to final COD: submission
    time to when the final COD took authority. One query; a median is None
    when there is nothing to take it over.
    """
    core = sa.table(
        CORE_MV_NAME,
        sa.column("va_sid"),
        sa.column("project_id"),
        sa.column("site_id"),
        sa.column("org_unit_id"),
        sa.column("submission_at", sa.DateTime),
        sa.column("submission_date", sa.Date),
        sa.column("odk_missing"),
    )
    case_row = sa.orm.aliased(VaDeathRegister, name="median_case")
    authority = VaFinalCodAuthority
    death_to_interview = core.c.submission_date - case_row.date_of_death
    cod_at = sa.func.coalesce(authority.effective_at, authority.created_at)
    interview_to_cod = sa.extract("epoch", cod_at - core.c.submission_at) / 86400.0

    def median(value):
        return sa.func.percentile_cont(0.5).within_group(value)

    row = db.session.execute(
        sa.select(
            median(death_to_interview).label("death_to_interview_days"),
            sa.func.count(death_to_interview).label("death_to_interview_n"),
            median(interview_to_cod).label("interview_to_final_cod_days"),
            sa.func.count(interview_to_cod).label("interview_to_final_cod_n"),
        )
        .select_from(core)
        .outerjoin(
            case_row,
            sa.and_(
                case_row.va_sid == core.c.va_sid,
                case_row.status.not_in([DUPLICATE_CASE_STATUS, CANCELLED_CASE_STATUS]),
            ),
        )
        .outerjoin(
            authority,
            sa.and_(
                authority.va_sid == core.c.va_sid,
                sa.or_(
                    authority.authoritative_final_assessment_id.is_not(None),
                    authority.authoritative_reviewer_final_assessment_id.is_not(None),
                ),
            ),
        )
        .where(
            in_area(core.c.project_id, core.c.site_id, core.c.org_unit_id),
            core.c.odk_missing.is_(False),
            authz.active_pair(core.c.project_id, core.c.site_id),
            not_confirmed_duplicate_condition(core.c.va_sid),
        )
    ).one()

    def days(value):
        return None if value is None else round(float(value), 1)

    return {
        "death_to_interview_days": days(row.death_to_interview_days),
        "death_to_interview_n": row.death_to_interview_n,
        "interview_to_final_cod_days": days(row.interview_to_final_cod_days),
        "interview_to_final_cod_n": row.interview_to_final_cod_n,
    }


def suppress_causes(total: int, causes: list[dict]) -> dict:
    """The cause card after small-cell suppression (docs/policy/area-dashboard.md).

    *total* is every coded death in the area and period, *causes* the
    per-cause counts, most first. Hidden (no rows) when *total* is under
    ``PERCENT_MIN_WHOLE``. Otherwise the top ``TOP_CAUSES`` causes with at
    least ``CAUSE_MIN_COUNT`` deaths, then one ``OTHER_CAUSES_LABEL`` row
    with every other coded death (small causes, causes past the top ten,
    codes the scheme does not map), so no row carries a small named cell.
    Shares are of *total*.
    """
    if total < PERCENT_MIN_WHOLE:
        return {"coded": total, "hidden": True, "rows": []}
    rows = [
        {"label": cause["label"], "coded_count": cause["coded_count"]}
        for cause in causes
        if cause["coded_count"] >= CAUSE_MIN_COUNT
    ][:TOP_CAUSES]
    other = total - sum(row["coded_count"] for row in rows)
    if other:
        rows.append({"label": OTHER_CAUSES_LABEL, "coded_count": other})
    for row in rows:
        row["percent"] = round(100 * row["coded_count"] / total, 1)
    return {"coded": total, "hidden": False, "rows": rows}


def _causes(scope: AreaScope, unit, site_id: str | None, since) -> dict:
    """Coded deaths by cause in the selected area, period by date of death, suppressed.

    The COD bucket report's own scope arguments: a unit area is its subtree's
    unit ids (``allowed_project_site_pairs=set()`` turns the unit filter on),
    a site area its (project, site) pair, a project-wide root the project's
    active pairs.
    """
    scheme_code = default_reporting_scheme_code()
    if scheme_code is None:
        return suppress_causes(0, [])
    project_id = scope.project_id
    if unit is not None:
        subtree = set(
            db.session.scalars(
                sa.select(MasOrgUnit.org_unit_id).where(
                    MasOrgUnit.project_id == project_id, MasOrgUnit.path.op("<@")(unit.path)
                )
            )
        )
        area_kwargs = {"allowed_project_site_pairs": set(), "allowed_org_unit_ids": subtree}
    elif site_id:
        area_kwargs = {"allowed_project_site_pairs": {(project_id, site_id)}}
    elif scope.project_wide:
        # Active pairs, not just the project: inactive project-sites are out
        # of every count on the page.
        area_kwargs = {
            "allowed_project_site_pairs": {(project_id, s) for s in _active_site_ids(scope)}
        }
    elif scope.has_tree:
        area_kwargs = {
            "allowed_project_site_pairs": set(),
            "allowed_org_unit_ids": set(scope.unit_ids),
        }
    else:
        area_kwargs = {"allowed_project_site_pairs": {(project_id, s) for s in scope.site_ids}}
    total, causes = count_coded_submissions_by_cause(
        scheme_code=scheme_code,
        project_id=project_id,
        death_date_from=since.date() if since else None,
        **area_kwargs,
    )
    return suppress_causes(total, causes)


def _area_card(
    scope: AreaScope, rows: list[dict], screens: set[str], unit=None, site_id=None, since=None
) -> dict:
    """The selected area's card: *rows*' counts summed (the caller passes the
    selected unit's own subtree row, or rows that do not overlap), the
    medians, the suppressed causes and links where a filter is exact."""
    links = {}
    if unit is not None:
        dm_filters = {"org_unit": str(unit.org_unit_id)}
    elif site_id:
        dm_filters = {"site": site_id}
    elif scope.project_wide:
        dm_filters = {}
    else:
        dm_filters = None  # several roots: no single data manager filter
    if SCREEN_DATA_MANAGEMENT in screens and dm_filters is not None:
        links["submitted"] = _dm_link(
            project=scope.project_id, date_from=_date_from(since), **dm_filters
        )
        links["visit_notes"] = _dm_link(project=scope.project_id, visit_note="1", **dm_filters)
    elif SCREEN_INTAKE in screens:
        links["submitted"] = {"endpoint": SCREEN_INTAKE, "params": {}}
    if SCREEN_CODING in screens:
        links["awaiting_coding"] = {"endpoint": SCREEN_CODING, "params": {}}
    return {
        "counts": {key: sum(row["counts"][key] for row in rows) for key in COUNT_KEYS},
        "medians": _medians(_in_area(scope, unit, site_id)),
        "causes": _causes(scope, unit, site_id, since),
        "links": links,
    }


# ---------------------------------------------------------------------------
# Project card and links
# ---------------------------------------------------------------------------

SCREEN_DATA_MANAGEMENT = "data_management.dashboard"
SCREEN_CODING = "coding.dashboard"
SCREEN_INTAKE = "intake.dashboard"

# The data manager dashboard admits both viewer roles
# (``role_required`` on data_management.dashboard).
VIEWER_ROLES = frozenset({VaAccessRoles.collaborator, VaAccessRoles.collaborator_pii})
VIEWER_ROLE_NAMES = frozenset(role.value for role in VIEWER_ROLES)

# Every filter the data manager page reads from its URL
# (loadStateFromUrl in app/static/js/data_manager_dashboard.js). A link sends
# them all, blank unless set, because the page overlays URL values on the
# filters it saved in the browser; a stale saved filter would otherwise make
# the landing count disagree with the count that was clicked.
DM_URL_FILTERS = (
    "search", "project", "site", "date_from", "date_to", "odk_status",
    "smartva", "age_group", "gender", "odk_sync", "workflow", "visit_note", "org_unit",
)


def _dm_link(**filters) -> dict:
    return {
        "endpoint": SCREEN_DATA_MANAGEMENT,
        "params": {key: filters.get(key, "") for key in DM_URL_FILTERS},
    }


def _date_from(since) -> str:
    """The data manager's ``date_from`` for a period start (blank for all time)."""
    return since.date().isoformat() if since else ""


def link_screens(user, project_id: str) -> set[str]:
    """Screens a count on *project_id* may link to for this user.

    A screen is offered only when the user holds the role that does that
    work on this project, and passes the target route's own role gate, so a
    link never leads to a 403: data managers, collaborators (either kind) and
    admin the data manager dashboard, coders the coding dashboard,
    interviewers web intake. The target screens still enforce their own scope
    on every request.
    """
    roles = _project_roles(user, project_id)
    screens = set()
    if (
        user.is_admin()
        or (VaAccessRoles.data_manager in roles and user.is_data_manager())
        or (roles & VIEWER_ROLES and VIEWER_ROLE_NAMES & authz.role_flags(user))
    ):
        screens.add(SCREEN_DATA_MANAGEMENT)
    if VaAccessRoles.coder in roles and user.is_coder():
        screens.add(SCREEN_CODING)
    # Through authz, not *roles*: a coder in a self-coding project interviews
    # without an interviewer grant row.
    interviews_here = any(
        g.project_id == project_id
        for g in authz.resolve_grants(user).of({VaAccessRoles.interviewer}, virtual=False)
    )
    if interviews_here and user.is_interviewer():
        screens.add(SCREEN_INTAKE)
    return screens


def project_stations(project_id: str) -> dict:
    """The project's offline stations, in one query.

    A station is an active (not revoked) enrolled device that has been
    issued a station config; handsets are not stations. ``never_synced``
    have sent no bundle; ``oldest_last_bundle_at`` is the latest bundle of
    the station that has waited longest; ``latest_bundle_at`` the newest
    bundle of any station. Counts and times only.
    """
    per_station = (
        sa.select(sa.func.max(VaBundleIngest.received_at).label("last_bundle_at"))
        .select_from(AuthDevice)
        .outerjoin(VaBundleIngest, VaBundleIngest.device_id == AuthDevice.device_id)
        .where(
            AuthDevice.project_id == project_id,
            AuthDevice.revoked_at.is_(None),
            sa.exists().where(AuthStationConfig.device_id == AuthDevice.device_id),
        )
        .group_by(AuthDevice.device_id)
        .subquery("per_station")
    )
    last = per_station.c.last_bundle_at
    row = db.session.execute(
        sa.select(
            sa.func.count().label("active"),
            sa.func.count().filter(last.is_(None)).label("never_synced"),
            sa.func.min(last).label("oldest_last_bundle_at"),
            sa.func.max(last).label("latest_bundle_at"),
        ).select_from(per_station)
    ).one()
    return dict(row._mapping)


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


def area_summary(
    user, project_id: str, unit_id=None, site_id: str | None = None, period: str = DEFAULT_PERIOD
) -> dict:
    """The card and the table for one level of the user's area in *project_id*.

    Tree project, no unit: the grant roots, plus an Unrouted row when the
    scope is project-wide. With a unit: that unit's direct children. Each row
    is the row's whole subtree, counted once. Sites-mode project: one row per
    in-scope site (just *site_id* when given).

    ``card`` is the selected area as a whole (``_area_card``); at the
    project root a project-wide scope also gets ``project_card`` (offline
    stations), None otherwise. *period* (a ``PERIOD_DAYS`` key) filters
    deaths reported, submitted and causes; ValueError for any other value.

    Cached per user and argument set for a minute, like ``home_kpis``; a grant
    change shows within that minute. AreaNotFound and ValueError are never
    cached. Policy: "Area summary cache" in docs/policy/area-dashboard.md.

    Raises AreaNotFound for a project, unit or site outside the user's area.
    """
    mark_consulted()
    cache_key = f"{AREA_SUMMARY_CACHE_PREFIX}{user.user_id}:{project_id}:{unit_id}:{site_id}:{period}"
    try:
        cached = cache.get(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        return cached
    result = _area_summary(user, project_id, unit_id, site_id, period)
    try:
        cache.set(cache_key, result, timeout=HOME_KPI_CACHE_TTL)
    except Exception:
        pass
    return result


def _area_summary(user, project_id, unit_id, site_id, period) -> dict:
    since = period_start(period)
    scope = resolve_area_scope(user, project_id)
    if scope is None:
        raise AreaNotFound()
    result = {
        "project_id": scope.project_id,
        "project_name": scope.project_name,
        "mode": "organization" if scope.has_tree else "sites",
        "project_wide": scope.project_wide,
        "period": period,
        "unit": None,
        "breadcrumb": [],
        "project_card": None,
    }
    screens = link_screens(user, project_id)
    dm_links = SCREEN_DATA_MANAGEMENT in screens

    if not scope.has_tree:
        if unit_id:
            raise AreaNotFound()
        rows = _site_rows(scope, site_id or None, dm_links=dm_links, since=since)
        result["card"] = _area_card(scope, rows, screens, site_id=site_id or None, since=since)
    elif unit_id:
        if site_id:
            raise AreaNotFound()
        unit = _selected_unit(scope, unit_id)
        result["unit"] = {
            "org_unit_id": str(unit.org_unit_id),
            "code": unit.unit_code,
            "name": unit.unit_name,
        }
        result["breadcrumb"] = _breadcrumb(scope, unit)
        # The unit itself rides along in the children's grouped queries, so
        # its card costs no extra query per section.
        units = _unit_rows(
            [
                MasOrgUnit.project_id == scope.project_id,
                sa.or_(
                    MasOrgUnit.parent_org_unit_id == unit.org_unit_id,
                    MasOrgUnit.org_unit_id == unit.org_unit_id,
                ),
            ]
        )
        all_rows = _unit_summary_rows(scope, units, dm_links=dm_links, since=since)
        own = [row for row in all_rows if row["key"] == str(unit.org_unit_id)]
        rows = [row for row in all_rows if row["key"] != str(unit.org_unit_id)]
        result["card"] = _area_card(scope, own, screens, unit=unit, since=since)
    else:
        if site_id:
            raise AreaNotFound()
        rows = _unit_summary_rows(scope, grant_root_units(scope), dm_links=dm_links, since=since)
        if scope.project_wide:
            rows.append(_unrouted_row(scope, since))
        result["card"] = _area_card(scope, rows, screens, since=since)
    result["rows"] = rows

    if not unit_id and not site_id and scope.project_wide:
        result["project_card"] = {"stations": project_stations(scope.project_id)}
    return result


#: Columns of the CSV export: one line per (section, area, measure).
CSV_HEADER = ("section", "area_code", "area_name", "measure", "value")


def _csv_cell(value):
    """A cell a spreadsheet will not run: text starting with ``= + - @`` (or
    a tab or carriage return) gets a leading ``'``. Numbers pass as they are."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def summary_csv(summary: dict) -> str:
    """*summary* (``area_summary``) as CSV of aggregates only.

    The period, the card's counts, medians and suppressed causes, each table
    row's counts and, at a project-wide root, the stations. Area codes and
    names only: no person names, no submission or case ids, no case rows.
    """
    out = io.StringIO()
    writer = csv.writer(out)

    def line(section, code, name, measure, value):
        writer.writerow([_csv_cell(cell) for cell in (section, code or "", name, measure, value)])

    selected = summary["unit"] or {"code": summary["project_id"], "name": summary["project_name"]}
    code, name = selected["code"], selected["name"]
    card = summary["card"]
    writer.writerow(CSV_HEADER)
    line("period", code, name, "period", summary["period"])
    for key in COUNT_KEYS:
        line("area", code, name, key, card["counts"][key])
    for key, value in card["medians"].items():
        line("area", code, name, key, "" if value is None else value)
    line("area", code, name, "causes_coded", card["causes"]["coded"])
    for cause in card["causes"]["rows"]:
        line("cause", code, name, cause["label"], cause["coded_count"])
    for row in summary["rows"]:
        for key in COUNT_KEYS:
            line("row", row["code"], row["name"], key, row["counts"][key])
    if summary["project_card"]:
        for key, value in summary["project_card"]["stations"].items():
            if isinstance(value, datetime):
                value = value.isoformat()
            line("stations", code, name, key, "" if value is None else value)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Home KPIs
# ---------------------------------------------------------------------------

HOME_KPI_CACHE_PREFIX = "home_kpis:"
AREA_SUMMARY_CACHE_PREFIX = "area_summary:"
#: Seconds a user's home strip may trail the live counts.
HOME_KPI_CACHE_TTL = 60


#: Smallest denominator a percentage is shown for; below it a share misleads.
PERCENT_MIN_WHOLE = 20


def _percent(part: int, whole: int) -> int | None:
    """*part* as a whole percentage of *whole*, half up, never above 100.

    None when *whole* is below ``PERCENT_MIN_WHOLE`` or *part* exceeds it:
    *whole* then does not cover *part* (ODK interviews with no death register
    rows), so a share is false. Clients print the value as sent; this is the
    one percentage rule.
    """
    if whole < PERCENT_MIN_WHOLE or part > whole:
        return None
    return (200 * part + whole) // (2 * whole)


def _active_site_ids(scope: AreaScope) -> list[str]:
    where = [
        VaProjectSites.project_id == scope.project_id,
        VaProjectSites.project_site_status == VaStatuses.active,
    ]
    if scope.site_ids is not None:
        where.append(VaProjectSites.site_id.in_(sorted(scope.site_ids)))
    return list(db.session.scalars(sa.select(VaProjectSites.site_id).where(*where)))


def _scope_totals(scope: AreaScope) -> tuple[int, int, int]:
    """(deaths reported, VA submissions, final COD) over the scope's roots.

    Roots of a grant never overlap, so summing each root's subtree counts
    every record once. Grouped queries only: the count does not grow with
    the number of units or sites.
    """
    project_id = scope.project_id
    if scope.has_tree and scope.project_wide:
        deaths = (
            db.session.scalar(
                sa.select(sa.func.count(VaDeathRegister.death_id)).where(
                    VaDeathRegister.project_id == project_id,
                    VaDeathRegister.status.notin_(("duplicate", "cancelled")),
                )
            )
            or 0
        )
        core = sa.table(
            "va_submission_analytics_core_mv", sa.column("project_id"), sa.column("va_sid")
        )
        submissions = (
            db.session.scalar(
                sa.select(sa.func.count())
                .select_from(core)
                .where(
                    core.c.project_id == project_id,
                    not_confirmed_duplicate_condition(core.c.va_sid),
                )
            )
            or 0
        )
        return deaths, submissions, _live_counts_total(project_id)["final_cod"]

    if scope.has_tree:
        unit_ids = [row.org_unit_id for row in grant_root_units(scope)]
        submissions = 0
        if unit_ids:
            stats = get_dm_org_unit_stats_from_mv(
                project_id=project_id,
                project_ids=[project_id],
                project_site_pairs=[],
                unit_ids=unit_ids,
            )
            submissions = sum(row["total_submissions"] for row in stats)
        deaths = sum(c["deaths_reported"] for c in _case_counts_by_unit(project_id, unit_ids).values())
        final_cod = sum(c["final_cod"] for c in _live_counts_by_unit(project_id, unit_ids).values())
        return deaths, submissions, final_cod

    site_ids = _active_site_ids(scope)
    if not site_ids:
        return 0, 0, 0
    stats = get_area_site_stats_from_mv(
        project_ids=[], project_site_pairs=[(project_id, s) for s in site_ids]
    )
    deaths = (
        db.session.scalar(
            sa.select(sa.func.count(VaDeathRegister.death_id)).where(
                _reported_deaths(project_id),
                VaDeathRegister.site_id.in_(site_ids),
            )
        )
        or 0
    )
    final_cod = sum(c["final_cod"] for c in _live_counts_by_site(project_id, site_ids).values())
    return (
        deaths,
        sum(row["total_submissions"] for row in stats),
        final_cod,
    )


def home_kpis(user) -> list[dict]:
    """One KPI row per project in the user's area, cached per user for a minute.

    ``interviews_pct`` and ``coded_pct`` are percentages of ``deaths_reported``,
    None when that is under 20 or smaller than the count (``_percent``). Names only; no per-unit rows. Policy: "Home KPIs" in
    docs/policy/area-dashboard.md.
    """
    mark_consulted()
    cache_key = f"{HOME_KPI_CACHE_PREFIX}{user.user_id}"
    try:
        cached = cache.get(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        return cached

    projects = []
    if authz.effective_roles(user):
        candidates = candidate_projects(user)
        if candidates:
            tree_project_ids = org_grant_service.projects_with_org_tree({p for p, _ in candidates})
            for project_id, project_name in candidates:
                scope = resolve_area_scope(
                    user, project_id, project_name, tree_projects=tree_project_ids
                )
                if scope is None:
                    continue
                deaths, interviews, coded = _scope_totals(scope)
                projects.append(
                    {
                        "project_id": project_id,
                        "project_name": project_name,
                        "deaths_reported": deaths,
                        "interviews_done": interviews,
                        "coded": coded,
                        "interviews_pct": _percent(interviews, deaths),
                        "coded_pct": _percent(coded, deaths),
                    }
                )
    try:
        cache.set(cache_key, projects, timeout=HOME_KPI_CACHE_TTL)
    except Exception:
        pass
    return projects


# ---------------------------------------------------------------------------
# Staff breakdown
# ---------------------------------------------------------------------------

#: Most rows one staff query returns; one more sets ``truncated``.
STAFF_ROW_LIMIT = 500
CONTACT_WINDOW_DAYS = 30


def _staff_area(scope: AreaScope, unit_id, site_id: str | None):
    """The area the staff view counts, as ``in_area(project_col, site_col, unit_col)``.

    The same area as the summary at that level (``_in_area``): a selected
    unit's whole subtree, a selected site of a sites-mode project, or the
    whole project at its root for a project-wide scope. A root that is not
    project-wide has no single area and, like anything outside scope,
    raises AreaNotFound.
    """
    if (scope.has_tree and site_id) or (not scope.has_tree and unit_id):
        raise AreaNotFound()
    if unit_id:
        return _in_area(scope, unit=_selected_unit(scope, unit_id))
    if site_id:
        in_scope = scope.site_ids is None or site_id in scope.site_ids
        if not in_scope or not db.session.scalar(
            sa.select(
                sa.exists().where(
                    VaProjectSites.project_id == scope.project_id,
                    VaProjectSites.site_id == site_id,
                    VaProjectSites.project_site_status == VaStatuses.active,
                )
            )
        ):
            raise AreaNotFound()
        return _in_area(scope, site_id=site_id)
    if not scope.project_wide:
        raise AreaNotFound()
    return _in_area(scope)


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


def _sorted_staff(rows, keys) -> list[dict]:
    return sorted(rows, key=lambda row: (-sum(row[key] for key in keys), row["name"].lower()))


def area_staff(user, project_id: str, unit_id=None, site_id: str | None = None) -> dict:
    """Per-interviewer counts for one area of the dashboard.

    The area is the selected unit's subtree or sites-mode site, or the whole
    project at its root for a project-wide scope (``_staff_area``). Every row
    names a person, so a viewer ``should_redact_pii`` hides staff identity
    from gets no rows and ``staff_identity_redacted``, not pseudonyms: a
    "Coder 1" with its own throughput still singles out one person, which is
    why ``dm_coder_daily_statistics`` does the same (docs/policy/area-dashboard.md,
    "Staff identity"). The staff queries do not run for such a viewer. The
    per-coder table was cut on 2026-10-22; coder throughput is the data
    manager's coder statistics.

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
        "truncated": False,
    }
    if result["staff_identity_redacted"]:
        return result
    result["interviewers"], result["truncated"] = _interviewer_rows(in_area)
    return result
