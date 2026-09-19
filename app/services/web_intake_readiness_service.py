"""Is a project actually able to capture a VA through the browser form?

WP2 of ``docs/planning/web-capture-project-configuration-plan.md``. The rules
an administrator has to satisfy are spread over five panels — Projects,
Project Sites, Organization, Access Grants, Form Types — and nothing said
whether they line up. This module is the one place that answers it, and
``docs/policy/web-intake.md`` ("Ready for web capture") is the rule it
implements.

Pure reads: nothing here creates a web form, a site or a grant. It reuses the
helpers the runtime path itself uses, so what the check reports and what an
interviewer's page does cannot drift apart.

Every query is bounded — one round trip per check, never one per site, unit or
grant — because the Projects panel asks for one badge per visible row.
"""
from __future__ import annotations

import functools
import logging
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgLevel,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaStatuses,
    VaUserAccessGrants,
    VaUsers,
)
from app.services import organization_service as org
from app.services.web_form_instruments import instrument_locales
from app.services.web_intake_service import get_web_intake_mode

log = logging.getLogger(__name__)

__all__ = [
    "WebIntakeReadinessError",
    "CHECK_CODES",
    "assess_web_intake_readiness",
]


class WebIntakeReadinessError(LookupError):
    """The project asked about does not exist."""


#: Every check this module reports, in the order it reports them. Published so
#: the panel, the CLI and the tests all name the same set.
CHECK_CODES = (
    "mode",
    "sites",
    "web_forms",
    "form_type",
    "org_tree",
    "geography_fields",
    "interviewers",
    "coding_scope",
    "locales",
)

#: The XLSForm the vendored WHO 2022 instrument is built from. It is the only
#: description of the bundled questionnaire's field list that ships with the
#: application: ``app/static/vendor/who-va-2022/manifest.json`` records the
#: build, not the fields.
_REFERENCE_XLSFORM = (
    Path(__file__).resolve().parents[2]
    / "vendor"
    / "who-va-2022"
    / "whova2022_xls_form_for_odk.xlsx"
)

#: The instrument ``_REFERENCE_XLSFORM`` describes. Any other instrument code
#: has no field list here, and the geography check says so rather than
#: measuring one questionnaire against another's fields.
_REFERENCE_INSTRUMENT_CODE = "WHO_2022_VA"


def _check(code: str, status: str, message: str, fix_hint: str = "") -> dict:
    return {
        "code": code,
        "status": status,
        "message": message,
        "fix_hint": fix_hint,
    }


@functools.cache
def _bundled_instrument_fields() -> frozenset[str] | None:
    """Field names of the bundled WHO 2022 questionnaire, or ``None``.

    Read once per process from the reference XLSForm's ``survey`` sheet — the
    same workbook ``xlsform_instrument_builder`` converts — and cached, because
    a readiness check runs once per project row of the Projects panel and
    parsing a 479-row workbook per row would be absurd.

    ``None`` means the workbook is not on this deployment (it is a development
    checkout artefact), which the geography check reports as unverified rather
    than as a missing field.
    """
    if not _REFERENCE_XLSFORM.exists():
        log.info(
            "Reference XLSForm %s is not present; the web-capture geography "
            "check cannot verify the instrument's field list.",
            _REFERENCE_XLSFORM,
        )
        return None
    try:
        import pandas as pd

        survey = pd.read_excel(_REFERENCE_XLSFORM, sheet_name="survey", usecols=["name"])
    except Exception:  # noqa: BLE001 - a readiness check never fails the page
        log.warning(
            "Could not read the reference XLSForm %s; the web-capture "
            "geography check will report the field list as unverified.",
            _REFERENCE_XLSFORM,
            exc_info=True,
        )
        return None
    return frozenset(
        str(name).strip() for name in survey["name"].dropna() if str(name).strip()
    )


# ── individual checks ───────────────────────────────────────────────────────


def _check_mode(project: VaProjectMaster) -> dict:
    mode = get_web_intake_mode(project.project_id)
    if project.project_status != VaStatuses.active:
        return _check(
            "mode",
            "fail",
            "The project is not active, so no grant on it resolves and web "
            "intake is off whatever the setting says.",
            "Reactivate the project in the Projects panel.",
        )
    if mode == "off":
        return _check(
            "mode",
            "fail",
            "Web intake is off: this project collects through ODK only.",
            "Set Web Intake to direct, death_register or both in the Projects panel.",
        )
    return _check("mode", "ok", f"Web intake is on ({mode}).")


def _active_site_ids(project_id: str) -> list[str]:
    return list(
        db.session.scalars(
            sa.select(VaProjectSites.site_id)
            .where(
                VaProjectSites.project_id == project_id,
                VaProjectSites.project_site_status == VaStatuses.active,
            )
            .order_by(VaProjectSites.site_id)
        ).all()
    )


def _check_sites(site_ids: list[str]) -> dict:
    if not site_ids:
        return _check(
            "sites",
            "fail",
            "The project has no active site. Web forms are created per "
            "project-site, so there is nothing to collect against.",
            "Add a site to the project in the Project Sites panel.",
        )
    return _check("sites", "ok", f"{len(site_ids)} active site(s).")


def _check_web_forms(project: VaProjectMaster, site_ids: list[str]) -> dict:
    """One active web ``va_forms`` row per active site, carrying the right type.

    Interviewer access resolves through ``va_forms``
    (``VaUsers._get_granted_va_forms``), so a site without the row is a site
    nobody can open the questionnaire for. An existing row deliberately keeps
    the form type it was created with
    (``runtime_form_sync_service.ensure_web_runtime_form``), so a type that no
    longer matches the project setting is drift to report, not an error.
    """
    if not site_ids:
        return _check(
            "web_forms",
            "fail",
            "No web form rows exist, because the project has no active site.",
            "Add a site first; the web forms are materialized with it.",
        )
    rows = db.session.execute(
        sa.select(VaForms.site_id, VaForms.form_type_id).where(
            VaForms.project_id == project.project_id,
            VaForms.form_source == "web",
            VaForms.form_status == VaStatuses.active,
        )
    ).all()
    by_site = {row.site_id: row.form_type_id for row in rows}
    missing = [site_id for site_id in site_ids if site_id not in by_site]
    if missing:
        return _check(
            "web_forms",
            "fail",
            "No active web form for site(s) " + ", ".join(missing) + ".",
            "Re-save the project's Web Intake setting; the web forms are "
            "created for every active site when it is switched on.",
        )
    configured = project.web_intake_form_type_id
    if configured is not None:
        drifted = sorted(
            site_id
            for site_id, form_type_id in by_site.items()
            if form_type_id != configured
        )
        if drifted:
            return _check(
                "web_forms",
                "warn",
                "The web form for site(s) " + ", ".join(drifted) + " carries a "
                "different questionnaire from the one the project now names. "
                "An existing form keeps its type so the questionnaire cannot "
                "change under drafts already being filled.",
                "Leave it if those sites should keep collecting on the old "
                "questionnaire; otherwise retire the form and let a new one be "
                "created.",
            )
    return _check("web_forms", "ok", f"A web form exists for all {len(site_ids)} site(s).")


def _check_form_type(project: VaProjectMaster) -> tuple[dict, str | None]:
    """The default questionnaire is usable, and the instrument it layers on.

    Returns the check and the resolved ``instrument_code``, which the locales
    check needs and must not resolve a second time.
    """
    from app.routes.api.organization import _project_form_types
    from app.services.field_mapping_service import get_mapping_service

    default = next(
        (entry for entry in _project_form_types(project) if entry["is_default"]), None
    )
    if default is None:
        return (
            _check(
                "form_type",
                "fail",
                "No form type resolves for this project, so the intake page "
                "has no questionnaire to render.",
                "Set a Web form questionnaire on the project, or register an "
                "active WHO_2022_VA form type.",
            ),
            None,
        )
    code = default["form_type_code"]
    instrument_code = default["instrument_code"]
    if not instrument_code:
        return (
            _check(
                "form_type",
                "fail",
                f"Form type {code} has no base_instrument_code, so no "
                "questionnaire is bundled for it.",
                "Set base_instrument_code on the form type; see "
                "docs/policy/new-form-type-onboarding.md.",
            ),
            None,
        )
    if not get_mapping_service().is_pii_set_confirmed(code):
        return (
            _check(
                "form_type",
                "fail",
                f"Form type {code} has an unconfirmed PII set, so it may not "
                "collect real interviews: redaction fails closed on every "
                "field it owns.",
                "Confirm the PII set in the Field Mapping panel; see "
                "docs/policy/new-form-type-onboarding.md.",
            ),
            instrument_code,
        )
    return (
        _check(
            "form_type",
            "ok",
            f"Questionnaire {code} on instrument {instrument_code}, PII set confirmed.",
        ),
        instrument_code,
    )


def _check_org_tree(project_id: str, levels: list[MasOrgLevel]) -> dict:
    """A tree project must have live units at its deepest mandatory level.

    Routing attributes a submission to the deepest code naming a live unit,
    and coding eligibility is decided by the routed unit
    (docs/policy/organization-model.md), so a mandatory level with no active
    unit is a project whose submissions reach no coder.
    """
    if not levels:
        return _check(
            "org_tree",
            "warn",
            "The project has no organization tree, so submissions route the "
            "legacy way, through the project-site mapping only.",
            "Seed a tree in the Organization panel if unit-scoped coding is "
            "wanted; nothing is broken without one.",
        )
    counts = dict(
        db.session.execute(
            sa.select(MasOrgUnit.org_level_id, sa.func.count())
            .where(
                MasOrgUnit.project_id == project_id,
                MasOrgUnit.is_active.is_(True),
            )
            .group_by(MasOrgUnit.org_level_id)
        ).all()
    )
    required = [level for level in levels if not level.is_optional]
    empty = [
        level.level_code for level in required if not counts.get(level.org_level_id)
    ]
    if empty:
        return _check(
            "org_tree",
            "fail",
            "No active organization unit at required level(s) "
            + ", ".join(empty)
            + ". A submission that routes to no live unit reaches no coder.",
            "Add units at those levels in the Organization panel, or mark the "
            "level optional.",
        )
    deepest = required[-1] if required else levels[-1]
    return _check(
        "org_tree",
        "ok",
        f"{sum(counts.values())} active unit(s); the deepest required level "
        f"({deepest.level_code}) is populated.",
    )


def _check_geography_fields(
    levels: list[MasOrgLevel], instrument_code: str | None
) -> dict:
    """Does the bundled questionnaire itself carry the level code fields?

    The web form does not need them: ``web_intake_service._unit_context``
    fills every ``org_<level_code>_code`` from the unit the interviewer chose,
    server-side at submission. This check is about the instrument, which is
    what a project that *also* collects the same questionnaire through ODK
    depends on, and it is a warning for exactly that reason.
    """
    if not levels:
        return _check(
            "geography_fields",
            "ok",
            "No organization tree, so no geography fields are expected.",
        )
    if instrument_code != _REFERENCE_INSTRUMENT_CODE:
        return _check(
            "geography_fields",
            "warn",
            "The questionnaire's field list could not be verified: no "
            f"reference XLSForm is bundled for instrument {instrument_code!r}.",
            "Check by hand that the ODK form for this project carries an "
            "org_<level>_code field per level.",
        )
    fields = _bundled_instrument_fields()
    if fields is None:
        return _check(
            "geography_fields",
            "warn",
            "The questionnaire's field list could not be verified: the "
            "reference XLSForm is not readable on this deployment.",
            "Check by hand that the ODK form for this project carries an "
            "org_<level>_code field per level.",
        )
    missing = [
        org.odk_field_name_for_level(level.level_code)
        for level in levels
        if org.odk_field_name_for_level(level.level_code) not in fields
    ]
    if missing:
        return _check(
            "geography_fields",
            "warn",
            "The bundled questionnaire has no " + ", ".join(missing) + " field. "
            "The web form still routes correctly — it fills those codes from "
            "the unit the interviewer chose, at submission.",
            "Add the fields to the project's ODK XLSForm if the same "
            "questionnaire is also collected through ODK Central.",
        )
    return _check(
        "geography_fields",
        "ok",
        f"The questionnaire carries a code field for all {len(levels)} level(s).",
    )


def _interviewer_grant_scopes(project_id: str) -> set[VaAccessScopeTypes]:
    """Which scopes an active interviewer grant on this project exists at.

    Three bounded EXISTS-shaped lookups, one per scope a grant may carry. A
    grant held by a deactivated user is not counted: it reaches nobody.
    """
    scopes: set[VaAccessScopeTypes] = set()
    base = (
        sa.select(sa.literal(1))
        .select_from(VaUserAccessGrants)
        .join(VaUsers, VaUsers.user_id == VaUserAccessGrants.user_id)
        .where(
            VaUserAccessGrants.role == VaAccessRoles.interviewer,
            VaUserAccessGrants.grant_status == VaStatuses.active,
            VaUsers.user_status == VaStatuses.active,
        )
    )
    if db.session.scalar(
        base.where(
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project,
            VaUserAccessGrants.project_id == project_id,
        ).limit(1)
    ):
        scopes.add(VaAccessScopeTypes.project)
    if db.session.scalar(
        base.join(
            VaProjectSites,
            VaProjectSites.project_site_id == VaUserAccessGrants.project_site_id,
        ).where(
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.project_site,
            VaProjectSites.project_id == project_id,
            VaProjectSites.project_site_status == VaStatuses.active,
        ).limit(1)
    ):
        scopes.add(VaAccessScopeTypes.project_site)
    if db.session.scalar(
        base.join(
            MasOrgUnit, MasOrgUnit.org_unit_id == VaUserAccessGrants.org_unit_id
        ).where(
            VaUserAccessGrants.scope_type == VaAccessScopeTypes.org_unit,
            MasOrgUnit.project_id == project_id,
            MasOrgUnit.is_active.is_(True),
        ).limit(1)
    ):
        scopes.add(VaAccessScopeTypes.org_unit)
    return scopes


def _check_interviewers(project_id: str, levels: list[MasOrgLevel]) -> dict:
    scopes = _interviewer_grant_scopes(project_id)
    if not scopes:
        return _check(
            "interviewers",
            "fail",
            "No active user holds an interviewer grant that reaches this "
            "project, so nobody can open the questionnaire.",
            "Grant the interviewer role in the Access Grants panel, at "
            "project, project-site or organization-unit scope.",
        )
    if levels and VaAccessScopeTypes.org_unit not in scopes:
        return _check(
            "interviewers",
            "warn",
            "Every interviewer grant is project- or site-scoped. In a project "
            "with an organization tree such an interviewer may name any unit, "
            "so nothing narrows what they may attribute a death to.",
            "Grant unit-scoped interviewer access where the interviewer "
            "belongs to one unit.",
        )
    return _check(
        "interviewers",
        "ok",
        "Interviewer access is granted at "
        + ", ".join(sorted(scope.value for scope in scopes))
        + " scope.",
    )


def _check_coding_scope(project: VaProjectMaster) -> dict:
    """Unit-scoped coding is a pick-and-choose workflow, never random allocation.

    Random allocation would hand a coder submissions from outside their own
    units (docs/policy/organization-model.md), so the two settings together
    are a configuration that collects cases nobody may code.
    """
    if project.coding_scope_level_id is None:
        return _check(
            "coding_scope",
            "ok",
            "No coding scope level is set, so coding is not restricted by unit.",
        )
    if project.coding_intake_mode != "pick_and_choose":
        return _check(
            "coding_scope",
            "fail",
            "A coding scope level is set but the coding intake mode is "
            f"{project.coding_intake_mode!r}. Random allocation would hand a "
            "coder submissions from outside their own units.",
            "Set Coding Intake Mode to pick_and_choose, or clear the coding "
            "scope level.",
        )
    return _check(
        "coding_scope",
        "ok",
        "Unit-scoped coding with pick-and-choose intake.",
    )


def _check_locales(project: VaProjectMaster, instrument_code: str | None) -> dict:
    """Every stored display language is one the instrument actually has.

    ``_resolve_locales`` drops an unknown code rather than failing the page,
    so a project can quietly be offering fewer languages than it was
    configured with. This is where that is said out loud.
    """
    stored = project.web_intake_available_locales
    if stored is None:
        return _check(
            "locales",
            "ok",
            "Every language the questionnaire has is offered.",
        )
    available = set(instrument_locales(instrument_code))
    unknown = [code for code in stored if code not in available]
    if unknown:
        return _check(
            "locales",
            "warn",
            "Configured display language(s) " + ", ".join(unknown) + " are not "
            f"translated in instrument {instrument_code or 'WHO_2022_VA'}; the "
            "form drops them and opens in English.",
            "Remove them in the Projects panel, or import the translations "
            "for that language.",
        )
    return _check(
        "locales",
        "ok",
        f"{len(stored)} display language(s), all translated in the instrument.",
    )


# ── the assessment ──────────────────────────────────────────────────────────


def assess_web_intake_readiness(project_id: str) -> dict:
    """Whether *project_id* can capture a VA through the browser form.

    Returns ``{"project_id", "ready", "checks": [...]}`` where each check is
    ``{"code", "status", "message", "fix_hint"}`` and ``status`` is one of
    ``ok``, ``warn``, ``fail``. ``ready`` is true when no check failed: a
    warning describes something an administrator should look at, never
    something that stops an interview.

    Raises ``WebIntakeReadinessError`` when the project does not exist. Pure
    reads; the session is left untouched.
    """
    project = db.session.get(VaProjectMaster, project_id)
    if project is None:
        raise WebIntakeReadinessError(f"Project {project_id} not found.")

    site_ids = _active_site_ids(project_id)
    levels = org.list_levels(project_id)
    form_type_check, instrument_code = _check_form_type(project)

    checks = [
        _check_mode(project),
        _check_sites(site_ids),
        _check_web_forms(project, site_ids),
        form_type_check,
        _check_org_tree(project_id, levels),
        _check_geography_fields(levels, instrument_code),
        _check_interviewers(project_id, levels),
        _check_coding_scope(project),
        _check_locales(project, instrument_code),
    ]
    return {
        "project_id": project_id,
        "ready": not any(check["status"] == "fail" for check in checks),
        "checks": checks,
    }
