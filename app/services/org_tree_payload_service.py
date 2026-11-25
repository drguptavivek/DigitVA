"""The organization tree payload a cascading unit picker is served.

The body of ``GET /api/v1/organization/<project_id>/units``, also embedded by
``GET /api/v1/me/access`` (``access_summary_service``). The caller decides
access; this only builds the payload. Moved out of
``app.routes.api.organization`` so services never import a route module
(digitva-r8nh.13). Policy: docs/policy/organization-model.md.
"""

import sqlalchemy as sa

from app import db
from app.models import MasOrgLevel, MasOrgUnit
from app.services import organization_service as org


def _tree_version(project_id: str) -> str | None:
    """The latest change to this project's levels or units.

    A client caches the tree and refetches when this moves, which is how a
    deactivated unit or a new one reaches a form that is already open.
    """
    row = db.session.execute(
        sa.select(
            sa.select(sa.func.max(MasOrgUnit.updated_at))
            .where(MasOrgUnit.project_id == project_id)
            .scalar_subquery(),
            sa.select(sa.func.max(MasOrgLevel.updated_at))
            .where(MasOrgLevel.project_id == project_id)
            .scalar_subquery(),
        )
    ).first()
    stamps = [value for value in row if value is not None] if row else []
    return max(stamps).isoformat() if stamps else None


def units_payload(
    project_id: str,
    reachable: set | None,
    *,
    include_inactive: bool = False,
    include_tree_version: bool = True,
) -> dict:
    """The ``/units`` body for *project_id*, narrowed to *reachable* (None:
    the whole tree); the caller decides access. Also used by
    ``GET /api/v1/me/access`` (access_summary_service)."""
    levels = org.list_levels(project_id, include_inactive=include_inactive)
    active_levels = [lv for lv in levels if lv.is_active]
    top_depth = (
        next((lv.depth for lv in active_levels if not lv.is_optional), active_levels[0].depth)
        if active_levels
        else None
    )
    units = org.list_units(project_id, include_inactive=include_inactive, top_depth=top_depth)
    # An unplaced unit (imported, parent not yet mapped) and its subtree are
    # not offered: a picker cannot cascade to them, and their ancestor codes
    # would be wrong once they are placed. docs/policy/organization-model.md
    # ("Unplaced units").
    unplaced = {u["unit_code"] for u in units if u.get("is_unplaced")}
    if unplaced:
        units = [u for u in units if str(u["path"]).split(".")[0] not in unplaced]
    if reachable is not None:
        units = [u for u in units if u["org_unit_id"] in {str(x) for x in reachable}]

    # A scoped caller's `units` are their reachable subtree only -- a
    # PHC-scoped interviewer never gets the District or CHC rows above it.
    # A cascading client still needs those ancestors' *names* to show fixed
    # (non-editable) context above the level it can actually choose at, so
    # resolve them from the reachable units' `path` codes, in one query, and
    # mark them `selectable: false`: implied context, never a grantable
    # choice. This doesn't widen access -- those codes are already present
    # in `path` on every reachable unit -- and it changes nothing about what
    # `org_unit_id` the server will accept: `_require_scope` in
    # web_intake_service validates the submitted id against the reachable
    # set independent of this flag, so a forged ancestor id is refused there
    # regardless of what the client does with `selectable`.
    if reachable is not None:
        for unit in units:
            unit["selectable"] = True
        own_codes = {unit["unit_code"] for unit in units}
        ancestor_codes = {
            code
            for unit in units
            for code in str(unit["path"]).split(".")[:-1]
        } - own_codes
        ancestor_units = (
            org.list_units_by_codes(
                project_id,
                ancestor_codes,
                include_inactive=include_inactive,
                top_depth=top_depth,
            )
            if ancestor_codes
            else []
        )
        for unit in ancestor_units:
            unit["selectable"] = False
        units = ancestor_units + units
    else:
        for unit in units:
            unit["selectable"] = True

    return {
        "project_id": project_id,
        # Moves whenever a level or unit changes, so a client can cache the
        # tree and revalidate cheaply instead of refetching per form.
        "tree_version": _tree_version(project_id) if include_tree_version else None,
        "scoped": reachable is not None,
        "levels": [
            {
                "level_code": level.level_code,
                "level_name": level.level_name,
                "depth": level.depth,
                "is_optional": level.is_optional,
                "is_active": level.is_active,
                "field_name": org.odk_field_name_for_level(level.level_code),
                "choice_list_name": org.odk_choice_list_name_for_level(level.level_code),
            }
            for level in levels
        ],
        "units": [
            {
                "org_unit_id": unit["org_unit_id"],
                "unit_code": unit["unit_code"],
                "unit_name": unit["unit_name"],
                "level_code": unit["level_code"],
                "depth": unit["depth"],
                "parent_code": unit["parent_code"],
                "path": unit["path"],
                "is_active": unit["is_active"],
                # Context only, not a grantable choice, when false -- see
                # the comment above where this is computed. The server-side
                # scope check does not read this field; it exists purely so
                # the picker can render ancestor context as fixed text.
                "selectable": unit["selectable"],
            }
            for unit in units
        ],
    }
