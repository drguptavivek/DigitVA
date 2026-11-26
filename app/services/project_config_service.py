"""A project's tier-2 web form configuration: form types, locales, narration
languages, enabled extensions and the form-options payload.

The body of ``GET /api/v1/organization/<project_id>/form-options`` and the
pieces the station config, XLSForm export, web intake readiness check and
instrument translation services resolve the same way. The caller decides
access; this only builds the answer. Moved out of
``app.routes.api.organization`` so services never import a route module
(digitva-r8nh.13). Policy: docs/policy/va-web-form-options.md.
"""

import sqlalchemy as sa
from flask import current_app

from app import db
from app.models import (
    MapProjectSiteOdk,
    MasFieldDisplayConfig,
    MasFormTypes,
    MasLanguages,
    MasOrgLevel,
    VaProjectMaster,
    VaStatuses,
)
from app.services import served_form_service
from app.services.instrument_translation_service import active_locale_versions
from app.services.web_form_instruments import (
    DEFAULT_LOCALE,
    FALLBACK_INSTRUMENT_CODE,
    instrument_locale_catalogue,
    resolved_instrument_code,
)
from app.services.web_intake_service import resolve_intake_note

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


def instrument_code_for(form_type: "MasFormTypes | str | None") -> str | None:
    """The standard instrument a form type layers on, or ``None``.

    A DigitVA form type is not its own questionnaire: ``WHO_2022_VA_SOCIAL``
    and any future ``WHO_2022_VA_*`` are layers on the one standard WHO 2022
    VA instrument, and which layers apply is ``enabled_extensions``. Which
    instrument a form type layers on is recorded per form type in
    ``mas_form_types.base_instrument_code`` -- the naming convention that
    stood in for it until 2026-09-19 could not have covered a second
    instrument family (PHMRC). NULL means nothing is bundled for that form
    type, which the client renders as an error rather than guessing.

    Accepts a ``MasFormTypes`` row, which costs no query, or a form type code,
    which costs exactly one. Policy: docs/policy/va-web-form-options.md.
    """
    if form_type is None:
        return None
    if isinstance(form_type, MasFormTypes):
        base = form_type.base_instrument_code
    else:
        code = form_type.strip().upper()
        if not code:
            return None
        base = db.session.scalar(
            sa.select(MasFormTypes.base_instrument_code).where(
                MasFormTypes.form_type_code == code
            )
        )
    base = (base or "").strip()
    return base or None


def resolved_web_form_types(projects) -> dict[str, MasFormTypes | None]:
    """``{project_id: form type}`` each project's web questionnaire carries.

    The project's own setting decides it; a project that has not chosen one
    falls back to the form type its existing web ``va_forms`` row carries
    (the lowest ``form_type_code`` when there are several), and then to
    ``WHO_2022_VA``. A configured form type that has been deactivated is
    skipped like an unset one. ``None`` only when not even the default is
    registered and active.

    Batched so the admin project list costs three queries, not three per
    project (digitva-l2dg).
    """
    from app.models import VaForms
    from app.services.runtime_form_sync_service import (
        WEB_FORM_DEFAULT_FORM_TYPE_CODE,
    )

    projects = list(projects)
    configured_ids = {p.web_intake_form_type_id for p in projects if p.web_intake_form_type_id}
    configured = {}
    if configured_ids:
        configured = {
            form_type.form_type_id: form_type
            for form_type in db.session.scalars(
                sa.select(MasFormTypes).where(
                    MasFormTypes.form_type_id.in_(configured_ids),
                    MasFormTypes.is_active.is_(True),
                )
            )
        }

    resolved: dict[str, MasFormTypes | None] = {}
    unresolved = []
    for project in projects:
        form_type = configured.get(project.web_intake_form_type_id)
        if form_type is not None:
            resolved[project.project_id] = form_type
        else:
            unresolved.append(project.project_id)
    if not unresolved:
        return resolved

    for project_id, form_type in db.session.execute(
        sa.select(VaForms.project_id, MasFormTypes)
        .distinct(VaForms.project_id)
        .join(MasFormTypes, VaForms.form_type_id == MasFormTypes.form_type_id)
        .where(
            VaForms.project_id.in_(unresolved),
            VaForms.form_source == "web",
            VaForms.form_status == VaStatuses.active,
            MasFormTypes.is_active.is_(True),
        )
        .order_by(VaForms.project_id, MasFormTypes.form_type_code)
    ):
        resolved.setdefault(project_id, form_type)

    if any(project_id not in resolved for project_id in unresolved):
        default = db.session.scalar(
            sa.select(MasFormTypes).where(
                MasFormTypes.form_type_code == WEB_FORM_DEFAULT_FORM_TYPE_CODE,
                MasFormTypes.is_active.is_(True),
            )
        )
        for project_id in unresolved:
            resolved.setdefault(project_id, default)
    return resolved


def _web_form_type_row(project: VaProjectMaster) -> MasFormTypes | None:
    """The active form type this project's web questionnaire carries.

    ``resolved_web_form_types`` for one project. A project with a setting
    serves the type ``runtime_form_sync_service.resolve_web_form_type`` gives
    a new web form; with none, its existing web form's type comes first, so
    the questionnaire served is the one its forms carry (a *new* web form of
    such a project still gets ``WHO_2022_VA``).

    A configured form type that has been deactivated is skipped rather than
    raised on: this endpoint is what the interviewer's page loads, and
    degrading to the fallback questionnaire beats a page that will not open.
    The readiness check (WP2) is where that misconfiguration is reported.
    """
    form_type = resolved_web_form_types([project])[project.project_id]
    configured_id = project.web_intake_form_type_id
    if configured_id is not None and (form_type is None or form_type.form_type_id != configured_id):
        current_app.logger.warning(
            "Project %s web_intake_form_type_id %s is not an active form type; "
            "serving the fallback questionnaire.",
            project.project_id,
            configured_id,
        )
    return form_type


def _project_form_types(project: VaProjectMaster) -> list[dict]:
    """Active form types this project collects on, with exactly one default.

    Two sources, unioned: the form types reached through the project's
    ``map_project_site_odk`` rows, each with the number of *sites* that link
    it, and the form types of the project's active ``form_source='web'``
    ``va_forms`` rows. A project that collects on the web but has no web form
    row yet still gets its configured questionnaire listed, so a web-only
    project is never served an empty list -- the defect this fixes was the
    intake page stopping with "This project has no questionnaire configured".

    The default is the configured web questionnaire whenever the project
    collects on the web; otherwise it is the form type linked to the most
    sites, ties broken by ``form_type_code`` so the answer is stable across
    requests.
    """
    from app.models import VaForms

    site_count = sa.func.count(sa.distinct(MapProjectSiteOdk.site_id)).label("sites")
    odk_rows = db.session.execute(
        sa.select(
            MasFormTypes.form_type_code,
            MasFormTypes.form_type_name,
            MasFormTypes.base_instrument_code,
            site_count,
        )
        .join(MapProjectSiteOdk, MapProjectSiteOdk.form_type_id == MasFormTypes.form_type_id)
        .where(
            MapProjectSiteOdk.project_id == project.project_id,
            MasFormTypes.is_active.is_(True),
        )
        .group_by(
            MasFormTypes.form_type_code,
            MasFormTypes.form_type_name,
            MasFormTypes.base_instrument_code,
        )
    ).all()

    web_rows = db.session.execute(
        sa.select(
            MasFormTypes.form_type_code,
            MasFormTypes.form_type_name,
            MasFormTypes.base_instrument_code,
        )
        .distinct()
        .join(VaForms, VaForms.form_type_id == MasFormTypes.form_type_id)
        .where(
            VaForms.project_id == project.project_id,
            VaForms.form_source == "web",
            VaForms.form_status == VaStatuses.active,
            MasFormTypes.is_active.is_(True),
        )
    ).all()

    entries: dict[str, dict] = {}

    def _remember(code, name, base_instrument_code, sites):
        entry = entries.setdefault(
            code,
            {
                "form_type_code": code,
                "instrument_code": (base_instrument_code or "").strip() or None,
                "title": name,
                "sites": 0,
            },
        )
        entry["sites"] = max(entry["sites"], sites)

    for row in odk_rows:
        _remember(row.form_type_code, row.form_type_name, row.base_instrument_code, row.sites)
    for row in web_rows:
        _remember(row.form_type_code, row.form_type_name, row.base_instrument_code, 0)

    default_code = None
    if project.web_intake_mode != "off":
        web_form_type = _web_form_type_row(project)
        if web_form_type is not None:
            _remember(
                web_form_type.form_type_code,
                web_form_type.form_type_name,
                web_form_type.base_instrument_code,
                0,
            )
            default_code = web_form_type.form_type_code

    ordered = sorted(
        entries.values(), key=lambda entry: (-entry["sites"], entry["form_type_code"])
    )
    if default_code is None and ordered:
        default_code = ordered[0]["form_type_code"]

    return [
        {
            "form_type_code": entry["form_type_code"],
            "instrument_code": entry["instrument_code"],
            "title": entry["title"],
            "is_default": entry["form_type_code"] == default_code,
        }
        for entry in ordered
    ]


def _active_languages() -> dict[str, str]:
    """Active ``{code: label}`` from the canonical language list, in code order.

    Narration languages only. The form's *display* languages come from the
    bundled instrument (``app/services/web_form_instruments.py``), not from
    ``mas_languages``: a code here describes the language a narrative was
    recorded in and says nothing about what the questionnaire can render.
    """
    rows = db.session.execute(
        sa.select(MasLanguages.language_code, MasLanguages.language_name)
        .where(MasLanguages.is_active.is_(True))
        .order_by(MasLanguages.language_code)
    ).all()
    return {row.language_code: row.language_name for row in rows}


def _resolve_locales(
    project: VaProjectMaster, instrument_code: str | None
) -> tuple[str, list[dict]]:
    """The locale the form opens in and the locales it may be switched to.

    Decided 2026-09-19 (docs/policy/va-web-form-options.md): the display
    languages are the ones the bundled instrument actually has translations
    for, so they come from ``app/services/web_form_instruments.py`` and never
    from ``mas_languages``. ``DEFAULT_LOCALE`` is the instrument's base
    language: it is always offered, always first, and is the default whenever
    the stored default names something the instrument does not have.

    ``web_intake_available_locales`` NULL means every instrument locale; a
    stored list keeps the codes the instrument has, in stored order, and drops
    the rest. A misconfigured language degrades the form, never fails the page.

    Each entry carries ``under_review``: true for an ``in_review`` locale, which
    the form offers only with its English forced on beside every string
    (decided 2026-09-21, "English alongside the translation").
    """
    locales, under_review = instrument_locale_catalogue(instrument_code)

    default = project.web_intake_default_locale
    if default not in locales:
        if default and default != DEFAULT_LOCALE:
            current_app.logger.warning(
                "Project %s web_intake_default_locale %r is not a locale of "
                "instrument %r; opening in %r.",
                project.project_id,
                default,
                instrument_code,
                DEFAULT_LOCALE,
            )
        default = DEFAULT_LOCALE

    stored = project.web_intake_available_locales
    codes = list(locales) if stored is None else [c for c in stored if c in locales]

    ordered: list[str] = []
    for code in [DEFAULT_LOCALE, *codes, default]:
        if code not in ordered:
            ordered.append(code)
    return default, [
        {"code": code, "label": locales[code], "under_review": code in under_review}
        for code in ordered
    ]


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
    intake_note: str,
) -> list[str]:
    """Which form sections this project's configuration turns on.

    Derived, never stored. ``social_autopsy`` follows
    ``social_autopsy_collect_enabled`` ("Collect Social Autopsy"), not the
    coder's analysis switch (digitva-rglh). ``intake_screen`` follows the resolved welcome note
    -- a project that blanked the note wants no welcome screen -- and
    ``death_summary`` and ``medical_records`` each follow their own project
    switch, on unless an administrator turned it off (decided 2026-09-19,
    docs/policy/va-web-form-options.md); ``equity`` follows
    ``web_intake_equity_enabled``, off unless turned on. ``digitva_core`` and
    ``doris_support_whova_2022`` are always on: every web form asks the
    DORIS support questions, whatever the COD entry mode (decided
    2026-09-29, digitva-hln). The document upload itself lands with
    attachments phase 2; the extension is served now so the page can be built
    against the contract rather than against a constant.
    """
    extensions = ["digitva_core", "doris_support_whova_2022"]
    if project.social_autopsy_collect_enabled:
        extensions.append("social_autopsy")
    if intake_note:
        extensions.append("intake_screen")
    if project.web_intake_death_summary_enabled:
        extensions.append("death_summary")
    if project.web_intake_medical_records_enabled:
        extensions.append("medical_records")
    if project.web_intake_equity_enabled:
        extensions.append("equity")

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


def project_instrument_and_extensions(project: VaProjectMaster) -> tuple[str, list[str]]:
    """The instrument code the project's default form type layers on (the
    standard fallback when none is set) and its ``enabled_extensions``, exactly
    as form-options resolves them."""
    form_types = _project_form_types(project)
    default_form_type = next((ft for ft in form_types if ft["is_default"]), None)
    code = (default_form_type or {}).get("instrument_code") or FALLBACK_INSTRUMENT_CODE
    extensions = _enabled_extensions(
        project,
        form_types,
        _resolve_narration_languages(project, _active_languages()),
        resolve_intake_note(project),
    )
    return code, extensions


def served_instrument_locales(project: VaProjectMaster) -> tuple[str, set[str]]:
    """The instrument code this project's questionnaire uses and the locale
    codes it offers, exactly as ``form_options_payload`` resolves them."""
    default_form_type = next((ft for ft in _project_form_types(project) if ft["is_default"]), None)
    instrument_code = (default_form_type or {}).get("instrument_code")
    _default, available = _resolve_locales(project, instrument_code)
    return resolved_instrument_code(instrument_code), {entry["code"] for entry in available}


def form_options_payload(project: VaProjectMaster) -> dict:
    """The form-options body for *project*; the caller decides access."""
    project_id = project.project_id
    active = _active_languages()
    form_types = _project_form_types(project)
    default_form_type = next((ft for ft in form_types if ft["is_default"]), None)
    default_locale, available_locales = _resolve_locales(
        project, default_form_type["instrument_code"] if default_form_type else None
    )
    narration_languages = _resolve_narration_languages(project, active)
    intake_note = resolve_intake_note(project)
    # What an already-open page revalidates its cached translations against:
    # the version of every locale this instrument currently serves.
    # Resolved like available_locales (fallback to WHO_2022_VA when the
    # project's instrument has no servable locale), so the two agree.
    translation_versions = active_locale_versions(
        resolved_instrument_code(
            default_form_type["instrument_code"] if default_form_type else None
        )
    )

    enabled_extensions = _enabled_extensions(
        project, form_types, narration_languages, intake_note
    )
    # The composed definition exists for the WHO 2022 instrument only; a
    # project on any other instrument is served neither value.
    served_code = (default_form_type or {}).get("instrument_code") or FALLBACK_INSTRUMENT_CODE
    instrument_version = definition_sha256 = None
    if served_code == served_form_service.INSTRUMENT_CODE:
        try:
            instrument_version = served_form_service.composed_version()
            definition_sha256 = served_form_service.served_definition(enabled_extensions).sha256
        except served_form_service.ServedFormUnavailable:
            # The options must not fail with the generated file: the app
            # keeps its bundled form (null version) until it is rebuilt.
            current_app.logger.exception("form-options: composed definition unavailable")

    return {
        "project_id": project_id,
        "config_version": _config_version(project_id),
        "enabled_extensions": enabled_extensions,
        "form_types": form_types,
        # The text the intake_screen extension renders, or null when the
        # project turned the welcome screen off.
        "intake_note": intake_note or None,
        "default_locale": default_locale,
        "available_locales": available_locales,
        # {locale: version} for every locale served, "en" at 0. A client caches
        # a locale's strings by version and re-fetches only when it moves.
        "translation_versions": translation_versions,
        "narration_languages": narration_languages,
        "show_guidance": project.web_intake_show_guidance,
        # What the removed device bootstrap carried, per project and global:
        # which capture paths are open, and the composed form version the
        # server serves; definition_sha256 fingerprints this project's slice
        # of it so an app with that definition cached skips the fetch.
        "web_intake_mode": project.web_intake_mode or "off",
        "instrument_version": instrument_version,
        "definition_sha256": definition_sha256,
    }
