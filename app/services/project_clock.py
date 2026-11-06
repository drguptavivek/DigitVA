"""The project clock: each project's "today" in its own timezone.

``va_project_master.timezone`` (IANA name, default Asia/Kolkata) sets where a
project's day starts for the coding gate dates, the gate daily limits and the
coder daily allocation cap. Policy: docs/policy/project-clock-and-gates.md
("Project clock").
"""

from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import NamedTuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

import sqlalchemy as sa

from app import db
from app.models import VaProjectMaster

DEFAULT_PROJECT_TIMEZONE = "Asia/Kolkata"


class ProjectDay(NamedTuple):
    """*today* on the project clock and its midnight as naive UTC.

    Naive because the allocation and coding timestamps are stored as naive
    UTC (``sa.DateTime``); compare ``midnight`` with them directly.
    """

    today: date
    midnight: datetime


def _now() -> datetime:
    """The current instant; tests patch it to stand on a day boundary."""
    return datetime.now(UTC)


def is_valid_timezone(name) -> bool:
    """True when *name* is an IANA zone this server knows."""
    if not isinstance(name, str) or not name or name != name.strip():
        return False
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def timezone_choices() -> list[str]:
    """The IANA zones offered on the project form, sorted."""
    return sorted(available_timezones())


def project_day(tz_name: str | None, now: datetime | None = None) -> ProjectDay:
    """The project day containing *now* (default: the current instant) in *tz_name*.

    An unknown or empty zone falls back to the default rather than failing
    the coder's request; the admin save refuses such names.
    """
    try:
        zone = ZoneInfo(tz_name or DEFAULT_PROJECT_TIMEZONE)
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo(DEFAULT_PROJECT_TIMEZONE)
    local = (now or _now()).astimezone(zone)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return ProjectDay(
        today=local.date(),
        midnight=midnight.astimezone(UTC).replace(tzinfo=None),
    )


def project_days(project_ids: Iterable[str], now: datetime | None = None) -> dict[str, ProjectDay]:
    """``{project_id: ProjectDay}`` for *project_ids*, one query for their zones."""
    ids = set(project_ids)
    if not ids:
        return {}
    rows = db.session.execute(
        sa.select(VaProjectMaster.project_id, VaProjectMaster.timezone).where(
            VaProjectMaster.project_id.in_(ids)
        )
    ).all()
    zones = dict(rows)
    return {project_id: project_day(zones.get(project_id), now) for project_id in ids}
