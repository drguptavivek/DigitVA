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

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app import db, limiter
from app.models import VaAccessRoles, VaProjectMaster, VaStatuses
from app.routes.api.request_helpers import error as api_error
from app.services import organization_service as org
from app.services import served_form_service, training_scope
from app.services import web_intake_service as intake_svc
from app.services.authz import reachable_unit_ids
from app.services.org_grant_service import ROLES_ALLOWING_ORG_UNIT
from app.services.org_tree_payload_service import units_payload

# The payload builders live in services (digitva-r8nh.13); the names stay
# importable from here for existing callers and tests.
from app.services.project_config_service import (  # noqa: F401
    form_options_payload,
    instrument_code_for,
    project_instrument_and_extensions,
    served_instrument_locales,
)

bp = Blueprint("organization_api", __name__)


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
    roles = frozenset({role}) if role is not None else ROLES_ALLOWING_ORG_UNIT
    return reachable_unit_ids(current_user, project_id, roles)


@bp.get("/<project_id>/units")
@login_required
@limiter.limit("120 per minute")
def project_units(project_id: str):
    """The active levels and units of one project, for a cascading picker.

    Query parameters:
      ``include_inactive=1`` also returns deactivated rows, each flagged
      ``is_active: false``. Off by default: a form should not offer a closed
      unit, but an editor showing an old submission may need to name one.
      Unplaced units and their subtrees are never returned.
      ``role`` narrows scoping to that one role's grants (e.g.
      ``role=interviewer`` for the web intake picker) instead of the union of
      every role the user holds on the project. Unknown value -> 400.
      ``role=interviewer`` (and ``role=death_reporter``) answers by the web intake rule
      (``web_intake_service.reachable_unit_ids``): grant-only, no admin or
      PI bypass, the same tree device ``/units`` returns.

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
    role_error = None
    try:
        role = _parse_role(request.args.get("role"))
    except ValueError as exc:
        role, role_error = None, str(exc)
    # authz decides first; the refusals keep their order (404, 400, 403).
    if role in (VaAccessRoles.interviewer, VaAccessRoles.death_reporter):
        # Intake pickers (Jinja, Expo web) get the same grant-only tree as
        # device /units, decided from the user's grants alone (owner,
        # 2026-10-04); the create-time check stays the authority. A
        # death_reporter's picker is its own role's reach (digitva-t6q).
        reachable = intake_svc.reachable_unit_ids(current_user, project_id, roles=frozenset({role}))
    else:
        reachable = _reachable_unit_ids(project_id, role)
    project = db.session.get(VaProjectMaster, project_id)
    if project is None or project.project_status != VaStatuses.active:
        return api_error("Project not found.", status_code=404)
    if role_error:
        return api_error(role_error, status_code=400)
    if reachable is not None and not reachable:
        return api_error("You do not have access to that project.", status_code=403)

    return jsonify(units_payload(project_id, reachable, include_inactive=request.args.get("include_inactive") == "1"))


# ---------------------------------------------------------------------------
# Form options — docs/policy/va-web-form-options.md
# ---------------------------------------------------------------------------

@bp.get("/<project_id>/form-options")
@login_required
@limiter.limit("120 per minute")
def project_form_options(project_id: str):
    """The tier-2 (per-project) options the VA web form must be given.

    The contract is docs/policy/va-web-form-options.md: the form itself
    decides nothing, so every option that differs between two projects
    running the same questionnaire is served from here. Geography is
    deliberately *not* repeated -- it is the organization tree served by
    ``/units``, and duplicating it would create two sources for the codes
    that drive routing.

    Read-only, and gated exactly as ``/units`` is: a signed-in user with no
    grant reaching this project is refused. Unlike ``/units`` the response is
    not narrowed by what the grants reach -- project configuration is the same
    for everyone who may see the project at all.
    """
    training_scope.resolve("interview")
    project, refusal = form_options_project(project_id)
    if refusal is not None:
        return refusal
    served_form_service.record_served_version()
    return jsonify(form_options_payload(project))


def form_options_project(project_id: str) -> tuple[VaProjectMaster | None, tuple | None]:
    """The project behind a form-options style request, or the refusal.

    One check for everything served per project (form-options, the form
    definition): authz decides first and the refusals keep their order (404
    for a missing or inactive project, then 403 for a user whose grants reach
    nothing in it). Returns ``(project, None)`` or ``(None, (response, status))``.
    """
    project_id = (project_id or "").strip().upper()
    project = db.session.get(VaProjectMaster, project_id)
    if project is None or project.project_status != VaStatuses.active:
        return None, api_error("Project not found.", status_code=404)
    if not training_scope.keeps_project(project_id):
        return None, api_error("You do not have access to that project.", status_code=403)
    reachable = _reachable_unit_ids(project_id, None)
    if training_scope.current() == training_scope.ONLY:
        from app.services.training_demo_service import may_use_area

        if project_id != training_scope.training_project_id() or not may_use_area(current_user.user_id, "interview"):
            return None, api_error("You do not have access to that project.", status_code=403)
    if reachable is not None and not reachable:
        return None, api_error("You do not have access to that project.", status_code=403)
    return project, None


@bp.get("/me")
@login_required
@limiter.limit("120 per minute")
def my_organization():
    """The My organization page: the signed-in user's units, the units above
    them with their people, their level, and the units below, plus the user's
    own roles per project (``my_positions``, unit roles on ``my_units``).

    Every project where the user holds a grant; sites-mode projects carry no
    tree. Names, cadres and roles only (docs/policy/organization-model.md,
    "Who sees worker names", "My positions").
    """
    return jsonify(org.my_organization(current_user))


@bp.get("/units/<org_unit_id>/people")
@login_required
@limiter.limit("120 per minute")
def unit_people(org_unit_id: str):
    """One unit's people and child units, opened from the My organization page.

    404 for an unknown unit and for a unit in a project the user holds no grant
    in: the same answer either way.
    """
    payload = org.unit_people(current_user, org_unit_id)
    if payload is None:
        return api_error("Organization unit not found.", status_code=404)
    return jsonify(payload)
