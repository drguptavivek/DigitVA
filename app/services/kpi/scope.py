"""Request-independent pieces of the DM KPI scope: ``DmScope``, the SQL
fragment constants and the project-clock helpers.

Lives in the services layer so ``app.services.kpi.*`` never import a route
module. ``app.routes.api.dm_kpi.dm_kpi_scope`` re-exports every name and keeps
the request-bound code (``dm_scope``, the cache helpers); its docstring
holds the scope rules.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import cached_property

import sqlalchemy as sa

from app import db
from app.models import VaProjectMaster
from app.services import project_clock
from app.services.workflow.definition import NOT_DEMO_EVENT_SQL

# The project of a grant row ``g``: a project grant names it, a pair or unit
# grant resolves through its row, and only while that pair or unit is active
# (as authz's grant relation does). Only project grants carry ``project_id``,
# so the NULL there is never a wildcard. Joins are on primary keys.
GRANT_PROJECT_JOINS = """
    LEFT JOIN va_project_sites gps
           ON gps.project_site_id = g.project_site_id
          AND gps.project_site_status = 'active'
    LEFT JOIN mas_org_unit gou
           ON gou.org_unit_id = g.org_unit_id
          AND gou.is_active
"""
GRANT_PROJECT_SQL = "COALESCE(g.project_id, gps.project_id, gou.project_id)"

#: ``clock_pm``: the ``va_project_master`` row of form ``f``'s project, whose
#: timezone is the project clock (docs/policy/kpis.md, "Days follow the
#: project clock"). A LEFT primary-key join: ``va_forms.project_id`` points at
#: ``va_research_projects``, so a missing row keeps the count and takes the
#: default zone.
CLOCK_JOIN_SQL = "LEFT JOIN va_project_master clock_pm ON clock_pm.project_id = f.project_id"

#: Demo exclusion for output and rate KPIs (docs/policy/kpis.md, "Demo
#: exclusion"): no ``demo_started`` event on the submission and the form's
#: project is not ``demo_training_enabled``. Over ``va_submission_workflow_events
#: e`` joined to ``va_forms f``.
NOT_DEMO_OUTPUT_SQL = (
    f"({NOT_DEMO_EVENT_SQL} AND NOT EXISTS (SELECT 1 FROM va_project_master dm_demo_pm"
    " WHERE dm_demo_pm.project_id = f.project_id AND dm_demo_pm.demo_training_enabled))"
)


@dataclass(frozen=True)
class DmScope:
    """The current DM's KPI scope: direct (project, site) pairs plus a unit subtree.

    ``pairs`` are bound as two parallel text arrays and ``unit_ids`` (string
    UUIDs of the DM's granted units, the subtree anchors) as a ``uuid[]``;
    nothing is interpolated. Days are each project's own (``zones``); the
    viewer's timezone plays no part. ``unit_project_ids`` are the unit grants' projects (counts and project
    metadata only); ``direct`` says the DM holds a project or pair grant
    (authz ``Lens.DM_DIRECT``), which the system-level sync panels need.
    """

    pairs: list[tuple[str, str]]
    unit_ids: list[str]
    unit_project_ids: tuple[str, ...] = ()
    direct: bool = True
    grant_project_ids: tuple[str, ...] = ()

    def __bool__(self) -> bool:
        return bool(self.pairs or self.unit_ids)

    def sql(self, form: str = "f", sub: str = "s") -> str:
        """WHERE fragment for live queries joining va_forms *form* and va_submissions *sub*."""
        pair_sql = (
            f"({form}.project_id, {form}.site_id) IN (SELECT * FROM unnest("
            "CAST(:pair_project_ids AS text[]), CAST(:pair_site_ids AS text[])))"
        )
        if not self.unit_ids:
            return pair_sql
        subtree_sql = self.subtree_sql()
        # The form's pair is active (authz.active_pair as text): the grid
        # stops at a deactivated (project, site) pair for unit grants too.
        active_pair_sql = (
            "EXISTS (SELECT 1 FROM va_project_sites dm_scope_ps"
            f" WHERE dm_scope_ps.project_id = {form}.project_id"
            f" AND dm_scope_ps.site_id = {form}.site_id"
            " AND dm_scope_ps.project_site_status = 'active')"
        )
        return f"({pair_sql} OR ({sub}.org_unit_id IN ({subtree_sql}) AND {active_pair_sql}))"

    @staticmethod
    def subtree_sql() -> str:
        """Unit ids in the subtree of the granted units (authz.subtree_select
        as text): anchored on the grant ids, served by the ltree GiST index."""
        return (
            "SELECT dm_scope_cu.org_unit_id FROM mas_org_unit dm_scope_gu"
            " JOIN mas_org_unit dm_scope_cu"
            " ON dm_scope_cu.project_id = dm_scope_gu.project_id"
            " AND dm_scope_cu.path <@ dm_scope_gu.path"
            " WHERE dm_scope_gu.org_unit_id = ANY(CAST(:unit_ids AS uuid[]))"
            " AND dm_scope_cu.is_active"
        )

    def grant_in_scope_sql(self, grant: str = "g") -> str:
        """WHERE fragment: grant row *grant* sits inside this scope -- a project
        grant on a project the DM holds whole, a pair grant on one of the DM's
        pairs, a unit grant inside the DM's subtree or a project held whole.
        Binds ``params`` plus ``grant_project_ids``. Names coders, so it is
        never wider than the DM's own scope (owner decision 2026-10-03)."""
        return (
            f"(({grant}.scope_type = 'project'"
            f" AND {grant}.project_id = ANY(CAST(:grant_project_ids AS text[])))"
            f" OR ({grant}.scope_type = 'project_site' AND EXISTS ("
            "SELECT 1 FROM va_project_sites dm_scope_gps"
            f" WHERE dm_scope_gps.project_site_id = {grant}.project_site_id"
            " AND dm_scope_gps.project_site_status = 'active'"
            " AND (dm_scope_gps.project_id, dm_scope_gps.site_id) IN (SELECT * FROM unnest("
            "CAST(:pair_project_ids AS text[]), CAST(:pair_site_ids AS text[])))))"
            f" OR ({grant}.scope_type = 'org_unit' AND EXISTS ("
            "SELECT 1 FROM mas_org_unit dm_scope_gun"
            f" WHERE dm_scope_gun.org_unit_id = {grant}.org_unit_id"
            " AND dm_scope_gun.is_active"
            " AND (dm_scope_gun.project_id = ANY(CAST(:grant_project_ids AS text[]))"
            f" OR dm_scope_gun.org_unit_id IN ({self.subtree_sql()})))))"
        )

    @property
    def direct_project_ids(self) -> list[str]:
        """Projects of the direct pairs: a unit grant never names its project's coders."""
        return sorted({project_id for project_id, _ in self.pairs})

    @property
    def all_project_ids(self) -> list[str]:
        """Direct projects plus the unit grants' projects, for counts and
        project metadata only."""
        return sorted(set(self.direct_project_ids) | set(self.unit_project_ids))

    @cached_property
    def zones(self) -> dict[str, str]:
        """``{project_id: timezone}`` of every project in scope; one query, on first use."""
        ids = self.all_project_ids
        if not ids:
            return {}
        rows = db.session.execute(
            sa.select(VaProjectMaster.project_id, VaProjectMaster.timezone).where(
                VaProjectMaster.project_id.in_(ids)
            )
        ).all()
        return dict(rows)

    def _zone_names(self) -> list[str]:
        """The scope's zones; the default stands in for a project with no master row."""
        names = list(self.zones.values())
        if len(names) < len(self.all_project_ids) or not names:
            names.append(project_clock.DEFAULT_PROJECT_TIMEZONE)
        return names

    def today(self) -> date:
        """The latest project today in scope: the newest row of a day series.

        A project still on yesterday simply has nothing on the newest day.
        """
        now = project_clock._now()
        return max(project_clock.project_day(tz, now).today for tz in self._zone_names())

    def day_floor(self, day: date) -> datetime:
        """The earliest midnight of *day* across the scope's projects (aware):
        a raw-timestamp floor no later than any project's start of *day*."""
        return min(local_day_start(day, tz) for tz in self._zone_names())

    @property
    def params(self) -> dict:
        """Bind parameters matching ``sql`` and ``grant_in_scope_sql``."""
        return {
            "pair_project_ids": [project_id for project_id, _ in self.pairs],
            "pair_site_ids": [site_id for _, site_id in self.pairs],
            "unit_ids": self.unit_ids,
            "grant_project_ids": list(self.grant_project_ids),
        }

    def digest(self) -> str:
        """Short stable hash of the scope, for cache keys. Pairs, not sites:
        the same site in another project is another scope; the unit grant
        ids, not their subtrees: two grants are two scopes. Days follow
        the projects' clocks, not the viewer's, so no timezone is part of it;
        a project timezone edit shows once the cached figures expire."""
        raw = (
            "|".join(f"{project_id}/{site_id}" for project_id, site_id in self.pairs)
            + "#" + "|".join(self.unit_ids)
        )
        return hashlib.sha1(raw.encode()).hexdigest()[:16]


def local_day_start(day: date, tz: str) -> datetime:
    """Midnight of *day* in *tz*, as an aware datetime (binds as timestamptz)."""
    return datetime.combine(day, time(), project_clock.zone(tz))


def clock_day_sql(instant_sql: str, pm: str = "clock_pm") -> str:
    """SQL date of the timestamptz *instant_sql* on its project's clock.

    *pm* is the joined ``va_project_master`` alias (``CLOCK_JOIN_SQL``). A
    naive-UTC column goes in as ``timezone('UTC', col)``.
    """
    return f"DATE(timezone({clock_tz_sql(pm)}, {instant_sql}))"


def clock_tz_sql(pm: str = "clock_pm") -> str:
    """The project clock's zone name of the joined *pm*, the default when unjoined."""
    return f"COALESCE({pm}.timezone, '{project_clock.DEFAULT_PROJECT_TIMEZONE}')"


def in_last_days_sql(
    instant_sql: str,
    floor_sql: str = "TRUE",
    days_param: str = "clock_days",
    pm: str = "clock_pm",
) -> str:
    """WHERE fragment: *instant_sql* falls in the last ``:days_param`` days of
    its project's clock, today included (1 = today only).

    The date test is exact but wraps the column; *floor_sql* compares the
    raw column with ``clock_params``' floor (no later than any project's
    window start), so a timestamp index still serves the scan. Binds
    ``clock_params``.
    """
    today = f"DATE(timezone({clock_tz_sql(pm)}, CAST(:clock_now AS timestamptz)))"
    return (
        f"({floor_sql} AND {clock_day_sql(instant_sql, pm)}"
        f" > {today} - CAST(:{days_param} AS integer))"
    )


def clock_params(days: int, days_param: str = "clock_days") -> dict:
    """Bind parameters of ``in_last_days_sql`` for a *days*-day window.

    ``clock_floor`` (aware) and ``clock_floor_naive`` (naive UTC, for naive
    columns) are a day earlier than the earliest possible project start, so
    no event inside a project's window falls below them.
    """
    now = project_clock._now()
    floor = now - timedelta(days=days + 1)
    return {
        "clock_now": now,
        "clock_floor": floor,
        "clock_floor_naive": floor.astimezone(UTC).replace(tzinfo=None),
        days_param: days,
    }
