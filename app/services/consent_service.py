"""Respondent (informant) DPDP consent: config, records, the intake gate.

Contract: docs/policy/offline-api-contract.md section 5 (5.2 config reply,
5.3 consent object, 5.4 registration consent). One validation path,
``record_consent``, serves ``POST /intake/deaths``, ``PATCH
/intake/deaths/<id>``, ``POST /intake/submissions`` and its revisions and
(digitva-gb8w.2) bundle ``consent`` records; one gate, ``gate``, serves
every HTTPS write of covered data (those, plus ``/drafts/<id>/submit``). A
project without settings, or with ``consent_required`` false, keeps today's
rules: the gate passes, though a ``consent`` object that is sent is still
validated and stored. Records never hold informant personal data, and
nothing here logs a notice text or a choice. The caller owns the
transaction (commit).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import unicodedata
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (
    MapConsentAudit,
    MasConsentNoticeVersion,
    MasProjectConsentSettings,
    VaConsentRecord,
    VaConsentRecordPurpose,
    VaDeathRegister,
    VaProjectMaster,
)
from app.models.va_consent import (
    CONSENT_CHANNELS,
    CONSENT_MODES,
    EXPIRY_ACTIONS,
    REFUSAL_BEHAVIOURS,
)
from app.services import identifier_type_service
from app.services.consent_notice_seed import (
    PROJECT_NAME_PLACEHOLDER,
    SEED_ALLOWED_MODES,
    SEED_PURPOSES,
    SEED_TEXT,
)
from app.services.web_intake_service import _device_time

log = logging.getLogger(__name__)

#: The 5.3 consent object's keys; any other key is refused.
CONSENT_KEYS = frozenset({
    "client_id", "client_draft_id", "notice_version_id", "notice_language", "notice_sha256",
    "decision", "purposes", "mode", "witness_present", "supersedes_client_id", "recorded_at",
})
#: A new notice version's covered fields when none are given: the informant
#: register fields (contract 5.5), the WHO respondent name (Id10007) and the
#: WHO answers the register prefills with family or address data: usual
#: residence (Id10055), place of death address (Id10057), father's and
#: mother's names (Id10061, Id10062; ``web_intake_service._prefill_from_death``),
#: and the register columns those names are prefilled from.
DEFAULT_COVERED_FIELDS = (
    "informant_name", "informant_phone", "informant_phone_2", "address",
    "address_house_street", "address_village_ward", "address_landmark",
    "father_name", "mother_name",
    "Id10007", "Id10055", "Id10057", "Id10061", "Id10062",
)
#: Bounds of the configuration a project may store.
MAX_VERSIONS_LISTED = 200
MAX_NOTICE_CHARS = 20_000
MAX_PURPOSES = 30
MAX_COVERED_FIELDS = 100
MAX_DISTRICTS = 500
_CONTACT_CHARS = 200
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")
_LANGUAGE = re.compile(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8}){0,3}")
_PURPOSE_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
_FIELD_ID = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,63}")
_CONTACT_SHAPE = {
    "deletion": ("email", "phone"),
    "mentor_institution": ("name", "email", "phone"),
    "central_team": ("email", "phone"),
}
_PERSON_KEYS = ("name", "email", "phone")


class ConsentError(Exception):
    """A consent refusal: ``code`` is the contract's machine code, ``fields``
    the inputs to fix (``["consent"]`` on intake). The message is safe to show."""

    def __init__(self, message: str, code: str = "consent_invalid", status_code: int = 422,
                 fields: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.fields = ["consent"] if fields is None else fields


# ---------------------------------------------------------------------------
# Config (contract 5.2)
# ---------------------------------------------------------------------------


def get_settings(project_id: str) -> MasProjectConsentSettings | None:
    return db.session.get(MasProjectConsentSettings, project_id)


def active_versions(project_id: str) -> list[MasConsentNoticeVersion]:
    """The project's non-retired notice versions, oldest first. Past
    ``MAX_VERSIONS_LISTED`` the oldest are the ones left out, never the newest."""
    return _newest_versions(MasConsentNoticeVersion.retired_at.is_(None), project_id=project_id)


def _newest_versions(*conditions, project_id: str) -> list[MasConsentNoticeVersion]:
    """The newest ``MAX_VERSIONS_LISTED`` versions matching *conditions*,
    returned by (version, language) ascending."""
    rows = db.session.scalars(
        sa.select(MasConsentNoticeVersion)
        .where(MasConsentNoticeVersion.project_id == project_id, *conditions)
        .order_by(MasConsentNoticeVersion.version.desc(), MasConsentNoticeVersion.language)
        .limit(MAX_VERSIONS_LISTED)
    )
    return sorted(rows, key=lambda v: (v.version, v.language))


def empty_contacts() -> dict:
    """The 5.2 contacts object with nothing configured."""
    return {
        **{key: dict.fromkeys(names, "") for key, names in _CONTACT_SHAPE.items()},
        "dpo": None,
        "districts": {},
    }


def serialize_version(row: MasConsentNoticeVersion) -> dict:
    return {
        "notice_version_id": str(row.notice_version_id),
        "version": row.version,
        "language": row.language,
        "text": row.text,
        "text_sha256": row.text_sha256,
        "purposes": row.purposes,
        "covered_fields": row.covered_fields,
        "allowed_modes": row.allowed_modes,
        "witness_allowed": row.witness_allowed,
    }


def get_consent_config(project_id: str) -> dict:
    """The ``GET /intake/consent-config`` reply. Every key is always present;
    a project without settings (or not requiring consent) answers
    ``consent_required: false`` with ``notice_versions: []``."""
    settings = get_settings(project_id)
    required = bool(settings and settings.consent_required)
    return {
        "project_id": project_id,
        "consent_required": required,
        "notice_versions": [serialize_version(v) for v in active_versions(project_id)] if required else [],
        "contacts": (settings.contacts if settings and settings.contacts else empty_contacts()),
        "retention": {
            "period_days": settings.retention_period_days if settings else None,
            "expiry_action": settings.expiry_action if settings else "erase",
        },
        "refusal_behaviour": settings.refusal_behaviour if settings else REFUSAL_BEHAVIOURS[0],
    }


# ---------------------------------------------------------------------------
# Records (contract 5.3)
# ---------------------------------------------------------------------------


def _uuid(value: object) -> uuid.UUID | None:
    """*value* as a UUID when it is UUID text, else None."""
    try:
        return uuid.UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _parse(consent: object) -> dict:
    """The consent object checked for shape (no database read). Raises
    ``consent_invalid`` naming the first problem, never echoing a value."""
    if not isinstance(consent, dict):
        raise ConsentError("consent must be an object.")
    unknown = sorted(set(consent) - CONSENT_KEYS)
    if unknown:
        raise ConsentError(f"consent has unknown keys: {', '.join(unknown)}.")
    parsed = {}
    for name in ("client_id", "notice_version_id"):
        parsed[name] = _uuid(consent.get(name))
        if parsed[name] is None:
            raise ConsentError(f"consent.{name} must be a UUID.")
    for name in ("client_draft_id", "supersedes_client_id"):
        value = consent.get(name)
        parsed[name] = _uuid(value)
        if value is not None and parsed[name] is None:
            raise ConsentError(f"consent.{name} must be a UUID or null.")
    language, sha = consent.get("notice_language"), consent.get("notice_sha256")
    if not isinstance(language, str) or not language:
        raise ConsentError("consent.notice_language is required.")
    if not isinstance(sha, str) or not _SHA256_HEX.fullmatch(sha.lower()):
        raise ConsentError("consent.notice_sha256 must be 64 hex characters.")
    parsed["notice_language"], parsed["notice_sha256"] = language, sha.lower()
    if consent.get("decision") not in ("granted", "refused"):
        raise ConsentError("consent.decision must be granted or refused.")
    parsed["decision"] = consent["decision"]
    purposes = consent.get("purposes")
    if not isinstance(purposes, list) or len(purposes) > MAX_PURPOSES:
        raise ConsentError("consent.purposes must be a list of every purpose of the notice version.")
    choices = {}
    for item in purposes:
        if (not isinstance(item, dict) or set(item) != {"code", "granted"} or not isinstance(item["code"], str)
                or not isinstance(item["granted"], bool) or item["code"] in choices):
            raise ConsentError("Each consent purpose is {code, granted}, once per code.")
        choices[item["code"]] = item["granted"]
    parsed["purposes"] = choices
    if consent.get("mode") not in CONSENT_MODES:
        raise ConsentError("consent.mode must be spoken, tap or signed.")
    parsed["mode"] = consent["mode"]
    if not isinstance(consent.get("witness_present"), bool):
        raise ConsentError("consent.witness_present must be true or false.")
    parsed["witness_present"] = consent["witness_present"]
    parsed["recorded_at"] = _device_time(consent.get("recorded_at"))
    if parsed["recorded_at"] is None:
        raise ConsentError("consent.recorded_at must be an RFC 3339 time with an offset.")
    return parsed


def _fingerprint(parsed: dict, death_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """SHA-256 of the parsed object, the case and the recorder: equal for a
    resend of the same consent, different for any other content. Internal
    only; clients never compute it."""
    body = {
        **{k: str(v) if isinstance(v, uuid.UUID) else v for k, v in parsed.items() if k != "recorded_at"},
        "purposes": sorted(parsed["purposes"].items()),
        "recorded_at": parsed["recorded_at"].isoformat(),
        "death_id": str(death_id),
        "recorded_by": str(user_id),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _check_against_version(parsed: dict, project_id: str) -> MasConsentNoticeVersion:
    """The stored notice version *parsed* names, checked: the project's own,
    not retired, language, hash, exactly its purposes, a decision that agrees
    with the required purposes, an allowed mode and witness rule."""
    version = db.session.get(MasConsentNoticeVersion, parsed["notice_version_id"])
    if version is None or version.project_id != project_id or version.retired_at is not None:
        raise ConsentError("consent.notice_version_id is not a current notice version of this project.")
    if parsed["notice_language"] != version.language:
        raise ConsentError("consent.notice_language does not match the notice version.")
    if not hmac.compare_digest(parsed["notice_sha256"], version.text_sha256):
        raise ConsentError("consent.notice_sha256 does not match the notice text.")
    codes = {p["code"] for p in version.purposes}
    if set(parsed["purposes"]) != codes:
        raise ConsentError("consent.purposes must answer every purpose of the notice version, and no other.")
    all_required = all(parsed["purposes"][p["code"]] for p in version.purposes if p["required"])
    if (parsed["decision"] == "granted") != all_required:
        raise ConsentError("consent.decision must be granted exactly when every required purpose is granted.")
    if parsed["mode"] not in version.allowed_modes:
        raise ConsentError("consent.mode is not allowed by the notice version.")
    if parsed["witness_present"] and not version.witness_allowed:
        raise ConsentError("consent.witness_present must be false for this notice version.")
    return version


def _by_client_id(client_consent_id: uuid.UUID) -> VaConsentRecord | None:
    return db.session.scalar(
        sa.select(VaConsentRecord).where(VaConsentRecord.client_consent_id == client_consent_id)
    )


def _replay(existing: VaConsentRecord, fingerprint: str) -> tuple[VaConsentRecord, bool]:
    if existing.content_sha256 != fingerprint:
        raise ConsentError("That consent client_id is already used for other content.", "conflict", 409)
    return existing, False


def record_consent(user, *, project_id: str, death, consent: object, client_draft_id: uuid.UUID | None,
                   channel: str) -> tuple[VaConsentRecord, bool]:
    """Validate *consent* (a 5.3 object) and append it to *death*'s records;
    returns ``(record, created)``. *client_draft_id* is the attempt the
    caller expects the object to name: ``None`` for a registration consent,
    the body's id on an interview upload. Idempotent on ``client_id``: the
    same content returns the stored record (``created`` False); other content
    is 409 ``conflict``. Every other refusal is 422 ``consent_invalid``. The
    insert runs in a savepoint, so a concurrent resend of the same id
    resolves the same way."""
    if channel not in CONSENT_CHANNELS:
        raise ValueError(f"unknown consent channel {channel!r}")
    parsed = _parse(consent)
    if parsed["client_draft_id"] != client_draft_id:
        raise ConsentError(
            "consent.client_draft_id must be null at registration." if client_draft_id is None
            else "consent.client_draft_id must equal the interview's client_draft_id."
        )
    fingerprint = _fingerprint(parsed, death.death_id, user.user_id)
    existing = _by_client_id(parsed["client_id"])
    if existing is not None:
        return _replay(existing, fingerprint)
    version = _check_against_version(parsed, project_id)
    supersedes = None
    if parsed["supersedes_client_id"] is not None:
        supersedes = _by_client_id(parsed["supersedes_client_id"])
        if supersedes is None or supersedes.death_id != death.death_id:
            raise ConsentError("consent.supersedes_client_id is not a consent of this case.")
    required = {p["code"]: bool(p["required"]) for p in version.purposes}
    record = VaConsentRecord(
        client_consent_id=parsed["client_id"],
        project_id=project_id,
        death_id=death.death_id,
        client_draft_id=parsed["client_draft_id"],
        notice_version_id=version.notice_version_id,
        notice_language=version.language,
        notice_sha256=version.text_sha256,
        event=parsed["decision"],
        mode=parsed["mode"],
        witness_present=parsed["witness_present"],
        supersedes_consent_id=supersedes.consent_id if supersedes else None,
        recorded_by=user.user_id,
        recorded_at=parsed["recorded_at"],
        channel=channel,
        content_sha256=fingerprint,
        purposes=[
            VaConsentRecordPurpose(purpose_code=code, required=required[code], granted=granted)
            for code, granted in sorted(parsed["purposes"].items())
        ],
    )
    try:
        with db.session.begin_nested():
            db.session.add(record)
    except IntegrityError:
        existing = _by_client_id(parsed["client_id"])
        if existing is None:
            raise
        return _replay(existing, fingerprint)
    log.info("consent recorded | project=%s | death=%s | event=%s | channel=%s | by=%s",
             project_id, death.death_id, record.event, channel, user.user_id)
    return record, True


# ---------------------------------------------------------------------------
# The intake gate (contract 5.3, 5.4)
# ---------------------------------------------------------------------------


def _filled(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, dict)):
        return bool(value)
    return bool(str(value).strip())


def has_covered_data(values: dict, covered_fields) -> bool:
    """Whether *values* (register fields or answers) fill any covered field."""
    return any(_filled(values.get(name)) for name in covered_fields)


def _required_covered_fields(project_id: str) -> set[str] | None:
    """The fields that need a granted consent in *project_id*: the union of
    its current notice versions' covered fields; None when consent is not
    required there (the gate is off)."""
    settings = get_settings(project_id)
    if not settings or not settings.consent_required:
        return None
    covered = set()
    for version in active_versions(project_id):
        covered.update(version.covered_fields)
    return covered or set(DEFAULT_COVERED_FIELDS)


def _latest_record(death_id: uuid.UUID, client_draft_id: uuid.UUID | None) -> VaConsentRecord | None:
    """The case's newest record for one attempt or (None) for its
    registration consent. One indexed read."""
    attempt = (VaConsentRecord.client_draft_id.is_(None) if client_draft_id is None
               else VaConsentRecord.client_draft_id == client_draft_id)
    return db.session.scalar(
        sa.select(VaConsentRecord)
        .where(VaConsentRecord.death_id == death_id, attempt)
        .order_by(VaConsentRecord.received_at.desc(), VaConsentRecord.recorded_at.desc())
        .limit(1)
    )


def _covered_by(record: VaConsentRecord) -> list:
    return db.session.get(MasConsentNoticeVersion, record.notice_version_id).covered_fields


def _refuse_missing() -> None:
    raise ConsentError(
        "A granted consent is required before the informant's details are saved.", "consent_required")


def _refuse_conflict() -> None:
    raise ConsentError(
        "The consent was refused, so the informant's details must be left empty.", "consent_conflict")


def _check_on_file(record: VaConsentRecord | None, filled: set[str]) -> None:
    """*filled* (covered fields with a value) against the consent that
    applies: none or not granted refuses; a granted one must name every
    filled field in its notice version's ``covered_fields`` (422
    ``consent_invalid``, ``fields`` the uncovered names, never values)."""
    if record is None:
        _refuse_missing()
    if record.event == "refused":
        _refuse_conflict()
    if record.event != "granted":
        _refuse_missing()
    uncovered = sorted(filled - set(_covered_by(record)))
    if uncovered:
        raise ConsentError("The consent's notice version does not cover: " + ", ".join(uncovered) + ".",
                           fields=uncovered)


def gate(user, *, project_id: str, death, client_draft_id: uuid.UUID | None, consent: object,
         values: dict, channel: str) -> None:
    """The one consent gate of every write of covered data: registration and
    its correction (*values* the register fields sent, *client_draft_id*
    None) and interview answers (*values* as received, before prefill, the
    attempt's *client_draft_id*). A *consent* sent is stored first
    (``record_consent``) and is the one that applies; a refused one with its
    version's covered data is 422 ``consent_conflict`` in any project.
    Without one, the attempt's own consent on file applies, else the case's
    registration consent (contract 5.4). Only where the project requires
    consent are filled covered fields checked against it
    (``_check_on_file``); elsewhere nothing is looked up. *death* may be
    None only with no *consent* (a draft without a case: nothing on file)."""
    record = None
    if consent is not None and death is None:
        raise ConsentError("A consent is recorded on a case; this interview has none.")
    if consent is not None:
        record, _ = record_consent(user, project_id=project_id, death=death, consent=consent,
                                   client_draft_id=client_draft_id, channel=channel)
        if record.event != "granted" and has_covered_data(values, _covered_by(record)):
            _refuse_conflict()
    covered = _required_covered_fields(project_id)
    filled = {name for name in covered or () if _filled(values.get(name))}
    if not filled:
        return
    if record is None and death is not None:
        # Intended (contract 5.4): attempt B never inherits attempt A's
        # consent, only its own or the case's registration consent.
        record = ((client_draft_id and _latest_record(death.death_id, client_draft_id))
                  or _latest_record(death.death_id, None))
    _check_on_file(record, filled)


def apply_registration_consent(user, death, consent: object, *, fields: dict, channel: str) -> None:
    """``POST /intake/deaths`` and ``PATCH /intake/deaths/<id>``: ``gate``
    for *death*'s register *fields* (those the request sets) with its
    registration consent, sent now or on file."""
    gate(user, project_id=death.project_id, death=death, client_draft_id=None, consent=consent,
         values=fields, channel=channel)


def apply_interview_consent(user, *, project_id: str, death, client_draft_id: uuid.UUID | None, consent: object,
                            answers: dict, channel: str) -> None:
    """``POST /intake/submissions``, ``/submissions/<va_sid>/revisions`` and
    ``/drafts/<id>/submit``: ``gate`` for *answers* (as received) on *death*
    (the case the interview landed on)."""
    gate(user, project_id=project_id, death=death, client_draft_id=client_draft_id, consent=consent,
         values=answers, channel=channel)


def strip_unconsented_answers(*, project_id: str, death, client_draft_id: uuid.UUID | None,
                              answers: dict) -> tuple[dict, bool]:
    """In-progress saves (``POST /intake/drafts/sync`` and the browser
    ``PATCH /intake/drafts/<id>``): *answers* with the covered fields removed
    unless the gate would take them; returns ``(answers, stripped)``.

    A draft save carries no ``consent`` object (that travels with the final
    upload), so the gate runs on what is on file: the attempt's own consent,
    else the case's registration consent. Where the gate would refuse the
    covered fields are dropped instead of the save refused: a phone saving a
    draft before its consent is uploaded must not fail, and no covered data is
    stored without a granted consent on file. ``consent_invalid`` (a granted
    consent whose notice version does not cover some fields) drops only the
    fields it names; ``consent_required`` and ``consent_conflict`` drop every
    covered field. The phone keeps its own copy and sends the fields with the
    final upload, where ``gate`` decides again. *stripped* is False, and
    *answers* is returned itself, when nothing is dropped.
    """
    try:
        gate(None, project_id=project_id, death=death, client_draft_id=client_draft_id, consent=None,
             values=answers, channel="device")
        return answers, False
    except ConsentError as exc:
        drop = set(exc.fields) if exc.code == "consent_invalid" else (_required_covered_fields(project_id) or set())
        kept = {name: value for name, value in answers.items() if name not in drop}
        return kept, len(kept) != len(answers)


# ---------------------------------------------------------------------------
# Management (admin, project PI, project data manager; browser only)
# ---------------------------------------------------------------------------


def configuring_role(user, project_id: str) -> str:
    """Who may configure consent: the identifier-type rule (admin, project
    PI, project-scoped data manager); 404 / 403 as there."""
    return identifier_type_service.configuring_role(user, project_id)


def _bad(message: str, field: str) -> ConsentError:
    return ConsentError(message, "invalid_request", 400, fields=[field])


def _storable(value: str) -> bool:
    """Whether PostgreSQL can store *value* as text and JSON: no NUL and no
    lone surrogate (which UTF-8 cannot encode)."""
    if "\x00" in value:
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _text(value: object, field: str, *, max_len: int = _CONTACT_CHARS) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > max_len or not _storable(value):
        raise _bad(f"{field} must be text of at most {max_len} characters.", field)
    return value.strip()


def _person(value: object, field: str, keys=_PERSON_KEYS) -> dict:
    if not isinstance(value, dict) or set(value) - set(keys):
        raise _bad(f"{field} must be an object of {', '.join(keys)}.", field)
    return {key: _text(value.get(key), f"{field}.{key}") for key in keys}


def clean_contacts(value: object) -> dict:
    """The 5.2 contacts object validated and filled to its full shape."""
    if not isinstance(value, dict) or set(value) - {*_CONTACT_SHAPE, "dpo", "districts"}:
        raise _bad("contacts must be an object of deletion, mentor_institution, central_team, dpo, districts.",
                   "contacts")
    cleaned = {key: _person(value.get(key) or {}, f"contacts.{key}", names) for key, names in _CONTACT_SHAPE.items()}
    cleaned["dpo"] = None if value.get("dpo") is None else _person(value["dpo"], "contacts.dpo")
    districts = value.get("districts") or {}
    if not isinstance(districts, dict) or len(districts) > MAX_DISTRICTS:
        raise _bad(f"contacts.districts must be an object of at most {MAX_DISTRICTS} units.", "contacts.districts")
    cleaned["districts"] = {}
    for unit_id, contact in districts.items():
        if _uuid(unit_id) is None:
            raise _bad("contacts.districts is keyed by the district org_unit_id.", "contacts.districts")
        cleaned["districts"][str(uuid.UUID(unit_id))] = _person(contact, "contacts.districts")
    return cleaned


def _audit(user, role: str, project_id: str, event: str, details: dict, notice_version_id=None) -> None:
    db.session.add(MapConsentAudit(
        project_id=project_id, event=event, actor_user_id=user.user_id, actor_role=role,
        notice_version_id=notice_version_id, details=details,
    ))


SETTINGS_KEYS = frozenset({"consent_required", "contacts", "retention", "refusal_behaviour"})


def serialize_settings(project_id: str) -> dict:
    """The configuring view: the 5.2 settings plus every notice version, retired included."""
    config = get_consent_config(project_id)
    settings = get_settings(project_id)
    config["consent_required"] = bool(settings and settings.consent_required)
    versions = _newest_versions(project_id=project_id)
    config["notice_versions"] = [
        {**serialize_version(v), "created_at": v.created_at.isoformat(),
         "retired_at": v.retired_at.isoformat() if v.retired_at else None,
         "approved_at": v.approved_at.isoformat() if v.approved_at else None}
        for v in versions
    ]
    return config


def _lock_settings(project_id: str) -> MasProjectConsentSettings | None:
    return db.session.get(MasProjectConsentSettings, project_id, with_for_update=True)


def save_settings(user, project_id: str, body: dict, *, _retried: bool = False) -> MasProjectConsentSettings:
    """Set any of ``consent_required``, ``contacts``, ``retention``
    (``{period_days, expiry_action}``) and ``refusal_behaviour``; audited
    with old and new values of what changed. Requiring consent needs at
    least one current notice version (400 otherwise). Two first saves at
    once: the one whose insert loses is applied again over the winner's row
    (once; ``_retried`` is internal)."""
    role = configuring_role(user, project_id)
    unknown = sorted(set(body) - SETTINGS_KEYS)
    if unknown:
        raise _bad(f"Unknown field: {', '.join(unknown)}.", unknown[0])
    settings = _lock_settings(project_id)
    before = {
        "consent_required": bool(settings and settings.consent_required),
        "contacts": settings.contacts if settings else empty_contacts(),
        "retention_period_days": settings.retention_period_days if settings else None,
        "expiry_action": settings.expiry_action if settings else "erase",
        "refusal_behaviour": settings.refusal_behaviour if settings else REFUSAL_BEHAVIOURS[0],
    }
    after = dict(before)
    if "consent_required" in body:
        if not isinstance(body["consent_required"], bool):
            raise _bad("consent_required must be true or false.", "consent_required")
        after["consent_required"] = body["consent_required"]
    if "contacts" in body:
        after["contacts"] = clean_contacts(body["contacts"])
    if "retention" in body:
        retention = body["retention"]
        if not isinstance(retention, dict) or set(retention) - {"period_days", "expiry_action"}:
            raise _bad("retention must be {period_days, expiry_action}.", "retention")
        days = retention.get("period_days")
        if days is not None and (isinstance(days, bool) or not isinstance(days, int) or not 1 <= days <= 36_500):
            raise _bad("retention.period_days must be 1..36500 or null.", "retention.period_days")
        action = retention.get("expiry_action", after["expiry_action"])
        if action not in EXPIRY_ACTIONS:
            raise _bad("retention.expiry_action must be erase or lock.", "retention.expiry_action")
        after["retention_period_days"], after["expiry_action"] = days, action
    if "refusal_behaviour" in body:
        if body["refusal_behaviour"] not in REFUSAL_BEHAVIOURS:
            raise _bad("refusal_behaviour must be interview_without_informant_data.", "refusal_behaviour")
        after["refusal_behaviour"] = body["refusal_behaviour"]
    if after["consent_required"] and not active_versions(project_id):
        raise _bad("Add a notice version before requiring consent.", "consent_required")
    changed = {k: {"old": before[k], "new": after[k]} for k in after if before[k] != after[k]}
    if settings is not None and not changed:
        return settings
    created = settings is None
    if created:
        settings = MasProjectConsentSettings(project_id=project_id)
    for name, value in after.items():
        setattr(settings, name, value)
    settings.updated_by = user.user_id
    if created:
        try:
            with db.session.begin_nested():
                db.session.add(settings)
        except IntegrityError:
            # A concurrent first save committed the row first (the primary key).
            if _retried:
                raise
            return save_settings(user, project_id, body, _retried=True)
    db.session.flush()
    _audit(user, role, project_id, "consent_settings_saved", changed)
    return settings


NOTICE_KEYS = frozenset({"version", "language", "text", "purposes", "covered_fields", "allowed_modes",
                         "witness_allowed"})


def create_notice_version(user, project_id: str, body: dict) -> MasConsentNoticeVersion:
    """Add a notice version: ``language``, ``text`` (stored and hashed
    exactly as sent), ``purposes`` (``[{code, label, required}]``),
    ``allowed_modes``, optional ``version`` (default: the project's highest
    plus one; a translation of an existing version passes its number),
    ``covered_fields`` (default ``DEFAULT_COVERED_FIELDS``) and
    ``witness_allowed`` (default true). Never edited afterwards. 409
    ``conflict`` when that version and language exist."""
    role = configuring_role(user, project_id)
    unknown = sorted(set(body) - NOTICE_KEYS)
    if unknown:
        raise _bad(f"Unknown field: {', '.join(unknown)}.", unknown[0])
    language, text = body.get("language"), body.get("text")
    if not isinstance(language, str) or not _LANGUAGE.fullmatch(language) or len(language) > 16:
        raise _bad("language must be a BCP 47 code such as en or hi.", "language")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_NOTICE_CHARS:
        raise _bad(f"text is required, at most {MAX_NOTICE_CHARS} characters.", "text")
    if not _storable(text):
        raise _bad("text must not contain NUL characters or unpaired surrogates.", "text")
    # Stored and hashed in NFC: the signed station config is NFC (contract 11),
    # so the station's text_sha256 check must see the same bytes.
    text = unicodedata.normalize("NFC", text)
    purposes = body.get("purposes")
    if not isinstance(purposes, list) or not 1 <= len(purposes) <= MAX_PURPOSES:
        raise _bad(f"purposes must list 1..{MAX_PURPOSES} purposes.", "purposes")
    cleaned_purposes = {}
    for item in purposes:
        if (not isinstance(item, dict) or set(item) != {"code", "label", "required"}
                or not isinstance(item["code"], str) or not _PURPOSE_CODE.fullmatch(item["code"])
                or not isinstance(item["required"], bool) or item["code"] in cleaned_purposes):
            raise _bad("Each purpose is {code (lower_snake), label, required}, once per code.", "purposes")
        label = _text(item["label"], "purposes.label")
        if not label:
            raise _bad("Each purpose needs a label.", "purposes")
        cleaned_purposes[item["code"]] = {"code": item["code"], "label": label, "required": item["required"]}
    covered = body.get("covered_fields", list(DEFAULT_COVERED_FIELDS))
    if (not isinstance(covered, list) or not 1 <= len(covered) <= MAX_COVERED_FIELDS
            or not all(isinstance(f, str) and _FIELD_ID.fullmatch(f) for f in covered)):
        raise _bad("covered_fields must list field names.", "covered_fields")
    modes = body.get("allowed_modes")
    if not isinstance(modes, list) or not modes or not set(modes) <= set(CONSENT_MODES):
        raise _bad("allowed_modes must be a non-empty subset of spoken, tap, signed.", "allowed_modes")
    witness = body.get("witness_allowed", True)
    if not isinstance(witness, bool):
        raise _bad("witness_allowed must be true or false.", "witness_allowed")
    version = body.get("version")
    if version is None:
        version = (db.session.scalar(sa.select(sa.func.max(MasConsentNoticeVersion.version))
                                     .where(MasConsentNoticeVersion.project_id == project_id)) or 0) + 1
    elif isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= 1_000_000:
        raise _bad("version must be a whole number from 1.", "version")
    settings = get_settings(project_id)
    row = MasConsentNoticeVersion(
        project_id=project_id, version=version, language=language, text=text,
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        purposes=[cleaned_purposes[c] for c in sorted(cleaned_purposes)],
        covered_fields=sorted(set(covered)),
        allowed_modes=[m for m in CONSENT_MODES if m in modes],
        witness_allowed=witness,
        contacts_snapshot=settings.contacts if settings and settings.contacts else empty_contacts(),
        created_by=user.user_id,
    )
    try:
        with db.session.begin_nested():
            db.session.add(row)
    except IntegrityError:
        raise ConsentError("That version already exists in that language.", "conflict", 409,
                           fields=["version"]) from None
    _audit(user, role, project_id, "consent_notice_created", {
        "version": version, "language": language, "text_sha256": row.text_sha256,
        "purposes": [p["code"] for p in row.purposes],
    }, notice_version_id=row.notice_version_id)
    return row


def seed_notice_versions(user, project_id: str) -> list[MasConsentNoticeVersion]:
    """Project Setup's "Seed from draft": version 1 in English and Hindi from
    ``consent_notice_seed`` (the policy draft), ``[PROJECT NAME]`` filled in,
    pending legal review. Only for a project with no notice version yet (409
    ``conflict``); a concurrent seed loses on the version unique key (409)."""
    configuring_role(user, project_id)
    if db.session.scalar(sa.select(MasConsentNoticeVersion.notice_version_id)
                         .where(MasConsentNoticeVersion.project_id == project_id).limit(1)):
        raise ConsentError("This project already has a notice. Edit it to save a new version.",
                           "conflict", 409, fields=[])
    name = db.session.get(VaProjectMaster, project_id).project_name
    return [
        create_notice_version(user, project_id, {
            "version": 1, "language": language,
            "text": SEED_TEXT[language].replace(PROJECT_NAME_PLACEHOLDER, name),
            "purposes": SEED_PURPOSES[language], "allowed_modes": SEED_ALLOWED_MODES,
        })
        for language in ("en", "hi")
    ]


def approve_notice_version(user, project_id: str, notice_version_id: str) -> MasConsentNoticeVersion:
    """Mark a notice version legally reviewed (owner 2026-10-22: admin only,
    once; audited). Approving an approved version changes nothing. 404 for a
    version of another project or an unknown id."""
    role = configuring_role(user, project_id)
    if not user.is_admin():
        raise ConsentError("Only an admin approves a notice version.", "forbidden", 403, fields=[])
    version_id = _uuid(notice_version_id)
    row = db.session.get(MasConsentNoticeVersion, version_id, with_for_update=True) if version_id else None
    if row is None or row.project_id != project_id:
        raise ConsentError("Notice version not found.", "not_found", 404, fields=[])
    if row.approved_at is None:
        row.approved_at = datetime.now(UTC)
        row.approved_by = user.user_id
        _audit(user, role, project_id, "consent_notice_approved",
               {"version": row.version, "language": row.language, "text_sha256": row.text_sha256},
               notice_version_id=row.notice_version_id)
    return row


# ---------------------------------------------------------------------------
# The browser interview (digitva-athy, owner 2026-10-22)
# ---------------------------------------------------------------------------


def draft_consent_status(draft) -> dict:
    """What the interview page needs before it opens the form: whether the
    project requires consent and the decision on file for the draft's case
    (its attempt's own, else the registration consent: the gate's order),
    with the covered fields that decision's version names (locked empty on a
    refusal). No informant data."""
    settings = get_settings(draft.project_id)
    required = bool(settings and settings.consent_required)
    record = None
    if draft.death_id is not None:
        record = ((draft.client_draft_id and _latest_record(draft.death_id, draft.client_draft_id))
                  or _latest_record(draft.death_id, None))
    return {
        "consent_required": required,
        "decision": record.event if record else None,
        "covered_fields": sorted(_covered_by(record)) if record else [],
        "client_draft_id": str(draft.client_draft_id) if draft.client_draft_id else None,
    }


def record_draft_consent(user, draft, consent: object) -> dict:
    """Store a consent the browser took before an interview (granted or
    refused) on the draft's case: ``record_consent`` with the draft's own
    ``client_draft_id`` (null for a browser draft, so the case's consent the
    submit gate then finds). Returns ``draft_consent_status``."""
    if draft.death_id is None:
        raise ConsentError("A consent is recorded on a case; this interview has none.")
    death = db.session.get(VaDeathRegister, draft.death_id)
    record_consent(user, project_id=draft.project_id, death=death, consent=consent,
                   client_draft_id=draft.client_draft_id, channel="web")
    db.session.flush()
    return draft_consent_status(draft)
