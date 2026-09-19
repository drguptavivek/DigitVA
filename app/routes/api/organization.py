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
from flask import Blueprint, current_app, jsonify, request
from flask_login import current_user, login_required

from app import db, limiter
from app.models import (
    MapProjectSiteOdk,
    MasFieldDisplayConfig,
    MasFormTypes,
    MasLanguages,
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


# ---------------------------------------------------------------------------
# Form options — docs/policy/va-web-form-options.md
# ---------------------------------------------------------------------------

#: Field whose presence in a form type's display config means the ABHA
#: extension is in play for that questionnaire.
_ABHA_FIELD_ID = "abha_number"


def _config_version(project_id: str) -> str | None:
    """The latest change to anything this project's form options are built from.

    Serves the same purpose as ``_tree_version``: a client caches the options
    and revalidates, so a settings change reaches a page that is already open.
    What moves it is exactly what the response is derived from -- the project
    row (which carries all four tier-2 settings), the project-site/ODK form
    mappings (which decide ``form_types``), and the form type rows themselves
    (which carry the titles).
    """
    project_stamp = db.session.scalar(
        sa.select(VaProjectMaster.project_updated_at).where(
            VaProjectMaster.project_id == project_id
        )
    )
    latest_mapping = db.session.scalar(
        sa.select(sa.func.max(MapProjectSiteOdk.updated_at)).where(
            MapProjectSiteOdk.project_id == project_id
        )
    )
    latest_form_type = db.session.scalar(
        sa.select(sa.func.max(MasFormTypes.updated_at)).where(
            MasFormTypes.form_type_id.in_(
                sa.select(MapProjectSiteOdk.form_type_id).where(
                    MapProjectSiteOdk.project_id == project_id,
                    MapProjectSiteOdk.form_type_id.is_not(None),
                )
            )
        )
    )
    stamps = [
        value
        for value in (project_stamp, latest_mapping, latest_form_type)
        if value is not None
    ]
    return max(stamps).isoformat() if stamps else None

#: The one standard instrument DigitVA bundles today. Every ``WHO_2022_VA*``
#: form type is a layer on it, not a separate questionnaire.
_WHO_2022_VA_INSTRUMENT = "WHO_2022_VA"


def instrument_code_for(form_type_code: str | None) -> str | None:
    """The standard instrument a form type layers on, or ``None``.

    A DigitVA form type is not its own questionnaire: ``WHO_2022_VA_SOCIAL``
    and any future ``WHO_2022_VA_*`` are layers on the one standard WHO 2022
    VA instrument, and which layers apply is ``enabled_extensions``. So any
    code equal to or prefixed with ``WHO_2022_VA`` resolves to
    ``"WHO_2022_VA"``; anything else has no bundled instrument and resolves
    to ``None``, which the client renders as an error rather than guessing.

    This naming convention stands in for a ``base_instrument_code`` column on
    ``mas_form_types``, which is the follow-up recorded in
    docs/policy/va-web-form-options.md and becomes necessary as soon as a
    second standard instrument (PHMRC) is bundled.
    """
    if not form_type_code:
        return None
    code = form_type_code.strip().upper()
    if code == _WHO_2022_VA_INSTRUMENT or code.startswith(
        _WHO_2022_VA_INSTRUMENT + "_"
    ):
        return _WHO_2022_VA_INSTRUMENT
    return None


def _project_form_types(project_id: str) -> list[dict]:
    """Active form types linked to this project, with exactly one default.

    One query: the distinct form types reached through this project's
    ``map_project_site_odk`` rows, each with the number of *sites* that link
    it. The default is the form type linked to the most sites; ties are broken
    by ``form_type_code`` so the answer is stable across requests. With a
    single form type -- today's normal case -- that rule trivially picks it.
    An empty list means the project has no mapped questionnaire yet, and the
    caller has nothing to render.
    """
    site_count = sa.func.count(sa.distinct(MapProjectSiteOdk.site_id)).label("sites")
    rows = db.session.execute(
        sa.select(
            MasFormTypes.form_type_code,
            MasFormTypes.form_type_name,
            site_count,
        )
        .join(MapProjectSiteOdk, MapProjectSiteOdk.form_type_id == MasFormTypes.form_type_id)
        .where(
            MapProjectSiteOdk.project_id == project_id,
            MasFormTypes.is_active.is_(True),
        )
        .group_by(MasFormTypes.form_type_code, MasFormTypes.form_type_name)
        .order_by(site_count.desc(), MasFormTypes.form_type_code)
    ).all()
    return [
        {
            "form_type_code": row.form_type_code,
            "instrument_code": instrument_code_for(row.form_type_code),
            "title": row.form_type_name,
            "is_default": index == 0,
        }
        for index, row in enumerate(rows)
    ]


def _active_languages() -> dict[str, str]:
    """Active ``{code: label}`` from the canonical language list, in code order."""
    rows = db.session.execute(
        sa.select(MasLanguages.language_code, MasLanguages.language_name)
        .where(MasLanguages.is_active.is_(True))
        .order_by(MasLanguages.language_code)
    ).all()
    return {row.language_code: row.language_name for row in rows}


def _resolve_locales(
    project: VaProjectMaster, active: dict[str, str]
) -> tuple[str, list[dict]]:
    """The project's default locale and the locales it may switch to.

    ``web_intake_available_locales`` NULL means every active language. A
    stored code that is not an active language is dropped. The default locale
    is always present in the result: if the stored default is not available,
    the first available locale is used instead and a warning is logged -- a
    misconfigured language must degrade the form, never fail the page.
    """
    stored = project.web_intake_available_locales
    if stored is None:
        codes = list(active)
    else:
        codes = [code for code in stored if code in active]

    default = project.web_intake_default_locale
    if default not in codes:
        if default in active:
            # Active language that the project simply did not list: honour the
            # project's own default by including it rather than overriding it.
            codes = [default] + codes
        elif codes:
            current_app.logger.warning(
                "Project %s web_intake_default_locale %r is not an active "
                "language; falling back to %r.",
                project.project_id,
                default,
                codes[0],
            )
            default = codes[0]
        else:
            current_app.logger.warning(
                "Project %s has no available web intake locales; serving the "
                "stored default %r unresolved.",
                project.project_id,
                default,
            )
            codes = [default]

    available = [
        {"code": code, "label": active.get(code, code)} for code in codes
    ]
    return default, available


def _resolve_narration_languages(
    project: VaProjectMaster, active: dict[str, str]
) -> list[dict]:
    """Stored narration language codes resolved against the language list.

    NULL means none are offered. An unknown or deactivated code is dropped
    with a warning rather than served as an option the form cannot label.
    """
    stored = project.web_intake_narration_languages or []
    resolved = []
    for code in stored:
        if code in active:
            resolved.append({"code": code, "label": active[code]})
        else:
            current_app.logger.warning(
                "Project %s web_intake_narration_languages contains %r, which "
                "is not an active language; dropped.",
                project.project_id,
                code,
            )
    return resolved


def _enabled_extensions(
    project: VaProjectMaster,
    form_types: list[dict],
    narration_languages: list[dict],
) -> list[str]:
    """Which form sections this project's configuration turns on.

    Derived from configuration that already exists; nothing here is a new
    setting. ``intake_screen`` and ``death_summary`` are deliberately omitted:
    neither has anything in the data model to derive them from yet, and
    guessing a value would be worse than the form applying its own default.
    """
    extensions = ["digitva_core"]
    if project.social_autopsy_enabled:
        extensions.append("social_autopsy")

    has_geography = db.session.scalar(
        sa.select(sa.func.count())
        .select_from(MasOrgLevel)
        .where(MasOrgLevel.project_id == project.project_id)
    )
    if has_geography:
        extensions.append("geography")

    if narration_languages:
        extensions.append("narration_language")

    default_code = next(
        (ft["form_type_code"] for ft in form_types if ft["is_default"]), None
    )
    if default_code is not None:
        abha_configured = db.session.scalar(
            sa.select(sa.func.count())
            .select_from(MasFieldDisplayConfig)
            .join(
                MasFormTypes,
                MasFormTypes.form_type_id == MasFieldDisplayConfig.form_type_id,
            )
            .where(
                MasFormTypes.form_type_code == default_code,
                MasFieldDisplayConfig.field_id == _ABHA_FIELD_ID,
                MasFieldDisplayConfig.is_active.is_(True),
            )
        )
        if abha_configured:
            extensions.append("abha")

    return extensions


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
    project_id = (project_id or "").strip().upper()
    project = db.session.get(VaProjectMaster, project_id)
    if project is None or project.project_status != VaStatuses.active:
        return _error("Project not found.", 404)

    reachable = _reachable_unit_ids(project_id, None)
    if reachable is not None and not reachable:
        return _error("You do not have access to that project.", 403)

    active = _active_languages()
    form_types = _project_form_types(project_id)
    default_locale, available_locales = _resolve_locales(project, active)
    narration_languages = _resolve_narration_languages(project, active)

    return jsonify({
        "project_id": project_id,
        "config_version": _config_version(project_id),
        "enabled_extensions": _enabled_extensions(
            project, form_types, narration_languages
        ),
        "form_types": form_types,
        "default_locale": default_locale,
        "available_locales": available_locales,
        "narration_languages": narration_languages,
        "show_guidance": project.web_intake_show_guidance,
    })
