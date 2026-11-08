"""The data-collection gate: may this interviewer start new work here today?

Policy: docs/policy/project-clock-and-gates.md ("Data-collection gate"). A
site gate (``va_project_sites.collection_*``) and the nearest gated ancestor's
unit gate (``map_org_unit_collection_gate``) both apply; the first that is
closed decides, site first. "Today" and midnight are the project clock's.

Only a *new start* is gated: a new death registration, or a new interview
with no registration. Both create a ``va_death_register`` row
(``source`` ``register`` or ``direct``, ``registered_by`` the starter), so
``today_count`` counts those rows since project midnight, however they
arrived (device uploads included, though an upload is never refused).
Interviewing an already-registered death, uploads, edits and revisions are
never gated; callers decide that by calling ``require_open`` only at the
browser's new-start points.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime

import sqlalchemy as sa

from app import db
from app.models import MasOrgUnit, VaDeathRegister, VaProjectSites, VaSiteMaster, VaWebIntakeDraft
from app.services.case_transition_service import WebIntakeError
from app.services.org_grant_service import resolve_unit_collection_gates
from app.services.project_clock import project_days

#: The one error code of a refused new start (HTTP 403).
ERROR_CODE = "collection_closed"

PAUSED = "collection_paused"
NOT_STARTED = "collection_not_started"
ENDED = "collection_ended"
DAILY_LIMIT = "collection_daily_limit"

#: The ``source`` values of a new start (``odk`` rows come from ODK Central).
_NEW_START_SOURCES = ("register", "direct")


class CollectionClosed(WebIntakeError):
    """A refused new start; ``gate`` holds the structured fields of the reply."""

    def __init__(self, gate: dict):
        super().__init__(gate["message"], 403, ERROR_CODE)
        self.gate = {k: gate[k] for k in ("reason", "display_name", "date", "daily_interviewer_limit")}


def _human(d: date) -> str:
    return d.strftime("%B %-d, %Y")


def _closed(enabled, start, end, limit, count, name, today) -> tuple | None:
    """``(reason, date, message)`` when this one gate is closed today, else None."""
    if not enabled:
        return PAUSED, None, f"Data collection for {name} is paused."
    if start and start > today:
        return NOT_STARTED, start, f"Data collection for {name} opens on {_human(start)}."
    if end and end < today:
        return ENDED, end, f"Data collection for {name} ended on {_human(end)}."
    if limit is not None and count >= limit:
        plural = "s" if limit != 1 else ""
        return DAILY_LIMIT, None, (
            f"You have reached today's limit of {limit} new interview{plural} for {name}."
        )
    return None


def resolve(user, targets: Iterable[tuple[str, str, uuid.UUID | None]],
            now: datetime | None = None, *, counts: bool = True) -> dict[tuple, dict]:
    """The effective collection gate for *user* at each ``(project_id, site_id, org_unit_id)``.

    *org_unit_id* is None for a site with no unit (a project with no tree).
    At most six queries whatever the number of targets: project zones, site rows,
    unit gates (with their units), unit names, the user's site counts and the
    user's unit-subtree counts. A missing project-site row is treated as open
    (access is decided elsewhere). Returns, per target::

        {"open", "enabled", "start_date", "end_date",
         "daily_interviewer_limit", "today_count", "display_name",
         "reason", "date", "message"}

    Dates are ISO strings or None. ``start_date``/``end_date`` are the
    narrowest of the site and unit windows (both inclusive);
    ``daily_interviewer_limit``/``today_count`` are the binding pair (the
    gate with the fewest starts left). ``reason``/``date``/``message`` are
    None while open; ``display_name`` is the deciding gate's name when
    closed, else the unit's gate (if one applies) or the site's.

    *counts* False skips the two count queries (every ``today_count`` is 0),
    for callers that read only the switch and the dates (collection_hold).
    """
    targets = {(p, s, uuid.UUID(str(u)) if u else None) for p, s, u in targets}
    if not targets:
        return {}
    days = project_days({p for p, _, _ in targets}, now)
    pairs = {(p, s) for p, s, _ in targets}
    sites = {
        (r.project_id, r.site_id): r
        for r in db.session.execute(
            sa.select(
                VaProjectSites.project_id, VaProjectSites.site_id,
                VaProjectSites.collection_enabled, VaProjectSites.collection_start_date,
                VaProjectSites.collection_end_date, VaProjectSites.daily_interviewer_limit,
                VaSiteMaster.site_name,
            )
            .join(VaSiteMaster, VaSiteMaster.site_id == VaProjectSites.site_id)
            .where(sa.tuple_(VaProjectSites.project_id, VaProjectSites.site_id).in_(sorted(pairs)))
        )
    }
    unit_gates = resolve_unit_collection_gates({u for _, _, u in targets if u})
    gate_unit_ids = {g.org_unit_id for g in unit_gates.values()}
    gate_units = {
        r.org_unit_id: r
        for r in db.session.execute(
            sa.select(MasOrgUnit.org_unit_id, MasOrgUnit.unit_name)
            .where(MasOrgUnit.org_unit_id.in_(gate_unit_ids))
        )
    } if gate_unit_ids else {}

    def since_midnight(project_col):
        return sa.or_(*[
            sa.and_(project_col == pid, VaDeathRegister.created_at >= day.midnight.replace(tzinfo=UTC))
            for pid, day in days.items()
        ])

    mine = (
        VaDeathRegister.registered_by == user.user_id,
        VaDeathRegister.source.in_(_NEW_START_SOURCES),
        # A recorded refusal (POST /intake/refusals) is not an interview start; its
        # draft alone carries this meta key (registration_refusal_service).
        ~sa.exists().where(
            VaWebIntakeDraft.death_id == VaDeathRegister.death_id,
            VaWebIntakeDraft.meta.has_key("registration_refusal_sha256"),
        ),
        VaDeathRegister.created_at >= min(d.midnight for d in days.values()).replace(tzinfo=UTC),
        since_midnight(VaDeathRegister.project_id),
    )
    site_counts = {} if not counts else {
        (r.project_id, r.site_id): r.cnt
        for r in db.session.execute(
            sa.select(VaDeathRegister.project_id, VaDeathRegister.site_id, sa.func.count().label("cnt"))
            .where(*mine)
            .group_by(VaDeathRegister.project_id, VaDeathRegister.site_id)
        )
    }
    unit_counts = {}
    if gate_unit_ids and counts:
        start_unit = sa.orm.aliased(MasOrgUnit, name="start_unit")
        gate_unit = sa.orm.aliased(MasOrgUnit, name="gate_unit")
        unit_counts = dict(db.session.execute(
            sa.select(gate_unit.org_unit_id, sa.func.count())
            .select_from(VaDeathRegister)
            .join(start_unit, start_unit.org_unit_id == VaDeathRegister.org_unit_id)
            .join(gate_unit, sa.and_(
                gate_unit.project_id == start_unit.project_id,
                sa.text("start_unit.path <@ gate_unit.path"),
            ))
            .where(*mine, gate_unit.org_unit_id.in_(gate_unit_ids))
            .group_by(gate_unit.org_unit_id)
        ).all())

    result = {}
    for project_id, site_id, unit_id in targets:
        today = days[project_id].today
        site = sites.get((project_id, site_id))
        # (name, enabled, start, end, limit, count) per applying gate, site first.
        gates = [(
            (site.site_name if site else None) or site_id,
            site.collection_enabled if site else True,
            site.collection_start_date if site else None,
            site.collection_end_date if site else None,
            site.daily_interviewer_limit if site else None,
            site_counts.get((project_id, site_id), 0),
        )]
        unit_gate = unit_gates.get(unit_id) if unit_id else None
        if unit_gate is not None:
            unit_row = gate_units.get(unit_gate.org_unit_id)
            gates.append((
                (unit_row.unit_name if unit_row else None) or "this unit",
                unit_gate.collection_enabled, unit_gate.collection_start_date,
                unit_gate.collection_end_date, unit_gate.daily_interviewer_limit,
                unit_counts.get(unit_gate.org_unit_id, 0),
            ))
        closed = None
        decider = gates[-1][0]
        for name, *values in gates:
            closed = _closed(*values, name, today)
            if closed:
                decider = name
                break
        starts = [g[2] for g in gates if g[2]]
        ends = [g[3] for g in gates if g[3]]
        limited = [g for g in gates if g[4] is not None]
        binding = min(limited, key=lambda g: g[4] - g[5]) if limited else None
        reason, when, message = closed or (None, None, None)
        result[(project_id, site_id, unit_id)] = {
            "open": closed is None,
            "enabled": all(g[1] for g in gates),
            "start_date": max(starts).isoformat() if starts else None,
            "end_date": min(ends).isoformat() if ends else None,
            "daily_interviewer_limit": binding[4] if binding else None,
            "today_count": binding[5] if binding else gates[-1][5],
            "display_name": decider,
            "reason": reason,
            "date": when.isoformat() if when else None,
            "message": message,
        }
    return result


def require_open(user, project_id: str, site_id: str, org_unit_id: object | None) -> None:
    """Raise ``CollectionClosed`` (403 ``collection_closed``) when *user* may
    not start new work at this site and unit now. Call only at a new start."""
    gate = resolve(user, [(project_id, site_id, org_unit_id)])[
        (project_id, site_id, uuid.UUID(str(org_unit_id)) if org_unit_id else None)]
    if not gate["open"]:
        raise CollectionClosed(gate)


def clean_settings(data: dict) -> dict:
    """The four gate fields of an admin save, validated; ``ValueError`` names
    the bad one. ``collection_enabled`` a boolean; dates ISO or empty, end on
    or after start; ``daily_interviewer_limit`` empty (no limit) or >= 1."""
    if not isinstance(data, dict):
        raise ValueError("The body must be a JSON object.")
    enabled = data.get("collection_enabled")
    if not isinstance(enabled, bool):
        raise ValueError("collection_enabled must be a boolean.")
    try:
        start = date.fromisoformat(data["collection_start_date"]) if data.get("collection_start_date") else None
        end = date.fromisoformat(data["collection_end_date"]) if data.get("collection_end_date") else None
    except (ValueError, TypeError):
        raise ValueError(
            "collection_start_date and collection_end_date must be ISO date strings (YYYY-MM-DD)."
        ) from None
    if start and end and end < start:
        raise ValueError("collection_end_date must be on or after collection_start_date.")
    raw = data.get("daily_interviewer_limit")
    limit = None
    if raw not in (None, ""):
        if isinstance(raw, bool):
            raise ValueError("daily_interviewer_limit must be an integer.")
        try:
            limit = int(raw)
        except (ValueError, TypeError):
            raise ValueError("daily_interviewer_limit must be an integer.") from None
        if not 1 <= limit <= 100000:
            raise ValueError("daily_interviewer_limit must be between 1 and 100000.")
    return {
        "collection_enabled": enabled,
        "collection_start_date": start,
        "collection_end_date": end,
        "daily_interviewer_limit": limit,
    }


def serialize_settings(row) -> dict:
    """The four gate fields of a site or unit gate row, dates as ISO strings."""
    return {
        "collection_enabled": row.collection_enabled,
        "collection_start_date": row.collection_start_date.isoformat() if row.collection_start_date else None,
        "collection_end_date": row.collection_end_date.isoformat() if row.collection_end_date else None,
        "daily_interviewer_limit": row.daily_interviewer_limit,
    }
