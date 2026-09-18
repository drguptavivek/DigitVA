"""Route a synced submission to an organization unit.

A health-system project's ODK form carries one ``org_<level_code>_code`` field
per level of the project's tree, filled from unit codes DigitVA itself
exported. Routing reads those fields, takes the deepest one that names a live
unit of that project, and attributes the death to it. When nothing in the
payload resolves, the submission falls back to the unit named on its ODK form
mapping; when the mapping names none either, the submission stays unrouted and
appears in the data manager's unrouted queue.

Three rules keep this safe to run repeatedly:

- routing is idempotent: the same payload always yields the same unit, so
  re-running a sync rewrites nothing;
- a manual pin by a data manager is never overwritten by a later sync;
- a project with no organization tree is left alone entirely.

Policy: docs/policy/organization-model.md. Plan:
docs/planning/health-system-organization-model-plan.md (phase 3).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import sqlalchemy as sa

from app import db
from app.models import MasOrgLevel, MasOrgUnit, VaSubmissions

log = logging.getLogger(__name__)

# Values of va_submissions.org_unit_resolution.
RESOLUTION_FORM_FIELD = "form_field"
RESOLUTION_MAPPING_FALLBACK = "mapping_fallback"
RESOLUTION_MANUAL = "manual"


@dataclass(frozen=True)
class RoutingOutcome:
    """What routing decided for one submission."""

    org_unit_id: uuid.UUID | None
    resolution: str | None
    # The level whose field supplied the code, for logging and the DM queue.
    level_code: str | None = None
    # A code present in the payload that named no live unit of this project.
    # Set when routing fell back or failed, so the DM sees why.
    unmatched_code: str | None = None

    @property
    def routed(self) -> bool:
        return self.org_unit_id is not None


UNROUTED = RoutingOutcome(org_unit_id=None, resolution=None)


def _levels_deepest_first(project_id: str) -> list[MasOrgLevel]:
    return list(
        db.session.scalars(
            sa.select(MasOrgLevel)
            .where(MasOrgLevel.project_id == project_id, MasOrgLevel.is_active.is_(True))
            .order_by(MasOrgLevel.depth.desc())
        ).all()
    )


class RoutingContext:
    """Per-form routing state, built once before a sync loop.

    Holds the project's levels and a lazy cache of unit codes, so routing a
    form's thousandth submission costs no more queries than its first: a
    form's submissions name the same handful of units over and over.
    """

    __slots__ = ("project_id", "fallback_org_unit_id", "_levels", "_units_by_code", "_fallback")

    def __init__(self, project_id: str, *, fallback_org_unit_id: uuid.UUID | None = None):
        self.project_id = project_id
        self.fallback_org_unit_id = fallback_org_unit_id
        self._levels = _levels_deepest_first(project_id)
        self._units_by_code: dict[str, MasOrgUnit | None] = {}
        self._fallback: MasOrgUnit | None | object = _UNSET

    @property
    def has_tree(self) -> bool:
        return bool(self._levels)

    @property
    def levels_deepest_first(self) -> list[MasOrgLevel]:
        return self._levels

    def unit_for_code(self, code: str) -> MasOrgUnit | None:
        """The live unit of this project with *code*, cached (misses included)."""
        if code in self._units_by_code:
            return self._units_by_code[code]
        unit = db.session.scalar(
            sa.select(MasOrgUnit).where(
                MasOrgUnit.project_id == self.project_id,
                MasOrgUnit.unit_code == code,
                MasOrgUnit.is_active.is_(True),
            )
        )
        self._units_by_code[code] = unit
        return unit

    def fallback_unit(self) -> MasOrgUnit | None:
        """The mapping's fallback unit, if it is live and in this project."""
        if self._fallback is _UNSET:
            unit = None
            if self.fallback_org_unit_id is not None:
                candidate = db.session.get(MasOrgUnit, self.fallback_org_unit_id)
                if (
                    candidate is not None
                    and candidate.is_active
                    and candidate.project_id == self.project_id
                ):
                    unit = candidate
            self._fallback = unit
        return self._fallback


_UNSET = object()


def _payload_code(payload: dict, field_name: str) -> str | None:
    """Read one unit code from a payload, tolerating ODK's shapes.

    ODK flattens group paths, so the same answer may arrive as ``org_phc_code``
    or as ``some/group/org_phc_code``. Values are upper-cased because unit
    codes are stored that way.
    """
    raw = payload.get(field_name)
    if raw is None:
        suffix = f"/{field_name}"
        for key, value in payload.items():
            if isinstance(key, str) and key.endswith(suffix):
                raw = value
                break
    if raw is None:
        return None
    code = str(raw).strip().upper()
    return code or None


def resolve_org_unit_from_payload(context: RoutingContext, payload: dict | None) -> RoutingOutcome:
    """Resolve the deepest unit code in *payload* to a live unit of the project.

    Returns UNROUTED when the project has no tree, the payload carries no unit
    code, or no code names a live unit at its own level.
    """
    if not payload or not context.has_tree:
        return UNROUTED

    codes: list[tuple[MasOrgLevel, str]] = []
    for level in context.levels_deepest_first:
        code = _payload_code(payload, level.odk_field_name)
        if code:
            codes.append((level, code))
    if not codes:
        return UNROUTED

    for level, code in codes:
        unit = context.unit_for_code(code)
        if unit is None:
            continue
        if unit.org_level_id != level.org_level_id:
            # The code exists but at a different level than the field claims;
            # trust neither side and keep looking up the tree.
            log.warning(
                "Routing: %s carried %r for project %s, which is a unit at another level",
                level.odk_field_name,
                code,
                context.project_id,
            )
            continue
        return RoutingOutcome(
            org_unit_id=unit.org_unit_id,
            resolution=RESOLUTION_FORM_FIELD,
            level_code=level.level_code,
        )

    # Codes were present but none matched a live unit at its own level. Report
    # the deepest one so the data manager sees the most specific failure.
    return RoutingOutcome(
        org_unit_id=None,
        resolution=None,
        level_code=codes[0][0].level_code,
        unmatched_code=codes[0][1],
    )


def resolve_submission_org_unit(
    context: RoutingContext, payload: dict | None
) -> RoutingOutcome:
    """Full routing decision for one submission: payload first, then fallback."""
    outcome = resolve_org_unit_from_payload(context, payload)
    if outcome.routed:
        return outcome
    fallback = context.fallback_unit()
    if fallback is None:
        return outcome
    return RoutingOutcome(
        org_unit_id=fallback.org_unit_id,
        resolution=RESOLUTION_MAPPING_FALLBACK,
        level_code=outcome.level_code,
        unmatched_code=outcome.unmatched_code,
    )


def apply_routing(
    submission: VaSubmissions,
    outcome: RoutingOutcome,
) -> bool:
    """Write *outcome* onto *submission*. Returns True when anything changed.

    A manually pinned submission is left untouched: a data manager's decision
    outranks anything a later sync computes.
    """
    if submission.org_unit_resolution == RESOLUTION_MANUAL:
        return False
    if (
        submission.org_unit_id == outcome.org_unit_id
        and submission.org_unit_resolution == outcome.resolution
    ):
        return False
    submission.org_unit_id = outcome.org_unit_id
    submission.org_unit_resolution = outcome.resolution
    return True


def route_submission(
    submission: VaSubmissions,
    *,
    context: RoutingContext,
    payload: dict | None,
) -> RoutingOutcome:
    """Resolve and apply a submission's unit in one call. Caller commits."""
    outcome = resolve_submission_org_unit(context, payload)
    apply_routing(submission, outcome)
    return outcome


def context_for_form(va_form) -> RoutingContext:
    """Build a routing context for one legacy ``va_forms`` row.

    The fallback unit comes from the form's active ODK mapping, so a project
    whose Central form carries no unit fields can still attribute its
    submissions to one district or to the project's root unit.
    """
    from app.services.runtime_form_sync_service import get_active_mapping_for_form

    mapping = get_active_mapping_for_form(va_form)
    return RoutingContext(
        va_form.project_id,
        fallback_org_unit_id=mapping.org_unit_id if mapping else None,
    )


def pin_submission_org_unit(
    submission: VaSubmissions,
    org_unit_id: object,
    *,
    actor_user_id: uuid.UUID,
    project_id: str,
) -> MasOrgUnit:
    """Pin a submission to a unit by hand. Later syncs will not overwrite it.

    ``org_unit_id`` may be a UUID or its string form, so a request body can be
    passed straight through.
    """
    from app.services.organization_service import OrganizationError

    if not isinstance(org_unit_id, uuid.UUID):
        try:
            org_unit_id = uuid.UUID(str(org_unit_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise OrganizationError("Invalid organization unit id.") from exc

    unit = db.session.get(MasOrgUnit, org_unit_id)
    if unit is None or unit.project_id != project_id:
        raise OrganizationError("Organization unit not found in this submission's project.")
    if not unit.is_active:
        raise OrganizationError("Organization unit is inactive.")
    submission.org_unit_id = unit.org_unit_id
    submission.org_unit_resolution = RESOLUTION_MANUAL
    submission.org_unit_pinned_by = actor_user_id
    submission.org_unit_pinned_at = datetime.now(timezone.utc)
    return unit


def clear_pin(submission: VaSubmissions) -> None:
    """Drop a manual pin so the next sync routes the submission again."""
    submission.org_unit_resolution = (
        RESOLUTION_MAPPING_FALLBACK if submission.org_unit_id else None
    )
    submission.org_unit_pinned_by = None
    submission.org_unit_pinned_at = None


# ---------------------------------------------------------------------------
# Preflight: does the mapped ODK form actually carry the routing fields?
#
# Routing is silent when a field is misnamed: nothing errors, every submission
# simply falls back. This check answers the question before a sync runs, by
# reading the form's field list from ODK Central.
# ---------------------------------------------------------------------------


def expected_odk_fields(project_id: str) -> list[dict]:
    """The survey field and choice list each active level expects, deepest last."""
    from app.services.organization_service import (
        odk_choice_list_name_for_level,
        odk_field_name_for_level,
    )

    levels = db.session.scalars(
        sa.select(MasOrgLevel)
        .where(MasOrgLevel.project_id == project_id, MasOrgLevel.is_active.is_(True))
        .order_by(MasOrgLevel.depth)
    ).all()
    return [
        {
            "level_code": level.level_code,
            "level_name": level.level_name,
            "depth": level.depth,
            "is_optional": level.is_optional,
            "field_name": odk_field_name_for_level(level.level_code),
            "choice_list_name": odk_choice_list_name_for_level(level.level_code),
        }
        for level in levels
    ]


def _field_basename(entry: dict) -> str | None:
    """The leaf name of one ODK Central field entry.

    Central returns ``{"name": "org_phc_code", "path": "/data/grp/org_phc_code"}``;
    older servers may return only a path. Either way the leaf is what a payload
    key ends with, which is what routing matches on.
    """
    name = entry.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    path = entry.get("path")
    if isinstance(path, str) and path.strip():
        return path.strip().rstrip("/").rsplit("/", 1)[-1] or None
    return None


def fetch_odk_form_field_names(
    odk_project_id: int, odk_form_id: str, *, client
) -> set[str]:
    """Leaf field names of one ODK Central form. Raises on an unusable response."""
    from app.services.odk_connection_guard_service import guarded_odk_call

    response = guarded_odk_call(
        lambda: client.get(
            f"projects/{odk_project_id}/forms/{odk_form_id}/fields",
            params={"odata": "false"},
        ),
        client=client,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"ODK Central returned {response.status_code} for the form's field list."
        )
    entries = response.json()
    if not isinstance(entries, list):
        raise RuntimeError("ODK Central returned an unexpected field list.")
    names = {
        basename
        for basename in (_field_basename(entry) for entry in entries if isinstance(entry, dict))
        if basename
    }
    if not names:
        raise RuntimeError("ODK Central returned no fields for this form.")
    return names


def check_odk_form_fields(
    project_id: str, odk_project_id: int, odk_form_id: str, *, client=None
) -> dict:
    """Compare a mapped ODK form's fields against the project's expected ones.

    Returns the per-level verdict plus a summary. Raises RuntimeError with an
    operator-readable message when the form cannot be read.
    """
    expected = expected_odk_fields(project_id)
    if not expected:
        return {
            "project_id": project_id,
            "odk_project_id": odk_project_id,
            "odk_form_id": odk_form_id,
            "has_tree": False,
            "levels": [],
            "missing_count": 0,
            "present_count": 0,
        }

    if client is None:
        from app.utils.va_odk.va_odk_01_clientsetup import va_odk_clientsetup

        client = va_odk_clientsetup(project_id)

    form_fields = fetch_odk_form_field_names(odk_project_id, odk_form_id, client=client)

    levels = []
    for item in expected:
        present = item["field_name"] in form_fields
        levels.append({**item, "present": present})
    missing = [item for item in levels if not item["present"]]
    return {
        "project_id": project_id,
        "odk_project_id": odk_project_id,
        "odk_form_id": odk_form_id,
        "has_tree": True,
        "levels": levels,
        "missing_count": len(missing),
        "present_count": len(levels) - len(missing),
        "form_field_count": len(form_fields),
    }
