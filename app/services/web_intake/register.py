"""The death register: registering, listing, editing and flagging deaths.

Part of the web intake service split (bead digitva-r8nh.12); the public
module is ``app.services.web_intake_service``, which re-exports every name.
Code that tests patch on that module is read back through ``facade()``.
"""
from __future__ import annotations

import math
import uuid
from datetime import date

import sqlalchemy as sa

from app import db
from app.models import (
    MasOrgUnit,
    VaDeathRegister,
    VaProjectMaster,
    VaUsers,
)
from app.models.va_web_intake import (
    DEATH_SEX_VALUES,
)
from app.services import case_transition_service as cases
from app.services import (
    collection_gate,
    project_clock,
    public_demo_service,
    register_pii_accessor,
    training_scope,
)
from app.services import death_identifier_service as death_identifiers
from app.services.authz.actions import DEATH_REGISTERING_ROLES
from app.services.case_transition_service import WebIntakeError
from app.services.web_intake import facade
from app.services.web_intake.common import (
    _ABHA_ADDRESS_RE,
    _ABHA_NUMBER_RE,
    _PARTIAL_DATE_RE,
    PARTIAL_BIRTH_MIN_YEAR,
    log,
)
from app.services.web_intake.scope import (
    _DEATH_REPORTER,
    _allocate_unique_id,
    _mode_allows,
    _require_scope,
    _worklist_scope,
    get_web_intake_mode,
)
from app.utils.national_id import redact_national_id_digits
from app.utils.phone import normalise_phone


def _clean(raw: object, *, what: str, required: bool = False, max_len: int | None = None) -> str | None:
    value = str(raw).strip() if raw is not None else ""
    if not value:
        if required:
            raise WebIntakeError(f"{what} is required.")
        return None
    if max_len and len(value) > max_len:
        raise WebIntakeError(f"{what} must be at most {max_len} characters.")
    return value


def _project_today(project_id: str) -> date:
    """Today on the project's clock (its timezone, default Asia/Kolkata), the
    day "not in the future" is judged by (owner, digitva-vz9f)."""
    project = db.session.get(VaProjectMaster, project_id)
    return project_clock.project_day(project.timezone if project else None).today


def _clean_date(raw: object, *, what: str, required: bool = False, today: date | None = None) -> date | None:
    """*today*: the project's day (``_project_today``); the server's date when not given."""
    value = _clean(raw, what=what, required=required)
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise WebIntakeError(f"{what} must be a date in YYYY-MM-DD form.") from exc
    if parsed > (today or date.today()):
        raise WebIntakeError(f"{what} cannot be in the future.")
    return parsed


def _clean_partial_birth(raw: object, date_of_death: date, today: date | None = None) -> str | None:
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
    if value > (today or date.today()).isoformat()[:len(value)]:
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
    """A phone number normalised to its 10 digits, or None if blank.

    The VA form's one phone format: exactly 10 digits, no restriction on the
    first. Spaces, hyphens and parentheses are ignored; a +91, 91 or 0 in
    front is dropped when 10 digits remain. The client mirrors this in
    ``mobile/digitva-collect/src/phoneFormat.ts``.
    """
    value = _clean(raw, what=what, max_len=32)
    if value is None:
        return None
    phone = normalise_phone(value)
    if phone is None:
        raise WebIntakeError(f"{what} must be a 10-digit phone number, for example 987 654 3210.")
    return phone


#: The register form's fields (``VaDeathRegister`` columns ``_clean_death_fields`` fills).
REGISTER_FIELDS = (
    "deceased_name", "deceased_sex", "abha_number", "abha_address", "date_of_birth", "date_of_birth_partial",
    "age_years", "date_of_death", "place_of_death", "address", "address_house_street",
    "address_village_ward", "address_landmark", "informant_name", "informant_phone",
    "informant_phone_2", "remarks", "father_name", "mother_name",
    "latitude", "longitude", "accuracy_m",
)


#: The informant phone columns, validated only when an edit changes them.
_PHONE_FIELDS = ("informant_phone", "informant_phone_2")


#: The GPS fix's columns; ``captured_at`` follows them, set by the server.
LOCATION_FIELDS = ("latitude", "longitude", "accuracy_m")


def _clean_number(raw: object, *, what: str, low: float, high: float) -> float | None:
    """A finite number within [low, high], or None if blank. Booleans and
    non-numeric text are refused; the message never echoes the value."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if isinstance(raw, bool):
        raise WebIntakeError(f"{what} must be a number.")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise WebIntakeError(f"{what} must be a number.") from None
    if not math.isfinite(value) or not low <= value <= high:
        raise WebIntakeError(f"{what} must be between {low:g} and {high:g}.")
    return value


def _clean_location(fields: dict) -> dict:
    """The GPS fix: latitude and longitude together or not at all, accuracy
    (metres) only with them. Rounded to 6 decimals (about 0.1 m)."""
    lat = _clean_number(fields.get("latitude"), what="Latitude", low=-90, high=90)
    lng = _clean_number(fields.get("longitude"), what="Longitude", low=-180, high=180)
    accuracy = _clean_number(fields.get("accuracy_m"), what="Location accuracy", low=0, high=1e7)
    if (lat is None) != (lng is None):
        raise WebIntakeError("Latitude and longitude must be given together.")
    if lat is None:
        if accuracy is not None:
            raise WebIntakeError("Location accuracy needs a latitude and longitude.")
        return {"latitude": None, "longitude": None, "accuracy_m": None}
    return {
        "latitude": round(lat, 6),
        "longitude": round(lng, 6),
        "accuracy_m": round(accuracy, 1) if accuracy is not None else None,
    }


#: The birth-date and age columns, one unit for the age-information rule.
_AGE_INFO_FIELDS = ("date_of_birth", "date_of_birth_partial", "age_years")


def _require_age_info(cleaned: dict, current: dict | None = None) -> None:
    """A registration carries age information: a date of birth (exact, month
    and year, or year only) or an estimated ``age_years``. 400 otherwise.

    With *current* (the stored values, on an edit) the rule applies only when
    this edit changes one of the three fields, so an older row without age
    information stays editable until they are touched; clearing them on a row
    that had one is a change and is refused. 0 is a valid age."""
    if any(cleaned[name] is not None for name in _AGE_INFO_FIELDS):
        return
    if current is not None and all(cleaned[name] == current[name] for name in _AGE_INFO_FIELDS):
        return
    raise WebIntakeError(
        "Enter the date of birth, or choose Date of birth unknown and enter an estimated age."
    )


def _clean_death_fields(fields: dict, *, keep_phones: frozenset[str] = frozenset(),
                        today: date | None = None) -> dict:
    """The register form's fields validated and normalised to ``VaDeathRegister``
    columns; the one validation path of ``register_death`` and ``update_death``.
    Raises 400 on the first bad value. A phone named in *keep_phones* is an
    unchanged stored value and passes as it is, so an older non-conforming
    number never blocks an edit of another field. *today* is the project's day
    for the not-in-the-future checks (``_project_today``)."""
    name = _clean(fields.get("deceased_name"), what="Deceased name", required=True)
    sex = (_clean(fields.get("deceased_sex"), what="Sex", required=True) or "").lower()
    if sex not in DEATH_SEX_VALUES:
        raise WebIntakeError("Sex must be one of " + ", ".join(DEATH_SEX_VALUES) + ".")
    date_of_death = _clean_date(fields.get("date_of_death"), what="Date of death", required=True,
                               today=today)
    date_of_birth = _clean_date(fields.get("date_of_birth"), what="Date of birth", today=today)
    if date_of_birth and date_of_birth > date_of_death:
        raise WebIntakeError("Date of birth cannot be after the date of death.")
    date_of_birth_partial = _clean_partial_birth(fields.get("date_of_birth_partial"), date_of_death, today)
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
    return {
        "deceased_name": name,
        "deceased_sex": sex,
        "abha_number": abha_number,
        "abha_address": abha_address,
        "date_of_birth": date_of_birth,
        "date_of_birth_partial": date_of_birth_partial,
        "age_years": age_years,
        "date_of_death": date_of_death,
        "place_of_death": redact_national_id_digits(_clean(fields.get("place_of_death"), what="Place of death"))[0],
        "address": _clean(fields.get("address"), what="Address"),
        "address_house_street": _clean(fields.get("address_house_street"), what="House or street", max_len=200),
        "address_village_ward": _clean(fields.get("address_village_ward"), what="Village or ward", max_len=200),
        "address_landmark": _clean(fields.get("address_landmark"), what="Landmark", max_len=200),
        "informant_name": _clean(fields.get("informant_name"), what="Informant name"),
        "father_name": _clean(fields.get("father_name"), what="Father's name", max_len=200),
        "mother_name": _clean(fields.get("mother_name"), what="Mother's name", max_len=200),
        "informant_phone": fields.get("informant_phone") if "informant_phone" in keep_phones
        else _clean_phone(fields.get("informant_phone"), what="Informant phone"),
        "informant_phone_2": fields.get("informant_phone_2") if "informant_phone_2" in keep_phones
        else _clean_phone(fields.get("informant_phone_2"), what="Second phone"),
        # Free text: a national-ID-like digit run is masked (PII slice 1a).
        "remarks": redact_national_id_digits(_clean(fields.get("remarks"), what="Remarks"))[0],
        **_clean_location(fields),
    }


def register_death(user: VaUsers, *, project_id: str, site_id: str, org_unit_id: object | None = None,
                   client_death_id: uuid.UUID | None = None, identifiers: dict | None = None,
                   warnings: list | None = None, enforce_collection_gate: bool = False,
                   **fields) -> VaDeathRegister:
    """Register a death. *identifiers* (``{type code: text}``) are validated
    and stored with it (``death_identifier_service.set_identifiers``), always
    checked for the project's ``required_at_report`` types; any
    ``identifier_in_use`` warnings are appended to *warnings*.
    *enforce_collection_gate*: a live new start (the browser's register), so a
    closed collection gate refuses it (``collection_gate.require_open``); an
    upload of a registration made offline never passes it."""
    mode = get_web_intake_mode(project_id)
    if not _mode_allows(mode, death_register=True):
        raise WebIntakeError("This project does not use the death register.", 403)
    org_unit_id = org_unit_id or public_demo_service.default_org_unit_id(project_id)
    # An interviewer or a death_reporter (register_death_context's predicate).
    _require_scope(user, project_id, site_id, org_unit_id, DEATH_REGISTERING_ROLES)
    if enforce_collection_gate:
        collection_gate.require_open(user, project_id, site_id, org_unit_id)
    public_demo_service.check_new_registration(user, project_id)
    cleaned = _clean_death_fields(fields, today=_project_today(project_id))
    _require_age_info(cleaned)
    unit = db.session.get(MasOrgUnit, uuid.UUID(str(org_unit_id))) if org_unit_id else None
    number, unique_id = _allocate_unique_id(unit.unit_code if unit else site_id)
    death = VaDeathRegister(
        project_id=project_id,
        site_id=site_id,
        org_unit_id=unit.org_unit_id if unit else None,
        death_number=number,
        unique_id=unique_id,
        **cleaned,
        captured_at=facade()._utcnow() if cleaned["latitude"] is not None else None,
        registered_by=user.user_id,
        source="register",
        client_death_id=client_death_id,
    )
    # Flag on: sealed before it is added, so the flags are right for open_case.
    register_pii_accessor.seal_new_row(death)
    cases.open_case(death, actor=user)
    _, found = death_identifiers.set_identifiers(
        death, user, identifiers or {}, reason_context="registration", enforce_required=True)
    if warnings is not None:
        warnings.extend(found)
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
        (e for e in facade().interviewer_context(user) if e["project_id"] == project_id and e["site_id"] == site_id),
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


def get_death(user: VaUsers, death_id: object, *, entries: list[dict] | None = None) -> VaDeathRegister:
    try:
        death = db.session.get(VaDeathRegister, uuid.UUID(str(death_id)))
    except ValueError:
        death = None
    if death is None or not training_scope.keeps_project(death.project_id):
        raise WebIntakeError("Death entry not found.", 404)
    try:
        _require_scope(user, death.project_id, death.site_id, death.org_unit_id, entries=entries)
    except WebIntakeError as exc:
        # Out of scope reads as not found: an id is not proof the case exists.
        if exc.status_code == 403:
            raise WebIntakeError("Death entry not found.", 404) from None
        raise
    # A public-demo account reaches only the deaths it registered (a direct
    # start registers its own): docs/policy/public-demo.md section 3.
    if user.is_public_demo and death.registered_by != user.user_id:
        raise WebIntakeError("Death entry not found.", 404)
    # A consent-withdrawn case is sealed: admin only (docs/policy/consent-withdrawal.md).
    if death.consent_withdrawn_at is not None and not user.is_admin():
        raise WebIntakeError("Death entry not found.", 404)
    # "Details pending" is its starter's (and supervisors') only (owner,
    # 2026-09-30, item 11); for anyone else it does not exist.
    if (
        death.status == "draft_identity"
        and death.started_by_user_id != user.user_id
        and not cases.is_interview_supervisor_for(user, death)
    ):
        raise WebIntakeError("Death entry not found.", 404)
    return death


def reporter_reaches(user: VaUsers, death: VaDeathRegister) -> bool:
    """Whether *death* is one *user* registered and a death_reporter grant of
    theirs still reaches (project, site and unit): the reporter's whole
    claim on a case. An interviewer's reach is ``get_death``'s, separate on
    purpose, so holding both roles never lets one lend the other its cases."""
    if death.registered_by != user.user_id:
        return False
    try:
        _require_scope(user, death.project_id, death.site_id, death.org_unit_id, _DEATH_REPORTER)
    except WebIntakeError:
        return False
    return True


_reporter_reaches = reporter_reaches  # the earlier name: this package and tests still use it


def interviewer_reaches(user: VaUsers, death: VaDeathRegister) -> bool:
    """Whether *user*'s interviewer grants reach *death*: the worklist's own
    scope (``_worklist_scope``), so it agrees with what ``GET /cases/<id>``
    shows. Decides whether a reply carries the interview's prefill and links
    (a user holding both roles gets the reporter-shaped body for a case they
    reach only as a reporter)."""
    scope = _worklist_scope(user)
    return scope is not None and bool(db.session.scalar(
        sa.select(sa.exists().where(scope, VaDeathRegister.death_id == death.death_id))
    ))
