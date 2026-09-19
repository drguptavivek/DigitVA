"""Web intake of WHO VA 2022 questionnaires: death register, drafts, submission.

Plan: docs/planning/who-va-2022-web-intake-plan.md
Policy: docs/policy/web-intake.md

Deep module: every rule of the web intake path lives here. Routes only parse
requests and serialize results. A submitted questionnaire becomes a
``va_submissions`` row through exactly the projection and workflow entry
that ODK sync uses, so SmartVA, coding and reporting see no difference
between the two sources.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, date, datetime

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgUnit,
    VaAccessRoles,
    VaDeathRegister,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionsAuditlog,
    VaUsers,
    VaWebIntakeDraft,
    VaWebIntakeDraftSection,
)
from app.models.va_web_intake import (
    DEATH_NUMBER_SEQUENCE,
    DEATH_SEX_VALUES,
    WEB_INTAKE_MODES,
)
from app.services import org_grant_service
from app.services import organization_service as org
from app.services.runtime_form_sync_service import ensure_web_runtime_form
from app.services import org_unit_routing_service as org_routing
from app.services.submission_payload_version_service import ensure_active_payload_version
from app.services.va_data_sync.va_data_sync_01_odkcentral import (
    build_submission_projection,
    consent_is_valid,
    normalize_consent,
)
from app.services.workflow.transitions import (
    mark_attachment_sync_completed,
    route_synced_submission,
    system_actor,
)

log = logging.getLogger(__name__)

__all__ = [
    "WebIntakeError",
    "WEB_INTAKE_MODES",
    "WEB_PROJECT_DEFAULTS",
    "DEFAULT_INTAKE_NOTE",
    "INSTRUMENT_ID",
    "resolve_intake_note",
    "get_web_intake_mode",
    "interviewer_context",
    "register_death",
    "list_deaths",
    "get_death",
    "start_draft",
    "list_drafts",
    "get_draft",
    "load_draft_envelope",
    "save_draft_sections",
    "discard_draft",
    "submit_draft",
    "build_web_payload",
    "serialize_death",
    "serialize_draft",
]

INSTRUMENT_ID = "va_who_2022"
ATTACHMENT_REFERENCE_PREFIX = "who-va-attachment:"
AUDIT_ROLE = "vainterviewer"
PAYLOAD_ROLE = "vainterviewer"
_ABHA_NUMBER_RE = re.compile(r"^(\d{14}|\d{2}-\d{4}-\d{4}-\d{4})$")
_ABHA_ADDRESS_RE = re.compile(r"^[A-Za-z0-9._]{4,32}@(abdm|sbx)$")
_SECTION_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")

#: The welcome note a project shows before the questionnaire starts when it
#: has not written one of its own. A constant rather than a stored default so
#: the wording can change without a migration: a NULL
#: ``web_intake_intake_note`` resolves to this text, an empty string means the
#: project wants no welcome screen. Decided 2026-09-19,
#: docs/policy/va-web-form-options.md.
DEFAULT_INTAKE_NOTE = (
    "Before you begin: confirm the respondent has consented, is comfortable, "
    "and has time for the interview. Answers are saved as you go."
)

#: What a project that collects on the web is created with when the client
#: says nothing (docs/planning/web-capture-project-configuration-plan.md, WP1).
#: Applied by POST /admin/api/projects to every key the payload omits whenever
#: ``web_intake_mode`` is not ``off``; an explicit value always wins. The two
#: language lists are filtered to the codes the validators accept before they
#: are applied, so a deployment that has not vendored Hindi translations or
#: seeded the language rows still creates the project instead of failing it.
WEB_PROJECT_DEFAULTS = {
    "web_intake_form_type_code": "WHO_2022_VA",
    "web_intake_intake_note": None,
    "web_intake_death_summary_enabled": True,
    "social_autopsy_enabled": False,
    "web_intake_available_locales": ["en", "hi"],
    "web_intake_narration_languages": ["english", "hindi"],
    "coding_intake_mode": "pick_and_choose",
}


def resolve_intake_note(project: VaProjectMaster) -> str:
    """The welcome note this project shows, ``""`` when it shows none.

    NULL is "the project never set one", which is the system default text;
    a stored empty (or whitespace-only) string is a project that deliberately
    turned the welcome screen off. The ``intake_screen`` extension is served
    exactly when this is non-empty.
    """
    note = project.web_intake_intake_note
    if note is None:
        return DEFAULT_INTAKE_NOTE
    return note.strip()



class WebIntakeError(ValueError):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Project mode and interviewer scope
# ---------------------------------------------------------------------------


def get_web_intake_mode(project_id: str) -> str:
    project = db.session.get(VaProjectMaster, project_id)
    if project is None or project.project_status != VaStatuses.active:
        return "off"
    return project.web_intake_mode or "off"


def _mode_allows(mode: str, *, death_register: bool) -> bool:
    if mode == "both":
        return True
    return mode == ("death_register" if death_register else "direct")


def interviewer_context(user: VaUsers) -> list[dict]:
    """Projects and sites where this user may fill questionnaires.

    One entry per (project, site) reachable through interviewer grants at
    project, project-site or organization-unit scope, for projects whose
    web intake is switched on. Unit grants list the units the interviewer
    belongs to so drafts and deaths can be attributed to a unit.
    """
    form_ids = user.get_interviewer_va_forms()
    pairs: dict[tuple[str, str], dict] = {}
    if form_ids:
        rows = db.session.execute(
            sa.select(VaForms.project_id, VaForms.site_id)
            .where(VaForms.form_id.in_(list(form_ids)))
            .distinct()
        ).all()
        for project_id, site_id in rows:
            pairs[(project_id, site_id)] = {"org_units": []}

    for unit in org_grant_service.granted_units(user.user_id, VaAccessRoles.interviewer):
        site_ids = db.session.scalars(
            sa.select(VaProjectSites.site_id).where(
                VaProjectSites.project_id == unit.project_id,
                VaProjectSites.project_site_status == VaStatuses.active,
            ).order_by(VaProjectSites.site_id)
        ).all()
        for site_id in site_ids:
            entry = pairs.setdefault((unit.project_id, site_id), {"org_units": []})
            entry["org_units"].append(
                {
                    "org_unit_id": str(unit.org_unit_id),
                    "unit_code": unit.unit_code,
                    "unit_name": unit.unit_name,
                    "path": str(unit.path),
                }
            )

    if not pairs:
        return []
    project_ids = {p for p, _ in pairs}
    projects = {
        p.project_id: p
        for p in db.session.scalars(
            sa.select(VaProjectMaster).where(
                VaProjectMaster.project_id.in_(project_ids),
                VaProjectMaster.project_status == VaStatuses.active,
            )
        )
    }
    sites = {
        s.site_id: s
        for s in db.session.scalars(
            sa.select(VaSiteMaster).where(VaSiteMaster.site_id.in_({s for _, s in pairs}))
        )
    }
    active_pairs = set(
        db.session.execute(
            sa.select(VaProjectSites.project_id, VaProjectSites.site_id).where(
                VaProjectSites.project_id.in_(project_ids),
                VaProjectSites.project_site_status == VaStatuses.active,
            )
        ).all()
    )
    context = []
    for (project_id, site_id), entry in sorted(pairs.items()):
        project = projects.get(project_id)
        if project is None or (project_id, site_id) not in active_pairs:
            continue
        mode = project.web_intake_mode or "off"
        if mode == "off":
            continue
        site = sites.get(site_id)
        context.append(
            {
                "project_id": project_id,
                "project_name": project.project_name,
                "site_id": site_id,
                "site_name": site.site_name if site else site_id,
                "web_intake_mode": mode,
                "org_units": entry["org_units"],
            }
        )
    return context


def _reachable_unit_ids(user: VaUsers, project_id: str) -> set[uuid.UUID] | None:
    """Active units of *project_id* this interviewer may attribute an entry to.

    ``None`` means the whole tree: the user holds a project- or site-scoped
    interviewer grant there, which by design reaches every unit (that is the
    point of a grant wider than one unit) — mirroring what
    ``org_grant_service.project_wide_grant_exists`` means for the
    organization API's picker. Otherwise the union of the user's
    interviewer unit-scoped grants' subtrees, filtered to this project.

    Mirrors ``app/routes/api/organization.py::_reachable_unit_ids`` for
    ``role=interviewer`` — no admin/project-manager bypass here, since web
    intake access is strictly grant-based. Both share
    ``org_grant_service.project_wide_grant_exists`` so the unit picker an
    interviewer sees and this check their submission is held to cannot
    silently disagree.
    """
    roles = frozenset({VaAccessRoles.interviewer})
    if org_grant_service.project_wide_grant_exists(user.user_id, project_id, roles):
        return None
    reachable = org_grant_service.scope_unit_ids(user.user_id, VaAccessRoles.interviewer)
    if not reachable:
        return set()
    in_project = db.session.scalars(
        sa.select(MasOrgUnit.org_unit_id).where(
            MasOrgUnit.project_id == project_id,
            MasOrgUnit.org_unit_id.in_(sorted(reachable)),
        )
    ).all()
    return set(in_project)


def _require_scope(user: VaUsers, project_id: str, site_id: str, org_unit_id: object | None) -> dict:
    """Return the context entry for (project, site) or raise 403.

    In a project with an organization tree, a unit must always be named,
    whatever the grant's scope — the routed unit is what makes a submission
    codeable at all (docs/policy/organization-model.md phase 4), and an
    unrouted one is invisible to every coder. A project- or site-scoped
    interviewer grant may name *any* active unit of the project; a
    unit-scoped grant is held to its own subtree. A project with no tree
    keeps the pre-phase-4 behaviour: no unit is required.
    """
    entry = None
    for candidate in interviewer_context(user):
        if candidate["project_id"] == project_id and candidate["site_id"] == site_id:
            entry = candidate
            break
    if entry is None:
        raise WebIntakeError("You do not have interviewer access to that project and site.", 403)

    has_tree = project_id in org_grant_service.projects_with_org_tree({project_id})
    if not has_tree:
        if org_unit_id:
            allowed = {u["org_unit_id"] for u in entry["org_units"]}
            if str(org_unit_id) not in allowed:
                raise WebIntakeError("You are not attached to that organization unit.", 403)
        elif entry["org_units"]:
            raise WebIntakeError("Choose the organization unit for this entry.", 400)
        return entry

    if not org_unit_id:
        raise WebIntakeError("Choose the organization unit for this entry.", 400)
    try:
        unit_id = uuid.UUID(str(org_unit_id))
    except (ValueError, TypeError, AttributeError):
        raise WebIntakeError("Invalid organization unit.", 400) from None

    reachable = _reachable_unit_ids(user, project_id)
    if reachable is not None and unit_id not in reachable:
        raise WebIntakeError("That organization unit is outside what you may access.", 403)

    unit = db.session.get(MasOrgUnit, unit_id)
    if unit is None or unit.project_id != project_id or not unit.is_active:
        raise WebIntakeError("That organization unit is not active in this project.", 400)

    return entry


# ---------------------------------------------------------------------------
# Unique ids and unit context
# ---------------------------------------------------------------------------


def _allocate_unique_id(prefix: str) -> tuple[int, str]:
    number = db.session.execute(sa.text(f"SELECT nextval('{DEATH_NUMBER_SEQUENCE}')")).scalar_one()
    return int(number), f"{prefix}-{int(number):06d}"


def _unit_context(org_unit_id: object | None) -> dict:
    """Ancestor codes of a unit keyed by level: {"org_<level>_code": code, ...}."""
    if not org_unit_id:
        return {}
    unit = db.session.get(MasOrgUnit, uuid.UUID(str(org_unit_id)))
    if unit is None:
        return {}
    codes = str(unit.path).split(".")
    # Routing attributes a submission to the deepest code naming a *live*
    # unit, so a deactivated ancestor's code would be inert at best and
    # misleading in the stored payload -- keep the active-only default.
    rows = org.list_units_by_codes(unit.project_id, codes)
    context: dict = {}
    for row in rows:
        context[f"org_{row['level_code']}_code"] = row["unit_code"]
        context[f"org_{row['level_code']}_name"] = row["unit_name"]
    return context


# ---------------------------------------------------------------------------
# Death register
# ---------------------------------------------------------------------------


def _clean(raw: object, *, what: str, required: bool = False, max_len: int | None = None) -> str | None:
    value = str(raw).strip() if raw is not None else ""
    if not value:
        if required:
            raise WebIntakeError(f"{what} is required.")
        return None
    if max_len and len(value) > max_len:
        raise WebIntakeError(f"{what} must be at most {max_len} characters.")
    return value


def _clean_date(raw: object, *, what: str, required: bool = False) -> date | None:
    value = _clean(raw, what=what, required=required)
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise WebIntakeError(f"{what} must be a date in YYYY-MM-DD form.") from exc
    if parsed > date.today():
        raise WebIntakeError(f"{what} cannot be in the future.")
    return parsed


def _clean_abha(number: object, address: object) -> tuple[str | None, str | None]:
    abha_number = _clean(number, what="ABHA number", max_len=17)
    abha_address = _clean(address, what="ABHA address", max_len=64)
    if abha_number and not _ABHA_NUMBER_RE.match(abha_number):
        raise WebIntakeError("ABHA number must be 14 digits (optionally grouped 2-4-4-4).")
    if abha_address and not _ABHA_ADDRESS_RE.match(abha_address):
        raise WebIntakeError("ABHA address must look like name@abdm.")
    return abha_number, abha_address


def register_death(user: VaUsers, *, project_id: str, site_id: str, org_unit_id: object | None = None, **fields) -> VaDeathRegister:
    mode = get_web_intake_mode(project_id)
    if not _mode_allows(mode, death_register=True):
        raise WebIntakeError("This project does not use the death register.", 403)
    _require_scope(user, project_id, site_id, org_unit_id)
    name = _clean(fields.get("deceased_name"), what="Deceased name", required=True)
    sex = (_clean(fields.get("deceased_sex"), what="Sex", required=True) or "").lower()
    if sex not in DEATH_SEX_VALUES:
        raise WebIntakeError("Sex must be one of " + ", ".join(DEATH_SEX_VALUES) + ".")
    date_of_death = _clean_date(fields.get("date_of_death"), what="Date of death", required=True)
    date_of_birth = _clean_date(fields.get("date_of_birth"), what="Date of birth")
    if date_of_birth and date_of_birth > date_of_death:
        raise WebIntakeError("Date of birth cannot be after the date of death.")
    age_years = None
    if fields.get("age_years") not in (None, ""):
        try:
            age_years = int(fields["age_years"])
        except (TypeError, ValueError) as exc:
            raise WebIntakeError("Age must be a whole number of years.") from exc
        if age_years < 0 or age_years > 130:
            raise WebIntakeError("Age must be between 0 and 130 years.")
    abha_number, abha_address = _clean_abha(fields.get("abha_number"), fields.get("abha_address"))
    unit = db.session.get(MasOrgUnit, uuid.UUID(str(org_unit_id))) if org_unit_id else None
    number, unique_id = _allocate_unique_id(unit.unit_code if unit else site_id)
    death = VaDeathRegister(
        project_id=project_id,
        site_id=site_id,
        org_unit_id=unit.org_unit_id if unit else None,
        death_number=number,
        unique_id=unique_id,
        deceased_name=name,
        deceased_sex=sex,
        abha_number=abha_number,
        abha_address=abha_address,
        date_of_birth=date_of_birth,
        age_years=age_years,
        date_of_death=date_of_death,
        place_of_death=_clean(fields.get("place_of_death"), what="Place of death"),
        address=_clean(fields.get("address"), what="Address"),
        informant_name=_clean(fields.get("informant_name"), what="Informant name"),
        informant_phone=_clean(fields.get("informant_phone"), what="Informant phone", max_len=32),
        remarks=_clean(fields.get("remarks"), what="Remarks"),
        registered_by=user.user_id,
    )
    db.session.add(death)
    db.session.flush()
    log.info("web intake death registered | project=%s | site=%s | unique_id=%s | by=%s", project_id, site_id, unique_id, user.user_id)
    return death


def list_deaths(user: VaUsers, *, project_id: str, site_id: str, status: str | None = None) -> list[VaDeathRegister]:
    entry = _require_scope(user, project_id, site_id, None) if not _has_units(user, project_id, site_id) else None
    stmt = sa.select(VaDeathRegister).where(
        VaDeathRegister.project_id == project_id, VaDeathRegister.site_id == site_id
    )
    if entry is None:
        unit_ids = _scope_unit_ids(user, project_id, site_id)
        stmt = stmt.where(VaDeathRegister.org_unit_id.in_(unit_ids))
    if status:
        stmt = stmt.where(VaDeathRegister.status == status)
    return list(db.session.scalars(stmt.order_by(VaDeathRegister.created_at.desc()).limit(500)).all())


def _has_units(user: VaUsers, project_id: str, site_id: str) -> bool:
    for entry in interviewer_context(user):
        if entry["project_id"] == project_id and entry["site_id"] == site_id:
            return bool(entry["org_units"])
    raise WebIntakeError("You do not have interviewer access to that project and site.", 403)


def _scope_unit_ids(user: VaUsers, project_id: str, site_id: str) -> list[uuid.UUID]:
    """All units in the subtrees of the user's interviewer unit grants."""
    return [
        unit_id
        for unit_id in org_grant_service.scope_unit_ids(user.user_id, VaAccessRoles.interviewer)
    ]


def get_death(user: VaUsers, death_id: object) -> VaDeathRegister:
    try:
        death = db.session.get(VaDeathRegister, uuid.UUID(str(death_id)))
    except ValueError:
        death = None
    if death is None:
        raise WebIntakeError("Death entry not found.", 404)
    _require_scope(user, death.project_id, death.site_id, death.org_unit_id)
    return death


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


def _prefill_from_death(death: VaDeathRegister | None, user: VaUsers) -> dict:
    prefill: dict = {"interviewer": {"name": user.name, "id": str(user.user_id)}}
    answers: dict = {}
    if death is not None:
        names = death.deceased_name.strip().split(" ", 1)
        deceased = {
            "givenNames": names[0],
            "sex": death.deceased_sex if death.deceased_sex in ("male", "female") else "undetermined",
            "dateOfDeath": death.date_of_death.isoformat(),
            "yearOfDeath": str(death.date_of_death.year),
        }
        if len(names) > 1:
            deceased["surname"] = names[1]
        if death.date_of_birth:
            deceased["dateOfBirth"] = death.date_of_birth.isoformat()
        elif death.age_years is not None and 12 <= death.age_years <= 119:
            deceased["ageInYears"] = death.age_years
        prefill["deceased"] = deceased
        if death.abha_number:
            answers["abha_number"] = death.abha_number
        if death.abha_address:
            answers["abha_address"] = death.abha_address
    prefill["answers"] = answers
    prefill["lockedQuestionNames"] = sorted(answers)
    return prefill


def start_draft(user: VaUsers, *, project_id: str, site_id: str, org_unit_id: object | None = None, death_id: object | None = None) -> VaWebIntakeDraft:
    mode = get_web_intake_mode(project_id)
    death = get_death(user, death_id) if death_id else None
    if death is not None:
        if not _mode_allows(mode, death_register=True):
            raise WebIntakeError("This project does not use the death register.", 403)
        if death.project_id != project_id or death.site_id != site_id:
            raise WebIntakeError("Death entry belongs to another project or site.")
        if death.status == "va_submitted":
            raise WebIntakeError("A questionnaire has already been submitted for this death.", 409)
        existing = db.session.scalar(
            sa.select(VaWebIntakeDraft).where(
                VaWebIntakeDraft.death_id == death.death_id, VaWebIntakeDraft.status == "draft"
            )
        )
        if existing is not None:
            if existing.user_id != user.user_id:
                raise WebIntakeError("Another interviewer already has a draft for this death.", 409)
            return existing
        org_unit_id = death.org_unit_id
    elif not _mode_allows(mode, death_register=False):
        raise WebIntakeError("This project requires a death register entry before the questionnaire.", 403)
    _require_scope(user, project_id, site_id, org_unit_id)
    form = ensure_web_runtime_form(project_id, site_id)
    if death is not None:
        unique_id = death.unique_id
    else:
        unit = db.session.get(MasOrgUnit, uuid.UUID(str(org_unit_id))) if org_unit_id else None
        _, unique_id = _allocate_unique_id(unit.unit_code if unit else site_id)
    now = _utcnow().isoformat()
    draft = VaWebIntakeDraft(
        project_id=project_id,
        site_id=site_id,
        org_unit_id=uuid.UUID(str(org_unit_id)) if org_unit_id else None,
        death_id=death.death_id if death else None,
        form_id=form.form_id,
        user_id=user.user_id,
        unique_id=unique_id,
        meta={"createdAt": now, "updatedAt": now, "instrumentId": INSTRUMENT_ID},
        prefill=_prefill_from_death(death, user),
    )
    db.session.add(draft)
    if death is not None:
        death.status = "va_in_progress"
    db.session.flush()
    log.info("web intake draft started | project=%s | site=%s | unique_id=%s | by=%s", project_id, site_id, unique_id, user.user_id)
    return draft


def list_drafts(user: VaUsers, *, status: str = "draft") -> list[VaWebIntakeDraft]:
    stmt = sa.select(VaWebIntakeDraft).where(VaWebIntakeDraft.user_id == user.user_id)
    if status:
        stmt = stmt.where(VaWebIntakeDraft.status == status)
    return list(db.session.scalars(stmt.order_by(VaWebIntakeDraft.updated_at.desc()).limit(200)).all())


def get_draft(user: VaUsers, draft_id: object, *, for_update: bool = False) -> VaWebIntakeDraft:
    try:
        draft = db.session.get(VaWebIntakeDraft, uuid.UUID(str(draft_id)))
    except ValueError:
        draft = None
    if draft is None or draft.user_id != user.user_id:
        raise WebIntakeError("Draft not found.", 404)
    if for_update and draft.status != "draft":
        raise WebIntakeError("This draft is no longer editable.", 409)
    return draft


def load_draft_envelope(draft: VaWebIntakeDraft) -> dict:
    """Reassemble the package's draft envelope from the per-section rows."""
    data: dict = {}
    for section in draft.sections:
        data.update(section.data or {})
    meta = dict(draft.meta or {})
    return {
        "schemaVersion": meta.get("schemaVersion", 1),
        "formVersion": meta.get("formVersion", "2022"),
        "id": str(draft.draft_id),
        "instrumentId": meta.get("instrumentId", INSTRUMENT_ID),
        "instrumentVersion": meta.get("instrumentVersion", ""),
        "currentSection": draft.current_section or meta.get("currentSection", ""),
        "createdAt": meta.get("createdAt", draft.created_at.isoformat()),
        "updatedAt": meta.get("updatedAt", draft.updated_at.isoformat()),
        "data": data,
    }


def save_draft_sections(draft: VaWebIntakeDraft, *, sections: dict, meta: dict | None = None, current_section: str | None = None) -> int:
    """Upsert the given sections' answers; returns the number of sections written."""
    if not isinstance(sections, dict):
        raise WebIntakeError("sections must be an object keyed by section name.")
    existing = {row.section_name: row for row in draft.sections}
    written = 0
    for name, answers in sections.items():
        if not isinstance(name, str) or not _SECTION_NAME_RE.match(name):
            raise WebIntakeError(f"Invalid section name {name!r}.")
        if not isinstance(answers, dict):
            raise WebIntakeError(f"Section {name!r} must be an object of answers.")
        row = existing.get(name)
        if row is None:
            row = VaWebIntakeDraftSection(draft_id=draft.draft_id, section_name=name, data=answers)
            db.session.add(row)
            draft.sections.append(row)
        else:
            row.data = answers
            row.saved_at = _utcnow()
        written += 1
    if meta:
        keep = {k: meta[k] for k in ("schemaVersion", "formVersion", "instrumentId", "instrumentVersion", "createdAt", "updatedAt") if k in meta}
        draft.meta = {**(draft.meta or {}), **keep}
    if current_section is not None:
        if not _SECTION_NAME_RE.match(str(current_section)):
            raise WebIntakeError("Invalid current section.")
        draft.current_section = str(current_section)
    draft.updated_at = _utcnow()
    db.session.flush()
    return written


def discard_draft(draft: VaWebIntakeDraft) -> None:
    draft.status = "discarded"
    if draft.death_id:
        death = db.session.get(VaDeathRegister, draft.death_id)
        if death is not None and death.status == "va_in_progress":
            death.status = "registered"
    db.session.flush()


# ---------------------------------------------------------------------------
# Submission
# ---------------------------------------------------------------------------


def _is_attachment_reference(value: object) -> bool:
    if isinstance(value, str):
        return value.startswith(ATTACHMENT_REFERENCE_PREFIX)
    if isinstance(value, dict):
        return str(value.get("id", "")).startswith(ATTACHMENT_REFERENCE_PREFIX) or "id" in value and "mimeType" in value
    return False


def build_web_payload(draft: VaWebIntakeDraft, data: dict, user: VaUsers, *, submitted_at: datetime) -> tuple[dict, dict]:
    """Return (payload, attachment_references) shaped like a synced ODK record.

    Attachment answers are lifted out of the payload (phase 2 uploads them
    through the attachment store) and their slot names returned separately.
    """
    payload: dict = {}
    references: dict = {}
    for key, value in (data or {}).items():
        if _is_attachment_reference(value):
            references[key] = value
            payload[key] = None
        else:
            payload[key] = value

    form = db.session.get(VaForms, draft.form_id)
    death = db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None
    unit_context = _unit_context(draft.org_unit_id)
    submitted_iso = submitted_at.isoformat()
    meta = draft.meta or {}

    payload.update(unit_context)
    payload.setdefault("Site", draft.site_id)
    payload["unique_id"] = draft.unique_id
    payload["site_individual_id"] = draft.unique_id
    payload.setdefault("survey_state", unit_context.get("org_state_name", ""))
    payload.setdefault("survey_district", unit_context.get("org_district_name", ""))
    payload["narr_language"] = payload.get("narr_language") or "english"
    payload["language"] = payload.get("language") or payload["narr_language"]
    if death is not None:
        payload.setdefault("abha_number", death.abha_number)
        payload.setdefault("abha_address", death.abha_address)
        payload["death_register_id"] = str(death.death_id)

    # ODK-shaped metadata so the shared projection and payload-version code
    # see a complete record (see va_odk_06_fetchsubmissions._normalize_odata_record).
    payload["KEY"] = f"web:{draft.draft_id}"
    payload["instanceID"] = f"web:{draft.draft_id}"
    payload["SubmissionDate"] = submitted_iso
    payload["updatedAt"] = submitted_iso
    payload["SubmitterName"] = user.name
    payload["SubmitterID"] = str(user.user_id)
    payload["DeviceID"] = "digitva-web"
    payload["FormVersion"] = str(meta.get("instrumentVersion") or meta.get("formVersion") or "2022")
    payload["ReviewState"] = None
    payload["instanceName"] = f"{draft.unique_id}_WHOVA2022"
    payload["form_def"] = form.form_id
    payload["sid"] = f"web-{draft.draft_id}-{form.form_id.lower()}"
    payload["start"] = meta.get("createdAt") or submitted_iso
    payload["end"] = submitted_iso
    payload["today"] = submitted_at.date().isoformat()
    payload["AttachmentsExpected"] = len(references)
    payload["AttachmentsPresent"] = 0
    payload["intake_source"] = "web"
    payload["unique_id2"] = f"{draft.unique_id}_{submitted_at.strftime('%H%M%S')}{int(submitted_at.microsecond / 1000):03}"
    return payload, references


def _require_live_org_unit(draft: VaWebIntakeDraft) -> None:
    """Refuse a submission whose organization unit is no longer active.

    A unit can be deactivated between starting a draft and submitting it.
    Routing only attributes a submission to a live unit, so the case would fall
    back to the mapping's unit or stay unrouted — and since coding eligibility
    is decided by the routed unit, an unrouted case in a project with an
    organization tree is visible to no coder at all. Failing here tells the
    interviewer while the draft is still safe, instead of filing a death
    nobody can see.
    """
    if not draft.org_unit_id:
        return
    unit = db.session.get(MasOrgUnit, uuid.UUID(str(draft.org_unit_id)))
    if unit is None:
        raise WebIntakeError(
            "The organization unit for this case no longer exists. Ask an "
            "administrator to restore it or move the case before submitting.",
            409,
        )
    if not unit.is_active:
        raise WebIntakeError(
            f"The organization unit for this case ({unit.unit_name}) is no "
            "longer active, so the case could not be attributed to it or "
            "reach a coder. Ask an administrator to reactivate it or move the "
            "case before submitting.",
            409,
        )


def submit_draft(draft: VaWebIntakeDraft, user: VaUsers, *, completion: dict) -> VaSubmissions:
    """Turn a completed draft into a submission and route it into the workflow."""
    if draft.status != "draft":
        raise WebIntakeError("This draft has already been submitted.", 409)
    if not isinstance(completion, dict) or not isinstance(completion.get("data"), dict):
        raise WebIntakeError("completion.data is required.")
    data = completion["data"]
    if completion.get("valid") is not True:
        raise WebIntakeError("The questionnaire is not valid yet; complete the sections flagged by the form.", 422)
    consent = normalize_consent(data.get("Id10013"))
    if not consent:
        raise WebIntakeError("The consent question (Id10013) must be answered.", 422)
    _require_live_org_unit(draft)

    submitted_at = _utcnow()
    payload, references = build_web_payload(draft, data, user, submitted_at=submitted_at)
    form = db.session.get(VaForms, draft.form_id)
    fields = build_submission_projection(form, payload)
    va_sid = fields["va_sid"]
    if db.session.get(VaSubmissions, va_sid) is not None:
        raise WebIntakeError("This questionnaire was already submitted.", 409)

    submission = VaSubmissions(
        va_sid=va_sid,
        va_form_id=fields["va_form_id"],
        va_submission_date=fields["va_submission_date"],
        va_odk_updatedat=fields["va_odk_updatedat"],
        va_data_collector=fields["va_data_collector"],
        va_odk_reviewstate=fields["va_odk_reviewstate"],
        va_odk_reviewcomments=fields["va_odk_reviewcomments"],
        va_instance_name=fields["va_instance_name"],
        va_uniqueid_real=fields["va_uniqueid_real"],
        va_uniqueid_masked=fields["va_uniqueid_masked"],
        va_consent=fields["va_consent"],
        va_narration_language=fields["va_narration_language"],
        va_deceased_age=fields["va_deceased_age"],
        va_deceased_age_normalized_days=fields["va_deceased_age_normalized_days"],
        va_deceased_age_normalized_years=fields["va_deceased_age_normalized_years"],
        va_deceased_age_source=fields["va_deceased_age_source"],
        va_deceased_gender=fields["va_deceased_gender"],
        va_summary=fields["va_summary"],
        va_catcount=fields["va_catcount"],
        va_category_list=fields["va_category_list"],
    )
    db.session.add(submission)
    db.session.flush()
    # Attribute the death to an organization unit, exactly as ODK sync does:
    # the web questionnaire carries the same org_<level_code>_code fields, and
    # the project-site's ODK mapping supplies the same fallback unit.
    # No-op for a project without an organization tree.
    routing_context = org_routing.context_for_form(form)
    if routing_context.has_tree:
        org_routing.route_submission(
            submission, context=routing_context, payload=payload
        )
    ensure_active_payload_version(
        submission,
        payload_data=payload,
        source_updated_at=fields["va_odk_updatedat"],
        created_by_role=PAYLOAD_ROLE,
        created_by=user.user_id,
    )
    valid_consent = consent_is_valid(consent)
    route_synced_submission(
        va_sid,
        consent_valid=valid_consent,
        reason="web_intake_submitted",
        actor=system_actor(),
    )
    if valid_consent and not references:
        mark_attachment_sync_completed(
            va_sid, reason="web_intake_no_attachments", actor=system_actor()
        )
    db.session.add(
        VaSubmissionsAuditlog(
            va_sid=va_sid,
            va_audit_byrole=AUDIT_ROLE,
            va_audit_by=user.user_id,
            va_audit_operation="c",
            va_audit_action="va_submission_created_from_web_intake",
            va_audit_entityid=draft.draft_id,
        )
    )
    draft.status = "submitted"
    draft.va_sid = va_sid
    draft.submitted_at = submitted_at
    draft.client_valid = True
    draft.client_issue_count = len(completion.get("issues") or [])
    draft.meta = {**(draft.meta or {}), "attachmentReferences": references}
    if draft.death_id:
        death = db.session.get(VaDeathRegister, draft.death_id)
        if death is not None:
            death.status = "va_submitted"
            death.va_sid = va_sid
    db.session.flush()
    log.info("web intake submitted | sid=%s | unique_id=%s | by=%s | attachments=%d", va_sid, draft.unique_id, user.user_id, len(references))
    return submission


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


def serialize_death(death: VaDeathRegister) -> dict:
    return {
        "death_id": str(death.death_id),
        "project_id": death.project_id,
        "site_id": death.site_id,
        "org_unit_id": str(death.org_unit_id) if death.org_unit_id else None,
        "unique_id": death.unique_id,
        "deceased_name": death.deceased_name,
        "deceased_sex": death.deceased_sex,
        "abha_number": death.abha_number,
        "abha_address": death.abha_address,
        "date_of_birth": death.date_of_birth.isoformat() if death.date_of_birth else None,
        "age_years": death.age_years,
        "date_of_death": death.date_of_death.isoformat(),
        "place_of_death": death.place_of_death,
        "address": death.address,
        "informant_name": death.informant_name,
        "informant_phone": death.informant_phone,
        "remarks": death.remarks,
        "status": death.status,
        "va_sid": death.va_sid,
        "created_at": death.created_at.isoformat(),
    }


def serialize_draft(draft: VaWebIntakeDraft) -> dict:
    return {
        "draft_id": str(draft.draft_id),
        "project_id": draft.project_id,
        "site_id": draft.site_id,
        "org_unit_id": str(draft.org_unit_id) if draft.org_unit_id else None,
        "death_id": str(draft.death_id) if draft.death_id else None,
        "form_id": draft.form_id,
        "unique_id": draft.unique_id,
        "current_section": draft.current_section,
        "status": draft.status,
        "va_sid": draft.va_sid,
        "sections_saved": len(draft.sections),
        "created_at": draft.created_at.isoformat(),
        "updated_at": draft.updated_at.isoformat(),
    }
