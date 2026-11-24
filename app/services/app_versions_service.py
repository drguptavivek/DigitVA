"""Which app version each device and person runs in one project (digitva-jrzd).

Read-only. Policy: docs/policy/app-versions-screen.md. The caller has
already passed the roster gate; the people list is limited here to the
roster (``on_project_roster``), the predicate the roster person panel uses.
"""
import re
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from app import db
from app.models import VaStatuses, VaUserAccessGrants, VaUsers
from app.models.auth_devices import AuthDevice, AuthDeviceSession
from app.services.device_auth_service import live_session_clauses
from app.services.org_grid import _grant_in_project, on_project_roster
from app.services.worker_enrolment_service import hosted_android_apk

PEOPLE_LIMIT = 500
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(-plus)?")
_APK_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)-arm64-v8a\.apk$")


def _latest_releases() -> dict[str, tuple[int, int, int] | None]:
    """The hosted release per variant, as a version tuple, or None."""
    latest = {}
    for variant in ("normal", "plus"):
        match = _APK_VERSION_RE.search(hosted_android_apk(variant) or "")
        latest[variant] = tuple(map(int, match.groups())) if match else None
    return latest


def behind_latest(platform, app_version, latest) -> bool | None:
    """Whether an Android *app_version* is below the hosted release of its
    variant (``-plus`` suffix: Collect Plus). None when it cannot be told:
    not Android, no parsable version, or no release hosted."""
    match = _VERSION_RE.match(app_version or "")
    if platform != "android" or not match:
        return None
    release = latest["plus" if match.group(4) else "normal"]
    if release is None:
        return None
    return tuple(map(int, match.groups()[:3])) < release


def _version_key(app_version):
    match = _VERSION_RE.match(app_version or "")
    return tuple(map(int, match.groups()[:3])) if match else (-1, -1, -1)


def _iso(dt):
    return dt.isoformat() if dt else None


def project_app_versions(project_id: str, *, app_version=None, filter_version=False) -> dict:
    """Summary per (platform, app_version) of the project's active devices,
    and the roster people signed in on them (newest activity first, at most
    ``PEOPLE_LIMIT``). With *filter_version*, people are limited to
    *app_version* (None: devices that reported none). Four queries, whatever
    the number of devices."""
    now = datetime.now(UTC)
    latest = _latest_releases()
    D, S = AuthDevice, AuthDeviceSession
    active = (D.project_id == project_id, D.revoked_at.is_(None))

    def seen_since(days):
        return sa.func.count().filter(D.last_seen_at >= now - timedelta(days=days))

    summary_rows = db.session.execute(
        sa.select(D.platform, D.app_version, sa.func.count(), seen_since(7), seen_since(30),
                  sa.func.max(D.last_seen_at))
        .where(*active)
        .group_by(D.platform, D.app_version)
    ).all()
    summary = [
        {"platform": platform, "app_version": version, "active_devices": total,
         "seen_7d": seen_7d, "seen_30d": seen_30d, "last_seen_at": _iso(last_seen),
         "behind_latest": behind_latest(platform, version, latest)}
        for platform, version, total, seen_7d, seen_30d, last_seen in summary_rows
    ]
    # Newest version first within each platform.
    summary.sort(key=lambda r: (_version_key(r["app_version"]), r["app_version"] or ""), reverse=True)
    summary.sort(key=lambda r: r["platform"])

    last_seen = sa.func.max(S.last_seen_at).label("last_seen_at")
    pairs = (
        sa.select(S.user_id, D.device_id, D.platform, D.app_version, D.enrolled_at, last_seen)
        .join(D, D.device_id == S.device_id)
        .where(*active, *live_session_clauses(now), on_project_roster(project_id, S.user_id))
        .group_by(S.user_id, D.device_id)
    )
    if filter_version:
        pairs = pairs.where(D.app_version == app_version if app_version is not None else D.app_version.is_(None))
    pairs = pairs.subquery()
    total = db.session.scalar(sa.select(sa.func.count()).select_from(pairs))
    rows = db.session.execute(
        sa.select(pairs.c.user_id, VaUsers.name, pairs.c.platform, pairs.c.app_version,
                  pairs.c.enrolled_at, pairs.c.last_seen_at)
        .join(VaUsers, VaUsers.user_id == pairs.c.user_id)
        .order_by(pairs.c.last_seen_at.desc().nulls_last(), VaUsers.name, pairs.c.device_id)
        .limit(PEOPLE_LIMIT)
    ).all()

    roles: dict = {}
    user_ids = {r.user_id for r in rows}
    if user_ids:
        G = VaUserAccessGrants
        for user_id, role in db.session.execute(
            sa.select(G.user_id, G.role).distinct()
            .where(G.user_id.in_(user_ids), G.grant_status == VaStatuses.active, _grant_in_project(project_id))
        ).all():
            roles.setdefault(user_id, set()).add(role.value)

    people = [
        {"name": r.name, "roles": sorted(roles.get(r.user_id, ())), "platform": r.platform,
         "app_version": r.app_version, "last_seen_at": _iso(r.last_seen_at),
         "enrolled_at": _iso(r.enrolled_at),
         "behind_latest": behind_latest(r.platform, r.app_version, latest)}
        for r in rows
    ]
    return {
        "latest": {variant: ".".join(map(str, v)) if v else None for variant, v in latest.items()},
        "summary": summary,
        "people": people,
        "people_total": total,
        "people_truncated": total > len(people),
    }
