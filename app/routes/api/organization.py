"""Organization tree JSON API — /api/v1/organization/

Serves the levels and units a form-filling or coding client needs to render a
cascading unit selection: which codes are valid, how they nest, and which are
active. It is the same data that generates the XLSForm ``choices`` sheet for
ODK, from the same service, so a web form and an ODK form offer the same
choices and produce the same ``org_<level_code>_code`` values.

Read-only. Any signed-in user with an active grant on the project may read it,
and what they get back is scoped to what their grants reach — a coder at one
PHC is served that PHC's branch, not the district's whole tree.

The web intake picker (the interviewer flow) must pass ``role=interviewer``:
without it, the response is a union across every role the user holds on the
project, which would leak a branch reachable only through some other role
(e.g. a coder grant at a PHC the user does not interview at) into the
picker's choices.

Policy: docs/policy/organization-model.md.
"""

import sqlalchemy as sa
from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app import db, limiter
from app.models import (
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaProjectMaster,
    VaStatuses,
)
from app.services import organization_service as org
from app.services.org_grant_service import ROLES_ALLOWING_ORG_UNIT, scope_unit_ids_for_roles

bp = Blueprint("organization_api", __name__)


def _error(message: str, status_code: int = 400):
    return jsonify({"error": message}), status_code


def _project_wide_grant_exists(project_id: str, roles: frozenset) -> bool:
    """A project- or site-scoped grant in *roles* reaches the project's whole tree.

    Delegates to ``org_grant_service.project_wide_grant_exists``, which is
    the single definition of this rule and documents exactly what it promises
    about inactive grants, inactive project-sites, and admin bypass. The web
    intake service's scope check calls the same function, so the picker an
    interviewer sees and the check their submission is held to cannot
    disagree.
    """
    from app.services import org_grant_service as grants

    return grants.project_wide_grant_exists(current_user.user_id, project_id, roles)


def _parse_role(raw: str | None) -> "VaAccessRoles | None":
    """Validate the optional ``role`` query parameter.

    Raises ValueError (caller turns it into a 400) on an unknown value.
    """
    if raw is None or raw == "":
        return None
    try:
        return VaAccessRoles(raw)
    except ValueError:
        raise ValueError(f"Unknown role {raw!r}.") from None


def _reachable_unit_ids(project_id: str, role: "VaAccessRoles | None") -> set | None:
    """Unit ids this user's grants reach in *project_id*.

    ``None`` means the whole tree: an admin, a PI of the project, or anyone
    holding a project- or site-scoped grant there (in *role*, when given). An
    empty set means the user reaches nothing and the request is refused.

    *role* narrows the union to that one role's grants — e.g. ``interviewer``
    for the intake picker — so scope earned through an unrelated role never
    leaks in. Left ``None``, every role that may hold an org_unit grant is
    unioned, for read-only browsing.
    """
    if current_user.is_admin() or current_user.can_manage_project(project_id):
        return None

    roles = frozenset({role}) if role is not None else ROLES_ALLOWING_ORG_UNIT
    if _project_wide_grant_exists(project_id, roles):
        return None

    reachable = scope_unit_ids_for_roles(current_user.user_id, roles)
    if not reachable:
        return set()

    # Keep only this project's units — a user may hold grants in several.
    in_project = db.session.scalars(
        sa.select(MasOrgUnit.org_unit_id).where(
            MasOrgUnit.project_id == project_id,
            MasOrgUnit.org_unit_id.in_(sorted(reachable)),
        )
    ).all()
    return set(in_project)


def _tree_version(project_id: str) -> str | None:
    """The latest change to this project's levels or units.

    A client caches the tree and refetches when this moves, which is how a
    deactivated unit or a new one reaches a form that is already open.
    """
    latest_unit = db.session.scalar(
        sa.select(sa.func.max(MasOrgUnit.updated_at)).where(
            MasOrgUnit.project_id == project_id
        )
    )
    latest_level = db.session.scalar(
        sa.select(sa.func.max(MasOrgLevel.updated_at)).where(
            MasOrgLevel.project_id == project_id
        )
    )
    stamps = [value for value in (latest_unit, latest_level) if value is not None]
    return max(stamps).isoformat() if stamps else None


@bp.get("/<project_id>/units")
@login_required
@limiter.limit("120 per minute")
def project_units(project_id: str):
    """The active levels and units of one project, for a cascading picker.

    Query parameters:
      ``include_inactive=1`` also returns deactivated rows, each flagged
      ``is_active: false``. Off by default: a form should not offer a closed
      unit, but an editor showing an old submission may need to name one.
      ``role`` narrows scoping to that one role's grants (e.g.
      ``role=interviewer`` for the web intake picker) instead of the union of
      every role the user holds on the project. Unknown value -> 400.

    Each returned unit carries ``selectable``: ``true`` for a unit the
    caller's grants actually reach, ``false`` for an ancestor unit included
    only so a cascading client can render context above the caller's
    reachable branch (e.g. the District/CHC above a PHC-scoped
    interviewer's own unit) -- never a grantable choice. This is a UI
    affordance only; the server-side scope check a submission is held to
    (``web_intake_service._require_scope``) validates the submitted
    ``org_unit_id`` against the reachable set independently of this flag.
    """
    project_id = (project_id or "").strip().upper()
    project = db.session.get(VaProjectMaster, project_id)
    if project is None or project.project_status != VaStatuses.active:
        return _error("Project not found.", 404)

    try:
        role = _parse_role(request.args.get("role"))
    except ValueError as exc:
        return _error(str(exc), 400)

    reachable = _reachable_unit_ids(project_id, role)
    if reachable is not None and not reachable:
        return _error("You do not have access to that project.", 403)

    include_inactive = request.args.get("include_inactive") == "1"
    levels = org.list_levels(project_id, include_inactive=include_inactive)
    units = org.list_units(project_id, include_inactive=include_inactive)
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
            org.list_units_by_codes(project_id, ancestor_codes, include_inactive=include_inactive)
            if ancestor_codes
            else []
        )
        for unit in ancestor_units:
            unit["selectable"] = False
        units = ancestor_units + units
    else:
        for unit in units:
            unit["selectable"] = True

    return jsonify({
        "project_id": project_id,
        # Moves whenever a level or unit changes, so a client can cache the
        # tree and revalidate cheaply instead of refetching per form.
        "tree_version": _tree_version(project_id),
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
    })
