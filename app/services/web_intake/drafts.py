"""Drafts: starting, saving, locking and loading them, with the envelope and device answer checks.

Part of the web intake service split (bead digitva-r8nh.12); the public
module is ``app.services.web_intake_service``, which re-exports every name.
Code that tests patch on that module is read back through ``facade()``.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from app import db
from app.models import (
    MasOrgUnit,
    VaDeathRegister,
    VaUsers,
    VaWebIntakeDraft,
    VaWebIntakeDraftSection,
)
from app.models.va_users import USER_SEX_VALUES
from app.models.va_web_intake import (
    DEATH_SEX_VALUES,
)
from app.services import case_transition_service as cases
from app.services import (
    collection_gate,
    notification_service,
    org_grant_service,
    public_demo_service,
    register_pii_accessor,
    training_scope,
)
from app.services import web_intake_attachment_service as attachments
from app.services.case_transition_service import WebIntakeError
from app.services.runtime_form_sync_service import ensure_web_runtime_form
from app.services.web_form_instruments import DEFAULT_LOCALE
from app.services.web_intake import facade
from app.services.web_intake.common import (
    _LOCALE_CODE_RE,
    _SECTION_NAME_RE,
    ATTACHMENT_REFERENCE_PREFIX,
    INSTRUMENT_ID,
    _device_time,
    _expression_now,
    log,
)
from app.services.web_intake.register import (
    _clean_partial_birth,
    get_death,
)
from app.services.web_intake.register_access import (
    IDENTITY_FROM_INTERVIEW,
    _audit_details_change,
)
from app.services.web_intake.scope import (
    _allocate_unique_id,
    _mode_allows,
    _require_scope,
    _unit_label,
    get_web_intake_mode,
)
from app.services.who_va_answers import age_field, birth_answer
from app.services.who_va_answers import choice as choice_answer
from app.services.who_va_answers import whole as whole_answer
from app.services.workflow_timeline_service import (
    CODING_TIMELINE_EVENTS,
    INTERVIEW_TIMELINE_EVENTS,
    WorkflowTimelineError,
    merge_timeline,
    parse_timeline,
    server_event,
)
from app.utils.national_id import redact_payload_national_ids

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


_ADDRESS_ATTRS = ("address_house_street", "address_village_ward", "address_landmark", "address")


def _case_address(values: dict) -> str:
    """The case's address parts, structured first, joined with commas.
    *values* holds the opened register attributes (``current_values``)."""
    parts = tuple(values[attr] for attr in _ADDRESS_ATTRS)
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


#: Id10010a's own constraint (``(.>=18 and .<90) or .=99``): an age outside it
#: would trap the interviewer, so it is not prefilled.
_INTERVIEWER_AGE_RANGE = range(18, 90)


def _interviewer_age(user: VaUsers) -> int | None:
    """The interviewer's age for Id10010a: the interview year (now, in the
    user's timezone) minus the profile's ``year_of_birth``; None without a
    year of birth or when the age is outside Id10010a's 18-89."""
    if user.year_of_birth is None:
        return None
    age = _expression_now(user, facade()._utcnow()).year - user.year_of_birth
    return age if age in _INTERVIEWER_AGE_RANGE else None


def _prefill_from_death(death: VaDeathRegister | None, user: VaUsers, org_unit_id: uuid.UUID | None = None,
                        unit_parts: tuple[dict, str] | None = None) -> dict:
    """The draft's prefill, per the map in docs/policy/web-intake.md.

    ``deceased`` and ``interviewer`` go through the package's
    ``createWhoVaInitialDataFromPrefill``; ``answers`` are WHO answers merged
    on top; ``lockedQuestionNames`` are the read-only ones (interviewer
    name, sex and id, area presets, ABHA). Everything else is an ordinary editable
    answer, the interviewer's age (``interviewer.age``) included. Name split: the last word is the surname (Id10018), the words
    before it the given name (Id10017); a one-word name is a given name only.

    Birth date: an exact ``date_of_birth`` goes as ``deceased.dateOfBirth``
    (prefill.ts sets Id10020 = yes, Id10021). A ``date_of_birth_partial``
    never touches Id10021 (WHO's full date only); it sets Id10020 = no and
    the DigitVA precision block after it, whose relevance needs that no:
    ``YYYY-MM`` -> dob_precision = month_year, dob_month_year = YYYY-MM-01;
    ``YYYY`` -> dob_precision = year, dob_year = YYYY-01-01 (the day and
    month the ODK date type stores for those appearances, never read back
    as known). Age, when also known, still prefills as below.

    Age: the registered ``age_years`` prefills ``age_group`` and its age
    field, editable like the date of birth: where an interview is completed
    its date of birth and age win (``_sync_case_identity``). An exact date
    of birth sends no age (the form calculates it).

    ``unit_parts`` is the unit's ``(presets, unit label)`` already resolved
    for a batch (``prefill_policy``); without it both are queried here.
    """
    interviewer: dict = {"name": user.name, "id": str(user.user_id)}
    age = _interviewer_age(user)
    if age is not None:
        # Not locked: a birth year alone is accurate to a year.
        interviewer["age"] = age
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
    unit_label = (unit_parts[1] if unit_parts
                  else _unit_label(db.session.get(MasOrgUnit, org_unit_id) if org_unit_id else None))
    # Opened once (one unwrap for a sealed row); the sealed columns are NULL.
    register = (register_pii_accessor.current_values(death, (
        *_ADDRESS_ATTRS, *PREFILL_ANSWER_FIELDS.values(), *PREFILL_LOCKED_FIELDS, "deceased_name", "remarks"))
        if death is not None else {})
    # No registered address: the registration's remarks say where the person lived.
    address = (_case_address(register) or (register["remarks"] or "").strip()) if death is not None else ""
    # Id10055 (usual residence): "<unit code> <unit name>; <address or remarks>". Place of
    # death (Id10057) is never prefilled; Id10051 comes from the form default.
    residence = "; ".join(part for part in (unit_label, address) if part)
    if residence:
        answers["Id10055"] = residence
    if death is not None:
        for name, field in PREFILL_ANSWER_FIELDS.items():
            value = register[field]
            if name == "Id10058":
                value = _who_place_of_death(value)
            if value:
                answers[name] = value
    if death is not None and cases.identity_complete(death):
        names = register["deceased_name"].split()
        deceased = {
            "givenNames": " ".join(names[:-1] or names),
            "sex": death.deceased_sex if death.deceased_sex in ("male", "female") else "undetermined",
            # Only one of dateOfDeath/yearOfDeath may be sent -- prefill.ts
            # throws on both (WhoVaDeathEvidence). A case with its identity
            # always has the exact date; yearOfDeath is for a future path
            # that only knows the year.
            "dateOfDeath": death.date_of_death.isoformat(),
        }
        if len(names) > 1:
            deceased["surname"] = names[-1]
        if death.date_of_birth:
            deceased["dateOfBirth"] = death.date_of_birth.isoformat()
        elif death.age_years is not None and 12 <= death.age_years <= 119:
            # ageInYears for prefill.ts (device and web clients); the same
            # answers it derives. Not locked: the interview's age wins.
            deceased["ageInYears"] = death.age_years
            answers.update({"age_group": "adult", "age_adult": death.age_years})
        elif death.age_years is not None and 1 <= death.age_years <= 11:
            # prefill.ts maps adults only. Age 0 is not prefilled: days
            # (neonate) or months (child) cannot be told from 0 years.
            answers.update({"Id10020": "no", "age_group": "child", "age_child_unit": "years",
                            "age_child_years": death.age_years})
        if not death.date_of_birth and death.date_of_birth_partial:
            partial = death.date_of_birth_partial
            answers["Id10020"] = "no"
            if len(partial) == 7:
                answers.update({"dob_precision": "month_year", "dob_month_year": f"{partial}-01"})
            else:
                answers.update({"dob_precision": "year", "dob_year": f"{partial}-01-01"})
        prefill["deceased"] = deceased
        for name in PREFILL_LOCKED_FIELDS:
            value = register[name]
            if value:
                answers[name] = value
                locked.add(name)
    # Free-text answers built from the register (Id10055/Id10057) carry no
    # national-ID digit run (PII slice 1a).
    prefill["answers"] = redact_payload_national_ids(answers)[0]
    prefill["lockedQuestionNames"] = sorted(locked)
    return prefill


#: Locked interviewer questions and the ``prefill["interviewer"]`` key each is
#: filled from, as prefill.ts's addInterviewer maps them.
#: Id10010a (interviewer age) is prefilled but never locked (owner,
#: 2026-10-20); leaving it out also stops a draft's stored lock list from
#: enforcing it.
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


def _current_prefill(draft: VaWebIntakeDraft) -> dict:
    """*draft*'s prefill as a new draft would get it now: ``_prefill_from_death``
    from its case as it stands, its owner and its unit."""
    death = db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None
    return _prefill_from_death(death, db.session.get(VaUsers, draft.user_id), draft.org_unit_id)


def _draft_locked_answers(draft: VaWebIntakeDraft) -> dict:
    """``_locked_answers`` for *draft*, always recomputed from the case and
    the draft's owner, never from the stored prefill: a draft saved before a
    lock existed (no ``lockedQuestionNames``, ``{}``, or an older list) gets
    today's locks, and a corrected registration wins. Never written back."""
    return _locked_answers(_current_prefill(draft))


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


def start_draft(user: VaUsers, *, project_id: str, site_id: str, org_unit_id: object | None = None, death_id: object | None = None, entries: list[dict] | None = None, locked_death: VaDeathRegister | None = None, unrouted_ok: bool = False, enforce_collection_gate: bool = False) -> VaWebIntakeDraft:
    """Open (or return the caller's own) draft for a case, or start directly.

    *entries* and *locked_death* are plumbing for a caller that already built
    ``interviewer_context(user)`` and already passed ``get_death`` and
    ``lock_case`` on this case in this transaction (``submit_device_interview``):
    reused instead of rebuilt, re-read and re-locked. Every check still runs.
    *unrouted_ok* as ``_require_scope`` (a standalone push only).
    *enforce_collection_gate*: a live direct start (the browser's), refused
    by a closed collection gate; it never applies to a case already
    registered, which is continuing work (project-clock-and-gates.md).

    A direct start creates its case at once (``source = direct``,
    ``draft_identity``); the draft's answers fill the identity in.

    One open draft per interviewer per case: another interviewer's draft never
    blocks a start, each gets their own copy (web-intake.md "Parallel
    interviews").
    """
    mode = get_web_intake_mode(project_id)
    if locked_death is not None and str(locked_death.death_id) == str(death_id):
        death = locked_death
    else:
        death = get_death(user, death_id, entries=entries) if death_id else None
    if death is not None:
        if not _mode_allows(mode, death_register=death.source == "register"):
            raise WebIntakeError("This project does not use the death register.", 403)
        if death.project_id != project_id or death.site_id != site_id:
            raise WebIntakeError("Death entry belongs to another project or site.")
        # Serialises starts on one case: the second waits here, then sees the
        # caller's own open draft below instead of opening another.
        if death is not locked_death:
            death = cases.lock_case(death)
        if death.status == "submitted":
            raise WebIntakeError("A questionnaire has already been submitted for this death.", 409)
        if death.status in ("duplicate", "cancelled") or death.consent_withdrawn_at is not None:
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
    else:
        org_unit_id = org_unit_id or public_demo_service.default_org_unit_id(project_id)
    _require_scope(user, project_id, site_id, org_unit_id, entries=entries, unrouted_ok=unrouted_ok)
    if enforce_collection_gate and death is None:
        collection_gate.require_open(user, project_id, site_id, org_unit_id)
    # Only a new draft counts against the public demo's open-draft limit.
    public_demo_service.check_new_draft(user, project_id)
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
    now = facade()._utcnow().isoformat()
    started_event = server_event("interview_started", at=datetime.fromisoformat(now))
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
            _TIMELINE_META_KEY: [started_event],
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
    stmt = sa.select(VaWebIntakeDraft).where(
        VaWebIntakeDraft.user_id == user.user_id, *training_scope.conditions(VaWebIntakeDraft.project_id)
    )
    if status:
        stmt = stmt.where(VaWebIntakeDraft.status == status)
    if not user.is_admin():
        # A consent-withdrawn case is sealed: admin only (docs/policy/consent-withdrawal.md).
        stmt = stmt.where(~sa.exists().where(
            VaDeathRegister.death_id == VaWebIntakeDraft.death_id,
            VaDeathRegister.consent_withdrawn_at.is_not(None),
        ))
    return list(db.session.scalars(stmt.order_by(VaWebIntakeDraft.updated_at.desc()).limit(200)).all())


def get_draft(user: VaUsers, draft_id: object, *, require_open: bool = False) -> VaWebIntakeDraft:
    """The caller's own draft (404 for anyone else's or an unknown id: the one
    ownership predicate of every draft route). *require_open* also refuses a
    draft that is no longer ``draft`` (409). Takes no row lock;
    ``lock_draft_for_browser_write`` takes the case lock a write needs."""
    try:
        draft = db.session.get(VaWebIntakeDraft, uuid.UUID(str(draft_id)))
    except ValueError:
        draft = None
    if draft is None or draft.user_id != user.user_id or not training_scope.keeps_project(draft.project_id):
        raise WebIntakeError("Draft not found.", 404)
    # A consent-withdrawn case is sealed: admin only (docs/policy/consent-withdrawal.md).
    if draft.death_id is not None and not user.is_admin() and db.session.scalar(
        sa.select(VaDeathRegister.consent_withdrawn_at).where(VaDeathRegister.death_id == draft.death_id)
    ) is not None:
        raise WebIntakeError("Draft not found.", 404)
    if require_open and draft.status != "draft":
        raise WebIntakeError("This draft is no longer editable.", 409)
    # A real project keeps an in-flight draft after its grant goes
    # (digitva-9xn9.22); a training draft ends with its session's grants.
    if draft.project_id == training_scope.training_project_id():
        _require_scope(user, draft.project_id, draft.site_id, draft.org_unit_id)
    return draft


def answers_of(draft: VaWebIntakeDraft) -> dict:
    """The draft's answers: the ``final`` section alone once the draft is
    closed (a submitted or superseded draft keeps its complete final answers
    there), else the per-section saves merged."""
    data: dict = {}
    for section in draft.sections:
        if section.section_name == FINAL_SECTION and draft.status != "draft":
            return dict(section.data or {})
        data.update(section.data or {})
    return data


_answers_of = answers_of  # the earlier name: this package and tests still use it


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
        # Only when recorded: a browser draft (bundled form) has no slice identity.
        **{k: meta[k] for k in _DEFINITION_IDENTITY_KEYS if k in meta},
        **(
            {_TIMELINE_META_KEY: parse_timeline(meta[_TIMELINE_META_KEY], INTERVIEW_TIMELINE_EVENTS)}
            if _TIMELINE_META_KEY in meta else {}
        ),
        **(
            {_CODING_TIMELINE_META_KEY: _parse_coding_timeline(meta[_CODING_TIMELINE_META_KEY])}
            if _CODING_TIMELINE_META_KEY in meta else {}
        ),
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


def _parse_coding_timeline(value: object, allowed_events=CODING_TIMELINE_EVENTS) -> list[dict]:
    """Validate the fixed, separately bounded coding event stream."""
    timeline = parse_timeline(value, allowed_events)
    if len(timeline) > _CODING_TIMELINE_MAX:
        raise WorkflowTimelineError("Invalid workflow timeline.")
    return timeline


def merge_incoming_timeline_meta(
    draft: VaWebIntakeDraft,
    incoming: dict | None,
    *,
    allow_server_receipts: bool = False,
) -> dict:
    """Merge client timeline metadata without replacing server-owned receipts.

    This is shared by ordinary saves, revisions and idempotent upload resends.
    ``submitted`` and ``final_saved`` are server receipts: a client may echo
    them, but can never add or replace their stored timestamps.
    """
    if not isinstance(incoming, dict):
        return {}
    updates: dict = {}
    try:
        if _TIMELINE_META_KEY in incoming:
            current = parse_timeline((draft.meta or {}).get(_TIMELINE_META_KEY), INTERVIEW_TIMELINE_EVENTS)
            received = parse_timeline(incoming[_TIMELINE_META_KEY], INTERVIEW_TIMELINE_EVENTS)
            received = [event for event in received if event["event"] != "submitted"]
            updates[_TIMELINE_META_KEY] = merge_timeline(current, received, INTERVIEW_TIMELINE_EVENTS)
        if _CODING_TIMELINE_META_KEY in incoming:
            current = _parse_coding_timeline((draft.meta or {}).get(_CODING_TIMELINE_META_KEY), CODING_TIMELINE_EVENTS)
            received = _parse_coding_timeline(
                incoming[_CODING_TIMELINE_META_KEY],
                CODING_TIMELINE_EVENTS if allow_server_receipts else _CODING_TIMELINE_CLIENT_EVENTS,
            )
            received = [event for event in received if event["event"] not in {"final_saved", "coding_allocated"}]
            updates[_CODING_TIMELINE_META_KEY] = _parse_coding_timeline(
                merge_timeline(current, received, CODING_TIMELINE_EVENTS)
            )
    except WorkflowTimelineError as exc:
        # Keep the existing coding-specific API error for callers that send
        # only the coding stream.  The combined helper is also used by
        # revisions and upload resends, where the distinction is useful to
        # clients without changing validation semantics.
        if _CODING_TIMELINE_META_KEY in incoming and _TIMELINE_META_KEY not in incoming:
            raise WebIntakeError("Invalid coding timeline.", 400, "invalid_coding_timeline") from exc
        raise WebIntakeError("Invalid workflow timeline.", 400, "invalid_workflow_timeline") from exc
    return updates


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


def _approximate_date_of_death(data: dict) -> date | None:
    """1 July of the ``Id10024`` year of death, when the exact date is not known.

    Only when the answers give no exact date (``_identity_from_answers``) and
    ``Id10022`` is not "yes". Mid-year minimises the worst-case error; it is
    capped at today (a current-year death before July is not a future date).
    None for an unusable year (not four digits, before 1900, or after this
    year). Callers use it only where the case holds no date of death.
    """
    if "date_of_death" in _identity_from_answers(data) or data.get("Id10022") == "yes":
        return None
    raw = str(data.get("Id10024") or "").strip()[:4]
    if not (raw.isascii() and raw.isdigit() and len(raw) == 4):
        return None
    year, today = int(raw), facade().date.today()
    if not 1900 <= year <= today.year:
        return None
    return min(facade().date(year, 7, 1), today)


def _missing_identity_error(data: dict, *, name: bool, sex: bool, date_of_death: bool) -> WebIntakeError:
    """The 422 for an incomplete identity, naming the WHO questions to answer.

    Each flag says that part is present. ``fields`` lists only the missing
    parts' input questions (``Id10023`` is calculated, so its ``_a``/``_b``
    sources stand in once the date is said to be known)."""
    fields: list[str] = [] if name else ["Id10017", "Id10018"]
    if not sex:
        fields.append("Id10019")
    if not date_of_death:
        fields.append("Id10022")
        fields += ["Id10023_a", "Id10023_b"] if data.get("Id10022") == "yes" else ["Id10024"]
    return WebIntakeError("Record the name, date of death and sex of the deceased before submitting.", 422, fields=fields)


def _birth_age_from_answers(data: dict, date_of_death: date | None) -> dict:
    """The interview's date of birth and age as case columns (the reverse of
    ``_prefill_from_death``); the answers are read by ``who_va_answers``, the
    case's rules are here. The case keeps its own where the interview gives
    nothing usable.

    The date of birth is one unit: the exact date (``date_of_birth``, partial
    cleared) or the year/month (``date_of_birth_partial`` as ``YYYY`` or
    ``YYYY-MM``, exact cleared), each valid as ``register_death`` requires
    (not future, not after the death); one that fails is unusable. The age is
    whole years 0..130, as ``register_death`` accepts: ``ageInYears`` (the
    form's, from an exact date of birth; "NaN" without one), else the
    ``age_group`` answers, under a year being 0.

    An age with the date of birth said to be unknown (``Id10020`` = no or
    ref, no usable partial date) clears the registered date of birth, exact
    and partial: the interview wins (owner, 2026-10-06, ``digitva-uq6v``).
    """
    out: dict = {}
    answer = birth_answer(data)
    if answer is not None:
        precision, _key, born = answer
        if precision == "exact":
            if born <= min(date_of_death or date.max, date.today()):
                out.update(date_of_birth=born, date_of_birth_partial=None)
        elif date_of_death is not None:
            partial = f"{born.year:04d}" + (f"-{born.month:02d}" if precision == "month_year" else "")
            try:
                out.update(date_of_birth=None, date_of_birth_partial=_clean_partial_birth(partial, date_of_death))
            except WebIntakeError:
                pass
    age = whole_answer(data, "ageInYears") if out.get("date_of_birth") else None
    field = age_field(data)
    if age is None and field is not None:
        group, unit, key = field
        if group == "neonate" or unit == "days":
            age = 0
        elif unit == "months":
            months = whole_answer(data, key)
            age = months // 12 if months is not None and months >= 0 else None
        else:
            age = whole_answer(data, key)
    if age is None or not 0 <= age <= 130:
        return out
    if "date_of_birth" not in out and choice_answer(data, "Id10020") in ("no", "ref"):
        out.update(date_of_birth=None, date_of_birth_partial=None)
    out["age_years"] = age
    return out


def _sync_case_identity(death: VaDeathRegister, data: dict, actor: VaUsers) -> None:
    """Copy the form's identity answers onto the case (the form is the record
    of the interview); a direct start leaves ``draft_identity`` once complete.
    Name, sex, date of death, date of birth and age: the interview's replace
    the case's, the previous values going to the audit. An empty or unusable
    answer never blanks a value the case already holds. ``date_of_death_year_only``
    follows the date it marks: True for a year-only date written here; False
    for an exact answer that changes the date or replaces a year-only one;
    otherwise unchanged. It is not audited (a marker, not a value)."""
    incoming = _identity_from_answers(data)
    year_only = None
    if "date_of_death" in incoming:
        if incoming["date_of_death"] != death.date_of_death or death.date_of_death_year_only:
            year_only = False
    elif not death.date_of_death:
        approximate = _approximate_date_of_death(data)
        if approximate:
            incoming["date_of_death"] = approximate
            year_only = True
    if year_only is not None:
        death.date_of_death_year_only = year_only
    incoming.update(_birth_age_from_answers(data, incoming.get("date_of_death") or death.date_of_death))
    opened = register_pii_accessor.current_values(death)
    before: dict = {}
    after: dict = {}
    for field, value in incoming.items():
        stored = opened[field] if field in opened else getattr(death, field)
        if stored != value:
            before[field] = stored
            after[field] = value
    register_pii_accessor.write_fields(death, after)
    if before and death.status != "draft_identity":
        # A completed interview overwrote registered details: the field
        # names go in the reason, the old and new values in ``changes``.
        _audit_details_change(death, actor, IDENTITY_FROM_INTERVIEW, before, after)
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


_TIMELINE_META_KEY = "workflowTimelineV1"


_CODING_TIMELINE_META_KEY = "codingTimelineV1"


_CODING_TIMELINE_CLIENT_EVENTS = CODING_TIMELINE_EVENTS - {"final_saved", "coding_allocated"}


_CODING_TIMELINE_MAX = 6


#: Draft meta keys a client (browser save or device envelope) may set.
_ENVELOPE_META_KEYS = (
    "schemaVersion", "formVersion", "instrumentId", "instrumentVersion", "createdAt", "updatedAt",
    *_DEFINITION_IDENTITY_KEYS, _TIMELINE_META_KEY, _CODING_TIMELINE_META_KEY,
)


#: The device's interview start and completion times (ISO 8601 with offset),
#: taken from the checked device envelope only: a browser save cannot set
#: them, so it cannot choose the date ``today()`` is evaluated at.
_DEVICE_TIME_KEYS = ("startedAt", "completedAt")


def scrub_attachment_names(answers: dict) -> dict:
    """*answers* without the file names inside attachment references.

    A reference carries ``name`` and ``originalName``; the package fills them
    from the picked file, and a file name can name the deceased or the
    respondent. The server keeps only the id, ``uri``, type, size and the
    like: names are dropped before any answer is stored (docs/policy/web-intake.md,
    "Attachments"). A new dict; values that are not references are shared."""
    return {
        key: ({k: v for k, v in value.items() if k not in ("name", "originalName")}
              if isinstance(value, dict) and _is_attachment_reference(value) else value)
        for key, value in answers.items()
    }


def stored_answers(answers: dict) -> dict:
    """*answers* as every draft row stores them: attachment file names
    dropped (``scrub_attachment_names``) and national IDs reduced
    (``redact_payload_national_ids``: ``Id10073`` to its last 3 digits, digit
    runs in free text masked; PII slice 1a, docs/kb/pii-slice-1a.md). The
    server applies it whatever the client sent; the client's
    ``answers_sha256`` is kept as sent, an upload identity only."""
    return redact_payload_national_ids(scrub_attachment_names(answers))[0]


def is_new_refusal(draft: VaWebIntakeDraft, answers: dict, consent: object = None,
                   client_draft_id: uuid.UUID | None = None) -> bool:
    """Whether this request records a new refusal of *draft*'s own, the
    moment its teammates are cleared (``clear_direct_identity_for_refusal``
    *hold_others*). Own: WHO ``Id10013 = no`` in *answers*, a refused
    *consent* arriving with this request (device), or a refused consent
    recorded for its attempt (*client_draft_id*, default the draft's), not
    only the case's older case-level refusal it inherits. New: the draft is
    not already refused and unresumed (``refusalResumePending``, which only
    ``scrub_refused_draft`` sets and only an explicit resume clears), so a
    later autosave or submit of the same refusal clears no one again. Read it
    before this request scrubs the draft."""
    from app.services import consent_service

    if (draft.meta or {}).get("refusalResumePending"):
        return False
    if str(answers.get("Id10013") or "").strip().lower() == "no":
        return True
    if isinstance(consent, dict) and consent.get("decision") in ("granted", "refused"):
        return consent["decision"] == "refused"
    attempt = client_draft_id or draft.client_draft_id
    if attempt is None or draft.death_id is None:
        return False
    record = consent_service._latest_record(draft.death_id, attempt)
    return bool(record and record.event == "refused")


def clear_direct_identity_for_refusal(draft: VaWebIntakeDraft, actor: VaUsers, *, hold_others: bool) -> None:
    """Remove identity copied from an unsent direct interview, not a register.

    On a shared case (other open drafts) the case's identity stays. When
    *hold_others* (this request records a new refusal of the draft's own,
    ``is_new_refusal``) every other open draft is scrubbed as this one is
    (``scrub_refused_draft``: refusal-only answers, no prefill, history or
    uploads) and paused for an explicit resume, and this draft holds the case
    until a fresh grant on it or its submit
    (docs/policy/respondent-consent-notice-draft.md, "Later agreement and
    shared cases"). A draft refused only by the case's older refusal, or
    saved again under a refusal already recorded, leaves the others alone:
    they may hold a fresh grant of their own. Submitted
    drafts are never touched."""
    death = db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None
    if death is None:
        return
    open_others = sa.select(VaWebIntakeDraft).where(
        VaWebIntakeDraft.death_id == death.death_id, VaWebIntakeDraft.draft_id != draft.draft_id,
        VaWebIntakeDraft.status == "draft",
    )
    if not hold_others:
        if db.session.scalar(sa.select(open_others.exists())):
            return
    else:
        # Locked so a teammate's concurrent save cannot land over the scrub;
        # ordered so concurrent refusals take the locks in one order.
        others = db.session.scalars(
            open_others.order_by(VaWebIntakeDraft.draft_id).options(selectinload(VaWebIntakeDraft.sections))
            .with_for_update(of=VaWebIntakeDraft).execution_options(populate_existing=True)
        ).all()
        if others:
            for other in others:
                scrub_refused_draft(other)
            draft.meta = {**(draft.meta or {}), "caseRefusalHold": True}
            return
    if death.source != "direct" or death.status not in ("draft_identity", "in_progress") or death.va_sid or db.session.scalar(sa.select(sa.exists().where(
        VaWebIntakeDraft.death_id == death.death_id, VaWebIntakeDraft.status == "submitted",
    ))):
        return
    if death.status == "in_progress":
        cases.transition(death, "draft_identity", actor=actor, action="refusal_identity_cleared")
    register_pii_accessor.write_fields(death, {
        "deceased_name": None, "deceased_sex": None, "date_of_death": None, "date_of_death_year_only": None,
        "date_of_birth": None, "date_of_birth_partial": None, "age_years": None,
    })
    db.session.flush()


def scrub_refused_draft(draft: VaWebIntakeDraft) -> None:
    """Scrub this unsent draft and its saved losing versions."""
    from app.services import consent_service

    history = sa.select(VaWebIntakeDraft.draft_id).where(
        VaWebIntakeDraft.status == "replaced", VaWebIntakeDraft.user_id == draft.user_id,
        VaWebIntakeDraft.death_id == draft.death_id,
        VaWebIntakeDraft.meta["replacedDraftId"].astext == str(draft.draft_id),
    )
    section_data = VaWebIntakeDraftSection.data
    pairs = []
    for key, values in consent_service.REFUSAL_ANSWERS.items():
        pairs.extend((key, sa.case((section_data[key].astext.in_(values), section_data[key].astext), else_=None)))
    db.session.execute(sa.update(VaWebIntakeDraftSection).where(
        VaWebIntakeDraftSection.draft_id.in_(history)
    ).values(data=sa.func.jsonb_strip_nulls(sa.func.jsonb_build_object(*pairs))))
    db.session.execute(sa.update(VaWebIntakeDraft).where(VaWebIntakeDraft.draft_id.in_(history)).values(prefill={}))
    for row in draft.sections:
        row.data = consent_service.refusal_answers(row.data or {})
    draft.prefill = {}
    draft.updated_at = facade()._utcnow()
    draft.meta = {**(draft.meta or {}), "refusalBarrier": draft.updated_at.isoformat(), "refusalResumePending": True}
    _note_last_change(draft, refusal=True)
    attachments.delete_draft_uploads(draft)


def _note_last_change(draft: VaWebIntakeDraft, *, user_id=None, channel: str | None = None,
                      refusal: bool = False) -> None:
    """Record on the draft who changed it at its current ``updated_at``, on
    which channel and whether a consent refusal cleared it (``last_change``)."""
    draft.meta = {**(draft.meta or {}), "lastChange": {
        "at": draft.updated_at.isoformat(),
        **({"userId": str(user_id)} if user_id else {}),
        **({"channel": channel} if channel else {}),
        **({"refusal": True} if refusal else {}),
    }}


_CHANGE_CHANNELS = {"device": "phone", "web": "browser"}


def last_change(draft: VaWebIntakeDraft, viewer: VaUsers) -> dict:
    """``{at, via, by_you, name, refusal}``: the draft's last change for a
    reply to *viewer*, who must be allowed to edit it (its owner,
    ``get_draft``). ``via`` is ``phone`` or ``browser``, ``name`` the editor's
    display name only (never an email or number); both null when the draft
    did not record its current version (saved before this was kept, or a
    metadata-only change). ``refusal``: a consent refusal cleared it."""
    note = (draft.meta or {}).get("lastChange") or {}
    if _device_time(note.get("at")) != draft.updated_at:
        note = {}
    editor_id = note.get("userId")
    by_you = None if editor_id is None else editor_id == str(viewer.user_id)
    editor = viewer if by_you else (db.session.get(VaUsers, uuid.UUID(editor_id)) if editor_id else None)
    return {
        "at": draft.updated_at.isoformat(),
        "via": _CHANGE_CHANNELS.get(note.get("channel")),
        "by_you": by_you,
        "name": editor.name if editor is not None else None,
        "refusal": bool(note.get("refusal")),
    }


def check_refusal_resume(draft: VaWebIntakeDraft, *, base_updated_at: object, resume_refused: bool) -> bool:
    """Require a current, explicit first resume and reject pre-refusal saves.

    The first resume rebuilds the prefill the refusal cleared
    (``scrub_refused_draft``) from the case, owner and unit as they are now
    (``_current_prefill``), as for a new draft: area presets, interviewer,
    registration answers and locked names come back; nothing from before the
    refusal is restored. Its saved losing versions stay scrubbed."""
    meta = draft.meta or {}
    barrier = _device_time(meta.get("refusalBarrier"))
    if barrier is None:
        return False
    base = _device_time(base_updated_at)
    if base is None or base < barrier:
        raise refusal_stale(draft, "Reload the cleared draft before continuing.")
    if meta.get("refusalResumePending"):
        if not resume_refused or base != draft.updated_at:
            raise refusal_stale(draft, "Confirm the new consent decision on the current draft.")
        draft.meta = {**meta, "refusalResumePending": False}
        draft.prefill = _current_prefill(draft)
        return True
    return False


def refusal_stale(draft: VaWebIntakeDraft, message: str) -> WebIntakeError:
    exc = WebIntakeError(message, 409, "refusal_stale")
    exc.draft_id = str(draft.draft_id)
    return exc


def release_who_refusal_hold(draft: VaWebIntakeDraft, *, answers: dict, base_updated_at: object,
                             resume_refused: bool, consent=None) -> bool:
    if not ((draft.meta or {}).get("caseRefusalHold") and resume_refused and answers.get("Id10013") == "yes"):
        return False
    from app.services import consent_service
    death = db.session.get(VaDeathRegister, draft.death_id)
    if consent_service.interview_refused(death=death, client_draft_id=draft.client_draft_id,
                                         answers=answers, consent=consent, include_case_hold=False):
        return False
    check_refusal_resume(draft, base_updated_at=base_updated_at, resume_refused=True)
    draft.meta = {**draft.meta, "caseRefusalHold": False}
    db.session.flush()
    return True


def save_draft_sections(draft: VaWebIntakeDraft, *, sections: dict, meta: dict | None = None, current_section: str | None = None, actor: VaUsers | None = None, refusal_override: bool | None = None, resume_refused: bool = False, new_refusal: bool | None = None, channel: str = "web") -> int:
    """Upsert the given sections' answers; returns the number of sections written.

    A direct start's case (``draft_identity``) takes its identity from the
    merged answers of every saved section (a save sends only the sections that
    changed); any other case takes it at submit. *actor* is the saver,
    recorded when the case leaves ``draft_identity``; it defaults to the
    draft's owner, the only user who may save it. *new_refusal*:
    ``is_new_refusal`` decided by a caller that scrubs the draft or knows an
    incoming consent first (device paths); None decides it here. *channel*
    (``web`` or ``device``) is recorded with the saver for ``last_change``.
    """
    if not isinstance(sections, dict):
        raise WebIntakeError("sections must be an object keyed by section name.")
    from app.services import consent_service

    combined = _answers_of(draft)
    if resume_refused and any(isinstance(answers, dict) and answers.get("Id10013") == "yes"
                              for answers in sections.values()):
        for row in draft.sections:
            row.data = {key: value for key, value in (row.data or {}).items() if key != "Id10013"}
        combined.pop("Id10013", None)
    if str(combined.get("Id10013") or "").strip().lower() == "no" and not resume_refused:
        prior_sections = {row.section_name for row in draft.sections if (row.data or {}).get("Id10013") == "no"}
        sections = {name: ({**answers, "Id10013": "no"} if isinstance(answers, dict)
                           and ("Id10013" in answers or name in prior_sections) else answers)
                    for name, answers in sections.items()}
    for answers in sections.values():
        if isinstance(answers, dict):
            combined.update(answers)
    death = db.session.get(VaDeathRegister, draft.death_id) if draft.death_id else None
    refused = refusal_override if refusal_override is not None else consent_service.interview_refused(
        death=death, client_draft_id=draft.client_draft_id, answers=combined,
    )
    if refused:
        new = new_refusal if new_refusal is not None else is_new_refusal(draft, combined)
        clear_direct_identity_for_refusal(draft, actor or db.session.get(VaUsers, draft.user_id), hold_others=new)
        scrub_refused_draft(draft)
        sections = {name: consent_service.refusal_answers(answers) if isinstance(answers, dict) else answers
                    for name, answers in sections.items()}
    # Validate metadata before writing answers so an invalid pin, locale, or
    # timeline cannot leave the answers saved while its metadata is refused.
    locale_meta = _clean_locale_meta(meta) if meta else {}
    if meta:
        check_definition_identity(meta)
    timeline_meta = merge_incoming_timeline_meta(draft, meta)
    existing = {row.section_name: row for row in draft.sections}
    # docs/policy/web-intake.md "Locked prefill": a tampered or dropped locked
    # answer is put back, not refused (see submit_draft).
    locked = {} if refused else _draft_locked_answers(draft)
    written = 0
    browser_keys: set = set()
    for name, answers in sections.items():
        if not isinstance(name, str) or not _SECTION_NAME_RE.match(name):
            raise WebIntakeError(f"Invalid section name {name!r}.")
        if not isinstance(answers, dict):
            raise WebIntakeError(f"Section {name!r} must be an object of answers.")
        check_device_answers(answers)
        row = existing.get(name)
        if name != DEVICE_SECTION:
            browser_keys.update(answers)
            # An answer the browser cleared is null or gone from the section it
            # had saved: it must beat the phone's value for the same question.
            browser_keys.update((row.data or {}) if row is not None else ())
        answers = stored_answers(_enforce_locked(answers, locked, row.data if row is not None else None))
        if row is None:
            row = VaWebIntakeDraftSection(draft_id=draft.draft_id, section_name=name, data=answers)
            db.session.add(row)
            draft.sections.append(row)
        else:
            row.data = answers
            row.saved_at = facade()._utcnow()
        written += 1
    device_row = existing.get(DEVICE_SECTION)
    if browser_keys:
        # A browser save over a phone-won draft is no longer the phone's
        # content, and its answers beat the phone's for the same questions
        # (no section merge: web-intake.md "Parallel interviews").
        draft.answers_sha256 = None
        if device_row is not None and browser_keys & set(device_row.data or {}):
            device_row.data = {k: v for k, v in device_row.data.items() if k not in browser_keys}
    if meta:
        keep = {k: meta[k] for k in _ENVELOPE_META_KEYS if k in meta}
        keep.update(locale_meta)
        keep.update(timeline_meta)
        draft.meta = {**(draft.meta or {}), **keep}
    if current_section is not None:
        if not _SECTION_NAME_RE.match(str(current_section)):
            raise WebIntakeError("Invalid current section.")
        draft.current_section = str(current_section)
    if written:
        # Only an answer write dates the draft: a locale or position save from
        # merely opening the form must not outrank a newer phone save.
        draft.updated_at = facade()._utcnow()
        _note_last_change(draft, user_id=actor.user_id if actor else draft.user_id, channel=channel, refusal=refused)
    if written and draft.death_id:
        death = db.session.get(VaDeathRegister, draft.death_id)
        # Identity follows the form only for a direct start, which only its
        # starter sees; on a shared case it updates at the winning submit.
        if death.status == "draft_identity" and not refused:
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
    # The draft's uploaded files go with it (their stored objects too): a
    # discarded draft is never submitted, so nothing would ever read them.
    deleted = attachments.delete_draft_uploads(draft)
    if deleted and death is not None:
        cases.record_action(death, actor=actor, action="draft_attachments_deleted")
    if deleted:
        log.info("draft discarded with %d uploaded file(s) deleted | unique_id=%s | by=%s", deleted, draft.unique_id, actor.user_id)
    db.session.flush()


def _is_attachment_reference(value: object) -> bool:
    if isinstance(value, str):
        return value.startswith(ATTACHMENT_REFERENCE_PREFIX)
    if isinstance(value, dict):
        return str(value.get("id", "")).startswith(ATTACHMENT_REFERENCE_PREFIX) or "id" in value and "mimeType" in value
    return False


#: Case states a submit is kept for as a superseded copy instead of
#: submitted: a teammate's complete submission won, or a supervisor closed
#: the case. Never refused, so nothing is left stuck on the phone or page.
_SUPERSEDED_CASE_STATES = frozenset({"submitted", "duplicate", "cancelled"})


#: Section holding a browser draft's final answers when it is superseded.
FINAL_SECTION = "final"


#: The one section a device upload's answers are stored under: the app sends
#: the whole envelope at once, not section-wise saves.
DEVICE_SECTION = "device"


#: Bounds on a device upload's answers, checked before anything is stored
#: (the request itself is capped at 2 MB by the device blueprint). Answers
#: are flat values, choice lists and small attachment/audit objects.
DEVICE_ANSWERS_MAX_BYTES = 1024 * 1024


DEVICE_ANSWERS_MAX_DEPTH = 6


def check_device_answers(data: dict) -> None:
    """Refuse (422) answers nested deeper than DEVICE_ANSWERS_MAX_DEPTH or (413)
    whose serialized JSON exceeds DEVICE_ANSWERS_MAX_BYTES."""
    stack = [(data, 1)]
    while stack:
        value, depth = stack.pop()
        if depth > DEVICE_ANSWERS_MAX_DEPTH:
            raise WebIntakeError("answers_json is nested too deeply.", 422)
        children = value.values() if isinstance(value, dict) else value
        stack.extend((child, depth + 1) for child in children if isinstance(child, (dict, list)))
    if len(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8", "surrogatepass")) > facade().DEVICE_ANSWERS_MAX_BYTES:
        raise WebIntakeError("answers_json is too large.", 413, "payload_too_large")


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
