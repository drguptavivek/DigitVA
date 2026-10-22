"""Offline station onboarding and the signed station config (beads
digitva-gb8w.4, digitva-gb8w.8).

Contract docs/policy/offline-api-contract.md 3.8, 4.1, 6.6, 7 and 11; file
format docs/policy/offline-bundle-and-transfer.md 6.4. The consumer is
``VerifiedStationConfig::parse_and_verify`` in
desktop/crates/digitva-bundle/src/lib.rs; the bytes here are what it checks.

A station (an ``auth_devices`` row) is onboarded in three steps, each by an
admin, project PI or project-scoped data manager of the station's project
and each audited in ``auth_security_events``: record the custodian, set the
roster, issue a config. A config is **issued** only when a custodian is
recorded and the roster has an active member; issuing signs the file once
and stores it, so the browser download and the station's own
``GET /intake/station-config`` serve the same bytes (and one ETag) until the
next issue.

The file: line 1 is the RFC 8785 (JCS) canonical JSON payload with every
string NFC (``canonical_json``); line 2 is
``{"alg":"ed25519","sig":<b64url>,"signing_key_id":<16 hex>}`` over
``b"digitva-station-config-v1\\x00" || line1``, signed with the server key
in ``BUNDLE_SERVER_SIGNING_KEY_FILE``. Nothing here logs the key or a
custodian's contact.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import unicodedata
import uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from flask import current_app

from app import db
from app.models import (
    AuthDevice,
    AuthStationConfig,
    AuthStationCustodian,
    AuthStationRosterMember,
    MasOrgUnit,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaUsers,
)
from app.models.va_selectives import VaAccessRoles
from app.services import consent_service, identifier_type_service
from app.services import organization_service as org
from app.services.authz import resolve_grants
from app.services.authz.actions import SUPERVISING_ROLES
from app.services.cod_entry_mode import project_mode
from app.services.device_signing_service import compute_signing_key_id, decode_b64url
from app.services.pii_field_registry import sealed_field_ids
from app.services.security_event_service import record_security_event
from app.services.web_intake_service import WebIntakeError, _require_scope, interviewer_context
from app.utils import pii_crypto
from app.utils.phone import normalise_phone
from app.utils.va_form.va_form_02_formtyperesolution import va_get_form_type_code_from_form

log = logging.getLogger(__name__)

STATION_CONFIG_FORMAT_VERSION = 1
#: Rust ``STATION_CONFIG_SIG_DOMAIN``.
STATION_CONFIG_SIG_DOMAIN = b"digitva-station-config-v1\x00"
#: Contract 4.1 defaults; the roster's and custodian's ``designation`` is one of these codes.
DESIGNATIONS = (
    {"code": "medical_officer", "label": "Medical Officer"},
    {"code": "health_supervisor", "label": "Health Supervisor"},
    {"code": "health_worker", "label": "Health Worker / ANM / MPW"},
    {"code": "other", "label": "Other"},
)
_DESIGNATION_CODES = frozenset(d["code"] for d in DESIGNATIONS)
#: The server grants that back each roster role (contract 4.1; owner decision 10
#: for ``station_supervisor``: a supervising grant at that site).
ROSTER_ROLE_GRANTS = {
    "death_reporter": frozenset({VaAccessRoles.death_reporter}),
    "interviewer": frozenset({VaAccessRoles.interviewer}),
    "coder": frozenset({VaAccessRoles.coder}),
    "station_supervisor": SUPERVISING_ROLES,
}
#: ``signing_key_id`` of the published TEST key in tests/fixtures/station_config/
#: (its seed is public): ``server_signing_key`` refuses it outside TESTING.
FIXTURE_SIGNING_KEY_ID = "334b2b6b54b0d965"
#: The station coding mode each project mode is coded in (contract 4.3,
#: bundle spec 2.4 Q5); a project mode absent here has none, so the station
#: does not code that project: masked DORIS has no station workspace, and a
#: masked simple final needs the coder's Step 1, which the station's
#: unmasked workspaces never make.
STATION_CODING_MODES = {"unmasked_doris": "icd11_doris", "unmasked_simple": "icd10"}
MAX_ROSTER_MEMBERS = 50
MAX_ROLES_PER_MEMBER = 10
_JCS_MAX_INT = 2**53 - 1
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_CUSTODIAN_KEYS = frozenset({"name", "designation", "phone", "email", "onboarded_on"})
_MEMBER_KEYS = frozenset({"user_id", "designation", "roles", "active"})
_ROLE_KEYS = frozenset({"role", "site_id", "org_unit_id"})


class StationConfigError(Exception):
    """A refusal with an HTTP status, a contract code and optional ``fields``;
    the message is safe to show."""

    def __init__(self, message: str, code: str, status: int, fields: list[str] | None = None):
        super().__init__(message)
        self.code = code
        self.status = status
        self.fields = fields


def _bad(message: str, field: str) -> StationConfigError:
    return StationConfigError(message, "invalid_request", 400, fields=[field])


# ---------------------------------------------------------------------------
# Canonical JSON (contract 11) and signing
# ---------------------------------------------------------------------------


def _jcs(value) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if not -_JCS_MAX_INT <= value <= _JCS_MAX_INT:
            raise ValueError("integer outside the JCS safe range")
        return str(value)
    if isinstance(value, str):
        # json.dumps escapes exactly what JCS escapes (", \, and C0 controls,
        # with \b \t \n \f \r short forms and lowercase \u00xx otherwise).
        return json.dumps(unicodedata.normalize("NFC", value), ensure_ascii=False)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_jcs(item) for item in value) + "]"
    if isinstance(value, dict):
        entries = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("object keys must be text")
            nfc_key = unicodedata.normalize("NFC", key)
            if nfc_key in entries:
                raise ValueError("two keys are equal after NFC")
            entries[nfc_key] = item
        # JCS orders keys by UTF-16 code units; big-endian bytes compare the same way.
        ordered = sorted(entries, key=lambda k: k.encode("utf-16-be"))
        return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + _jcs(entries[k]) for k in ordered) + "}"
    raise ValueError(f"{type(value).__name__} has no canonical form (integers, text, booleans, null only)")


def canonical_json(value) -> bytes:
    """RFC 8785 bytes of *value* with every string and key NFC; integers in
    the 2^53 range only (no floats). ``ValueError`` for anything else."""
    return _jcs(value).encode("utf-8")


def _b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def parse_signing_key(text: str) -> Ed25519PrivateKey:
    """The key from its file text: a base64url 32-byte Ed25519 seed (the
    Rust ``StationSigningKey::from_base64url_secret`` form). ``ValueError``
    when malformed; the message never carries the text."""
    seed = decode_b64url((text or "").strip())
    if seed is None or len(seed) != 32:
        raise ValueError("The station config signing key must be a base64url 32-byte Ed25519 seed.")
    return Ed25519PrivateKey.from_private_bytes(seed)


def server_signing_key() -> Ed25519PrivateKey:
    """The configured server key, read once per process and path. 503
    ``station_config_unavailable`` when unset, unreadable or malformed, or
    (outside TESTING) when it is the published test key (the reason is
    logged, never the key)."""
    path = (current_app.config.get("BUNDLE_SERVER_SIGNING_KEY_FILE") or "").strip()
    unavailable = StationConfigError(
        "Station configs cannot be signed on this server yet.", "station_config_unavailable", 503)
    if not path:
        log.error("station config signing key not configured (BUNDLE_SERVER_SIGNING_KEY_FILE)")
        raise unavailable
    cache = current_app.extensions.setdefault("station_config_signing_keys", {})
    if path not in cache:
        try:
            with open(path, encoding="ascii") as handle:
                cache[path] = parse_signing_key(handle.read())
        except (OSError, UnicodeDecodeError, ValueError):
            log.error("station config signing key file is unreadable or malformed")
            raise unavailable from None
    if (not current_app.config.get("TESTING")
            and public_signing_key(cache[path])["signing_key_id"] == FIXTURE_SIGNING_KEY_ID):
        log.error("station config signing key is the published test key; generate a real one")
        raise unavailable
    return cache[path]


def public_signing_key(key: Ed25519PrivateKey) -> dict:
    """``server_signing_key`` of the payload: ``{signing_key_id, public}``."""
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return {"signing_key_id": compute_signing_key_id(raw), "public": _b64u(raw)}


def sign_station_config(payload: dict, key: Ed25519PrivateKey) -> str:
    """The two-line signed file of *payload*, LF-terminated, no CR or BOM."""
    return sign_two_line(payload, key, STATION_CONFIG_SIG_DOMAIN)


def sign_two_line(payload: dict, key: Ed25519PrivateKey, domain: bytes) -> str:
    """*payload* as canonical JSON on line 1 and the server signature over
    ``domain || line1`` on line 2: the station config and the bundle
    receipt (bundle spec 5.6) share this form."""
    line1 = canonical_json(payload)
    signature = key.sign(domain + line1)
    line2 = canonical_json({
        "alg": "ed25519", "sig": _b64u(signature),
        "signing_key_id": public_signing_key(key)["signing_key_id"],
    })
    return (line1 + b"\n" + line2 + b"\n").decode("utf-8")


def _rfc3339(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Lookups and authorization
# ---------------------------------------------------------------------------


def authorize(user, project_id: str) -> str:
    """Admin, project PI or project-scoped data manager of *project_id*
    (the identifier-type rule); 404 / 403 ``IdentifierTypeError`` otherwise."""
    return identifier_type_service.configuring_role(user, project_id)


def _station(project_id: str, device_id, *, lock: bool = False) -> AuthDevice:
    """The device *device_id* of *project_id*, else 404 (a device of another
    project is not found, alike)."""
    try:
        device_uuid = uuid.UUID(str(device_id))
    except ValueError:
        raise _bad("device_id must be a UUID.", "device_id") from None
    query = sa.select(AuthDevice).where(AuthDevice.device_id == device_uuid, AuthDevice.project_id == project_id)
    device = db.session.scalar(query.with_for_update() if lock else query)
    if device is None:
        raise StationConfigError("Station not found.", "not_found", 404)
    return device


def _live_station(project_id: str, device_id) -> AuthDevice:
    device = _station(project_id, device_id, lock=True)
    if device.revoked_at is not None:
        raise StationConfigError("This station has been revoked.", "device_revoked", 409)
    return device


def latest_config(device_id) -> AuthStationConfig | None:
    """The config in force for *device_id*: the newest issued."""
    return db.session.scalar(
        sa.select(AuthStationConfig)
        .where(AuthStationConfig.device_id == device_id)
        .order_by(AuthStationConfig.issued_at.desc(), AuthStationConfig.config_id.desc())
        .limit(1)
    )


def _roster_rows(device_id) -> list[tuple[AuthStationRosterMember, VaUsers]]:
    return db.session.execute(
        sa.select(AuthStationRosterMember, VaUsers)
        .join(VaUsers, VaUsers.user_id == AuthStationRosterMember.user_id)
        .where(AuthStationRosterMember.device_id == device_id)
        .order_by(VaUsers.user_number)
    ).all()


# ---------------------------------------------------------------------------
# Custodian
# ---------------------------------------------------------------------------


def _clean_name(value) -> str:
    if not isinstance(value, str):
        raise _bad("name must be text.", "name")
    name = unicodedata.normalize("NFC", value).strip()
    if not 1 <= len(name) <= 128 or any(unicodedata.category(ch) == "Cc" for ch in name):
        raise _bad("name must be 1 to 128 characters, without control characters.", "name")
    return name


def _clean_designation(value, field: str) -> str:
    if value not in _DESIGNATION_CODES:
        raise _bad(f"{field} must be one of {', '.join(sorted(_DESIGNATION_CODES))}.", field)
    return value


def _clean_custodian(body: dict) -> dict:
    if not isinstance(body, dict) or set(body) - _CUSTODIAN_KEYS:
        raise _bad("Send name, designation, phone, email and onboarded_on only.", "custodian")
    phone = body.get("phone")
    if phone in (None, ""):
        phone = None
    elif not isinstance(phone, str) or (phone := normalise_phone(phone)) is None:
        raise _bad("phone must be a 10-digit mobile number.", "phone")
    email = body.get("email")
    if email in (None, ""):
        email = None
    elif not isinstance(email, str) or len(email.strip()) > 254 or not _EMAIL_RE.fullmatch(email.strip()):
        raise _bad("email must be an email address.", "email")
    else:
        email = email.strip()
    if phone is None and email is None:
        raise _bad("Give the custodian's phone or email.", "phone")
    raw_date = body.get("onboarded_on")
    try:
        if not isinstance(raw_date, str) or not _DATE_RE.fullmatch(raw_date):
            raise ValueError
        onboarded_on = date.fromisoformat(raw_date)
    except ValueError:
        raise _bad("onboarded_on must be a date, YYYY-MM-DD.", "onboarded_on") from None
    if onboarded_on > datetime.now(UTC).date() + timedelta(days=1):
        raise _bad("onboarded_on cannot be in the future.", "onboarded_on")
    return {
        "name": _clean_name(body.get("name")),
        "designation": _clean_designation(body.get("designation"), "designation"),
        "phone": phone, "email": email, "onboarded_on": onboarded_on,
    }


def set_custodian(actor: VaUsers, project_id: str, device_id, body) -> AuthStationCustodian:
    """Record or replace the station's custodian; the caller verifies them
    and is recorded as ``verified_by``. Audited as ``station_custodian_set``
    with the changed field names only. Caller commits."""
    authorize(actor, project_id)
    device = _live_station(project_id, device_id)
    cleaned = _clean_custodian(body)
    row = db.session.get(AuthStationCustodian, device.device_id)
    if row is None:
        row = AuthStationCustodian(device_id=device.device_id)
        db.session.add(row)
        changed = sorted(cleaned)
    else:
        changed = sorted(k for k, v in cleaned.items() if getattr(row, k) != v)
    for key, value in cleaned.items():
        setattr(row, key, value)
    row.verified_by = actor.user_id
    row.updated_at = datetime.now(UTC)
    db.session.flush()
    record_security_event(
        user_id=None, actor_user_id=actor.user_id, event_type="station_custodian_set",
        detail={"device_id": str(device.device_id), "project_id": project_id, "changed": changed},
    )
    return row


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------


def _role_reaches(user: VaUsers, role: str, project_id: str, site_id: str, org_unit_id: str | None) -> bool:
    """Whether *user* holds the server grant behind roster *role* there. A
    null unit means the whole site, so it needs a project or site-wide grant
    (an ``interviewer_context`` entry with no unit list)."""
    grants = ROSTER_ROLE_GRANTS[role]
    if org_unit_id is None:
        return any(
            e["project_id"] == project_id and e["site_id"] == site_id and not e["org_units"]
            for e in interviewer_context(user, grants)
        )
    try:
        _require_scope(user, project_id, site_id, org_unit_id, grants)
    except WebIntakeError:
        return False
    return True


def _clean_roles(value, field: str, project_id: str) -> list[dict]:
    if not isinstance(value, list) or len(value) > MAX_ROLES_PER_MEMBER:
        raise _bad(f"{field} must be a list of at most {MAX_ROLES_PER_MEMBER} roles.", field)
    roles = []
    for index, raw in enumerate(value):
        here = f"{field}[{index}]"
        if not isinstance(raw, dict) or set(raw) - _ROLE_KEYS:
            raise _bad("A role is {role, site_id, org_unit_id}.", here)
        if raw.get("role") not in ROSTER_ROLE_GRANTS:
            raise _bad(f"role must be one of {', '.join(sorted(ROSTER_ROLE_GRANTS))}.", f"{here}.role")
        site_id = raw.get("site_id")
        if not isinstance(site_id, str) or not site_id.strip() or len(site_id) > 32:
            raise _bad("site_id is required.", f"{here}.site_id")
        unit = raw.get("org_unit_id")
        if unit is not None:
            try:
                unit = str(uuid.UUID(str(unit)))
            except ValueError:
                raise _bad("org_unit_id must be a UUID or null.", f"{here}.org_unit_id") from None
        role = {"role": raw["role"], "project_id": project_id, "site_id": site_id.strip(), "org_unit_id": unit}
        if role in roles:
            raise _bad("A role is listed twice.", here)
        roles.append(role)
    return sorted(roles, key=lambda r: (r["role"], r["site_id"], r["org_unit_id"] or ""))


def _unbacked_role(user: VaUsers, roles: list[dict]) -> int | None:
    """Index of the first of *roles* no server grant of *user* backs, else None."""
    # ponytail: one grant resolution per role (bounded by MAX_ROSTER_MEMBERS x
    # MAX_ROLES_PER_MEMBER, admin-only and rare); batch it if rosters grow.
    for index, role in enumerate(roles):
        if not _role_reaches(user, role["role"], role["project_id"], role["site_id"], role["org_unit_id"]):
            return index
    return None


def _check_grants(user: VaUsers, roles: list[dict], field: str) -> None:
    index = _unbacked_role(user, roles)
    if index is not None:
        role = roles[index]
        raise StationConfigError(
            f"This user holds no grant for {role['role']} at {role['site_id']}"
            + (" in that unit." if role["org_unit_id"] else " (whole site)."),
            "invalid_roster", 422, fields=[f"{field}[{index}]"],
        )


def _holds_project_grant(user: VaUsers, project_id: str) -> bool:
    """Whether *user* holds any live grant in *project_id* (full grants)."""
    return any(grant.project_id == project_id for grant in resolve_grants(user, native=False).grants)


def _check_role_places(cleaned: list[dict], project_id: str) -> None:
    """Every role's site is an active site of the project and its unit a unit
    of the project's tree, for active and inactive members alike: two
    queries for the whole roster."""
    roles = [(index, r_index, role) for index, member in enumerate(cleaned)
             for r_index, role in enumerate(member["roles"])]
    sites = set(db.session.scalars(sa.select(VaProjectSites.site_id).where(
        VaProjectSites.project_id == project_id, VaProjectSites.project_site_status == VaStatuses.active)))
    wanted_units = {uuid.UUID(role["org_unit_id"]) for _i, _r, role in roles if role["org_unit_id"]}
    units = {str(u) for u in db.session.scalars(sa.select(MasOrgUnit.org_unit_id).where(
        MasOrgUnit.project_id == project_id, MasOrgUnit.org_unit_id.in_(wanted_units)))} if wanted_units else set()
    for index, r_index, role in roles:
        here = f"members[{index}].roles[{r_index}]"
        if role["site_id"] not in sites:
            raise StationConfigError("This site is not an active site of the project.",
                                     "invalid_roster", 422, fields=[f"{here}.site_id"])
        if role["org_unit_id"] and role["org_unit_id"] not in units:
            raise StationConfigError("This organization unit is not in the project.",
                                     "invalid_roster", 422, fields=[f"{here}.org_unit_id"])


def _clean_members(body, project_id: str, on_roster: frozenset = frozenset()) -> list[dict]:
    """The roster body checked: shapes, users, designations, places, and the
    grants behind every active member's roles. An inactive member must still
    hold some live grant in the project, or already be on this roster
    (*on_roster*, user ids), so a roster cannot name an outsider."""
    if not isinstance(body, dict) or set(body) - {"members"} or not isinstance(body.get("members"), list):
        raise _bad("Send {\"members\": [...]}.", "members")
    members = body["members"]
    if len(members) > MAX_ROSTER_MEMBERS:
        raise _bad(f"A roster holds at most {MAX_ROSTER_MEMBERS} members.", "members")
    raw_ids = []
    for index, raw in enumerate(members):
        if not isinstance(raw, dict) or set(raw) - _MEMBER_KEYS:
            raise _bad("A member is {user_id, designation, roles, active}.", f"members[{index}]")
        try:
            raw_ids.append(uuid.UUID(str(raw.get("user_id"))))
        except ValueError:
            raise _bad("user_id must be a user's id.", f"members[{index}].user_id") from None
    if len(set(raw_ids)) != len(raw_ids):
        raise _bad("A user is listed twice.", "members")
    users = {u.user_id: u for u in db.session.scalars(sa.select(VaUsers).where(VaUsers.user_id.in_(raw_ids)))}
    cleaned = []
    for index, (raw, user_id) in enumerate(zip(members, raw_ids, strict=True)):
        field = f"members[{index}]"
        user = users.get(user_id)
        if user is None:
            raise _bad("No such user.", f"{field}.user_id")
        active = raw.get("active", True)
        if not isinstance(active, bool):
            raise _bad("active must be true or false.", f"{field}.active")
        if active and user.user_status != VaStatuses.active:
            raise _bad("This account is not active.", f"{field}.active")
        roles = _clean_roles(raw.get("roles"), f"{field}.roles", project_id)
        if active and not roles:
            raise _bad("An active member needs at least one role.", f"{field}.roles")
        cleaned.append({
            "user_id": user_id, "designation": _clean_designation(raw.get("designation"), f"{field}.designation"),
            "roles": roles, "active": active,
        })
    _check_role_places(cleaned, project_id)
    for index, member in enumerate(cleaned):
        user = users[member["user_id"]]
        if member["active"]:
            _check_grants(user, member["roles"], f"members[{index}].roles")
        elif member["user_id"] not in on_roster and not _holds_project_grant(user, project_id):
            raise StationConfigError("This user holds no grant in the project.", "invalid_roster", 422,
                                     fields=[f"members[{index}].user_id"])
    return cleaned


def set_roster(actor: VaUsers, project_id: str, device_id, body) -> list[AuthStationRosterMember]:
    """Replace the station's roster. Every role of an active member must be
    backed by that user's server grant (``ROSTER_ROLE_GRANTS``) on the
    station's project; roles are scoped to that project. Audited as
    ``station_roster_set`` with the user ids added, removed and changed.
    Caller commits."""
    authorize(actor, project_id)
    device = _live_station(project_id, device_id)
    existing = {
        row.user_id: row for row in db.session.scalars(
            sa.select(AuthStationRosterMember).where(AuthStationRosterMember.device_id == device.device_id))
    }
    cleaned = _clean_members(body, project_id, frozenset(existing))
    now = datetime.now(UTC)
    added, changed = [], []
    wanted = {m["user_id"] for m in cleaned}
    removed = sorted(str(uid) for uid in existing if uid not in wanted)
    for user_id in existing.keys() - wanted:
        db.session.delete(existing[user_id])
    rows = []
    for member in cleaned:
        row = existing.get(member["user_id"])
        if row is None:
            row = AuthStationRosterMember(device_id=device.device_id, user_id=member["user_id"])
            db.session.add(row)
            added.append(str(member["user_id"]))
        elif (row.designation, row.roles, row.active) != (member["designation"], member["roles"], member["active"]):
            changed.append(str(member["user_id"]))
        else:
            rows.append(row)
            continue
        row.designation, row.roles, row.active = member["designation"], member["roles"], member["active"]
        row.updated_by, row.updated_at = actor.user_id, now
        rows.append(row)
    db.session.flush()
    record_security_event(
        user_id=None, actor_user_id=actor.user_id, event_type="station_roster_set",
        detail={"device_id": str(device.device_id), "project_id": project_id,
                "added": sorted(added), "removed": removed, "changed": sorted(changed)},
    )
    return rows


# ---------------------------------------------------------------------------
# Payload and issue
# ---------------------------------------------------------------------------


def purge_client_ids(device: AuthDevice) -> list[str]:
    """Client ids this station must delete (contract 7): withdrawn consents'
    ``client_id`` and closed cases' ``client_death_id``, sorted, unique.

    Hook for digitva-athy: consent withdrawal does not exist yet, so the
    list is empty. When it lands, return the ids here and issue a new config
    on each withdrawal (the station reads only the issued file)."""
    return []


def _sealed_ids(project_id: str) -> list[str]:
    """The project's sealed set (contract 6.6): the union over the form
    types of its active forms; ``PII_FIELDS`` when it has none."""
    forms = db.session.scalars(
        sa.select(VaForms).where(VaForms.project_id == project_id, VaForms.form_status == VaStatuses.active)
    ).all()
    ids = set(sealed_field_ids(None))
    for code in {va_get_form_type_code_from_form(form) for form in forms}:
        ids |= sealed_field_ids(code)
    return sorted(ids)


def _org_unit_paths(project_id: str, unit_ids: list[str]) -> dict[str, str]:
    """``{org_unit_id: "District, Block, PHC"}``: active unit names from the
    top of the project tree down to each unit, ", " joined (the
    ``web_intake_service._org_path_names`` rule), in two queries for all."""
    if not unit_ids:
        return {}
    paths = dict(db.session.execute(sa.select(MasOrgUnit.org_unit_id, MasOrgUnit.path).where(
        MasOrgUnit.project_id == project_id,
        MasOrgUnit.org_unit_id.in_([uuid.UUID(u) for u in unit_ids]))).all())
    codes = {code for path in paths.values() for code in str(path).split(".")}
    names = {row["unit_code"]: row["unit_name"] for row in org.list_units_by_codes(project_id, codes)}
    return {
        str(unit_id): ", ".join(names[code] for code in str(path).split(".") if code in names)
        for unit_id, path in paths.items()
    }


def _form_policy(project_id: str) -> dict:
    """``form_options`` and ``translations`` of a ``projects[]`` entry: the
    project's form-options body exactly as ``GET /organization/<p>/form-options``
    serves it, and for each non-English locale it offers, the body
    ``GET /instruments/<code>/translations/<locale>`` serves (the same
    servable-locale gate as ``translations_response``). The station serves
    both as they are and its own copy of the composed definition, whose
    SHA-256 must equal ``form_options.definition_sha256``."""
    # Routes import services: import here, as instruments.py does.
    from app.routes.api.organization import form_options_payload, served_instrument_locales
    from app.services.instrument_translation_service import (
        BASE_LOCALE,
        export_translations,
        get_locale,
    )
    from app.services.web_form_instruments import is_servable

    project = db.session.get(VaProjectMaster, project_id)
    code, locales = served_instrument_locales(project)
    translations = {}
    for locale in sorted(locales - {BASE_LOCALE}):
        row = get_locale(code, locale)
        if row is not None and is_servable(row):
            translations[locale] = export_translations(code, locale)
    return {"form_options": form_options_payload(project), "translations": translations}


def _project_entry(project_id: str, roster: list[dict]) -> dict:
    """One ``projects[]`` entry. ``org_unit_sites`` maps each roster unit to
    the site of the role naming it (the first site in order when two do):
    the server has no site of its own for a unit, a site grant reaches the
    whole tree, so the roster is the only source. ``coding_mode`` is the
    station mode the project's coding mode locks it to, or null when the
    station must not code it (``STATION_CODING_MODES``)."""
    roles = [role for member in roster for role in member["roles"]]
    sites = sorted({r["site_id"] for r in roles})
    units = sorted({r["org_unit_id"] for r in roles if r["org_unit_id"]})
    unit_sites: dict[str, str] = {}
    for role in sorted(roles, key=lambda r: r["site_id"]):
        if role["org_unit_id"]:
            unit_sites.setdefault(role["org_unit_id"], role["site_id"])
    display = {
        "site_names": dict(db.session.execute(
            sa.select(VaSiteMaster.site_id, VaSiteMaster.site_name).where(
                VaSiteMaster.site_id.in_(sites), VaSiteMaster.site_name.isnot(None))).all()) if sites else {},
        "org_unit_paths": _org_unit_paths(project_id, units),
        "org_unit_sites": unit_sites,
    }
    project = db.session.get(VaProjectMaster, project_id)
    return {
        "project_id": project_id,
        "sites": sites,
        "org_units": units,
        # Omitted when empty, as the station's own writer does (serde
        # ``skip_serializing_if``); readers default a missing map to empty.
        **{key: value for key, value in display.items() if value},
        "identifier_types": [
            identifier_type_service.serialize_type(t, identifier_type_service.INTAKE_FIELDS)
            for t in identifier_type_service.active_types(project_id)
        ],
        "consent": consent_service.get_consent_config(project_id),
        "sealed_field_ids": _sealed_ids(project_id),
        "project_name": project.project_name,
        "coding_mode": STATION_CODING_MODES.get(project_mode(project)),
        **_form_policy(project_id),
    }


def build_payload(device: AuthDevice, *, config_id: uuid.UUID, issued_at: datetime, signing_key) -> dict:
    """Line 1 of the station config for *device* (bundle spec 6.4, contract
    4.1). 409 ``station_not_onboarded`` without a custodian or an active
    roster member; 422 ``invalid_roster`` naming in ``fields`` the user ids
    (``va_users.user_id``) whose grant has gone since the roster was set;
    503 ``station_config_unavailable`` without ``DEVICE_PUBLIC_URL``."""
    custodian = db.session.get(AuthStationCustodian, device.device_id)
    rows = _roster_rows(device.device_id)
    if custodian is None or not any(m.active and u.user_status == VaStatuses.active for m, u in rows):
        raise StationConfigError(
            "Record the custodian and at least one active roster member first.", "station_not_onboarded", 409)
    roster, stale = [], []
    for member, user in rows:
        active = member.active and user.user_status == VaStatuses.active
        if active and _unbacked_role(user, member.roles) is not None:
            stale.append(str(user.user_id))
        roster.append({
            "user_id": user.user_number, "name": user.name, "designation": member.designation,
            "roles": member.roles, "active": active,
        })
    if stale:
        raise StationConfigError(
            "A roster member no longer holds the grant behind a role; set the roster again.",
            "invalid_roster", 422, fields=stale)
    server_url = (current_app.config.get("DEVICE_PUBLIC_URL") or "").strip()
    if not server_url:
        raise StationConfigError("DEVICE_PUBLIC_URL is not configured on this server.",
                                 "station_config_unavailable", 503)
    verifier = db.session.get(VaUsers, custodian.verified_by)
    kem = pii_crypto.current_public_key()
    return {
        "station_config_format_version": STATION_CONFIG_FORMAT_VERSION,
        "config_id": str(config_id),
        "issued_at": _rfc3339(issued_at),
        "expires_at": _rfc3339(issued_at + timedelta(days=current_app.config["STATION_CONFIG_VALID_DAYS"])),
        "device_id": str(device.device_id),
        "server_url": server_url,
        "kem_public_key": {"key_id": kem.key_id, "public": kem.to_config()},
        "server_signing_key": public_signing_key(signing_key),
        "projects": [_project_entry(device.project_id, roster)],
        "custodian": {
            "name": custodian.name, "designation": custodian.designation,
            "phone": custodian.phone, "email": custodian.email,
            "onboarded_on": custodian.onboarded_on.isoformat(),
            "verified_by_user_id": verifier.user_number,
        },
        "designations": [dict(d) for d in DESIGNATIONS],
        "roster": roster,
        "purge": purge_client_ids(device),
    }


def _check_notice_texts(payload: dict) -> None:
    """A notice text that is not NFC would be changed by the canonical form
    and fail the station's ``text_sha256`` check: refuse to issue instead."""
    for project in payload["projects"]:
        for version in project["consent"]["notice_versions"]:
            if unicodedata.normalize("NFC", version["text"]) != version["text"]:
                raise StationConfigError(
                    "A consent notice text is not in Unicode NFC form; add a new notice version.",
                    "notice_not_nfc", 409)


def issue_config(actor: VaUsers, project_id: str, device_id) -> AuthStationConfig:
    """Build, sign and store a new config for the station; it becomes the
    one in force. Needs a live station with a signing key, a custodian and
    an active roster member whose grants still hold. Audited as
    ``station_config_issued``. Caller commits."""
    authorize(actor, project_id)
    device = _live_station(project_id, device_id)
    if device.signing_public_key is None:
        raise StationConfigError("This station has no signing key yet.", "station_not_onboarded", 409)
    key = server_signing_key()
    config_id = uuid.uuid4()
    # Full precision in the row (orders two issues in one second); the file
    # carries whole seconds (``_rfc3339``).
    issued_at = datetime.now(UTC)
    payload = build_payload(device, config_id=config_id, issued_at=issued_at, signing_key=key)
    _check_notice_texts(payload)
    try:
        signed = sign_station_config(payload, key)
    except (ValueError, UnicodeEncodeError):
        # A stored value with no canonical form (a float, an out-of-range
        # integer, a lone surrogate): refuse rather than 500.
        log.error("station config payload has no canonical form | device=%s", device.device_id)
        raise StationConfigError("The station config could not be put in canonical form; "
                                 "check the project's configuration.", "config_not_canonical", 409) from None
    row = AuthStationConfig(
        config_id=config_id, device_id=device.device_id, issued_at=issued_at,
        expires_at=issued_at + timedelta(days=current_app.config["STATION_CONFIG_VALID_DAYS"]),
        issued_by=actor.user_id, signed_text=signed,
        text_sha256=hashlib.sha256(signed.encode("utf-8")).hexdigest(),
    )
    db.session.add(row)
    db.session.flush()
    record_security_event(
        user_id=None, actor_user_id=actor.user_id, event_type="station_config_issued",
        detail={"device_id": str(device.device_id), "project_id": project_id, "config_id": str(config_id),
                "roster_members": len(payload["roster"]), "text_sha256": row.text_sha256},
    )
    log.info("station config issued | device=%s | config=%s", device.device_id, config_id)
    return row


def browser_config(actor: VaUsers, project_id: str, device_id) -> AuthStationConfig:
    """The config in force for the browser download; 404 when none issued."""
    authorize(actor, project_id)
    row = latest_config(_station(project_id, device_id).device_id)
    if row is None:
        raise StationConfigError("No station config has been issued for this station.", "not_found", 404)
    return row


def device_config(device_id) -> AuthStationConfig:
    """The config in force for the caller's own device (from its bearer
    session): 403 ``device_revoked``, 404 ``not_found`` when none issued."""
    device = db.session.get(AuthDevice, device_id)
    if device is None or device.revoked_at is not None:
        raise StationConfigError("This device has been revoked.", "device_revoked", 403)
    row = latest_config(device.device_id)
    if row is None:
        raise StationConfigError("No station config has been issued for this station.", "not_found", 404)
    return row


def serialize_station(actor: VaUsers, project_id: str, device_id) -> dict:
    """The admin view of one station: custodian, roster and the config in
    force (no file)."""
    authorize(actor, project_id)
    device = _station(project_id, device_id)
    custodian = db.session.get(AuthStationCustodian, device.device_id)
    config = latest_config(device.device_id)
    return {
        "device_id": str(device.device_id),
        "designations": [dict(d) for d in DESIGNATIONS],
        "custodian": None if custodian is None else {
            "name": custodian.name, "designation": custodian.designation, "phone": custodian.phone,
            "email": custodian.email, "onboarded_on": custodian.onboarded_on.isoformat(),
            "verified_by": str(custodian.verified_by),
        },
        "roster": [
            {"user_id": str(user.user_id), "user_number": user.user_number, "name": user.name,
             "designation": member.designation, "roles": member.roles, "active": member.active}
            for member, user in _roster_rows(device.device_id)
        ],
        "config": None if config is None else {
            "config_id": str(config.config_id), "issued_at": config.issued_at.isoformat(),
            "expires_at": config.expires_at.isoformat(), "text_sha256": config.text_sha256,
        },
    }
