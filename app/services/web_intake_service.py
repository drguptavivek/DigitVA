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

import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, date, datetime, timedelta

import pytz
import sqlalchemy as sa
from sqlalchemy.orm import aliased

from app import db
from app.models import (
    MapCaseContactAttempt,
    MapCaseTransition,
    MasOrgLevel,
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
from app.models.va_users import USER_SEX_VALUES
from app.models.va_web_intake import (
    CASE_STATES,
    CONTACT_OUTCOMES,
    DEATH_NUMBER_SEQUENCE,
    DEATH_SEX_VALUES,
    WEB_INTAKE_MODES,
)
from app.services import case_transition_service as cases
from app.services import notification_service, org_grant_service, served_form_service
from app.services import org_unit_routing_service as org_routing
from app.services import organization_service as org
from app.services.authz import resolve_grants, subtree_select, supervision
from app.services.authz.consulted import mark_consulted
from app.services.case_transition_service import WebIntakeError
from app.services.coding_release_service import (
    SOURCE_INTERVIEWER_REVISION,
    SOURCE_SUPERVISOR_CHOICE,
    release_coding_for_changed_payload,
    reopen_coding_after_revision,
)
from app.services.runtime_form_sync_service import ensure_web_runtime_form
from app.services.submission_payload_version_service import (
    canonical_payload_fingerprint,
    ensure_active_payload_version,
    get_active_payload_version,
    get_latest_pending_upstream_payload_version,
    reject_pending_upstream_payload_version,
)
from app.services.va_data_sync.va_data_sync_01_odkcentral import (
    apply_submission_projection,
    build_submission_projection,
    consent_is_valid,
    normalize_consent,
)
from app.services.web_form_instruments import DEFAULT_LOCALE
from app.services.web_form_relevance_service import (
    derive_validation_errors,
    form_version_of,
    strip_irrelevant_answers,
)
from app.services.workflow.definition import (
    PROTECTED_WORKFLOW_STATES,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
)
from app.services.workflow.state_store import get_submission_workflow_state
from app.services.workflow.transitions import (
    INTERVIEW_CHOSEN_REASON,
    WorkflowTransitionError,
    admin_actor,
    data_manager_actor,
    interview_supervisor_actor,
    mark_attachment_sync_completed,
    mark_upstream_change_detected,
    route_synced_submission,
    system_actor,
)
from app.services.workflow.upstream_changes import (
    UPSTREAM_CHANGE_STATUS_REJECTED,
    get_open_revision_request,
    resolve_pending_upstream_change,
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
    "flag_death",
    "set_visit",
    "log_contact_attempt",
    "pause_interview",
    "PAUSE_REASONS",
    "mask_phone",
    "list_worklist",
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
    "serialize_worklist_row",
    "serialize_case_detail",
    "choose_interview",
    "list_candidates",
    "get_case_detail",
    "worklist_page",
    "prefill_policy",
]

INSTRUMENT_ID = "va_who_2022"
ATTACHMENT_REFERENCE_PREFIX = "who-va-attachment:"
AUDIT_ROLE = "vainterviewer"
PAYLOAD_ROLE = "vainterviewer"
#: ``YYYY`` or ``YYYY-MM``: a birth date whose day (or day and month) is unknown.
_PARTIAL_DATE_RE = re.compile(r"^\d{4}(-(0[1-9]|1[0-2]))?$", re.ASCII)
#: The earliest plausible birth year; the WHO dob_year constraint's floor.
PARTIAL_BIRTH_MIN_YEAR = 1900
_ABHA_NUMBER_RE = re.compile(r"^(\d{14}|\d{2}-\d{4}-\d{4}-\d{4})$")
_ABHA_ADDRESS_RE = re.compile(r"^[A-Za-z0-9._]{4,32}@(abdm|sbx)$")
# Indian mobile: 10 digits starting 6-9, optionally after +91 or 0.
_PHONE_RE = re.compile(r"^(?:\+91|0)?([6-9]\d{9})$")
_PHONE_SEPARATORS_RE = re.compile(r"[\s-]")
_SECTION_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
#: An instrument locale code as the XLSForm writes it ("hi", "kha", "pt-BR").
_LOCALE_CODE_RE = re.compile(r"^[A-Za-z0-9-]{2,16}$")

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
    "web_intake_medical_records_enabled": True,
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




def _utcnow() -> datetime:
    return datetime.now(UTC)


def _expression_now(user: VaUsers, at: datetime) -> datetime:
    """``at`` read in the interviewer's own timezone, for the expression
    evaluator's ``today()`` -- the same "whatever the device considers
    local" the browser's ``formatLocalDate`` uses (see
    docs/policy/xform-expression-evaluator.md). Falls back to this
    application's primary deployment timezone, matching
    ``app._current_user_timezone``."""
    tz_name = getattr(user, "timezone", None) or "Asia/Kolkata"
    try:
        tz = pytz.timezone(tz_name)
    except pytz.UnknownTimeZoneError:
        tz = pytz.timezone("Asia/Kolkata")
    return at.astimezone(tz)


def _device_time(value: object) -> datetime | None:
    """An ISO 8601 time with a UTC offset, in that offset; None for anything
    else (not text, unparsable, or no offset -- an offset-less time cannot
    be placed, docs/policy/field-data-collection.md "Interview times")."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() is not None else None


def _completion_time(envelope: dict, now: datetime) -> datetime:
    """When the interview was completed, in server time: the device's
    ``completedAt`` corrected by its clock drift (``now - deviceClockAt`` is
    how far the device runs behind, as in ``sync_device_draft``) and never
    later than *now*. Without both times (a browser submit, an older app) it
    is *now*, the moment the server received it."""
    done, clock = _device_time(envelope.get("completedAt")), _device_time(envelope.get("deviceClockAt"))
    if done is None or clock is None:
        return now
    return min(now, now - (clock - done))


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


def reachable_unit_ids(user: VaUsers, project_id: str, site_id: str | None = None) -> set[uuid.UUID] | None:
    """Active units of *project_id* this interviewer may attribute an entry to.

    The unit-picking half of the rule ``_worklist_scope`` applies to cases
    (docs/policy/web-intake.md, "Who sees which cases"), built from the same
    ``resolve_grants`` data. ``None`` means the whole tree: a project grant
    on the project, or a site grant on exactly (*project_id*, *site_id*).
    Otherwise the subtrees of the user's interviewer unit grants in this
    project (an empty set reaches nothing). A site grant on another site
    widens nothing here.

    With ``site_id=None`` (the per-project picker, which has no site: device
    ``/units`` and ``prefill_policy``) a wide grant on *any* site of the
    project returns ``None``: the picker offers every unit some site of the
    project allows, and the create-time check (``_require_scope``, which
    passes its site) still holds each site to its own grants.

    No admin or project_pi bypass: web intake is strictly grant-based.
    """
    mark_consulted()
    units: set[uuid.UUID] = set()
    for grant in resolve_grants(user).of({VaAccessRoles.interviewer}, virtual=False):
        if grant.project_id != project_id:
            continue
        if not grant.is_wide:
            units.add(grant.org_unit_id)
        elif site_id is None or grant.site_id in (None, site_id):  # site_id None: project grant
            return None
    if not units:
        return set()
    return set(db.session.scalars(subtree_select(units)))


def _require_scope(user: VaUsers, project_id: str, site_id: str, org_unit_id: object | None) -> dict:
    """Return the context entry for (project, site) or raise 403.

    In a project with an organization tree, a unit must always be named,
    whatever the grant's scope — the routed unit is what makes a submission
    codeable at all (docs/policy/organization-model.md phase 4), and an
    unrouted one is invisible to every coder. A project- or site-scoped
    interviewer grant on this project-site may name *any* active unit of
    the project; a unit-scoped grant is held to its own subtree
    (``reachable_unit_ids``). A project with no tree
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

    reachable = reachable_unit_ids(user, project_id, site_id)
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


def _clean_partial_birth(raw: object, date_of_death: date) -> str | None:
    """A partial birth date as ``YYYY`` or ``YYYY-MM``, or None if blank.

    Refused (400) when malformed, before PARTIAL_BIRTH_MIN_YEAR, or after
    today or the date of death at the precision given -- the month or year
    of death itself is plausible. Compared as strings, which order like the
    dates they name at equal length.
    """
    value = _clean(raw, what="Partial date of birth", max_len=7)
    if value is None:
        return None
    if not _PARTIAL_DATE_RE.match(value):
        raise WebIntakeError("Partial date of birth must be YYYY-MM or YYYY.")
    if int(value[:4]) < PARTIAL_BIRTH_MIN_YEAR:
        raise WebIntakeError(f"Partial date of birth cannot be before {PARTIAL_BIRTH_MIN_YEAR}.")
    if value > date.today().isoformat()[:len(value)]:
        raise WebIntakeError("Partial date of birth cannot be in the future.")
    if value > date_of_death.isoformat()[:len(value)]:
        raise WebIntakeError("Date of birth cannot be after the date of death.")
    return value


def _clean_abha(number: object, address: object) -> tuple[str | None, str | None]:
    abha_number = _clean(number, what="ABHA number", max_len=17)
    abha_address = _clean(address, what="ABHA address", max_len=64)
    if abha_number and not _ABHA_NUMBER_RE.match(abha_number):
        raise WebIntakeError("ABHA number must be 14 digits (optionally grouped 2-4-4-4).")
    if abha_address and not _ABHA_ADDRESS_RE.match(abha_address):
        raise WebIntakeError("ABHA address must look like name@abdm.")
    return abha_number, abha_address


def _clean_phone(raw: object, *, what: str) -> str | None:
    """An Indian mobile number normalised to its 10 digits, or None if blank.

    Spaces and hyphens are ignored; a +91 or 0 prefix is dropped.
    """
    value = _clean(raw, what=what, max_len=32)
    if value is None:
        return None
    match = _PHONE_RE.match(_PHONE_SEPARATORS_RE.sub("", value))
    if not match:
        raise WebIntakeError(f"{what} must be a 10-digit mobile number starting 6-9 (+91 or 0 in front is fine).")
    return match.group(1)


def mask_phone(phone: str | None) -> str | None:
    """``******1234``: the last four digits only, for lists. Tolerates the free
    text older rows may hold."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    return "******" + (digits[-4:] if len(digits) >= 4 else "")


def register_death(user: VaUsers, *, project_id: str, site_id: str, org_unit_id: object | None = None,
                   client_death_id: uuid.UUID | None = None, **fields) -> VaDeathRegister:
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
    date_of_birth_partial = _clean_partial_birth(fields.get("date_of_birth_partial"), date_of_death)
    if date_of_birth and date_of_birth_partial:
        raise WebIntakeError("Give an exact or a partial date of birth, not both.")
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
        date_of_birth_partial=date_of_birth_partial,
        age_years=age_years,
        date_of_death=date_of_death,
        place_of_death=_clean(fields.get("place_of_death"), what="Place of death"),
        address=_clean(fields.get("address"), what="Address"),
        address_house_street=_clean(fields.get("address_house_street"), what="House or street", max_len=200),
        address_village_ward=_clean(fields.get("address_village_ward"), what="Village or ward", max_len=200),
        address_landmark=_clean(fields.get("address_landmark"), what="Landmark", max_len=200),
        informant_name=_clean(fields.get("informant_name"), what="Informant name"),
        father_name=_clean(fields.get("father_name"), what="Father's name", max_len=200),
        mother_name=_clean(fields.get("mother_name"), what="Mother's name", max_len=200),
        informant_phone=_clean_phone(fields.get("informant_phone"), what="Informant phone"),
        informant_phone_2=_clean_phone(fields.get("informant_phone_2"), what="Second phone"),
        remarks=_clean(fields.get("remarks"), what="Remarks"),
        registered_by=user.user_id,
        source="register",
        client_death_id=client_death_id,
    )
    cases.open_case(death, actor=user)
    log.info("web intake death registered | project=%s | site=%s | unique_id=%s | by=%s", project_id, site_id, unique_id, user.user_id)
    return death


#: Status filter values the register list accepted before the case states
#: (digitva-vzk.4), mapped forward so an old bookmark or client keeps working.
_LEGACY_STATUS = {"va_in_progress": "in_progress", "va_submitted": "submitted"}


def list_deaths(user: VaUsers, *, project_id: str, site_id: str, status: str | None = None) -> list[VaDeathRegister]:
    """Registered deaths (``source = register``) of one project-site in scope.

    Direct starts are cases too, but they are listed by ``list_worklist``;
    this list stays what it was, the death register.
    """
    stmt = sa.select(VaDeathRegister).where(
        VaDeathRegister.project_id == project_id,
        VaDeathRegister.site_id == site_id,
        VaDeathRegister.source == "register",
    )
    entry = next(
        (e for e in interviewer_context(user) if e["project_id"] == project_id and e["site_id"] == site_id),
        None,
    )
    if entry is None:
        raise WebIntakeError("You do not have interviewer access to that project and site.", 403)
    # The same per-project-site rule the worklist uses; its draft-identity
    # clause is moot here, register rows never sit in that state.
    scope = _worklist_scope(user, [entry])
    if scope is None:
        return []
    stmt = stmt.where(scope)
    if status:
        stmt = stmt.where(VaDeathRegister.status == _LEGACY_STATUS.get(status, status))
    return list(db.session.scalars(stmt.order_by(VaDeathRegister.created_at.desc()).limit(500)).all())


def get_death(user: VaUsers, death_id: object) -> VaDeathRegister:
    try:
        death = db.session.get(VaDeathRegister, uuid.UUID(str(death_id)))
    except ValueError:
        death = None
    if death is None:
        raise WebIntakeError("Death entry not found.", 404)
    try:
        _require_scope(user, death.project_id, death.site_id, death.org_unit_id)
    except WebIntakeError as exc:
        # Out of scope reads as not found: an id is not proof the case exists.
        if exc.status_code == 403:
            raise WebIntakeError("Death entry not found.", 404) from None
        raise
    # "Details pending" is its starter's (and supervisors') only (owner,
    # 2026-09-30, item 11); for anyone else it does not exist.
    if (
        death.status == "draft_identity"
        and death.started_by_user_id != user.user_id
        and not cases.is_interview_supervisor_for(user, death)
    ):
        raise WebIntakeError("Death entry not found.", 404)
    return death


def flag_death(user: VaUsers, death_id: object, *, kind: str, reason: str | None = None,
               duplicate_of: object | None = None) -> VaDeathRegister:
    """Flag a case in scope as a possible duplicate of another case in scope, or
    for cancellation. A supervisor confirms or rejects it later."""
    death = get_death(user, death_id)
    target = get_death(user, duplicate_of) if kind == "duplicate" and duplicate_of else None
    return cases.flag_case(death, actor=user, kind=kind, reason=reason, duplicate_of=target)


# ---------------------------------------------------------------------------
# Visits, contact attempts, pause (phase 5, digitva-vzk.9)
# ---------------------------------------------------------------------------

#: Pause reason codes (a code, never free text: the audit reason holds no PII).
PAUSE_REASONS = ("respondent_busy", "respondent_left", "needs_other_respondent", "other")
#: Cases waiting for a visit: a visit date may be set and attempts logged.
_VISIT_STATES = frozenset({"registered", "scheduled", "not_reachable", "paused"})
_VISIT_PAST = timedelta(days=1)
_VISIT_AHEAD = timedelta(days=366)


def _clean_visit_at(raw: object) -> datetime | None:
    """An ISO date-time with a timezone, from yesterday to a year ahead, or None."""
    value = _clean(raw, what="Visit date")
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = None
    if parsed is None or parsed.tzinfo is None:
        raise WebIntakeError("Visit date must be a date and time with a timezone.")
    now = _utcnow()
    if not now - _VISIT_PAST <= parsed <= now + _VISIT_AHEAD:
        raise WebIntakeError("Visit date must be between yesterday and a year from now.")
    return parsed.astimezone(UTC)


def _waiting_case(user: VaUsers, death_id: object) -> VaDeathRegister:
    """A case in scope (else 404), row-locked, that is waiting for a visit (else 409)."""
    death = cases.lock_case(get_death(user, death_id))
    if death.status not in _VISIT_STATES:
        raise WebIntakeError("Only a case waiting for a visit can take a visit date or a contact attempt.", 409)
    return death


def set_visit(user: VaUsers, death_id: object, *, next_visit_at: object | None) -> VaDeathRegister:
    """Set or clear a case's next visit (appointment or follow-up).

    Setting moves registered / not_reachable to ``scheduled``; on a scheduled
    or paused case it only changes the date. Clearing moves ``scheduled`` back
    to ``registered``; elsewhere it only clears the date.
    """
    visit_at = _clean_visit_at(next_visit_at)
    death = _waiting_case(user, death_id)
    death.next_visit_at = visit_at
    if visit_at is not None and death.status in ("registered", "not_reachable"):
        cases.transition(death, "scheduled", actor=user, action="visit_scheduled")
    elif visit_at is None and death.status == "scheduled":
        cases.transition(death, "registered", actor=user, action="visit_cleared")
    db.session.flush()
    return death


def log_contact_attempt(user: VaUsers, death_id: object, *, outcome: str,
                        next_visit_at: object | None = None,
                        client_attempt_id: uuid.UUID | None = None) -> VaDeathRegister:
    """Record one contact attempt and move the case by its outcome.

    - ``refused``: the case becomes ``refused``; its visit date is cleared (a
      next date is refused).
    - ``no_answer`` / ``wrong_number`` / ``moved``: ``not_reachable`` (stays
      so if already), next visit = the given date or none.
    - ``reached``: with a date, registered / not_reachable become
      ``scheduled`` and a scheduled or paused case takes the new date; without
      one nothing changes but the contact time.
    """
    if outcome not in CONTACT_OUTCOMES:
        raise WebIntakeError("Outcome must be one of " + ", ".join(CONTACT_OUTCOMES) + ".")
    visit_at = _clean_visit_at(next_visit_at)
    if outcome == "refused" and visit_at is not None:
        raise WebIntakeError("A refusal takes no next visit date.")
    death = _waiting_case(user, death_id)
    now = _utcnow()
    db.session.add(MapCaseContactAttempt(
        death_id=death.death_id, attempted_at=now, outcome=outcome,
        next_visit_at=visit_at, by_user_id=user.user_id, client_attempt_id=client_attempt_id,
    ))
    death.last_contact_at = now
    if outcome == "refused":
        death.next_visit_at = None
        cases.transition(death, "refused", actor=user, action="contact_refused")
    elif outcome == "reached":
        if visit_at is not None:
            death.next_visit_at = visit_at
            if death.status in ("registered", "not_reachable"):
                cases.transition(death, "scheduled", actor=user, action="contact_reached")
    else:
        death.next_visit_at = visit_at
        if death.status != "not_reachable":
            cases.transition(death, "not_reachable", actor=user, action=f"contact_{outcome}")
    db.session.flush()
    return death


def pause_interview(user: VaUsers, death_id: object, *, reason: str,
                    next_visit_at: object | None = None) -> VaDeathRegister:
    """Pause an in-progress interview with a reason code and optional revisit
    date. Resuming is starting the draft again (``start_draft``)."""
    if reason not in PAUSE_REASONS:
        raise WebIntakeError("Reason must be one of " + ", ".join(PAUSE_REASONS) + ".")
    visit_at = _clean_visit_at(next_visit_at)
    death = cases.lock_case(get_death(user, death_id))
    # Only an interview in progress pauses; a submitted case leaves coding only
    # through its submitter's later version (revise_submission).
    if death.status != "in_progress":
        raise WebIntakeError("Only an interview in progress can be paused.", 409)
    death.next_visit_at = visit_at
    cases.transition(death, "paused", actor=user, action="interview_paused", reason=reason)
    return death


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


#: Id10010's own constraint (letters and spaces). A locked answer that fails
#: its constraint would trap the interviewer, so a name outside it stays editable.
_INTERVIEWER_NAME_RE = re.compile(r"[A-Za-z ]+")

#: Id10058 choices matched exactly, by value or English label.
_PLACE_OF_DEATH_CHOICES = {
    "hospital": "hospital",
    "other health facility": "other_health_facility",
    "home": "home",
    "on route to hospital or facility": "on_route_to_hospital_or_facility",
    "other": "other",
}
#: Then keywords, in this order: "on the way to hospital" is en route, not a
#: hospital; "nursing home" is a facility, not home.
_PLACE_OF_DEATH_KEYWORDS = (
    ("on_route_to_hospital_or_facility", ("route", "on the way", "transit", "ambulance")),
    ("other_health_facility", ("phc", "chc", "health centre", "health center", "sub centre", "subcentre",
                               "clinic", "dispensary", "nursing home", "facility")),
    ("hospital", ("hospital",)),
    ("home", ("home", "house", "residence")),
)


def _who_place_of_death(text: str | None) -> str | None:
    """The Id10058 choice for a free-text register ``place_of_death``, or None
    when nothing matches with confidence (the question is then left unasked
    -- never defaulted to ``other``, since it is a coding input)."""
    value = " ".join((text or "").lower().replace("_", " ").split())
    if not value:
        return None
    if value in _PLACE_OF_DEATH_CHOICES:
        return _PLACE_OF_DEATH_CHOICES[value]
    for choice, words in _PLACE_OF_DEATH_KEYWORDS:
        if any(word in value for word in words):
            return choice
    return None


def _org_path_names(org_unit_id: uuid.UUID | None) -> list[str]:
    """Unit names from the tree root down to the unit (active units only),
    e.g. ["India", "Himachal Pradesh", "Solan", "Kandaghat"]. One query."""
    unit = db.session.get(MasOrgUnit, org_unit_id) if org_unit_id else None
    if unit is None:
        return []
    return [row["unit_name"] for row in org.list_units_by_codes(unit.project_id, str(unit.path).split("."))]


def _case_address(death: VaDeathRegister) -> str:
    """The case's address parts, structured first, joined with commas."""
    parts = (death.address_house_street, death.address_village_ward, death.address_landmark, death.address)
    return ", ".join(part.strip() for part in parts if part and part.strip())


#: WHO question -> the death-register column ``_prefill_from_death`` answers
#: it from, as an editable answer (Id10058 through ``_who_place_of_death``).
PREFILL_ANSWER_FIELDS = {
    "Id10058": "place_of_death",
    "Id10007": "informant_name",
    "Id10061": "father_name",
    "Id10062": "mother_name",
}
#: Death-register columns prefilled as the same-named question and locked.
PREFILL_LOCKED_FIELDS = ("abha_number", "abha_address")


def _prefill_from_death(death: VaDeathRegister | None, user: VaUsers, org_unit_id: uuid.UUID | None = None,
                        unit_parts: tuple[dict, list[str]] | None = None) -> dict:
    """The draft's prefill, per the map in docs/policy/web-intake.md.

    ``deceased`` and ``interviewer`` go through the package's
    ``createWhoVaInitialDataFromPrefill``; ``answers`` are WHO answers merged
    on top; ``lockedQuestionNames`` are the read-only ones (interviewer
    name, sex and id, area presets, ABHA, and the case's registered age
    fields). Everything else is an ordinary editable
    answer. Name split: the first word is the given name (Id10017), the rest
    the surname (Id10018).

    Birth date: an exact ``date_of_birth`` goes as ``deceased.dateOfBirth``
    (prefill.ts sets Id10020 = yes, Id10021). A ``date_of_birth_partial``
    never touches Id10021 (WHO's full date only); it sets Id10020 = no and
    the DigitVA precision block after it, whose relevance needs that no:
    ``YYYY-MM`` -> dob_precision = month_year, dob_month_year = YYYY-MM-01;
    ``YYYY`` -> dob_precision = year, dob_year = YYYY-01-01 (the day and
    month the ODK date type stores for those appearances, never read back
    as known). Age, when also known, still prefills as below.

    Age: the registered ``age_years`` is locked (``age_group`` and its age
    field); the date of birth, exact or partial, stays editable. An exact
    date of birth sends no age (the form calculates it), so nothing
    age-related is locked then, nor for an age that is not prefilled.

    ``unit_parts`` is the unit's ``(presets, org path
    names)`` already resolved for a batch (``prefill_policy``); without it
    both are queried here.
    """
    interviewer: dict = {"name": user.name, "id": str(user.user_id)}
    locked = {"Id10010c"}
    if _INTERVIEWER_NAME_RE.fullmatch((user.name or "").strip()):
        locked.add("Id10010")
    if user.sex in USER_SEX_VALUES:
        interviewer["sex"] = user.sex
        locked.add("Id10010b")
    prefill: dict = {"interviewer": interviewer}
    answers: dict = {}
    if org_unit_id is not None:
        # Area presets (Id10002/Id10003) from the organization tree, per
        # docs/policy/web-intake.md ("Area VA presets"). Merged before the
        # death-register answers below so a death-register value always wins.
        presets = unit_parts[0] if unit_parts else org_grant_service.resolve_va_presets(org_unit_id)
        answers.update(presets)
        locked.update(presets)
    org_path = ", ".join(unit_parts[1] if unit_parts else _org_path_names(org_unit_id))
    address = _case_address(death) if death is not None else ""
    # Id10057 in prefill.ts's location format: "path; address".
    place = "; ".join(part for part in (org_path, address) if part)
    residence = address or org_path
    if place:
        answers["Id10057"] = place
    if residence:
        answers["Id10055"] = residence
    if place or residence:
        # Id10055/Id10057 are asked only when Id10051 = yes.
        answers["Id10051"] = "yes"
    if death is not None:
        for name, field in PREFILL_ANSWER_FIELDS.items():
            value = getattr(death, field)
            if name == "Id10058":
                value = _who_place_of_death(value)
            if value:
                answers[name] = value
    if death is not None and cases.identity_complete(death):
        names = death.deceased_name.strip().split(None, 1)
        deceased = {
            "givenNames": names[0],
            "sex": death.deceased_sex if death.deceased_sex in ("male", "female") else "undetermined",
            # Only one of dateOfDeath/yearOfDeath may be sent -- prefill.ts
            # throws on both (WhoVaDeathEvidence). A case with its identity
            # always has the exact date; yearOfDeath is for a future path
            # that only knows the year.
            "dateOfDeath": death.date_of_death.isoformat(),
        }
        if len(names) > 1:
            deceased["surname"] = names[1]
        if death.date_of_birth:
            deceased["dateOfBirth"] = death.date_of_birth.isoformat()
        elif death.age_years is not None and 12 <= death.age_years <= 119:
            # ageInYears for prefill.ts (device and web clients); the same
            # answers it derives, repeated so _locked_answers can restore them.
            deceased["ageInYears"] = death.age_years
            age = {"age_group": "adult", "age_adult": death.age_years}
            answers.update(age)
            locked.update(age)
        elif death.age_years is not None and 1 <= death.age_years <= 11:
            # prefill.ts maps adults only. Age 0 is not prefilled: days
            # (neonate) or months (child) cannot be told from 0 years.
            age = {"age_group": "child", "age_child_unit": "years", "age_child_years": death.age_years}
            answers.update({"Id10020": "no", **age})
            locked.update(age)
        if not death.date_of_birth and death.date_of_birth_partial:
            partial = death.date_of_birth_partial
            answers["Id10020"] = "no"
            if len(partial) == 7:
                answers.update({"dob_precision": "month_year", "dob_month_year": f"{partial}-01"})
            else:
                answers.update({"dob_precision": "year", "dob_year": f"{partial}-01-01"})
        prefill["deceased"] = deceased
        for name in PREFILL_LOCKED_FIELDS:
            value = getattr(death, name)
            if value:
                answers[name] = value
                locked.add(name)
    prefill["answers"] = answers
    prefill["lockedQuestionNames"] = sorted(locked)
    return prefill


#: Locked interviewer questions and the ``prefill["interviewer"]`` key each is
#: filled from, as prefill.ts's addInterviewer maps them.
#: Id10010a (interviewer age) is not prefilled; leaving it out also stops a
#: draft's stored lock list from enforcing it.
_INTERVIEWER_ANSWER_KEYS = {"Id10010": "name", "Id10010b": "sex", "Id10010c": "id"}


def _locked_answers(prefill: dict) -> dict:
    """``{question: value}`` for every locked question of a draft's prefill.

    *prefill* is the draft's stored, server-computed prefill
    (``_prefill_from_death``), never the client's ``lockedQuestionNames``:
    the client list only drives the read-only display. Values come from
    ``prefill["answers"]`` (area presets, ABHA) or ``prefill["interviewer"]``
    (Id10010 trimmed, as prefill.ts does). A name with no value to restore,
    or a prefill without locked names (a draft from before them), yields
    nothing, so nothing is ever blanked.
    """
    answers = prefill.get("answers") or {}
    interviewer = prefill.get("interviewer") or {}
    out: dict = {}
    for name in prefill.get("lockedQuestionNames") or ():
        if name in answers:
            value = answers[name]
        elif name in _INTERVIEWER_ANSWER_KEYS:
            value = interviewer.get(_INTERVIEWER_ANSWER_KEYS[name])
            if isinstance(value, str):
                value = value.strip()
        else:
            value = None
        if value not in (None, ""):
            out[name] = value
    return out


def _draft_locked_answers(draft: VaWebIntakeDraft) -> dict:
    """``_locked_answers`` for *draft*, always recomputed from the case and
    the draft's owner, never from the stored prefill: a draft saved before a
    lock existed (no ``lockedQuestionNames``, ``{}``, or an older list) gets
    today's locks, and a corrected registration wins. Never written back."""
    death = db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None
    return _locked_answers(
        _prefill_from_death(death, db.session.get(VaUsers, draft.user_id), draft.org_unit_id)
    )


def _enforce_locked(answers: dict, locked: dict, previous: dict | None = None) -> dict:
    """*answers* with every locked question it carries, or *previous* (the
    section's last save) carried, set to its authoritative value. A new dict:
    the caller's is left as sent. Locked questions the section never held are
    not added, so a section save does not move answers between sections."""
    held = set(answers) | set(previous or {})
    return {**answers, **{name: value for name, value in locked.items() if name in held}}


#: Case states from which starting (or resuming) an interview moves the case
#: to ``in_progress``; ``refused`` included, since a refusal blocks nothing.
_STARTABLE_STATES = frozenset({"registered", "scheduled", "paused", "not_reachable", "refused"})


def _begin_interview(death: VaDeathRegister, user: VaUsers) -> None:
    """Move a case whose interview (re)starts to ``in_progress``, audited."""
    if death.started_by_user_id is None:
        death.started_by_user_id = user.user_id
    if death.status in _STARTABLE_STATES:
        action = "interview_restarted" if death.status == "refused" else "interview_started"
        # The visit is happening: the date no longer sorts the worklist.
        death.next_visit_at = None
        cases.transition(death, "in_progress", actor=user, action=action)


def start_draft(user: VaUsers, *, project_id: str, site_id: str, org_unit_id: object | None = None, death_id: object | None = None) -> VaWebIntakeDraft:
    """Open (or return the caller's own) draft for a case, or start directly.

    A direct start creates its case at once (``source = direct``,
    ``draft_identity``); the draft's answers fill the identity in.

    One open draft per interviewer per case: another interviewer's draft never
    blocks a start, each gets their own copy (web-intake.md "Parallel
    interviews").
    """
    mode = get_web_intake_mode(project_id)
    death = get_death(user, death_id) if death_id else None
    if death is not None:
        if not _mode_allows(mode, death_register=death.source == "register"):
            raise WebIntakeError("This project does not use the death register.", 403)
        if death.project_id != project_id or death.site_id != site_id:
            raise WebIntakeError("Death entry belongs to another project or site.")
        # Serialises starts on one case: the second waits here, then sees the
        # caller's own open draft below instead of opening another.
        death = cases.lock_case(death)
        if death.status == "submitted":
            raise WebIntakeError("A questionnaire has already been submitted for this death.", 409)
        if death.status in ("duplicate", "cancelled"):
            raise WebIntakeError("This case is closed.", 409)
        existing = db.session.scalar(
            sa.select(VaWebIntakeDraft).where(
                VaWebIntakeDraft.death_id == death.death_id,
                VaWebIntakeDraft.user_id == user.user_id,
                VaWebIntakeDraft.status == "draft",
            )
        )
        if existing is not None:
            _begin_interview(death, user)
            return existing
        org_unit_id = death.org_unit_id
    elif not _mode_allows(mode, death_register=False):
        raise WebIntakeError("This project requires a death register entry before the questionnaire.", 403)
    _require_scope(user, project_id, site_id, org_unit_id)
    form = ensure_web_runtime_form(project_id, site_id)
    resolved_org_unit_id = uuid.UUID(str(org_unit_id)) if org_unit_id else None
    prefill = _prefill_from_death(death, user, resolved_org_unit_id)
    if death is not None:
        _begin_interview(death, user)
    else:
        unit = db.session.get(MasOrgUnit, resolved_org_unit_id) if resolved_org_unit_id else None
        number, unique_id = _allocate_unique_id(unit.unit_code if unit else site_id)
        death = cases.open_case(
            VaDeathRegister(
                project_id=project_id,
                site_id=site_id,
                org_unit_id=resolved_org_unit_id,
                death_number=number,
                unique_id=unique_id,
                source="direct",
                registered_by=user.user_id,
                started_by_user_id=user.user_id,
            ),
            actor=user,
        )
    now = _utcnow().isoformat()
    draft = VaWebIntakeDraft(
        project_id=project_id,
        site_id=site_id,
        org_unit_id=resolved_org_unit_id,
        death_id=death.death_id,
        form_id=form.form_id,
        user_id=user.user_id,
        unique_id=death.unique_id,
        # The base locale until the page tells us otherwise; a locale switch
        # PATCHes both keys and build_web_payload copies them to the payload.
        meta={
            "createdAt": now,
            "updatedAt": now,
            "instrumentId": INSTRUMENT_ID,
            "locale": DEFAULT_LOCALE,
            "translation_version": 0,
        },
        prefill=prefill,
    )
    db.session.add(draft)
    db.session.flush()
    if death_id:
        # Other interviewers already holding an open draft on this case.
        holders = notification_service.open_draft_holders(death.death_id, exclude_user_id=user.user_id)
        notification_service.notify(
            holders, notification_service.OTHER_DRAFT_STARTED, project_id=project_id,
            death_id=death.death_id, draft_id=holders,
        )
    log.info("web intake draft started | project=%s | site=%s | unique_id=%s | by=%s", project_id, site_id, death.unique_id, user.user_id)
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


def _answers_of(draft: VaWebIntakeDraft) -> dict:
    """The draft's answers: the ``final`` section alone once the draft is
    closed (a submitted or superseded draft keeps its complete final answers
    there), else the per-section saves merged."""
    data: dict = {}
    for section in draft.sections:
        if section.section_name == FINAL_SECTION and draft.status != "draft":
            return dict(section.data or {})
        data.update(section.data or {})
    return data


def load_draft_envelope(draft: VaWebIntakeDraft) -> dict:
    """Reassemble the package's draft envelope from the per-section rows."""
    data = _answers_of(draft)
    meta = dict(draft.meta or {})
    return {
        "schemaVersion": meta.get("schemaVersion", 1),
        "formVersion": meta.get("formVersion", "2022"),
        "id": str(draft.draft_id),
        "instrumentId": meta.get("instrumentId", INSTRUMENT_ID),
        "instrumentVersion": meta.get("instrumentVersion", ""),
        "locale": meta.get("locale", DEFAULT_LOCALE),
        "translation_version": meta.get("translation_version", 0),
        "currentSection": draft.current_section or meta.get("currentSection", ""),
        "createdAt": meta.get("createdAt", draft.created_at.isoformat()),
        "updatedAt": meta.get("updatedAt", draft.updated_at.isoformat()),
        # Only when recorded: an older draft has no slice identity to echo.
        **{k: meta[k] for k in _DEFINITION_IDENTITY_KEYS if k in meta},
        "data": data,
    }


def _clean_locale_meta(meta: dict) -> dict:
    """The working language and translation version out of a client's meta.

    Recorded on the draft at every locale switch so the submission can say what
    the respondent was actually shown (WP6 of
    docs/planning/web-capture-project-configuration-plan.md). Both come from the
    browser, so both are validated here: an unparseable value is refused rather
    than stored and copied into a payload later.
    """
    out: dict = {}
    if "locale" in meta:
        locale = meta.get("locale")
        if not isinstance(locale, str) or not _LOCALE_CODE_RE.match(locale):
            raise WebIntakeError("Invalid locale.")
        out["locale"] = locale
    if "translation_version" in meta:
        version = meta.get("translation_version")
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise WebIntakeError("Invalid translation version.")
        out["translation_version"] = version
    return out


def _identity_from_answers(data: dict) -> dict:
    """Name, sex and date of death from WHO answers, only those validly given.

    ``Id10017``/``Id10018`` given names and surname, ``Id10019`` sex,
    ``Id10023`` the calculated date of death (else the ``Id10023_a``/``_b``
    answer it is calculated from). A malformed or future date is ignored:
    the form validates it, this only mirrors it onto the case.
    """
    out: dict = {}
    name = " ".join(
        part for part in (str(data.get(k) or "").strip() for k in ("Id10017", "Id10018")) if part
    )
    if name:
        out["deceased_name"] = name
    sex = data.get("Id10019")
    if sex in DEATH_SEX_VALUES:
        out["deceased_sex"] = sex
    raw = data.get("Id10023")
    if not raw and data.get("Id10022") == "yes":
        raw = data.get("Id10023_a") if data.get("Id10020") == "yes" else data.get("Id10023_b")
    try:
        parsed = date.fromisoformat(str(raw)[:10]) if raw else None
    except ValueError:
        parsed = None
    if parsed is not None and parsed <= date.today():
        out["date_of_death"] = parsed
    return out


def _sync_case_identity(death: VaDeathRegister, data: dict, actor: VaUsers) -> None:
    """Copy the form's identity answers onto the case (the form is the record
    of the interview); a direct start leaves ``draft_identity`` once complete.
    An empty answer never blanks a value the case already holds."""
    for field, value in _identity_from_answers(data).items():
        setattr(death, field, value)
    if death.status == "draft_identity" and cases.identity_complete(death):
        cases.transition(death, "in_progress", actor=actor, action="identity_captured")


#: Which served form slice the answers were filled on: the SHA-256 of its body
#: and the conditional extensions it contained (``instrumentVersion`` is the
#: composed version). Kept so a device can fetch exactly that slice again
#: (field-data-collection.md "Form definition from the server").
_DEFINITION_IDENTITY_KEYS = ("definitionSha256", "definitionExtensions")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_EXTENSION_NAME_RE = re.compile(r"[a-z][a-z0-9_]{0,31}")
_MAX_DEFINITION_EXTENSIONS = 16
#: Draft meta keys a client (browser save or device envelope) may set.
_ENVELOPE_META_KEYS = ("schemaVersion", "formVersion", "instrumentId", "instrumentVersion", "createdAt", "updatedAt", *_DEFINITION_IDENTITY_KEYS)
#: The device's interview start and completion times (ISO 8601 with offset),
#: taken from the checked device envelope only: a browser save cannot set
#: them, so it cannot choose the date ``today()`` is evaluated at.
_DEVICE_TIME_KEYS = ("startedAt", "completedAt")


def save_draft_sections(draft: VaWebIntakeDraft, *, sections: dict, meta: dict | None = None, current_section: str | None = None, actor: VaUsers | None = None) -> int:
    """Upsert the given sections' answers; returns the number of sections written.

    A direct start's case (``draft_identity``) takes its identity from the
    merged answers of every saved section (a save sends only the sections that
    changed); any other case takes it at submit. *actor* is the saver,
    recorded when the case leaves ``draft_identity``; it defaults to the
    draft's owner, the only user who may save it.
    """
    if not isinstance(sections, dict):
        raise WebIntakeError("sections must be an object keyed by section name.")
    # Validated before anything is written, so a bad locale cannot leave the
    # answers saved and the meta refused.
    locale_meta = _clean_locale_meta(meta) if meta else {}
    if meta:
        check_definition_identity(meta)
    existing = {row.section_name: row for row in draft.sections}
    # docs/policy/web-intake.md "Locked prefill": a tampered or dropped locked
    # answer is put back, not refused (see submit_draft).
    locked = _draft_locked_answers(draft)
    written = 0
    browser_keys: set = set()
    for name, answers in sections.items():
        if not isinstance(name, str) or not _SECTION_NAME_RE.match(name):
            raise WebIntakeError(f"Invalid section name {name!r}.")
        if not isinstance(answers, dict):
            raise WebIntakeError(f"Section {name!r} must be an object of answers.")
        if name != DEVICE_SECTION:
            browser_keys.update(answers)
        row = existing.get(name)
        answers = _enforce_locked(answers, locked, row.data if row is not None else None)
        if row is None:
            row = VaWebIntakeDraftSection(draft_id=draft.draft_id, section_name=name, data=answers)
            db.session.add(row)
            draft.sections.append(row)
        else:
            row.data = answers
            row.saved_at = _utcnow()
        written += 1
    device_row = existing.get(DEVICE_SECTION)
    if browser_keys:
        # A browser save over a phone-won draft is no longer the phone's
        # content, and its answers beat the phone's for the same questions
        # (no section merge: web-intake.md "Parallel interviews").
        # ponytail: an answer the browser *cleared* is absent from its section,
        # so the phone's old value for it survives; clear it by key if that bites.
        draft.answers_sha256 = None
        if device_row is not None and browser_keys & set(device_row.data or {}):
            device_row.data = {k: v for k, v in device_row.data.items() if k not in browser_keys}
    if meta:
        keep = {k: meta[k] for k in _ENVELOPE_META_KEYS if k in meta}
        keep.update(locale_meta)
        draft.meta = {**(draft.meta or {}), **keep}
    if current_section is not None:
        if not _SECTION_NAME_RE.match(str(current_section)):
            raise WebIntakeError("Invalid current section.")
        draft.current_section = str(current_section)
    if written:
        # Only an answer write dates the draft: a locale or position save from
        # merely opening the form must not outrank a newer phone save.
        draft.updated_at = _utcnow()
    if written and draft.death_id:
        death = db.session.get(VaDeathRegister, draft.death_id)
        # Identity follows the form only for a direct start, which only its
        # starter sees; on a shared case it updates at the winning submit.
        if death.status == "draft_identity":
            merged: dict = {}
            for row in draft.sections:
                merged.update(row.data or {})
            _sync_case_identity(death, merged, actor or db.session.get(VaUsers, draft.user_id))
        if death.status not in _SUPERSEDED_CASE_STATES:
            death.updated_at = draft.updated_at  # the worklist sorts by last activity
    db.session.flush()
    return written


def discard_draft(draft: VaWebIntakeDraft, actor: VaUsers | None = None) -> None:
    """Discard a draft. Its case waits for a new interview (``registered``)
    unless another interviewer still holds an open draft on it; a direct start
    discarded before it had an identity is cancelled."""
    draft.status = "discarded"
    death = db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None
    if death is not None:
        # Under the case lock, so two concurrent discards (or a discard racing
        # a teammate's start) see each other's drafts.
        death = cases.lock_case(death)
    actor = actor or db.session.get(VaUsers, draft.user_id)
    if death is not None and death.status == "in_progress":
        others_open = db.session.scalar(
            sa.select(
                sa.exists().where(
                    VaWebIntakeDraft.death_id == death.death_id,
                    VaWebIntakeDraft.status == "draft",
                    VaWebIntakeDraft.draft_id != draft.draft_id,
                )
            )
        )
        if not others_open:
            cases.transition(death, "registered", actor=actor, action="draft_discarded")
    elif death is not None and death.status == "draft_identity":
        cases.transition(death, "cancelled", actor=actor, action="draft_discarded")
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


def build_web_payload(draft: VaWebIntakeDraft, data: dict, user: VaUsers, *, submitted_at: datetime, intake_source: str = "web", meta: dict | None = None, carry: dict | None = None) -> tuple[dict, dict]:
    """Return (payload, attachment_references) shaped like a synced ODK record.

    Attachment answers are lifted out of the payload (phase 2 uploads them
    through the attachment store) and their slot names returned separately.

    ``meta`` replaces ``draft.meta`` when given (a revision builds the next
    version before it changes the draft).

    ``carry`` is the payload a revision replaces. Every value that is not an
    answer or an interview time is taken from it instead of today's world
    (the submitter's name, the organization-unit codes and names, the death
    register's ABHA), so renaming the interviewer or a unit after the submit
    does not turn a resend of the same answers into a change. So are the
    identifiers ``sid``, ``KEY`` and ``instanceID``: the submission keeps its
    id when another interviewer's draft supplies the answers (a supervisor's
    choice, ``choose_interview``), where they would otherwise name *draft*.

    ``data`` is expected to already have had ``strip_irrelevant_answers``
    applied (see ``submit_draft``): an attachment reference for a question
    that became irrelevant (e.g. an ``md_im*`` slot after ``md_available``
    flips to "no") must never reach ``references`` here, or it is counted in
    ``AttachmentsExpected`` and becomes phase 2's to upload. Today this is
    free -- ``who-va-attachment:`` values are client-local blob ids; nothing
    server-side is uploaded until a later phase reads
    ``draft.meta["attachmentReferences"]``, so dropping the reference here
    orphans no server storage. Phase 2 must not re-derive relevance from
    scratch against the browser's local blob store; it should trust that a
    reference present here was already relevant at submit time.
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
    if carry is None:
        unit_context = _unit_context(draft.org_unit_id)
    else:
        unit_context = {k: v for k, v in carry.items() if k.startswith("org_")}
    submitted_iso = submitted_at.isoformat()
    if meta is None:
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
        if death.source == "register":
            abha = {"abha_number": death.abha_number, "abha_address": death.abha_address}
            if carry is not None:
                abha = {k: carry[k] for k in abha if k in carry}
            for key, value in abha.items():
                payload.setdefault(key, value)
        payload["death_register_id"] = str(death.death_id)

    # ODK-shaped metadata so the shared projection and payload-version code
    # see a complete record (see va_odk_06_fetchsubmissions._normalize_odata_record).
    own_ids = {"KEY": f"web:{draft.draft_id}", "instanceID": f"web:{draft.draft_id}",
               "sid": f"web-{draft.draft_id}-{form.form_id.lower()}"}
    payload.update({k: (carry or {}).get(k) or v for k, v in own_ids.items()})
    payload["SubmissionDate"] = submitted_iso
    payload["updatedAt"] = submitted_iso
    payload["SubmitterName"] = carry["SubmitterName"] if carry and "SubmitterName" in carry else user.name
    payload["SubmitterID"] = str(user.user_id)
    payload["DeviceID"] = f"digitva-{intake_source}"
    payload["FormVersion"] = str(meta.get("instrumentVersion") or meta.get("formVersion") or "2022")
    # QA flag, never a refusal: filled on a served form version older than the
    # one this server serves now.
    payload["form_version_outdated"] = _is_outdated_form_version(payload["FormVersion"])
    payload["ReviewState"] = None
    payload["instanceName"] = f"{draft.unique_id}_WHOVA2022"
    payload["form_def"] = form.form_id
    # Device-recorded times when the interview carried them, else the draft's
    # open time and the server submit time (docs/policy/field-data-collection.md
    # "Interview times"). ``today`` is the completion date the server's
    # re-check used; nothing else reads it.
    started_at, completed_at = _device_time(meta.get("startedAt")), _device_time(meta.get("completedAt"))
    payload["start"] = meta["startedAt"] if started_at else meta.get("createdAt") or submitted_iso
    payload["end"] = meta["completedAt"] if completed_at else submitted_iso
    payload["today"] = (completed_at or submitted_at).date().isoformat()
    payload["AttachmentsExpected"] = len(references)
    payload["AttachmentsPresent"] = 0
    payload["intake_source"] = intake_source
    # What the respondent was shown: the working language and the exact
    # translation version behind it, so the screen is reconstructible.
    payload["intake_locale"] = meta.get("locale") or DEFAULT_LOCALE
    payload["intake_translation_version"] = meta.get("translation_version") or 0
    payload["unique_id2"] = f"{draft.unique_id}_{submitted_at.strftime('%H%M%S')}{int(submitted_at.microsecond / 1000):03}"
    return payload, references


def _require_live_org_unit(draft: VaWebIntakeDraft) -> None:
    """Refuse a submission whose organization unit is inactive or unplaced.

    A unit can be deactivated, or turn out to be unplaced (imported, parent
    not yet mapped — see ``unplaced_unit_codes``), between starting a draft
    and submitting it. Routing only attributes a submission to a live, placed
    unit, so the case would fall back to the mapping's unit or stay unrouted —
    and since coding eligibility is decided by the routed unit, an unrouted
    case in a project with an organization tree is visible to no coder at
    all. Failing here tells the interviewer while the draft is still safe,
    instead of filing a death nobody can see.
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
    unplaced = org.unplaced_unit_codes(unit.project_id)  # same predicate as the intake unit picker
    if str(unit.path).split(".")[0] in unplaced:
        raise WebIntakeError(
            f"The organization unit for this case ({unit.unit_name}) is not yet placed in the "
            "organization tree, so the case could not be attributed to it or reach a coder. Ask an "
            "administrator to map its parent (Organization → Units → Map parents) before submitting.",
            409,
        )


#: ``interview_outcome`` -> the case state its submission leaves the case in
#: (decision 8 of .tasks/2026-09-28-interviewer-worklist.md). Only
#: ``completed`` enters coding; the rest keep the case open for a later
#: complete submission.
OUTCOME_CASE_STATES = {
    "completed": "submitted",
    "refused": "refused",
    "partially_completed": "paused",
    "respondent_unavailable": "not_reachable",
}
_INCOMPLETE_OUTCOMES = frozenset({"partially_completed", "respondent_unavailable"})


def _interview_outcome(data: dict, completion: dict) -> str:
    """The ``interview_outcome`` a submission is stored with, decided here.

    The form cannot compute it (docs/policy/web-intake.md, "The
    ``interview_outcome`` question"): ``refused`` when consent (Id10013) is
    no; ``completed`` when the form reports every required question answered;
    otherwise the interviewer's own pick, which must be ``partially_completed`` or
    ``respondent_unavailable``. Raises 422 for an invalid form with no such
    pick, or a valid one without consent.
    """
    consent = normalize_consent(data.get("Id10013"))
    if consent.lower() == "no":
        return "refused"
    if completion.get("valid") is True:
        if not consent:
            raise WebIntakeError("The consent question (Id10013) must be answered.", 422)
        return "completed"
    picked = data.get("interview_outcome")
    if picked in _INCOMPLETE_OUTCOMES:
        return picked
    raise WebIntakeError(
        "The questionnaire is not valid yet; complete the sections flagged by the form, "
        "or record the interview outcome as partially completed or respondent unavailable.",
        422,
    )


def _visit_note(data: dict) -> dict:
    """The visit note an identity-less refusal carries: address and date of
    the visit required (422), remarks optional. Keyed by the form's answer
    names so it is stored in the payload exactly as the form collects it."""
    try:
        address = _clean(data.get("visit_address"), what="Visit address", required=True, max_len=500)
        visited = _clean_date(data.get("visit_date"), what="Visit date", required=True)
        remarks = _clean(data.get("visit_remarks"), what="Visit remarks", max_len=2000)
    except WebIntakeError as exc:
        raise WebIntakeError(f"A refusal with no identity needs a visit note: {exc}", 422) from exc
    note = {"visit_address": address, "visit_date": visited.isoformat()}
    if remarks:
        note["visit_remarks"] = remarks
    return note


#: Case states a submit is kept for as a superseded copy instead of
#: submitted: a teammate's complete submission won, or a supervisor closed
#: the case. Never refused, so nothing is left stuck on the phone or page.
_SUPERSEDED_CASE_STATES = frozenset({"submitted", "duplicate", "cancelled"})
#: Section holding a browser draft's final answers when it is superseded.
FINAL_SECTION = "final"


def _set_final_section(draft: VaWebIntakeDraft, data: dict) -> None:
    """Store *data* as the draft's ``final`` section: the exact final raw
    answers, locked answers included, before irrelevant ones are stripped. A
    browser section saved under that name is overwritten, not duplicated."""
    for row in draft.sections:
        if row.section_name == FINAL_SECTION:
            row.data = data
            return
    draft.sections.append(VaWebIntakeDraftSection(section_name=FINAL_SECTION, data=data))


def _supersede_draft(draft: VaWebIntakeDraft, data: dict, completion: dict) -> None:
    """Keep a draft whose case was closed meanwhile (a teammate's complete
    submission won): final answers stored, no submission, no routing, the case
    left exactly as it is. The browser's saved sections may lack the last
    edits, which only the submit carries, so they are kept as one more section."""
    _set_final_section(draft, data)
    draft.status = "superseded"
    # ``submit_draft`` has set ``interview_outcome`` in *data*. Read by the
    # candidate rule (``_candidate_condition``): a complete copy can be chosen
    # by a supervisor, an incomplete one never.
    draft.meta = {**(draft.meta or {}), "interviewOutcome": data.get("interview_outcome")}
    draft.submitted_at = _utcnow()
    draft.client_valid = completion.get("valid") is True
    draft.client_issue_count = len(completion.get("issues") or [])
    db.session.flush()
    log.info("draft kept as superseded copy | unique_id=%s | by=%s", draft.unique_id, draft.user_id)


_COMPOSED_VERSION_RE = re.compile(r"^\d+-[0-9a-f]{10}$")


def _is_outdated_form_version(version: str) -> bool:
    """A served (composed) form version other than the current one. The
    browser's bundled version and unknown strings are not composed versions."""
    if not _COMPOSED_VERSION_RE.match(version):
        return False
    try:
        return version != served_form_service.composed_version()
    except served_form_service.ServedFormUnavailable:
        return False


def build_final_payload(draft: VaWebIntakeDraft, user: VaUsers, data: dict, *, submitted_at: datetime, expression_now: datetime, visit_note: dict, intake_source: str, meta: dict | None = None, carry: dict | None = None) -> tuple[dict, dict, list]:
    """The coding payload for the final raw answers *data*, with its
    attachment references and the server's own validation diagnostic:
    ``(payload, references, validation_err)``. Shared by a first submit and an
    interviewer's revision (which passes the payload it replaces as *carry*, see
    ``build_web_payload``), so both strip and build identically."""
    # Re-derive relevance and constraint over the client's raw answers before
    # anything is stripped: this is the diagnostic the client's own
    # "valid: true" is checked against (beads digitva-cal.2). It does not
    # block the submission -- see derive_validation_errors' docstring.
    # Against the form version the interview was filled on, when the server
    # served that version (field-data-collection.md "Form version"); any other
    # (the browser's bundled form, an unknown version) uses the current rules.
    version = form_version_of(meta if meta is not None else draft.meta)
    validation_err = derive_validation_errors(data, now=expression_now, version=version)
    # Final submit only (never a draft save): remove answers to questions
    # that are not relevant, resolved to a fixed point (beads digitva-aiy.1).
    stripped_data, _removed_answers = strip_irrelevant_answers(data, now=expression_now, version=version)
    # Added after stripping: the form shows the note only while no given name
    # is recorded, so a partial identity would otherwise lose it as irrelevant.
    stripped_data = {**stripped_data, **visit_note}
    payload, references = build_web_payload(
        draft, stripped_data, user, submitted_at=submitted_at, intake_source=intake_source, meta=meta, carry=carry,
    )
    return payload, references, validation_err


def submit_draft(draft: VaWebIntakeDraft, user: VaUsers, *, completion: dict, intake_source: str = "web", completed_at: datetime | None = None) -> VaSubmissions | None:
    """Turn a draft into a submission; its ``interview_outcome`` decides where it goes.

    Every outcome is stored as a submission. Only ``completed`` enters coding
    and moves the case to ``submitted`` (first complete submission wins);
    ``refused`` and the incomplete outcomes are routed to ``consent_refused``
    (no SmartVA, no allocation) and leave the case waiting
    (``OUTCOME_CASE_STATES``). A draft whose case is already closed
    (``_SUPERSEDED_CASE_STATES``) becomes a ``superseded`` copy and the result
    is None.

    The submitted draft's ``meta["effectiveSavedAt"]`` is its completion time
    (*completed_at*, a device's skew-corrected ``completedAt``; the submit
    time when None), the clock a later version of the same interview is
    compared against (``revise_submission`` with ``resubmit``).
    """
    if draft.status != "draft":
        raise WebIntakeError("This draft has already been submitted.", 409)
    if not isinstance(completion, dict) or not isinstance(completion.get("data"), dict):
        raise WebIntakeError("completion.data is required.")
    outcome = _interview_outcome(completion["data"], completion)
    # Locked answers (interviewer identity, area presets, ABHA, registered age) are
    # overwritten with the draft's server-computed prefill, added when the
    # client left them out, before relevance is derived or stripped. Overwrite,
    # not refuse: a device interview finished offline may hold a stale locked
    # value (a profile or case edit), and refusing
    # would strand a completed interview the interviewer cannot correct.
    data = {**completion["data"], **_draft_locked_answers(draft), "interview_outcome": outcome}
    consent = normalize_consent(data.get("Id10013"))
    _require_live_org_unit(draft)
    death = db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None
    visit_note: dict = {}
    if death is not None:
        # Under the case lock, so a teammate's concurrent winning submit is
        # seen here and this one is kept as a superseded copy, and before any
        # identity sync, so a closed case's identity is never rewritten.
        death = cases.lock_case(death)
        # Re-read under the lock: a double or retried submit of this same
        # draft that won meanwhile must not turn the winner into a copy.
        if db.session.scalar(sa.select(VaWebIntakeDraft.status).where(VaWebIntakeDraft.draft_id == draft.draft_id)) != "draft":
            raise WebIntakeError("This draft has already been submitted.", 409)
        if death.status in _SUPERSEDED_CASE_STATES:
            _supersede_draft(draft, data, completion)
            return None
        # Identity comes from a direct start's own (only) draft or from the
        # winning complete submit, never from a refused or partial one on a
        # shared case.
        if death.status == "draft_identity" or outcome == "completed":
            _sync_case_identity(death, data, user)
        # A refusal needs no identity: WHO asks it after consent, so a direct
        # start refused at consent never has one. The submission is stored as
        # refused and the nameless case closes as cancelled, the only closed
        # state the identity constraint allows without one (digitva-vzk.12).
        identity_pending = death.status == "draft_identity"
        if identity_pending and outcome != "refused":
            raise WebIntakeError(
                "Record the name, date of death and sex of the deceased before submitting.", 422
            )
        if identity_pending:
            visit_note = _visit_note(data)
        _begin_interview(death, user)
        if not (identity_pending or death.status in ("in_progress", "paused")):
            raise WebIntakeError("This case is closed.", 409)
        # A case restarted from such a refusal still has no identity.
        if outcome != "refused" and not cases.identity_complete(death):
            raise WebIntakeError(
                "Record the name, date of death and sex of the deceased before submitting.", 422
            )

    submitted_at = _utcnow()
    # The device's completion time in its own offset, else the submit time in
    # the interviewer's timezone (docs/policy/field-data-collection.md).
    expression_now = _device_time((draft.meta or {}).get("completedAt")) or _expression_now(user, submitted_at)
    payload, references, validation_err = build_final_payload(
        draft, user, data, submitted_at=submitted_at, expression_now=expression_now,
        visit_note=visit_note, intake_source=intake_source,
    )
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
        validation_err=validation_err,
        answers_sha256=draft.answers_sha256,
    )
    # A refused or incomplete interview is kept but never coded. consent_refused
    # is the only existing state that is outside coding *and* blocked from
    # SmartVA (SMARTVA_BLOCKED_WORKFLOW_STATES); no new workflow state.
    enters_coding = outcome == "completed" and consent_is_valid(consent)
    route_synced_submission(
        va_sid,
        consent_valid=enters_coding,
        reason="web_intake_submitted",
        actor=system_actor(),
    )
    if enters_coding and not references:
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
    # The complete raw answers, whatever sections the saves held.
    _set_final_section(draft, data)
    draft.status = "submitted"
    draft.va_sid = va_sid
    draft.submitted_at = submitted_at
    draft.client_valid = completion.get("valid") is True
    draft.client_issue_count = len(completion.get("issues") or [])
    draft.meta = {
        **(draft.meta or {}), "attachmentReferences": references, "interviewOutcome": outcome,
        "effectiveSavedAt": (completed_at or submitted_at).isoformat(),
    }
    if visit_note:
        draft.meta = {**draft.meta, "visitNote": visit_note}
    if death is not None:
        action = "submitted" if outcome == "completed" else f"submitted_{outcome}"
        to_state = "cancelled" if identity_pending else OUTCOME_CASE_STATES[outcome]
        cases.transition(death, to_state, actor=user, action=action)
        if outcome == "completed":
            # The case's submission is the complete one; an earlier refused or
            # incomplete one stays linked through its draft only.
            death.va_sid = va_sid
            # The case is closed: interviewers still holding an open draft on it.
            holders = notification_service.open_draft_holders(death.death_id, exclude_user_id=user.user_id)
            notification_service.notify(
                holders, notification_service.CASE_SUBMITTED_BY_OTHER, project_id=draft.project_id,
                death_id=death.death_id, draft_id=holders,
            )
    db.session.flush()
    log.info("web intake submitted | sid=%s | unique_id=%s | by=%s | outcome=%s | attachments=%d", va_sid, draft.unique_id, user.user_id, outcome, len(references))
    return submission


# ---------------------------------------------------------------------------
# Interviewer revisions (digitva-bhpl part A, docs/policy/interview-revisions.md)
# ---------------------------------------------------------------------------

#: The fixed reasons for a revision. No free text: a reason carries no
#: personal data.
REVISION_REASONS = ("interviewer_correction", "respondent_correction", "more_information", "finish_partial")
#: The reason of a correction the server itself makes when a later version of
#: an interviewer's own interview arrives (an upload resent with other answers,
#: a second upload, a browser submit of an already submitted draft). Internal:
#: never accepted from a client (``REVISION_REASONS`` is the public list).
RESUBMITTED_REASON = "resubmitted"


def revision_unlocked(submission: VaSubmissions) -> bool:
    """True while a coder's or reviewer's send-back, or a supervisor's reopen
    (``interview_send_back_service``), holds *submission* open for its
    interviewer: it is in ``finalized_upstream_changed`` and the latest
    workflow event that put it there was one of those two requests. An ODK
    upstream change leaves it locked: that case is the data manager's to
    accept or reject. One indexed lookup (``get_open_revision_request``)."""
    return get_open_revision_request(submission.va_sid) is not None


def revise_submission(user: VaUsers, va_sid: str, *, reason_code: str, data: dict, answers_sha256: str | None, completion: dict, envelope: dict, resubmit: bool = False) -> dict:
    """Revise the submitted interview *va_sid* as its interviewer; returns the
    reply ``{changed, va_sid, payload_version_id, answers_sha256, outcome,
    workflow_state}`` (plus ``kept`` and ``locked`` with *resubmit*).

    Only the user whose draft became the submission may (else 404, never
    revealing it exists). Done under the case lock with a lock on the
    submission, so a concurrent submit, revision or sync serialises with it.
    The payload is rebuilt from the new raw answers exactly as ``submit_draft``
    builds it, on the original submit time, ``intake_source`` and
    non-answer values (``build_web_payload``'s *carry*), so only a real
    change in the answers or times changes the fingerprint.

    An equal fingerprint is the ODK no-change rule, which is about coding: no
    payload version, no release, no SmartVA rerun, no routing, no case move.
    Raw answers that differ only in answers stripped as irrelevant are still
    kept (the previous ones as a ``replaced`` draft row, the new ones as the
    draft's ``final`` section, ``answers_sha256`` set to the sent hash), so
    nothing typed is lost and the phone's acknowledgement matches; raw answers
    with the stored hash write nothing. Otherwise the previous raw answers are
    kept as a ``replaced`` draft row, the draft takes the new ones, a new
    active payload version records reason and hash, the coding artifacts and
    allocations are dropped as an ODK edit drops them, and the submission is
    re-routed. An incomplete outcome revised to ``completed`` also runs
    ``submit_draft``'s completion branch (case to ``submitted``); one revised
    to another incomplete outcome moves the case to that outcome's state
    (``OUTCOME_CASE_STATES``) the way a submit does. A completed interview
    revised to refused or incomplete is allowed (the latest completed version
    wins, docs/policy/interview-revisions.md): coding is released first, the
    submission routes to ``consent_refused``, and the case it won leaves
    ``submitted`` for that outcome's state and loses its ``va_sid``. A
    completed-to-completed revision syncs the form's identity answers onto the
    case again: the winning submission is the one corrected.

    A protected case is locked, except one a coder, reviewer or supervisor
    sent back or reopened (``revision_unlocked``): its changed revision
    restarts coding at once (``reopen_coding_after_revision``, the data
    manager's accept block under a system actor), rejects any lingering
    pending upstream payload, and keeps the earlier COD as inactive history.
    An unchanged revision leaves that case sent back.

    The draft's ``meta["effectiveSavedAt"]`` becomes this version's completion
    time (``_completion_time`` of *envelope*).

    *resubmit* is the server's own correction of the interviewer's latest
    version (reason ``RESUBMITTED_REASON``) and never refuses for a reason the
    caller cannot act on: the version is applied only when it is not older than
    the stored one (a tie goes to the later received) and the case still takes
    it. Otherwise (coding finished, case closed or won by a teammate, or an
    older version) nothing in the case changes and the answers are kept as a
    ``replaced`` row, once per answers (``kept: "server"``; ``locked: true``
    when coding or the case no longer takes any version).

    Every other refusal is decided before anything is written, except the
    workflow race ``revision_locked`` (a coder finalised after the check) and a
    case transition ``cases.transition`` refuses; those raise after writes, and
    the route's error handler rolls the whole transaction back. Refusals: 404
    unknown or not the caller's, 409 ``revision_locked`` (protected workflow
    state not sent back or reopened), ``case_already_submitted`` (a teammate's
    complete submission won), ``case_closed`` (duplicate or cancelled),
    ``case_state_conflict`` (an outcome change a teammate's winning case state
    does not allow), the live-org-unit refusals when finishing a partial, 422
    ``invalid_reason``, the missing identity of a finished partial and
    ``_interview_outcome``'s own.
    """
    if not resubmit and reason_code not in REVISION_REASONS:
        raise WebIntakeError("reason_code must be one of: " + ", ".join(REVISION_REASONS) + ".", 422, "invalid_reason")
    draft = db.session.scalar(sa.select(VaWebIntakeDraft).where(
        VaWebIntakeDraft.va_sid == va_sid,
        VaWebIntakeDraft.user_id == user.user_id,
        VaWebIntakeDraft.status == "submitted",
    ))
    if draft is None:
        raise WebIntakeError("Submission not found.", 404)
    death = db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None
    if death is not None:
        death = cases.lock_case(death)
    submission = db.session.get(VaSubmissions, va_sid, with_for_update=True)
    # Re-read under the locks: a revision that won meanwhile is the version
    # this one compares against.
    db.session.refresh(draft)
    if submission is None or draft.status != "submitted":
        raise WebIntakeError("Submission not found.", 404)
    state = get_submission_workflow_state(va_sid)
    # A sent-back or reopened case takes the revision and restarts coding at
    # once; every other protected state is locked, an ODK upstream change
    # included (the data manager resolves that one).
    reopening = state == WORKFLOW_FINALIZED_UPSTREAM_CHANGED and revision_unlocked(submission)
    locked = state in PROTECTED_WORKFLOW_STATES and not reopening
    if locked and not resubmit:
        raise WebIntakeError("Coding has finished on this interview; it can no longer be revised.", 409, "revision_locked")

    active = get_active_payload_version(va_sid)
    prior = (active.payload_data if active is not None else None) or {}
    previous = (draft.meta or {}).get("interviewOutcome") or prior.get("interview_outcome")
    now = _utcnow()
    completed_at = _completion_time(envelope, now)

    def kept_apart(*, closed: bool) -> dict:
        """The resubmitted answers stay history; the coder's version stands."""
        _keep_losing_version(draft, data, answers_sha256, meta={
            "source": "resubmission", "effectiveSavedAt": completed_at.isoformat(), "receivedAt": now.isoformat(),
        })
        return {**_revision_reply(draft, active, False, previous), "kept": "server", "locked": closed}

    if resubmit:
        stored_at = (draft.meta or {}).get("effectiveSavedAt")
        stored_at = datetime.fromisoformat(stored_at) if stored_at else draft.submitted_at
        if locked:
            return kept_apart(closed=True)
        if stored_at is not None and completed_at < stored_at:
            return kept_apart(closed=False)
    outcome = _interview_outcome(data, completion)
    regressing = previous == "completed" and outcome != "completed"
    completing = outcome == "completed" and previous != "completed"
    # Locked answers keep the value the interview was submitted with; one the
    # submit never held is filled from the case and the interviewer, as on a
    # submit. Recomputing them all would turn a renamed interviewer or a
    # corrected registration into a change to answers nobody edited.
    stored = _answers_of(draft)
    locked_answers = {name: stored.get(name, value) for name, value in _draft_locked_answers(draft).items()}
    raw = {**data, **locked_answers, "interview_outcome": outcome}
    if death is not None:
        refusal = None
        if death.status in ("duplicate", "cancelled"):
            refusal = WebIntakeError("This case is closed.", 409, "case_closed")
        elif completing:
            if death.status == "submitted" and death.va_sid != va_sid:
                refusal = WebIntakeError("A complete interview of this case was already submitted.", 409, "case_already_submitted")
            else:
                _require_live_org_unit(draft)
                # What the identity sync below will leave on the case.
                identity = {
                    "deceased_name": death.deceased_name, "date_of_death": death.date_of_death,
                    "deceased_sex": death.deceased_sex, **_identity_from_answers(raw),
                }
                if not all(identity.values()):
                    raise WebIntakeError("Record the name, date of death and sex of the deceased before submitting.", 422)
        elif outcome != previous and death.status != OUTCOME_CASE_STATES[outcome] and death.va_sid != va_sid:
            # Incomplete to another incomplete outcome: the case follows it as
            # on a submit (via in_progress), or the revision is refused rather
            # than leave the case and the submission disagreeing. The case's
            # own winning submission always moves it (a regression included).
            if death.status not in _STARTABLE_STATES and death.status != "in_progress":
                refusal = WebIntakeError(
                    f"The case is {death.status}, so this interview's outcome can no longer be changed.",
                    409, "case_state_conflict",
                )
        if refusal is not None:
            if not resubmit:
                raise refusal
            return kept_apart(closed=True)

    meta = {
        **(draft.meta or {}),
        **{k: envelope[k] for k in (*_DEVICE_TIME_KEYS, *_DEFINITION_IDENTITY_KEYS) if k in envelope},
    }
    # The original submit time and source: SubmissionDate, the masked id and
    # the default end time stay as they were, so they never read as a change.
    submitted_at = datetime.fromisoformat(prior["SubmissionDate"]) if prior.get("SubmissionDate") else draft.submitted_at
    expression_now = _device_time(meta.get("completedAt")) or _expression_now(user, submitted_at)
    payload, references, validation_err = build_final_payload(
        draft, user, raw, submitted_at=submitted_at, expression_now=expression_now, visit_note={},
        intake_source=prior.get("intake_source") or "web", meta=meta, carry=prior if active is not None else None,
    )
    fingerprint = canonical_payload_fingerprint(payload)
    # Recomputed from the stored payload, as ensure_active_payload_version and
    # ODK sync decide "same payload": a stored column from an older
    # normalisation must not turn a no-op into a release.
    if active is not None and canonical_payload_fingerprint(prior) == fingerprint:
        if answers_sha256 != draft.answers_sha256:
            _replace_raw_answers(draft, raw, answers_sha256, completion, at=now, version_id=active.payload_version_id)
        reply = _revision_reply(draft, active, False, outcome)
        if resubmit:
            draft.meta = {**(draft.meta or {}), "effectiveSavedAt": completed_at.isoformat()}
            reply.update(kept="incoming", locked=False)
        return reply

    payload["updatedAt"] = now.isoformat()
    form = db.session.get(VaForms, draft.form_id)
    fields = build_submission_projection(form, payload)
    if fields["va_sid"] != va_sid:
        if resubmit:
            return kept_apart(closed=True)
        raise WebIntakeError("This interview's form changed; it cannot be revised.", 409)
    # All refusals above are decided; writes start here.
    if death is not None and outcome == "completed":
        _sync_case_identity(death, raw, user)
    apply_submission_projection(submission, fields, payload)
    version = ensure_active_payload_version(
        submission,
        payload_data=payload,
        source_updated_at=fields["va_odk_updatedat"],
        created_by_role=PAYLOAD_ROLE,
        created_by=user.user_id,
        validation_err=validation_err,
        revision_reason_code=reason_code,
        answers_sha256=answers_sha256,
    )
    # updatedAt moved: the stored daily KPI rows of the submission's days are recounted.
    cases._recompute_kpi_rows_after_commit(va_sid)
    _replace_raw_answers(draft, raw, answers_sha256, completion, at=now, version_id=version.payload_version_id)
    draft.meta = {**meta, "attachmentReferences": references, "interviewOutcome": outcome, "effectiveSavedAt": completed_at.isoformat()}

    enters_coding = outcome == "completed" and consent_is_valid(normalize_consent(raw.get("Id10013")))
    try:
        if reopening:
            # The revision is the new payload: no pending upstream version may
            # linger beside it. Coding restarts at smartva_pending, then the
            # routing below puts the case where any revision would be.
            pending = get_latest_pending_upstream_payload_version(va_sid)
            if pending is not None:
                reject_pending_upstream_payload_version(pending, reason="superseded_by_interviewer_revision")
            resolve_pending_upstream_change(
                va_sid, resolution_status=UPSTREAM_CHANGE_STATUS_REJECTED, resolved_by=user.user_id, resolved_by_role=AUDIT_ROLE,
            )
            reopen_coding_after_revision(va_sid, audit_by=user.user_id)
        else:
            release_coding_for_changed_payload(va_sid, source=SOURCE_INTERVIEWER_REVISION, audit_by=user.user_id)
        route_synced_submission(va_sid, consent_valid=enters_coding, reason="interviewer_revision", actor=system_actor())
    except WorkflowTransitionError as exc:
        # A coder finalised between the check above and here; the route rolls back.
        raise WebIntakeError("Coding has finished on this interview; it can no longer be revised.", 409, "revision_locked") from exc
    if enters_coding and not references:
        mark_attachment_sync_completed(va_sid, reason="web_intake_no_attachments", actor=system_actor())
    if death is not None and outcome != previous:
        target = OUTCOME_CASE_STATES[outcome]
        if completing or death.status != target:
            _begin_interview(death, user)
            cases.transition(
                death, target, actor=user, action="submitted" if completing else f"submitted_{outcome}", reason=reason_code,
            )
        if completing:
            death.va_sid = va_sid
        elif regressing and death.va_sid == va_sid:
            # The case waits for a new complete interview; the regressed
            # submission stays linked through its draft only.
            death.va_sid = None
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid,
        va_audit_byrole=AUDIT_ROLE,
        va_audit_by=user.user_id,
        va_audit_operation="u",
        va_audit_action="va_submission_revised_by_interviewer",
        va_audit_entityid=version.payload_version_id,
    ))
    db.session.flush()
    log.info("interview revised | sid=%s | by=%s | reason=%s | outcome=%s", va_sid, user.user_id, reason_code, outcome)
    reply = _revision_reply(draft, version, True, outcome)
    if resubmit:
        reply.update(kept="incoming", locked=False)
    return reply


def _replace_raw_answers(draft: VaWebIntakeDraft, raw: dict, answers_sha256: str, completion: dict, *, at: datetime, version_id: uuid.UUID) -> None:
    """Keep the draft's current raw answers as a ``replaced`` history row and
    make *raw* its only (``final``) section, with the sent hash and the
    completion that came with it. *version_id* is the payload version that was
    current when the answers were replaced."""
    _keep_history(draft, _answers_of(draft), sha256=draft.answers_sha256, meta={
        "source": "revision", "revisedAt": at.isoformat(), "payloadVersionId": str(version_id),
    })
    _set_final_section(draft, raw)
    for row in [r for r in draft.sections if r.section_name != FINAL_SECTION]:
        draft.sections.remove(row)
    draft.answers_sha256 = answers_sha256
    draft.client_valid = completion.get("valid") is True
    draft.client_issue_count = len(completion.get("issues") or [])


def _revision_reply(draft: VaWebIntakeDraft, version, changed: bool, outcome: str) -> dict:
    return {
        "changed": changed,
        "va_sid": draft.va_sid,
        "payload_version_id": str(version.payload_version_id),
        "answers_sha256": draft.answers_sha256,
        "outcome": outcome,
        "workflow_state": get_submission_workflow_state(draft.va_sid),
    }


# ---------------------------------------------------------------------------
# A supervisor chooses between two complete interviews (digitva-bqzm,
# docs/policy/web-intake.md "Parallel interviews")
# ---------------------------------------------------------------------------

#: Fixed reasons for a choice; no free text, so a reason carries no personal data.
CHOICE_REASONS = ("better_quality", "more_complete", "original_incorrect", "switch_back")
#: Most candidates one case detail lists (a case rarely has more than one).
CANDIDATES_MAX = 20


def _candidate_condition():
    """SQL condition on ``VaWebIntakeDraft``: a candidate for the case's
    interview, a ``superseded`` copy whose interview was complete. A ``replaced``
    row (history of a resend) and an incomplete copy never qualify."""
    return sa.and_(
        VaWebIntakeDraft.status == "superseded",
        VaWebIntakeDraft.meta["interviewOutcome"].astext == "completed",
    )


def _has_candidate():
    """Correlated EXISTS on ``VaDeathRegister``: the submitted case has a
    candidate, i.e. a second complete interview exists. One probe on
    ``ix_va_web_intake_drafts_death`` per case row."""
    return sa.exists().where(
        VaWebIntakeDraft.death_id == VaDeathRegister.death_id,
        _candidate_condition(),
        VaDeathRegister.status == "submitted",
        VaDeathRegister.va_sid.is_not(None),
    )


def list_candidates(death: VaDeathRegister) -> list[dict]:
    """The other complete interviews of a submitted case a supervisor may
    choose, newest first: ``{draft_id, interviewer_name, completed_at,
    outcome}``. Names are for supervisors only (staff identity, as the
    supervision list shows who registered a case); never serve this to an
    interviewer. One query, joined to the interviewer."""
    if death.status != "submitted" or not death.va_sid:
        return []
    rows = db.session.execute(
        sa.select(
            VaWebIntakeDraft.draft_id, VaUsers.name, VaWebIntakeDraft.submitted_at,
            VaWebIntakeDraft.meta["completedAt"].astext,
        )
        .join(VaUsers, VaUsers.user_id == VaWebIntakeDraft.user_id)
        .where(VaWebIntakeDraft.death_id == death.death_id, _candidate_condition())
        .order_by(VaWebIntakeDraft.submitted_at.desc())
        .limit(CANDIDATES_MAX)
    ).all()
    return [
        {
            "draft_id": str(draft_id), "interviewer_name": name,
            "completed_at": completed or (submitted_at.isoformat() if submitted_at else None),
            "outcome": "completed",
        }
        for draft_id, name, submitted_at, completed in rows
    ]


def _candidate_completed_at(draft: VaWebIntakeDraft) -> datetime:
    """When *draft*'s interview was completed, in server time: the device's
    ``completedAt`` corrected by the clock skew recorded at upload and never
    later than the upload (``_completion_time``'s rule), else the upload."""
    meta = draft.meta or {}
    done = _device_time(meta.get("completedAt"))
    if done is None:
        return draft.submitted_at
    skew = meta.get("clockSkewSeconds")
    if isinstance(skew, (int, float)) and not isinstance(skew, bool):
        done += timedelta(seconds=skew)
    return min(done, draft.submitted_at)


def _supervising_actor(user: VaUsers, death: VaDeathRegister):
    """The workflow actor *user* chooses as: an admin, or a supervisor or data
    manager whose supervision reach covers *death* (audited as a data manager
    when the grant is data-manager shaped, as ``reopen_for_revision`` does);
    else 404, so an id outside the caller's reach is never confirmed."""
    if user.is_admin():
        return admin_actor(user.user_id)
    if not cases.is_interview_supervisor_for(user, death):
        raise WebIntakeError("Case not found.", 404)
    shaped = supervision.dm_shaped_grant(user.user_id, death)
    return data_manager_actor(user.user_id) if shaped else interview_supervisor_actor(user.user_id)


def choose_interview(user: VaUsers, death_id: object, candidate_draft_id: object, reason_code: object) -> VaDeathRegister:
    """A supervisor, data manager or admin chooses the *candidate_draft_id*
    interview (another interviewer's complete one, kept as a superseded copy)
    over the one the submitted case now holds; returns the case.

    The submission keeps its ``va_sid``. The candidate's answers become a new
    active payload version (reason ``supervisor_choice``, built by
    ``build_final_payload`` on the original submit time with the sid, key and
    non-answer values carried over), so ``va_data_collector`` and the
    projection follow the chosen interviewer; the identity answers sync onto
    the case. The drafts swap: the candidate becomes the ``submitted`` draft
    carrying the ``va_sid``, the former winner becomes ``superseded`` (sid
    cleared, ``meta.previousVaSid`` set) and stays a candidate, so the choice
    can be switched back, each time audited.

    Coding restarts as for any changed payload: a protected case (final COD
    given) moves through ``finalized_upstream_changed`` and
    ``reopen_coding_after_revision``, the earlier COD kept as inactive
    history; an unprotected one is released
    (``release_coding_for_changed_payload``); the submission is then re-routed.
    Both interviewers are notified (``INTERVIEW_CHOSEN``; the chosen one with
    the ``va_sid``).

    Done under the case lock, then a lock on the submission
    (``revise_submission``'s order). Refusals: 422 ``invalid_reason``; 404 an
    unknown or out-of-reach case, or a candidate that is not this case's; 409
    ``case_not_submitted``, ``not_web_submission``, ``not_a_candidate`` (not a
    superseded, complete interview), ``form_mismatch``, ``wrong_state`` (a
    reviewer session is live) and the form-changed refusal.
    """
    if reason_code not in CHOICE_REASONS:
        raise WebIntakeError("reason_code must be one of: " + ", ".join(CHOICE_REASONS) + ".", 422, "invalid_reason")
    try:
        death = db.session.get(VaDeathRegister, uuid.UUID(str(death_id)))
    except ValueError:
        death = None
    if death is None:
        raise WebIntakeError("Case not found.", 404)
    try:
        candidate_id = uuid.UUID(str(candidate_draft_id))
    except ValueError:
        raise WebIntakeError("draft_id must be a UUID.") from None
    actor = _supervising_actor(user, death)
    death = cases.lock_case(death)
    if death.status != "submitted" or not death.va_sid:
        raise WebIntakeError("Only a submitted case has an interview to choose.", 409, "case_not_submitted")
    va_sid = death.va_sid
    submission = db.session.get(VaSubmissions, va_sid, with_for_update=True)
    winner = db.session.scalar(sa.select(VaWebIntakeDraft).where(
        VaWebIntakeDraft.va_sid == va_sid, VaWebIntakeDraft.status == "submitted"))
    candidate = db.session.get(VaWebIntakeDraft, candidate_id)
    if submission is None or winner is None:
        raise WebIntakeError("Only a web or device interview can be chosen between here.", 409, "not_web_submission")
    if candidate is None or candidate.death_id != death.death_id:
        raise WebIntakeError("Interview not found.", 404)
    if candidate.status != "superseded" or (candidate.meta or {}).get("interviewOutcome") != "completed":
        raise WebIntakeError("Only another complete interview of this case can be chosen.", 409, "not_a_candidate")
    if candidate.form_id != winner.form_id:
        raise WebIntakeError("That interview was filled on another form.", 409, "form_mismatch")
    state = get_submission_workflow_state(va_sid)  # read under the lock
    if state == WORKFLOW_REVIEWER_CODING_IN_PROGRESS:
        raise WebIntakeError("A reviewer is coding this interview; try again when the session ends.", 409, "wrong_state")
    active = get_active_payload_version(va_sid)
    if active is None:
        raise WebIntakeError("This submission has no payload to replace.", 409, "wrong_state")
    prior = active.payload_data or {}

    chosen_user = db.session.get(VaUsers, candidate.user_id)
    now = _utcnow()
    meta = {k: v for k, v in (candidate.meta or {}).items() if k != "previousVaSid"}
    raw = {**_answers_of(candidate), "interview_outcome": "completed"}
    submitted_at = datetime.fromisoformat(prior["SubmissionDate"]) if prior.get("SubmissionDate") else winner.submitted_at
    expression_now = _device_time(meta.get("completedAt")) or _expression_now(chosen_user, candidate.submitted_at)
    payload, references, validation_err = build_final_payload(
        winner, chosen_user, raw, submitted_at=submitted_at, expression_now=expression_now, visit_note={},
        intake_source=prior.get("intake_source") or "web", meta=meta,
        carry={k: v for k, v in prior.items() if k != "SubmitterName"},
    )
    payload["updatedAt"] = now.isoformat()
    fields = build_submission_projection(db.session.get(VaForms, winner.form_id), payload)
    if fields["va_sid"] != va_sid:
        raise WebIntakeError("This interview's form changed; it cannot be chosen.", 409, "form_mismatch")
    # All refusals are decided; writes start here.
    _sync_case_identity(death, raw, user)
    apply_submission_projection(submission, fields, payload)
    version = ensure_active_payload_version(
        submission, payload_data=payload, source_updated_at=fields["va_odk_updatedat"],
        created_by_role=actor.audit_role, created_by=user.user_id, validation_err=validation_err,
        revision_reason_code="supervisor_choice", answers_sha256=candidate.answers_sha256,
    )
    cases._recompute_kpi_rows_after_commit(va_sid)

    enters_coding = consent_is_valid(normalize_consent(raw.get("Id10013")))
    try:
        if state in PROTECTED_WORKFLOW_STATES:
            if state != WORKFLOW_FINALIZED_UPSTREAM_CHANGED:
                mark_upstream_change_detected(va_sid, reason=INTERVIEW_CHOSEN_REASON, actor=actor)
            # No pending upstream version may linger beside the chosen payload.
            pending = get_latest_pending_upstream_payload_version(va_sid)
            if pending is not None:
                reject_pending_upstream_payload_version(pending, reason="superseded_by_interview_choice")
            resolve_pending_upstream_change(
                va_sid, resolution_status=UPSTREAM_CHANGE_STATUS_REJECTED, resolved_by=user.user_id,
                resolved_by_role=actor.audit_role,
            )
            reopen_coding_after_revision(va_sid, audit_by=user.user_id, source=SOURCE_SUPERVISOR_CHOICE)
        else:
            release_coding_for_changed_payload(va_sid, source=SOURCE_SUPERVISOR_CHOICE, audit_by=user.user_id)
        route_synced_submission(va_sid, consent_valid=enters_coding, reason=INTERVIEW_CHOSEN_REASON, actor=system_actor())
    except WorkflowTransitionError as exc:
        # A coder finalised or a reviewer started after the check; the route rolls back.
        raise WebIntakeError("The interview changed state; try again.", 409, "wrong_state") from exc
    if enters_coding and not references:
        mark_attachment_sync_completed(va_sid, reason="web_intake_no_attachments", actor=system_actor())

    # The swap. The former winner keeps its answers and its outcome, so it is a
    # candidate again (switch back); the sid moves with the submitted draft.
    winner.status = "superseded"
    winner.va_sid = None
    winner.meta = {**(winner.meta or {}), "previousVaSid": va_sid}
    candidate.status = "submitted"
    candidate.va_sid = va_sid
    candidate.meta = {
        **meta, "attachmentReferences": references, "interviewOutcome": "completed",
        "effectiveSavedAt": _candidate_completed_at(candidate).isoformat(),
    }
    db.session.add(VaSubmissionsAuditlog(
        va_sid=va_sid, va_audit_byrole=actor.audit_role, va_audit_by=user.user_id, va_audit_operation="u",
        va_audit_action=f"va_submission_interview_chosen_by_supervisor:{reason_code}",
        va_audit_entityid=version.payload_version_id,
    ))
    cases.record_action(death, actor=user, action="interview_chosen", reason=reason_code)
    if candidate.user_id != user.user_id:
        notification_service.notify(
            [candidate.user_id], notification_service.INTERVIEW_CHOSEN, project_id=candidate.project_id,
            death_id=death.death_id, draft_id=candidate.draft_id, va_sid=va_sid,
        )
    if winner.user_id not in (user.user_id, candidate.user_id):
        notification_service.notify(
            [winner.user_id], notification_service.INTERVIEW_CHOSEN, project_id=winner.project_id,
            death_id=death.death_id, draft_id=winner.draft_id,
        )
    db.session.flush()
    log.info("interview chosen | sid=%s | by=%s | reason=%s | chosen_draft=%s", va_sid, user.user_id, reason_code, candidate.draft_id)
    return death


# ---------------------------------------------------------------------------
# Device uploads (Path B, .tasks/2026-09-30-android-collection-app.md)
# ---------------------------------------------------------------------------

#: The one section a device upload's answers are stored under: the app sends
#: the whole envelope at once, not section-wise saves.
DEVICE_SECTION = "device"
#: Bounds on a device upload's answers, checked before anything is stored
#: (the request itself is capped at 2 MB by the device blueprint). Answers
#: are flat values, choice lists and small attachment/audit objects.
DEVICE_ANSWERS_MAX_BYTES = 1024 * 1024
DEVICE_ANSWERS_MAX_DEPTH = 6


def check_device_answers(data: dict) -> None:
    """Refuse (422) answers nested deeper than DEVICE_ANSWERS_MAX_DEPTH. The
    size cap is on the upload's ``answers_json`` text, checked by the route."""
    stack = [(data, 1)]
    while stack:
        value, depth = stack.pop()
        if depth > DEVICE_ANSWERS_MAX_DEPTH:
            raise WebIntakeError("answers_json is nested too deeply.", 422)
        children = value.values() if isinstance(value, dict) else value
        stack.extend((child, depth + 1) for child in children if isinstance(child, (dict, list)))


def check_definition_identity(meta: dict) -> None:
    """Refuse (422) a ``definitionSha256`` that is not 64 lowercase hex or a
    ``definitionExtensions`` that is not a short list of extension names.
    Absent is fine (an older app, a browser form)."""
    sha = meta.get("definitionSha256")
    if "definitionSha256" in meta and not (isinstance(sha, str) and _SHA256_RE.fullmatch(sha)):
        raise WebIntakeError("definitionSha256 must be 64 lowercase hex characters.", 422)
    names = meta.get("definitionExtensions")
    if "definitionExtensions" in meta and not (
        isinstance(names, list)
        and len(names) <= _MAX_DEFINITION_EXTENSIONS
        and all(isinstance(n, str) and _EXTENSION_NAME_RE.fullmatch(n) for n in names)
    ):
        raise WebIntakeError("definitionExtensions must be a short list of extension names.", 422)


def check_device_times(envelope: dict) -> None:
    """Refuse (422) an envelope whose ``startedAt``, ``completedAt`` or
    ``deviceClockAt`` is present but not an ISO 8601 time with a UTC offset, or
    whose definition identity is malformed (``check_definition_identity``).
    Absent is fine (an older app)."""
    check_definition_identity(envelope)
    for field in ("startedAt", "completedAt", "deviceClockAt"):
        if field in envelope and _device_time(envelope[field]) is None:
            raise WebIntakeError(f"draft.{field} must be an ISO 8601 time with a UTC offset.", 422)


def find_device_upload(user: VaUsers, client_draft_id: uuid.UUID) -> VaWebIntakeDraft | None:
    """The draft an earlier upload of *client_draft_id* created, if any.
    Another interviewer's id is a 409, never their result."""
    draft = db.session.scalar(
        sa.select(VaWebIntakeDraft).where(VaWebIntakeDraft.client_draft_id == client_draft_id)
    )
    if draft is not None and draft.user_id != user.user_id:
        raise WebIntakeError("That client_draft_id is already in use.", 409)
    return draft


def _store_superseded_copy(user: VaUsers, death: VaDeathRegister, *, client_draft_id: uuid.UUID, site_id: str, data: dict, answers_sha256: str, meta: dict, completion: dict) -> VaWebIntakeDraft:
    """Keep a device interview for a closed case as a ``superseded`` draft
    linked to the case: answers stored, no submission, no routing, and the
    case (its identity included) left exactly as it is."""
    if death.site_id != site_id:
        raise WebIntakeError("Death entry belongs to another project or site.")
    try:
        outcome = _interview_outcome(data, completion)
    except WebIntakeError:
        outcome = None
    form = ensure_web_runtime_form(death.project_id, death.site_id)
    # Stored answers get the same locked-answer rule as a submission.
    prefill = _prefill_from_death(death, user, death.org_unit_id)
    data = {**data, **_locked_answers(prefill)}
    now = _utcnow()
    draft = VaWebIntakeDraft(
        project_id=death.project_id,
        site_id=death.site_id,
        org_unit_id=death.org_unit_id,
        death_id=death.death_id,
        form_id=form.form_id,
        user_id=user.user_id,
        unique_id=death.unique_id,
        meta={"instrumentId": INSTRUMENT_ID, "locale": DEFAULT_LOCALE, "translation_version": 0,
              **meta, "interviewOutcome": outcome},
        prefill=prefill,
        status="superseded",
        client_draft_id=client_draft_id,
        answers_sha256=answers_sha256,
        submitted_at=now,
        client_valid=completion.get("valid") is True,
    )
    draft.sections.append(VaWebIntakeDraftSection(section_name=DEVICE_SECTION, data=data))
    db.session.add(draft)
    db.session.flush()
    log.info("device interview kept as superseded copy | unique_id=%s | case_status=%s | by=%s", death.unique_id, death.status, user.user_id)
    return draft


def _device_completion(completion: dict, data: dict) -> dict:
    """The upload's ``{valid, issues}`` normalised, with the parsed answers as ``data``."""
    return {
        "valid": completion.get("valid") is True,
        "issues": completion.get("issues") if isinstance(completion.get("issues"), list) else [],
        "data": data,
    }


def _own_submitted_draft(user: VaUsers, death: VaDeathRegister) -> VaWebIntakeDraft | None:
    """The caller's submitted draft of *death* that a later upload of the same
    interview corrects (docs/policy/web-intake.md "Parallel interviews"): the
    one that won the case, else their latest. None when they have none, or
    when a teammate's complete submission or a supervisor closed the case and
    theirs is not the winner: that upload stays a superseded copy. One query
    on ``ix_va_web_intake_drafts_death``."""
    own = db.session.scalar(
        sa.select(VaWebIntakeDraft)
        .where(
            VaWebIntakeDraft.death_id == death.death_id,
            VaWebIntakeDraft.user_id == user.user_id,
            VaWebIntakeDraft.status == "submitted",
        )
        .order_by(sa.case((VaWebIntakeDraft.va_sid == death.va_sid, 0), else_=1), VaWebIntakeDraft.submitted_at.desc())
        .limit(1)
    )
    if own is not None and (own.va_sid == death.va_sid or death.status not in _SUPERSEDED_CASE_STATES):
        return own
    return None


def resubmit_device_interview(user: VaUsers, draft: VaWebIntakeDraft, *, envelope: dict, data: dict, answers_sha256: str, completion: dict) -> tuple[str, bool]:
    """Apply an upload of *draft*'s interview that is not the first (a resend
    with other answers, or a second upload of the case); returns
    ``(kept, locked)``.

    The last completed version wins: this one becomes the coder's version when
    its completion time is not older than the stored one's
    (``revise_submission`` with ``resubmit``, reason ``RESUBMITTED_REASON``),
    else, or when coding is final or the case closed (*locked*), its answers
    are kept as ``replaced`` history and ``kept`` is ``"server"``. A
    ``superseded`` copy (a closed case's upload) keeps the resend as history
    the same way, locked."""
    completion = _device_completion(completion, data)
    if draft.status != "submitted":
        now = _utcnow()
        _keep_losing_version(draft, data, answers_sha256, meta={
            "source": "resubmission", "effectiveSavedAt": _completion_time(envelope, now).isoformat(),
            "receivedAt": now.isoformat(),
        })
        return "server", True
    reply = revise_submission(
        user, draft.va_sid, reason_code=RESUBMITTED_REASON, data=data, answers_sha256=answers_sha256,
        completion=completion, envelope=envelope, resubmit=True,
    )
    return reply["kept"], reply["locked"]


def resubmit_browser_draft(user: VaUsers, draft: VaWebIntakeDraft, *, completion: dict) -> dict:
    """A browser submit of a draft that is already submitted (a stale tab, a
    second completion): the later completion is a correction of the interview
    (``revise_submission`` with ``resubmit``, completed now). Returns its reply
    (``kept``, ``locked``, ``va_sid``...). Refusals as ``submit_draft``'s for
    the completion (422), 404 when it is not the caller's."""
    if not isinstance(completion, dict) or not isinstance(completion.get("data"), dict):
        raise WebIntakeError("completion.data is required.")
    data = completion["data"]
    # A browser draft has no device hash; the correction needs one to tell
    # answers apart, taken over the data in a fixed form.
    sha = hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8", "surrogatepass")).hexdigest()
    return revise_submission(
        user, draft.va_sid, reason_code=RESUBMITTED_REASON, data=data, answers_sha256=sha,
        completion={
            "valid": completion.get("valid") is True,
            "issues": completion.get("issues") if isinstance(completion.get("issues"), list) else [],
        },
        envelope={}, resubmit=True,
    )


def submit_device_interview(user: VaUsers, *, project_id: str, client_draft_id: uuid.UUID, site_id: str, org_unit_id: object | None, death_id: object | None, envelope: dict, data: dict, answers_sha256: str, completion: dict, device_id: uuid.UUID | None = None) -> tuple[VaWebIntakeDraft, str, bool]:
    """Store and submit one completed device interview; returns
    ``(draft, kept, locked)`` (``"incoming"``/``"server"``: whose answers are
    the coder's version; *locked*: coding is final or the case closed).

    The same path as a web submit: ``start_draft`` (scope, case, prefill) in
    *project_id* only, which returns the interviewer's own open draft on the
    case when there is one (the upload completes it), the answers saved
    through ``save_draft_sections``, then ``submit_draft`` with
    ``intake_source = device``. When the caller already submitted an interview
    of the case, the upload is a later version of it
    (``resubmit_device_interview``) and no new draft is made. A case already
    closed is kept as a superseded copy instead (``_store_superseded_copy``).
    An open draft with browser saves newer than this completion keeps its
    content as ``replaced`` history first: the completion is the version
    submitted. *completion* is ``{valid, issues}`` from the app's form engine;
    without ``valid: true`` the upload needs an incomplete ``interview_outcome``
    pick, exactly as on the web. Idempotency is the caller's
    (``find_device_upload`` first; ``client_draft_id`` is unique).
    *device_id* is the uploading device's id, None for a browser-cookie request.
    *envelope* supplies only the meta keys; *data* is the parsed answers and
    *answers_sha256* the hash of their exact JSON text, both already checked
    by the caller (``check_device_answers``) and stored with the upload.
    """
    meta = {k: envelope[k] for k in _ENVELOPE_META_KEYS if k in envelope}
    # Stored beside the draft's meta, never through the client keep-list.
    stored = {k: envelope[k] for k in _DEVICE_TIME_KEYS if k in envelope}
    if device_id is not None:
        stored["deviceId"] = str(device_id)
    now = _utcnow()
    device_clock = _device_time(envelope.get("deviceClockAt"))
    if device_clock is not None:
        # Positive = the device clock is behind the server. Audit only: the
        # interview times above are never corrected by it.
        stored["clockSkewSeconds"] = round((now - device_clock).total_seconds())
    completed_at = _completion_time(envelope, now)
    completion = _device_completion(completion, data)
    if death_id:
        death = cases.lock_case(get_death(user, death_id))
        if death.project_id != project_id:
            raise WebIntakeError("Death entry not found.", 404)
        own = _own_submitted_draft(user, death)
        if own is not None:
            kept, locked = resubmit_device_interview(
                user, own, envelope=envelope, data=data, answers_sha256=answers_sha256, completion=completion,
            )
            return own, kept, locked
        if death.status in _SUPERSEDED_CASE_STATES:
            copy = _store_superseded_copy(
                user, death, client_draft_id=client_draft_id, site_id=site_id,
                data=data, answers_sha256=answers_sha256, meta={**meta, **stored}, completion=completion,
            )
            return copy, "server", True
    draft = start_draft(
        user, project_id=project_id, site_id=site_id, org_unit_id=org_unit_id,
        death_id=death_id,
    )
    if draft.sections:
        # An open draft with content: the phone's own earlier sync is the same
        # draft continuing; a newer browser save is unfinished work that must
        # not be lost to the completion (the last completed version wins).
        draft_meta = draft.meta or {}
        from_phone = draft.answers_sha256 is not None
        edited = datetime.fromisoformat(draft_meta["effectiveSavedAt"]) if from_phone and draft_meta.get("effectiveSavedAt") else draft.updated_at
        own_sync = from_phone and (draft_meta.get("lastSync") or {}).get("clientDraftId") == str(client_draft_id)
        if edited > completed_at and not own_sync:
            _keep_history(draft, _merged_answers(draft), sha256=draft.answers_sha256, meta={
                "source": "device" if from_phone else "web", "effectiveSavedAt": edited.isoformat(),
                "receivedAt": now.isoformat(),
            })
    draft.client_draft_id = client_draft_id
    draft.answers_sha256 = answers_sha256
    draft.meta = {**(draft.meta or {}), **stored}
    save_draft_sections(draft, sections={DEVICE_SECTION: data}, meta=meta or None, actor=user)
    if submit_draft(draft, user, completion=completion, intake_source="device", completed_at=completed_at) is None:
        return draft, "server", True
    return draft, "incoming", False


#: Section holding the answers of a draft version that lost an edit conflict.
HISTORY_SECTION = "history"
SYNC_MESSAGE = "This interview was also edited on another device; the newer version was kept."


def lock_draft_for_browser_write(draft: VaWebIntakeDraft) -> VaWebIntakeDraft:
    """Take the case lock a phone sync takes (``start_draft``), then re-read
    the draft, so a browser save or submit and a concurrent sync serialise and
    the stale check below sees the committed version."""
    if draft.death_id:
        cases.lock_case(db.session.get(VaDeathRegister, draft.death_id))
        db.session.refresh(draft)
        if draft.status != "draft":
            raise WebIntakeError("This draft is no longer editable.", 409)
    return draft


def draft_is_stale(draft: VaWebIntakeDraft, if_updated_at: object) -> bool:
    """True when a browser save made on an older view (*if_updated_at*, the
    ``updated_at`` of the last reply it saw) would overwrite a newer version.
    400 when not an ISO 8601 time with an offset."""
    seen = _device_time(if_updated_at)
    if seen is None:
        raise WebIntakeError("if_updated_at must be an ISO 8601 time with a UTC offset.")
    return seen != draft.updated_at


def _merged_answers(draft: VaWebIntakeDraft) -> dict:
    merged: dict = {}
    for row in draft.sections:
        merged.update(row.data or {})
    return merged


def _keep_history(draft: VaWebIntakeDraft, answers: dict, *, sha256: str | None, meta: dict) -> None:
    """Keep a losing version of *draft* as a ``replaced`` draft row: same case,
    owner and form, answers in one ``history`` section, no client id (the
    unique index on it must not match) and not ``draft`` (so the one-open-draft
    index ignores it)."""
    row = VaWebIntakeDraft(
        project_id=draft.project_id, site_id=draft.site_id, org_unit_id=draft.org_unit_id,
        death_id=draft.death_id, form_id=draft.form_id, user_id=draft.user_id, unique_id=draft.unique_id,
        meta={"replacedDraftId": str(draft.draft_id), **meta}, prefill={},
        status="replaced", answers_sha256=sha256,
    )
    row.sections.append(VaWebIntakeDraftSection(section_name=HISTORY_SECTION, data=answers))
    db.session.add(row)


def _keep_losing_version(draft: VaWebIntakeDraft, answers: dict, sha256: str | None, *, meta: dict, client_draft_id: str | None = None) -> None:
    """Keep a losing resend of *draft*'s interview as a ``replaced`` row, once:
    a retry of the same answers (same hash, and the same ``clientDraftId``
    when given) stores no second row. One indexed lookup on the case."""
    clauses = [
        VaWebIntakeDraft.death_id == draft.death_id,
        VaWebIntakeDraft.user_id == draft.user_id,
        VaWebIntakeDraft.status == "replaced",
        VaWebIntakeDraft.answers_sha256 == sha256,
    ]
    if client_draft_id is not None:
        clauses.append(VaWebIntakeDraft.meta["clientDraftId"].astext == client_draft_id)
    if not db.session.scalar(sa.select(sa.exists().where(*clauses))):
        _keep_history(draft, answers, sha256=sha256, meta=meta)
        db.session.flush()


def _sync_reply(draft: VaWebIntakeDraft, kept: str, conflict: bool) -> dict:
    reply = {
        "draft": serialize_draft(draft),
        "kept": kept,
        "conflict": conflict,
        "answers_sha256": draft.answers_sha256,
        "message": SYNC_MESSAGE if conflict else None,
    }
    if kept == "server":
        reply["envelope"] = load_draft_envelope(draft)  # the phone replaces its copy
    return reply


def sync_device_draft(user: VaUsers, *, project_id: str, site_id: str, org_unit_id: object | None, death_id: object | None, client_draft_id: uuid.UUID, envelope: dict, data: dict, answers_sha256: str, saved_at: object, device_clock_at: object, base_updated_at: object | None) -> dict:
    """Sync a phone's in-progress interview into the interviewer's one open
    draft of the case (web-intake.md "Parallel interviews"); returns the reply.

    The newer save wins, whole (no section merge): the phone's ``saved_at``
    corrected by the device clock's drift (``now - device_clock_at`` is how old
    the save is on the device, so the correction needs no absolute clock),
    against the draft's last save (``updated_at``, or the corrected phone time
    of an earlier phone win nobody has edited since). A tie goes to the phone,
    which is received later. The loser is kept as a ``replaced`` row. A conflict
    is a draft the phone had not seen (``base_updated_at`` is the ``updated_at``
    of its last download or sync reply, None if never); without one the phone
    simply continues the draft and always wins. A resend is a no-op.
    Never sets the draft's ``client_draft_id``: only the final upload does.
    Refusals (all before anything is written): 422 for the times, 400
    without a case, and ``start_draft``'s own (a closed case is 409).
    """
    saved = _device_time(saved_at)
    clock = _device_time(device_clock_at)
    if saved is None or clock is None:
        raise WebIntakeError("savedAt and deviceClockAt must be ISO 8601 times with a UTC offset.", 422)
    base = None
    if base_updated_at is not None:
        base = _device_time(base_updated_at)
        if base is None:
            raise WebIntakeError("base_updated_at must be null or an ISO 8601 time with a UTC offset.", 422)
    check_device_times(envelope)
    if not death_id:
        raise WebIntakeError("death_id is required.")
    now = _utcnow()
    draft = start_draft(user, project_id=project_id, site_id=site_id, org_unit_id=org_unit_id, death_id=death_id)
    meta = draft.meta or {}
    last = meta.get("lastSync") or {}
    cid = str(client_draft_id)
    # The phone's own earlier version, untouched since: the same draft
    # continuing, never a conflict.
    from_phone = draft.answers_sha256 is not None and last.get("clientDraftId") == cid
    if from_phone and draft.answers_sha256 == answers_sha256:
        return _sync_reply(draft, "incoming", bool(last.get("conflict")))
    has_content = bool(draft.sections)
    effective = min(now, now - (clock - saved))
    # An untouched phone win is dated by its corrected save time, not by the
    # (later) moment it was received.
    phone_won = draft.answers_sha256 is not None and meta.get("effectiveSavedAt")
    current = datetime.fromisoformat(meta["effectiveSavedAt"]) if phone_won else draft.updated_at
    conflict = has_content and not from_phone and (base is None or base != draft.updated_at)
    if has_content and (conflict or from_phone):
        incoming_wins = effective >= current
    else:
        incoming_wins = True
    source = "device" if phone_won else "web"
    if not incoming_wins:
        if conflict:
            _keep_losing_version(draft, data, answers_sha256, client_draft_id=cid, meta={
                "source": "device", "clientDraftId": cid, "savedAt": saved.isoformat(),
                "effectiveSavedAt": effective.isoformat(), "receivedAt": now.isoformat(),
            })
        return _sync_reply(draft, "server", conflict)
    if conflict:
        _keep_history(draft, _merged_answers(draft), sha256=draft.answers_sha256, meta={
            "source": source, "effectiveSavedAt": current.isoformat(), "receivedAt": now.isoformat(),
        })
    for row in [r for r in draft.sections if r.section_name != DEVICE_SECTION]:
        draft.sections.remove(row)
    draft.answers_sha256 = answers_sha256
    stored = {k: envelope[k] for k in ("startedAt",) if k in envelope}
    draft.meta = {
        **meta, **stored,
        "effectiveSavedAt": effective.isoformat(),
        "clockSkewSeconds": round((now - clock).total_seconds()),
        "lastSync": {"clientDraftId": cid, "conflict": conflict},
    }
    section = envelope.get("currentSection")
    save_draft_sections(
        draft, sections={DEVICE_SECTION: data},
        meta={k: envelope[k] for k in _ENVELOPE_META_KEYS if k in envelope} or None,
        current_section=section if isinstance(section, str) and section else None, actor=user,
    )
    log.info("device draft synced | unique_id=%s | conflict=%s | by=%s", draft.unique_id, conflict, user.user_id)
    return _sync_reply(draft, "incoming", conflict)


def serialize_device_upload(draft: VaWebIntakeDraft) -> dict:
    """The contract's upload result, rebuilt from the stored draft so a
    resend gets the same ``va_sid``, case and outcome as the first upload;
    ``case.status`` is the case's current state."""
    death = db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None
    return {
        "va_sid": draft.va_sid,
        "case": {
            "death_id": str(death.death_id) if death else None,
            "unique_id": draft.unique_id,
            "status": death.status if death else None,
        },
        "outcome": (draft.meta or {}).get("interviewOutcome"),
        "superseded": draft.status == "superseded",
        "answers_sha256": draft.answers_sha256,
    }


# ---------------------------------------------------------------------------
# Device cases (Path B phase 3, digitva-kmk.4)
# ---------------------------------------------------------------------------

def _unit_prefill_parts(unit_ids: set[uuid.UUID]) -> dict[uuid.UUID, tuple[dict, list[str]]]:
    """``{unit_id: (Id10002/Id10003 presets, org path names root first)}``
    for ``_prefill_from_death``'s ``unit_parts``, in three queries for any
    number of units (units, presets, one name lookup per project)."""
    if not unit_ids:
        return {}
    units = db.session.scalars(
        sa.select(MasOrgUnit).where(MasOrgUnit.org_unit_id.in_(sorted(unit_ids)))
    ).all()
    presets = org_grant_service.resolve_unit_va_presets(sorted(unit_ids))
    codes_by_project: dict[str, set[str]] = {}
    for unit in units:
        codes_by_project.setdefault(unit.project_id, set()).update(str(unit.path).split("."))
    names = {
        project_id: {row["unit_code"]: row["unit_name"] for row in org.list_units_by_codes(project_id, codes)}
        for project_id, codes in codes_by_project.items()
    }
    parts = {}
    for unit in units:
        unit_names = names[unit.project_id]
        parts[unit.org_unit_id] = (
            {
                org_grant_service.VA_PRESET_QUESTION_NAMES[column]: entry["value"]
                for column, entry in presets.get(unit.org_unit_id, {}).items()
            },
            [unit_names[code] for code in str(unit.path).split(".") if code in unit_names],
        )
    return parts


def case_prefill(user: VaUsers, death: VaDeathRegister, my_draft_id: uuid.UUID | None) -> dict | None:
    """What the web form page prefills for *death*: the case detail's
    ``prefill``, so an interview started offline opens prefilled. Carries the
    questionnaire's own answers (informant's and parents' names, address,
    ABHA), never a phone number.

    Only for a caller who may start or resume the interview, as
    ``start_draft`` decides: they hold the case's own draft (*my_draft_id*),
    or the case is open (another interviewer's draft does not matter).
    Otherwise None (a closed case): the identifiers are not theirs to read.
    """
    if my_draft_id is None and death.status in _SUPERSEDED_CASE_STATES:
        return None
    return _prefill_from_death(death, user, death.org_unit_id)


def case_row(user: VaUsers, death: VaDeathRegister) -> tuple:
    """A ``_worklist_select`` row for a case the caller already holds in scope
    (an offline registration's reply): the worklist query for that one case,
    without its scope."""
    return tuple(
        db.session.execute(_worklist_select(user).where(VaDeathRegister.death_id == death.death_id)).one()
    )


def get_device_case(user: VaUsers, project_id: str, death_id: object) -> VaDeathRegister:
    """A case in the caller's scope and in *project_id*, else 404."""
    death = get_death(user, death_id)
    if death.project_id != project_id:
        raise WebIntakeError("Death entry not found.", 404)
    return death


def find_device_registration(user: VaUsers, project_id: str, client_death_id: uuid.UUID) -> VaDeathRegister | None:
    """The case an earlier offline registration with *client_death_id*
    created, if any. Another user's id is a 409; a case since moved out of
    the caller's scope or *project_id* is a 404."""
    death = db.session.scalar(
        sa.select(VaDeathRegister).where(VaDeathRegister.client_death_id == client_death_id)
    )
    if death is None:
        return None
    if death.registered_by != user.user_id:
        raise WebIntakeError("That client_death_id is already in use.", 409)
    return get_device_case(user, project_id, death.death_id)


def find_device_attempt(user: VaUsers, death_id: object, client_attempt_id: uuid.UUID) -> VaDeathRegister | None:
    """The case of an earlier attempt logged with *client_attempt_id*, if
    any. The id reused by another user or on another case is a 409."""
    attempt = db.session.scalar(
        sa.select(MapCaseContactAttempt).where(MapCaseContactAttempt.client_attempt_id == client_attempt_id)
    )
    if attempt is None:
        return None
    try:
        same_case = attempt.death_id == uuid.UUID(str(death_id))
    except ValueError:
        same_case = False
    if attempt.by_user_id != user.user_id or not same_case:
        raise WebIntakeError("That client_attempt_id is already in use.", 409)
    return get_death(user, attempt.death_id)


# ---------------------------------------------------------------------------
# Worklist
# ---------------------------------------------------------------------------

WORKLIST_PAGE_DEFAULT = 50
WORKLIST_PAGE_MAX = 200
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _encode_cursor(updated_at: datetime, death_id: uuid.UUID) -> str:
    micros = (updated_at - _EPOCH) // timedelta(microseconds=1)
    return f"{micros}_{death_id}"


def _decode_cursor(raw: str) -> tuple[datetime, uuid.UUID]:
    try:
        micros, death_id = raw.split("_", 1)
        return _EPOCH + timedelta(microseconds=int(micros)), uuid.UUID(death_id)
    except (ValueError, OverflowError):
        raise WebIntakeError("Invalid cursor.") from None


def _micros(at: datetime) -> int:
    return (at - _EPOCH) // timedelta(microseconds=1)


def _encode_worklist_cursor(case: VaDeathRegister) -> str:
    visit = str(_micros(case.next_visit_at)) if case.next_visit_at else "-"
    return f"{visit}_{_micros(case.updated_at)}_{case.death_id}"


def _after_worklist_cursor(raw: str):
    """Keyset condition for rows after *raw* in the worklist order: next visit
    ascending with undated cases last, then last activity newest first."""
    try:
        visit, updated, death_id = raw.split("_", 2)
        visit_at = None if visit == "-" else _EPOCH + timedelta(microseconds=int(visit))
        at, death_uuid = _EPOCH + timedelta(microseconds=int(updated)), uuid.UUID(death_id)
    except (ValueError, OverflowError):
        raise WebIntakeError("Invalid cursor.") from None
    older = sa.tuple_(VaDeathRegister.updated_at, VaDeathRegister.death_id) < (at, death_uuid)
    if visit_at is None:
        return sa.and_(VaDeathRegister.next_visit_at.is_(None), older)
    return sa.or_(
        VaDeathRegister.next_visit_at.is_(None),
        VaDeathRegister.next_visit_at > visit_at,
        sa.and_(VaDeathRegister.next_visit_at == visit_at, older),
    )


def _worklist_scope(user: VaUsers, context: list[dict] | None = None):
    """SQL condition for the cases this interviewer's grants reach, or None.

    Per project-site of ``interviewer_context`` (*context* when the caller
    already has it): a project grant, or a site grant on that very site,
    sees the whole project-site; otherwise the subtrees of the user's unit
    grants in that project (a case with no unit is outside every subtree).
    A wider grant wins over a unit grant on the same project-site
    (docs/policy/web-intake.md, "Who sees which cases"). The subtrees stay
    sub-selects, so the grants cost one memoised lookup however many
    project-sites there are.
    """
    wide: set[tuple[str, str | None]] = set()
    unit_grants: dict[str, set[uuid.UUID]] = {}
    for grant in resolve_grants(user).of({VaAccessRoles.interviewer}, virtual=False):
        if grant.is_wide:
            wide.add((grant.project_id, grant.site_id))  # site_id None: project grant
        else:
            unit_grants.setdefault(grant.project_id, set()).add(grant.org_unit_id)
    conditions = []
    for entry in interviewer_context(user) if context is None else context:
        project_id, site_id = entry["project_id"], entry["site_id"]
        pair = sa.and_(VaDeathRegister.project_id == project_id, VaDeathRegister.site_id == site_id)
        if (project_id, None) not in wide and (project_id, site_id) not in wide:
            units = unit_grants.get(project_id)
            if not units:
                continue
            pair = sa.and_(pair, VaDeathRegister.org_unit_id.in_(subtree_select(units)))
        conditions.append(pair)
    if not conditions:
        return None
    return sa.and_(
        sa.or_(*conditions),
        # "Details pending" only for its starter; supervisors see it in
        # list_supervised_cases.
        sa.or_(
            VaDeathRegister.status != "draft_identity",
            VaDeathRegister.started_by_user_id == user.user_id,
        ),
    )


def _mine_condition(user: VaUsers):
    """Registered, started or otherwise worked on (any audited action or
    contact attempt) by *user*."""
    return sa.or_(
        VaDeathRegister.registered_by == user.user_id,
        VaDeathRegister.started_by_user_id == user.user_id,
        sa.exists().where(
            MapCaseTransition.death_id == VaDeathRegister.death_id,
            MapCaseTransition.actor_user_id == user.user_id,
        ),
        sa.exists().where(
            MapCaseContactAttempt.death_id == VaDeathRegister.death_id,
            MapCaseContactAttempt.by_user_id == user.user_id,
        ),
    )


def _worklist_select(user: VaUsers):
    """``SELECT (case, unit_name, my_draft_id, other_draft_started_at,
    my_submission, other_complete_interview)``: a worklist row, with the
    caller's own resumable web draft (at most one,
    ``uq_va_web_intake_drafts_user_death_open``, so the join never repeats a
    case), when the earliest other interviewer's open draft started (None
    without one), whether the caller's draft is the case's submission and
    whether a second complete interview exists (``_has_candidate``). One query
    for all of them. The caller adds the scope."""
    my_draft = aliased(VaWebIntakeDraft)
    other = aliased(VaWebIntakeDraft)
    won = aliased(VaWebIntakeDraft)
    other_started = (
        sa.select(sa.func.min(other.created_at))
        .where(
            other.death_id == VaDeathRegister.death_id, other.status == "draft", other.user_id != user.user_id,
            # A closed case has no live other interview to warn about.
            VaDeathRegister.status.not_in(tuple(_SUPERSEDED_CASE_STATES)),
        )
        .scalar_subquery()
    )
    return (
        sa.select(
            VaDeathRegister, MasOrgUnit.unit_name, my_draft.draft_id,
            other_started.label("other_draft_started_at"), (won.draft_id.is_not(None)).label("my_submission"),
            _has_candidate().label("other_complete_interview"),
        )
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == VaDeathRegister.org_unit_id)
        .outerjoin(
            my_draft,
            sa.and_(
                my_draft.death_id == VaDeathRegister.death_id,
                my_draft.status == "draft",
                my_draft.user_id == user.user_id,
            ),
        )
        # A join, not EXISTS: PostgreSQL hashes an EXISTS into one scan of all
        # the caller's submitted drafts, a join probes ``death_id`` per case.
        # Matches at most one row: a submission belongs to one draft.
        .outerjoin(
            won,
            sa.and_(
                won.death_id == VaDeathRegister.death_id,
                won.user_id == user.user_id,
                won.status == "submitted",
                won.va_sid == VaDeathRegister.va_sid,
            ),
        )
    )


def list_worklist(user: VaUsers, *, mine: bool = False, states: list[str] | None = None,
                  cursor: str | None = None, limit: int = WORKLIST_PAGE_DEFAULT,
                  project_id: str | None = None, context: list[dict] | None = None) -> dict:
    """Team cases in the interviewer's scope, soonest next visit first.

    Returns ``{"cases": [(case, unit_name, my_draft_id, other_draft_started_at,
    my_submission, other_complete_interview), ...], "counts":
    {state: n}, "next_cursor": str | None, "possible_duplicates": {death_id:
    [{"death_id", "unique_id"}, ...]}}``; the last is the page's possible
    duplicates (up to three a case) from one query. ``counts`` cover the scope and
    the *mine* filter but not *states*, so tabs can show their totals. Sorted
    by next visit (overdue first, undated last), then last activity newest
    first. Keyset-paged on (next_visit_at, updated_at, death_id).
    *project_id* narrows the scope to one project, counts included (the
    device list); possible duplicates still come from the whole scope.
    ``context``: the caller's ``interviewer_context``, if already computed.
    """
    for state in states or []:
        if state not in CASE_STATES:
            raise WebIntakeError(f"Unknown state {state!r}.")
    limit = max(1, min(int(limit), WORKLIST_PAGE_MAX))
    scope = _worklist_scope(user, context)
    if scope is None:
        return {"cases": [], "counts": {}, "next_cursor": None, "possible_duplicates": {}}
    base = [scope]
    if project_id is not None:
        base.append(VaDeathRegister.project_id == project_id)
    if mine:
        base.append(_mine_condition(user))

    counts = dict(
        db.session.execute(
            sa.select(VaDeathRegister.status, sa.func.count())
            .where(*base)
            .group_by(VaDeathRegister.status)
        ).all()
    )

    filters = list(base)
    if states:
        filters.append(VaDeathRegister.status.in_(states))
    if cursor:
        filters.append(_after_worklist_cursor(cursor))
    rows = db.session.execute(
        _worklist_select(user)
        .where(*filters)
        .order_by(
            VaDeathRegister.next_visit_at.asc().nulls_last(),
            VaDeathRegister.updated_at.desc(),
            VaDeathRegister.death_id.desc(),
        )
        .limit(limit + 1)
    ).all()
    page = [tuple(row) for row in rows[:limit]]
    next_cursor = _encode_worklist_cursor(page[-1][0]) if len(rows) > limit else None
    duplicates = _possible_duplicate_rows([row[0].death_id for row in page], scope, per_case=3)
    possible = {}
    for row in duplicates:
        possible.setdefault(row.subject_id, []).append(
            {"death_id": str(row.death_id), "unique_id": row.unique_id}
        )
    return {"cases": page, "counts": counts, "next_cursor": next_cursor, "possible_duplicates": possible}


_TRUE, _FALSE = ("1", "true", "yes"), ("", "0", "false", "no")


def worklist_page(user: VaUsers, args, *, project_id: str | None = None,
                  context: list[dict] | None = None) -> dict:
    """The worklist response ``GET /api/v1/intake/cases`` serves:
    ``{"cases": [row + possible_duplicates], "counts", "next_cursor"}``.

    *args* is the request's query string: ``mine`` (true/false), ``state``
    (comma-separated case states), ``limit`` (clamped to 1..200), ``cursor``
    (from ``next_cursor``); a malformed one is a 400 WebIntakeError.
    *project_id* and *context* as ``list_worklist``.
    """
    mine = (args.get("mine") or "").lower()
    if mine not in _TRUE + _FALSE:
        raise WebIntakeError("mine must be true or false.")
    try:
        limit = int(args.get("limit") or WORKLIST_PAGE_DEFAULT)
    except ValueError:
        raise WebIntakeError("limit must be a whole number.") from None
    result = list_worklist(
        user,
        mine=mine in _TRUE,
        states=[s for s in (args.get("state") or "").split(",") if s],
        cursor=args.get("cursor") or None,
        limit=limit,
        project_id=project_id,
        context=context,
    )
    possible = result["possible_duplicates"]
    rows = []
    for row in result["cases"]:
        serialized = serialize_worklist_row(user, *row)
        serialized["possible_duplicates"] = possible.get(row[0].death_id, [])
        rows.append(serialized)
    return {"cases": rows, "counts": result["counts"], "next_cursor": result["next_cursor"]}


def get_case_detail(user: VaUsers, death_id: object, *, context: list[dict] | None = None) -> tuple:
    """One case as a ``_worklist_select`` row, visible exactly when the
    worklist would list it (``_worklist_scope``, every project of the
    caller's), in any state. Unknown, out of scope or a malformed id: 404.
    ``context``: the caller's ``interviewer_context``, if already computed."""
    try:
        death_uuid = uuid.UUID(str(death_id))
    except ValueError:
        raise WebIntakeError("Case not found.", 404) from None
    scope = _worklist_scope(user, context)
    if scope is None:
        raise WebIntakeError("Case not found.", 404)
    row = db.session.execute(
        _worklist_select(user).where(scope, VaDeathRegister.death_id == death_uuid).limit(1)
    ).first()
    if row is None:
        raise WebIntakeError("Case not found.", 404)
    return tuple(row)


def prefill_policy(user: VaUsers, project_id: str) -> dict:
    """The offline prefill the server applies in *project_id*, for an app that
    builds a draft before it can reach the server. Derived from
    ``_prefill_from_death``, which stays the authority: an upload's locked
    answers are recomputed server-side whatever the app sent.

    ``direct``: the prefill of a direct start with no unit (interviewer and
    its locked questions). ``units``: ``{org_unit_id: {answers,
    lockedQuestionNames}}``, the area part a direct start in that unit adds,
    for every unit the caller may pick (``reachable_unit_ids``; None means
    every active unit). ``answer_fields``/``locked_fields``: which register
    columns become which answers. Name, sex, dates and age go to
    ``prefill.deceased`` and the package maps them; the registered age lock,
    the partial birth date and the place-of-death matching are conditional,
    so they arrive per case in the case detail's ``prefill``, not here.

    ponytail: ``units`` grows with the reachable tree, as ``/units`` does.
    """
    direct = _prefill_from_death(None, user)
    reachable = reachable_unit_ids(user, project_id)
    if reachable is None:
        reachable = set(db.session.scalars(
            sa.select(MasOrgUnit.org_unit_id).where(
                MasOrgUnit.project_id == project_id, MasOrgUnit.is_active.is_(True)
            )
        ).all())
    parts = _unit_prefill_parts(reachable)
    interviewer_locked = set(direct["lockedQuestionNames"])
    units = {}
    for unit_id, unit_parts in parts.items():
        prefill = _prefill_from_death(None, user, unit_id, unit_parts)
        units[str(unit_id)] = {
            "answers": prefill["answers"],
            "lockedQuestionNames": sorted(set(prefill["lockedQuestionNames"]) - interviewer_locked),
        }
    return {
        "direct": direct,
        "units": units,
        "answer_fields": dict(PREFILL_ANSWER_FIELDS),
        "locked_fields": list(PREFILL_LOCKED_FIELDS),
    }


# ---------------------------------------------------------------------------
# Possible-duplicate check (phase 6, digitva-vzk.11)
# ---------------------------------------------------------------------------

#: Dates of death this many days apart or less may be the same death.
DUPLICATE_DAYS = 3
#: pg_trgm ``similarity()`` of the normalised names at or above this matches.
DUPLICATE_NAME_SIMILARITY = 0.5
#: Most candidates the case API returns.
DUPLICATE_CANDIDATES_MAX = 50
_UNKNOWN_SEX = ("undetermined", "unknown")
#: Honorifics dropped before comparing names ("Late Smt. Kamla Devi").
_NAME_TITLES_RE = r"\m(late|lt|mr|mrs|ms|miss|smt|shrimati|shri|sri|dr|master|baby|kumari|km)\M"


def _normalised_name(column):
    """SQL: lowercase, punctuation to spaces, titles dropped, spaces collapsed."""
    text = sa.func.regexp_replace(sa.func.lower(column), r"[[:punct:]]+", " ", "g")
    text = sa.func.regexp_replace(text, _NAME_TITLES_RE, " ", "g")
    return sa.func.btrim(sa.func.regexp_replace(text, r"\s+", " ", "g"))


def _possible_duplicate_rows(subject_ids: list[uuid.UUID], scope, *, per_case: int) -> list:
    """Other cases that may be the same death as each subject, in ONE query.

    A candidate is in the subject's project, not the subject, not cancelled
    and not itself a confirmed duplicate (neither can be named as the kept
    case), inside *scope* (the caller's worklist reach, so no name leaves it),
    with a date of death within ``DUPLICATE_DAYS``, the same sex unless either
    is unknown, a normalised-name ``similarity()`` of at least
    ``DUPLICATE_NAME_SIMILARITY``, and a neighbouring unit: the same unit, its
    parent, a child, or a sibling (same parent), or either case has no unit.
    Two top-level units are not neighbours. Subjects without a name or date of
    death, already closed, or with a flag waiting for a supervisor get none. At most *per_case* candidates per
    subject, most similar first. Rows: ``subject_id``, ``death_id``,
    ``unique_id``, ``status``, ``unit_name``, ``score``.
    """
    if not subject_ids or scope is None:
        return []
    subject = aliased(VaDeathRegister)
    subject_unit = aliased(MasOrgUnit)
    unit = aliased(MasOrgUnit)
    closed = ("cancelled", "duplicate")
    days = sa.literal_column(str(DUPLICATE_DAYS), sa.Integer)  # a constant, never input
    score = sa.func.similarity(
        _normalised_name(subject.deceased_name), _normalised_name(VaDeathRegister.deceased_name)
    )
    ranked = (
        sa.select(
            subject.death_id.label("subject_id"),
            VaDeathRegister.death_id,
            VaDeathRegister.unique_id,
            VaDeathRegister.status,
            unit.unit_name,
            score.label("score"),
            sa.func.row_number()
            .over(partition_by=subject.death_id, order_by=(score.desc(), VaDeathRegister.death_id))
            .label("rank"),
        )
        .select_from(subject)
        .join(
            VaDeathRegister,
            sa.and_(
                VaDeathRegister.project_id == subject.project_id,
                VaDeathRegister.death_id != subject.death_id,
                VaDeathRegister.date_of_death.between(
                    subject.date_of_death - days, subject.date_of_death + days
                ),
                VaDeathRegister.status.not_in(closed),
                VaDeathRegister.deceased_name.is_not(None),
            ),
        )
        .outerjoin(subject_unit, subject_unit.org_unit_id == subject.org_unit_id)
        .outerjoin(unit, unit.org_unit_id == VaDeathRegister.org_unit_id)
        .where(
            subject.death_id.in_(subject_ids),
            subject.status.not_in(closed),
            subject.pending_flag.is_(None),
            subject.deceased_name.is_not(None),
            subject.date_of_death.is_not(None),
            sa.or_(
                subject.deceased_sex.is_(None),
                subject.deceased_sex.in_(_UNKNOWN_SEX),
                VaDeathRegister.deceased_sex.is_(None),
                VaDeathRegister.deceased_sex.in_(_UNKNOWN_SEX),
                VaDeathRegister.deceased_sex == subject.deceased_sex,
            ),
            sa.or_(
                subject.org_unit_id.is_(None),
                VaDeathRegister.org_unit_id.is_(None),
                VaDeathRegister.org_unit_id == subject.org_unit_id,
                VaDeathRegister.org_unit_id == subject_unit.parent_org_unit_id,
                unit.parent_org_unit_id == subject.org_unit_id,
                unit.parent_org_unit_id == subject_unit.parent_org_unit_id,
            ),
            score >= DUPLICATE_NAME_SIMILARITY,
            scope,
        )
        .subquery()
    )
    return db.session.execute(
        sa.select(ranked).where(ranked.c.rank <= per_case).order_by(ranked.c.subject_id, ranked.c.rank)
    ).all()


def possible_duplicates(user: VaUsers, case: VaDeathRegister) -> list[dict]:
    """Cases in *user*'s worklist reach that may be the same death as *case*.

    A warning for the interviewer, never a block and never a merge: flagging
    stays a person's decision (decisions 6 and 14). The caller has already
    checked *user* may see *case* (``get_death``). Rules in
    ``_possible_duplicate_rows``. The hint names the other case by its id,
    unit and state only, never its identity (docs/policy/web-intake.md,
    "Duplicate and cancel flags").
    """
    rows = _possible_duplicate_rows([case.death_id], _worklist_scope(user), per_case=DUPLICATE_CANDIDATES_MAX)
    return [
        {
            "death_id": str(row.death_id),
            "unique_id": row.unique_id,
            "unit_name": row.unit_name,
            "state": row.status,
            "score": round(float(row.score), 2),
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Supervisor view (digitva-vzk.5)
# ---------------------------------------------------------------------------


def get_supervised_case(user: VaUsers, death_id: object) -> VaDeathRegister:
    """A case *user* supervises, else 404: an id is not proof the case exists."""
    try:
        death = db.session.get(VaDeathRegister, uuid.UUID(str(death_id)))
    except ValueError:
        death = None
    # An admin may open any case here, as the choose action allows (they find
    # the case id in the admin panels; the supervision list stays grant-scoped).
    if death is None or not (user.is_admin() or cases.is_interview_supervisor_for(user, death)):
        raise WebIntakeError("Case not found.", 404)
    return death


def supervised_case_row(death: VaDeathRegister) -> tuple:
    """``(case, unit_name, registered_by_name, started_by_name,
    other_complete_interview)`` for a case the caller supervises
    (``list_supervised_cases``' row, for an action's reply), without
    re-running the list query."""
    unit = db.session.get(MasOrgUnit, death.org_unit_id) if death.org_unit_id else None
    registrant = db.session.get(VaUsers, death.registered_by) if death.registered_by else None
    starter = db.session.get(VaUsers, death.started_by_user_id) if death.started_by_user_id else None
    return (
        death,
        unit.unit_name if unit else None,
        registrant.name if registrant else None,
        starter.name if starter else None,
        bool(db.session.scalar(sa.select(_has_candidate()).where(VaDeathRegister.death_id == death.death_id))),
    )


def list_supervised_cases(user: VaUsers, *, states: list[str] | None = None, flagged: bool = False,
                          candidates: bool = False, cursor: str | None = None,
                          limit: int = WORKLIST_PAGE_DEFAULT) -> dict:
    """Every case in the supervisor's scope, "details pending" included.

    Returns ``{"cases": [(case, unit_name, registered_by_name,
    started_by_name, other_complete_interview), ...], "counts": {state: n},
    "next_cursor": ...}``; *flagged* keeps cases with a flag waiting for a
    supervisor, *candidates* those with a second complete interview to choose
    (``_has_candidate``). ``counts`` ignore *states*, *flagged* and
    *candidates*. Keyset-paged like ``list_worklist``.
    """
    for state in states or []:
        if state not in CASE_STATES:
            raise WebIntakeError(f"Unknown state {state!r}.")
    limit = max(1, min(int(limit), WORKLIST_PAGE_MAX))
    scope = cases.supervised_case_condition(user)
    counts = dict(
        db.session.execute(
            sa.select(VaDeathRegister.status, sa.func.count()).where(scope).group_by(VaDeathRegister.status)
        ).all()
    )
    filters = [scope]
    if states:
        filters.append(VaDeathRegister.status.in_(states))
    if flagged:
        filters.append(VaDeathRegister.pending_flag.is_not(None))
    if candidates:
        filters.append(_has_candidate())
    if cursor:
        at, death_id = _decode_cursor(cursor)
        filters.append(sa.tuple_(VaDeathRegister.updated_at, VaDeathRegister.death_id) < (at, death_id))
    registrant = aliased(VaUsers)
    starter = aliased(VaUsers)
    rows = db.session.execute(
        sa.select(VaDeathRegister, MasOrgUnit.unit_name, registrant.name, starter.name,
                  _has_candidate().label("other_complete_interview"))
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == VaDeathRegister.org_unit_id)
        .outerjoin(registrant, registrant.user_id == VaDeathRegister.registered_by)
        .outerjoin(starter, starter.user_id == VaDeathRegister.started_by_user_id)
        .where(*filters)
        .order_by(VaDeathRegister.updated_at.desc(), VaDeathRegister.death_id.desc())
        .limit(limit + 1)
    ).all()
    page = [tuple(row) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = page[-1][0]
        next_cursor = _encode_cursor(last.updated_at, last.death_id)
    return {"cases": page, "counts": counts, "next_cursor": next_cursor}


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
        "date_of_birth_partial": death.date_of_birth_partial,
        "age_years": death.age_years,
        "date_of_death": death.date_of_death.isoformat() if death.date_of_death else None,
        "place_of_death": death.place_of_death,
        "address": death.address,
        "address_house_street": death.address_house_street,
        "address_village_ward": death.address_village_ward,
        "address_landmark": death.address_landmark,
        "informant_name": death.informant_name,
        "father_name": death.father_name,
        "mother_name": death.mother_name,
        "informant_phone": death.informant_phone,
        "informant_phone_2": death.informant_phone_2,
        "remarks": death.remarks,
        "next_visit_at": death.next_visit_at.isoformat() if death.next_visit_at else None,
        "last_contact_at": death.last_contact_at.isoformat() if death.last_contact_at else None,
        "status": death.status,
        "source": death.source,
        "pending_flag": death.pending_flag,
        "va_sid": death.va_sid,
        "created_at": death.created_at.isoformat(),
    }


def serialize_worklist_row(user: VaUsers, death: VaDeathRegister, unit_name: str | None,
                           my_draft_id: uuid.UUID | None, other_draft_started_at: datetime | None = None,
                           my_submission: bool = False, other_complete_interview: bool = False) -> dict:
    """One worklist row (browser and device lists). No informant name or
    address, and phones masked (``******1234``): the list shows who died, not
    how to reach the family. ``va_sid`` only for the interviewer whose draft
    became the submission (*my_submission*): the interview form is its
    interviewer's own. ``other_draft_active`` / ``other_draft_started_at``
    warn that another interviewer holds an open draft, never who;
    ``other_complete_interview`` that a second complete interview of the case
    exists (a supervisor may choose it), never whose."""
    return {
        "death_id": str(death.death_id),
        "unique_id": death.unique_id,
        "project_id": death.project_id,
        "site_id": death.site_id,
        "org_unit_id": str(death.org_unit_id) if death.org_unit_id else None,
        "unit_name": unit_name,
        "source": death.source,
        "state": death.status,
        "details_pending": death.status == "draft_identity",
        "deceased_name": death.deceased_name,
        "deceased_sex": death.deceased_sex,
        "age_years": death.age_years,
        "date_of_death": death.date_of_death.isoformat() if death.date_of_death else None,
        "pending_flag": death.pending_flag,
        "next_visit_at": death.next_visit_at.isoformat() if death.next_visit_at else None,
        "last_contact_at": death.last_contact_at.isoformat() if death.last_contact_at else None,
        "informant_phone_masked": mask_phone(death.informant_phone),
        "informant_phone_2_masked": mask_phone(death.informant_phone_2),
        "registered_by_me": death.registered_by == user.user_id,
        "started_by_me": death.started_by_user_id == user.user_id,
        "my_draft_id": str(my_draft_id) if my_draft_id else None,
        "other_draft_active": other_draft_started_at is not None,
        "other_draft_started_at": other_draft_started_at.isoformat() if other_draft_started_at else None,
        "va_sid": death.va_sid if my_submission else None,
        "other_complete_interview": bool(other_complete_interview),
        "created_at": death.created_at.isoformat(),
        "updated_at": death.updated_at.isoformat(),
    }


def serialize_case_detail(user: VaUsers, death: VaDeathRegister, unit_name: str | None,
                          my_draft_id: uuid.UUID | None, other_draft_started_at: datetime | None = None,
                          my_submission: bool = False, other_complete_interview: bool = False) -> dict:
    """One case for the case page and the device detail: the worklist row's
    case fields plus the full contact details (informant name, both phones,
    household address, remarks). Never ABHA, parents' names, other users' ids
    or client ids: the ABHA and parents' names come only in the API's
    ``prefill`` (``case_prefill``), only to a caller who may start or resume
    the interview (docs/policy/web-intake.md, "Single-case detail"). The
    submission id (``va_sid``) only to the interviewer whose draft became the
    submission (*my_submission*); ``other_draft_active``,
    ``other_draft_started_at`` and ``other_complete_interview`` as in
    ``serialize_worklist_row``."""
    return {
        "death_id": str(death.death_id),
        "unique_id": death.unique_id,
        "project_id": death.project_id,
        "site_id": death.site_id,
        "org_unit_id": str(death.org_unit_id) if death.org_unit_id else None,
        "unit_name": unit_name,
        "source": death.source,
        "state": death.status,
        "details_pending": death.status == "draft_identity",
        "pending_flag": death.pending_flag,
        "deceased": {
            "name": death.deceased_name,
            "sex": death.deceased_sex,
            "age_years": death.age_years,
            "date_of_birth": death.date_of_birth.isoformat() if death.date_of_birth else None,
            "date_of_birth_partial": death.date_of_birth_partial,
            "date_of_death": death.date_of_death.isoformat() if death.date_of_death else None,
            "place_of_death": death.place_of_death,
        },
        "household_address": {
            "address": death.address,
            "house_street": death.address_house_street,
            "village_ward": death.address_village_ward,
            "landmark": death.address_landmark,
        },
        "informant": {
            "name": death.informant_name,
            "phone": death.informant_phone,
            "phone_2": death.informant_phone_2,
        },
        "remarks": death.remarks,
        "next_visit_at": death.next_visit_at.isoformat() if death.next_visit_at else None,
        "last_contact_at": death.last_contact_at.isoformat() if death.last_contact_at else None,
        "registered_by_me": death.registered_by == user.user_id,
        "started_by_me": death.started_by_user_id == user.user_id,
        "my_draft_id": str(my_draft_id) if my_draft_id else None,
        "other_draft_active": other_draft_started_at is not None,
        "other_draft_started_at": other_draft_started_at.isoformat() if other_draft_started_at else None,
        "va_sid": death.va_sid if my_submission else None,
        "other_complete_interview": bool(other_complete_interview),
        "created_at": death.created_at.isoformat(),
        "updated_at": death.updated_at.isoformat(),
    }


def serialize_supervised_row(user: VaUsers, death: VaDeathRegister, unit_name: str | None,
                             registered_by_name: str | None, started_by_name: str | None,
                             other_complete_interview: bool = False) -> dict:
    """A worklist row plus who registered and started the case (staff identity,
    decision 13), without the informant's phones: the supervisor list does not
    contact families. ``other_complete_interview``: a candidate to choose
    exists (``choose_interview``)."""
    row = serialize_worklist_row(user, death, unit_name, None, other_complete_interview=other_complete_interview)
    for key in ("my_draft_id", "informant_phone_masked", "informant_phone_2_masked",
                "other_draft_active", "other_draft_started_at"):
        row.pop(key)
    # Supervisors oversee every interview in scope, so they keep every va_sid
    # (the submitter-only rule is the interviewer lists').
    row["va_sid"] = death.va_sid
    row["registered_by_name"] = registered_by_name
    row["started_by_name"] = started_by_name
    row["duplicate_of_death_id"] = str(death.duplicate_of_death_id) if death.duplicate_of_death_id else None
    return row


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


def resolve_draft_display_names(draft: VaWebIntakeDraft) -> dict:
    """Project, site and (if any) org-unit/level names for the intake form
    header (digitva-wdj) -- names instead of the bare codes it used to show.

    One query for a single draft: not folded into ``serialize_draft`` because
    that is also called once per row of ``list_drafts``, where adding a join
    here would turn into an N+1.
    """
    row = db.session.execute(
        sa.select(
            VaProjectMaster.project_name,
            VaSiteMaster.site_name,
            MasOrgUnit.unit_name,
            MasOrgLevel.level_name,
        )
        .select_from(VaProjectMaster)
        # Project and site are unrelated tables (each narrowed to one row by
        # the WHERE below), so the join has no natural ON of its own.
        .join(VaSiteMaster, sa.true())
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == draft.org_unit_id)
        .outerjoin(MasOrgLevel, MasOrgLevel.org_level_id == MasOrgUnit.org_level_id)
        .where(VaProjectMaster.project_id == draft.project_id, VaSiteMaster.site_id == draft.site_id)
    ).one_or_none()
    if row is None:
        return {"project_name": draft.project_id, "site_name": draft.site_id, "org_unit_name": None, "org_level_name": None}
    project_name, site_name, unit_name, level_name = row
    return {
        "project_name": project_name,
        "site_name": site_name,
        "org_unit_name": unit_name,
        "org_level_name": level_name,
    }
