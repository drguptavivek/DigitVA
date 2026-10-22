"""The shared case list: one row per death, report to coded (digitva-pt0s).

Policy: docs/policy/case-list-views.md. API: ``GET /api/v1/cases`` and
``GET /api/v1/cases/filter-options`` (docs/current-state/api-v1.md). Read-only.

Scope is the OR of three existing rules, evaluated in one SELECT, none new:
the interviewer's and (own registrations only) death reporter's reach
(``web_intake_service._worklist_scope``), ``supervised_case_condition`` and the
submissions ``Action.VIEW`` scope through the case's ``va_sid``. The
``supervision`` preset narrows to the supervised cases. Admin has no bypass in
the first two, so it reaches only the cases that have a submission.

Combined status (``combined_status_case``, one SQL CASE shared by the row, the
status filter and the counts; first match wins) from ``VaDeathRegister.status``
and ``VaSubmissionWorkflow.workflow_state``:

- register ``duplicate`` / ``cancelled`` / ``refused`` -> the same word;
- register ``submitted``: workflow ``not_codeable_by_*`` -> ``not_codeable``,
  ``consent_refused`` -> ``refused``, ``coder_finalized`` / ``reviewer_eligible``
  / ``reviewer_finalized`` / ``finalized_upstream_changed`` -> ``coded``,
  ``coding_in_progress`` / ``coder_step1_saved`` /
  ``reviewer_coding_in_progress`` -> ``in_coding``, any other state or no
  workflow row yet -> ``submitted_awaiting_coding``;
- ``in_progress`` and ``draft_identity`` -> ``interview_in_progress``;
- ``scheduled``, ``paused``, ``not_reachable`` -> ``interview_pending``
  (owner-pending default, open question 3);
- ``registered`` -> ``reported``.
The register state itself stays in each row as ``register_state`` (and the
``state`` filter), so a supervisor can still tell "not reachable" apart.

Field visibility is per row from labelled boolean columns (``can_name``,
``can_unit``, ``can_staff``, ``via_field``): the widest reach that allows a
field wins (deceased and staff names of admin, supervising roles and data
managers also need personal-data access, ``should_redact_pii``), and a hidden field is omitted from the payload, not blanked. The
defaults for the policy's open cells are in docs/policy/case-list-views.md.

``created_at`` is when the case row was created: the report time only for
``source = 'register'`` (row field ``reported_at``, omitted otherwise); for
``direct`` and ``odk`` it is the interview start or the sync.

Registration numbers (digitva-kzyp, docs/policy/death-registration-identifiers.md):
each row carries ``identifiers`` (``death_identifier_service.identifier_payloads``,
one query per page): ``{code, label, value}`` where the caller may see values
(``can_identifiers``, the row-level half of ``IDENTIFIER_VALUE_ROLES``: field
reach, supervision, admin, data manager, In-charge, project PI or
collaborator_pii; a row reached by coding or as a plain collaborator is
badge-only), else ``{code, label, present}``; ``can_edit_identifiers`` is
True where the caller may change that case's numbers now
(``web_intake_service.identifier_edit_condition``, a column of the same
statement). Filters: ``identifier=has|missing`` (+ ``identifier_type``), an
EXISTS on ``map_death_identifier`` for everyone who sees the badge, and
``identifier_number`` (exact, by blind index, only where the caller sees values).
"""
from __future__ import annotations

import base64
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import sqlalchemy as sa
from sqlalchemy.orm import aliased

from app import db
from app.models import (
    MapDeathIdentifier,
    MasDeathIdentifierType,
    MasOrgUnit,
    VaAccessRoles,
    VaAllocations,
    VaDeathRegister,
    VaProjectMaster,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUsers,
)
from app.models.va_selectives import VaAllocation
from app.models.va_web_intake import CASE_STATES, DEATH_SEX_VALUES
from app.services import org_grant_service, register_pii_accessor
from app.services.authz import (
    Action,
    Lens,
    lens_filter,
    resolve_grants,
    scope_filter,
    subtree_select,
)
from app.services.authz.actions import SUPERVISING_ROLES
from app.services.authz.supervision import supervised_case_condition
from app.services.death_identifier_rules import normalise as normalise_identifier
from app.services.death_identifier_service import (
    MAX_RAW_LENGTH,
    identifier_payloads,
    identifier_values_visible,
)
from app.services.viewer_pii_service import should_redact_pii
from app.services.visit_note import has_visit_note_condition
from app.services.web_intake_service import (
    _DEATH_REPORTER,
    WORKLIST_PAGE_DEFAULT,
    WORKLIST_PAGE_MAX,
    WebIntakeError,
    _has_candidate,
    _worklist_scope,
    identifier_edit_condition,
    identifier_field_scopes,
    supervision_attention_conditions,
    supervision_tiles,
)
from app.services.workflow.definition import (
    WORKFLOW_CODER_FINALIZED,
    WORKFLOW_CODER_STEP1_SAVED,
    WORKFLOW_CODING_IN_PROGRESS,
    WORKFLOW_CONSENT_REFUSED,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
    WORKFLOW_NOT_CODEABLE_BY_CODER,
    WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER,
    WORKFLOW_REVIEWER_CODING_IN_PROGRESS,
    WORKFLOW_REVIEWER_ELIGIBLE,
    WORKFLOW_REVIEWER_FINALIZED,
)
from app.utils import pii_crypto

PRESETS = ("deaths", "interview", "coding", "supervision")
COMBINED_STATUSES = (
    "reported", "interview_pending", "interview_in_progress", "submitted_awaiting_coding",
    "in_coding", "coded", "refused", "not_codeable", "duplicate", "cancelled",
)
_HIDDEN_BY_DEFAULT = ("duplicate", "cancelled")
SORTS = ("reported", "updated", "oldest")
ATTENTION = ("needs_decision", "overdue", "stuck", "total")
AGE_MAX = 150
#: Ceilings of the filter-options lists; a deployment past them needs search.
OPTIONS_MAX = 500
_STATUS_DEFAULTS = {
    "interview": ("reported", "interview_pending", "interview_in_progress"),
    "coding": ("submitted_awaiting_coding", "in_coding"),
}
_PRESET_SORT = {"deaths": "reported", "interview": "updated", "coding": "updated", "supervision": "oldest"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$", re.ASCII)
IDENTIFIER_FILTERS = ("has", "missing")
#: An identifier type code (identifier_type_service): lower-case, 2..32.
_TYPE_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$", re.ASCII)
#: Active identifier types read per page by a number search; the search walks
#: every page (keyset on the type id), so no type is ever left out.
_NUMBER_TYPES_CHUNK = 1000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_NOT_CODEABLE = (WORKFLOW_NOT_CODEABLE_BY_CODER, WORKFLOW_NOT_CODEABLE_BY_DATA_MANAGER)
_CODED = (
    WORKFLOW_CODER_FINALIZED, WORKFLOW_REVIEWER_ELIGIBLE, WORKFLOW_REVIEWER_FINALIZED,
    WORKFLOW_FINALIZED_UPSTREAM_CHANGED,
)
_IN_CODING = (WORKFLOW_CODING_IN_PROGRESS, WORKFLOW_CODER_STEP1_SAVED, WORKFLOW_REVIEWER_CODING_IN_PROGRESS)


def combined_status_case():
    """The one SQL CASE for the combined status (module docstring). Needs
    ``VaSubmissionWorkflow`` outer-joined on ``va_sid``."""
    register, workflow = VaDeathRegister.status, VaSubmissionWorkflow.workflow_state
    submitted = register == "submitted"
    return sa.case(
        (register.in_(("duplicate", "cancelled", "refused")), register),
        (sa.and_(submitted, workflow.in_(_NOT_CODEABLE)), "not_codeable"),
        (sa.and_(submitted, workflow == WORKFLOW_CONSENT_REFUSED), "refused"),
        (sa.and_(submitted, workflow.in_(_CODED)), "coded"),
        (sa.and_(submitted, workflow.in_(_IN_CODING)), "in_coding"),
        (submitted, "submitted_awaiting_coding"),
        (register.in_(("in_progress", "draft_identity")), "interview_in_progress"),
        (register.in_(("scheduled", "paused", "not_reachable")), "interview_pending"),
        (register == "registered", "reported"),
    )


# ---------------------------------------------------------------------------
# The request: parsed and validated at the boundary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaseFilters:
    project_id: str | None = None
    site_id: str | None = None
    org_unit_id: uuid.UUID | None = None
    statuses: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    dod_from: date | None = None
    dod_to: date | None = None
    reported_from: date | None = None
    reported_to: date | None = None
    sex: str | None = None
    age_min: int | None = None
    age_max: int | None = None
    attention: str | None = None
    visit_note: bool = False
    sort: str | None = None
    #: ``has`` / ``missing``: a registration number of any active type (or of
    #: ``identifier_type``); ``identifier_number``: the raw search text, exact.
    identifier: str | None = None
    identifier_type: str | None = None
    identifier_number: str | None = None


def _one(args, name: str) -> str | None:
    values = [v.strip() for v in args.getlist(name) if v and v.strip()]
    if len(values) > 1:
        raise WebIntakeError(f"{name} may be given once.")
    return values[0] if values else None


def _text(args, name: str) -> str | None:
    value = _one(args, name)
    if value is not None and len(value) > 64:
        raise WebIntakeError(f"{name} is not valid.")
    return value


def _date(args, name: str) -> date | None:
    value = _one(args, name)
    if value is None:
        return None
    try:
        if not _DATE_RE.match(value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise WebIntakeError(f"{name} must be an ISO date (YYYY-MM-DD).") from None


def _uuid(args, name: str) -> uuid.UUID | None:
    value = _one(args, name)
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        raise WebIntakeError(f"{name} must be an id.") from None


def _age(args, name: str) -> int | None:
    value = _one(args, name)
    if value is None:
        return None
    # Length first: int() on a huge digit string raises past Python's 4300-digit limit.
    if len(value) > 3 or not value.isascii() or not value.isdigit() or int(value) > AGE_MAX:
        raise WebIntakeError(f"{name} must be a whole number of years.")
    return int(value)


def _choices(args, name: str, allowed) -> tuple[str, ...]:
    """A repeatable parameter (``status=a&status=b``); comma lists also work."""
    values = [p.strip() for raw in args.getlist(name) for p in raw.split(",") if p.strip()]
    if any(v not in allowed for v in values):
        raise WebIntakeError(f"{name} has an unknown value.")
    return tuple(dict.fromkeys(values))


def _boolean(args, name: str) -> bool:
    value = (_one(args, name) or "").lower()
    if value not in ("", "0", "false", "no", "1", "true", "yes"):
        raise WebIntakeError(f"{name} must be true or false.")
    return value in ("1", "true", "yes")


def parse_query(args) -> dict:
    """``{preset, filters, cursor, limit}`` from a request's query string
    (*args*: a MultiDict). A malformed value is a 400 ``WebIntakeError`` that
    never repeats the value."""
    preset = _one(args, "preset") or "deaths"
    if preset not in PRESETS:
        raise WebIntakeError("preset must be one of " + ", ".join(PRESETS) + ".")
    sex = _one(args, "sex")
    if sex is not None and sex not in DEATH_SEX_VALUES:
        raise WebIntakeError("sex has an unknown value.")
    attention = _one(args, "attention")
    if attention is not None and attention not in ATTENTION:
        raise WebIntakeError("attention has an unknown value.")
    sort = _one(args, "sort")
    if sort is not None and sort not in SORTS:
        raise WebIntakeError("sort must be one of " + ", ".join(SORTS) + ".")
    identifier = _one(args, "identifier")
    if identifier is not None and identifier not in IDENTIFIER_FILTERS:
        raise WebIntakeError("identifier must be has or missing.")
    identifier_type = _one(args, "identifier_type")
    if identifier_type is not None and (identifier is None or not _TYPE_CODE_RE.match(identifier_type)):
        raise WebIntakeError("identifier_type is not valid.")
    identifier_number = _one(args, "identifier_number")
    if identifier_number is not None and len(identifier_number) > MAX_RAW_LENGTH:
        raise WebIntakeError("identifier_number is not valid.")
    limit_raw = _one(args, "limit")
    try:
        limit = int(limit_raw) if limit_raw is not None else WORKLIST_PAGE_DEFAULT
    except ValueError:
        raise WebIntakeError("limit must be a whole number.") from None
    filters = CaseFilters(
        project_id=_text(args, "project_id"), site_id=_text(args, "site_id"),
        org_unit_id=_uuid(args, "org_unit_id"),
        statuses=_choices(args, "status", COMBINED_STATUSES), states=_choices(args, "state", CASE_STATES),
        dod_from=_date(args, "dod_from"), dod_to=_date(args, "dod_to"),
        reported_from=_date(args, "reported_from"), reported_to=_date(args, "reported_to"),
        sex=sex, age_min=_age(args, "age_min"), age_max=_age(args, "age_max"),
        attention=attention,
        visit_note=_boolean(args, "visit_note"), sort=sort,
        identifier=identifier, identifier_type=identifier_type, identifier_number=identifier_number,
    )
    for low, high, what in ((filters.dod_from, filters.dod_to, "dod"), (filters.reported_from, filters.reported_to, "reported"),
                            (filters.age_min, filters.age_max, "age")):
        if low is not None and high is not None and low > high:
            raise WebIntakeError(f"{what}: the start is after the end.")
    return {"preset": preset, "filters": filters, "cursor": _one(args, "cursor"),
            "limit": max(1, min(limit, WORKLIST_PAGE_MAX))}


# ---------------------------------------------------------------------------
# Reach: scope and per-row visibility, as SQL
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Reach:
    """The caller's reach as ``VaDeathRegister`` conditions. ``scope`` is the
    OR of the three rules; the ``can_*`` expressions decide the fields."""

    scope: object
    supervised: object
    via_field: object
    can_name: object
    can_unit: object
    can_staff: object
    can_identifiers: object
    can_edit_identifiers: object


def _on_submission(condition):
    return sa.exists().where(VaSubmissions.va_sid == VaDeathRegister.va_sid, condition)


def _reach(user: VaUsers) -> _Reach:
    grants = resolve_grants(user)
    interviewer = _worklist_scope(user)
    reporter = _worklist_scope(user, None, _DEATH_REPORTER)
    # A reporter's reach is its own registrations only (``list_worklist``).
    if reporter is not None:
        reporter = sa.and_(reporter, VaDeathRegister.registered_by == user.user_id)
    field = [c for c in (interviewer, reporter) if c is not None]
    via_field = sa.or_(*field) if field else sa.false()
    oversees = any(
        g.role in SUPERVISING_ROLES or g.role == VaAccessRoles.project_pi for g in grants.grants if not g.virtual
    )
    supervised = supervised_case_condition(user) if oversees else sa.false()
    # scope_filter marks the request consulted by authz; it is also the
    # coder, reviewer, data manager and collaborator reach.
    submissions = scope_filter(user, Action.VIEW)
    via_submission = _on_submission(submissions)

    admin = sa.true() if grants.is_admin else sa.false()
    # Per caller, as gps_projects: one grant read, a constant in the statement.
    pii = sa.false() if should_redact_pii(user) else sa.true()
    dm_lens = _on_submission(lens_filter(user, Lens.DM))
    other_lenses = _on_submission(sa.or_(*(
        lens_filter(user, lens) for lens in (Lens.DM, Lens.VIEWER, Lens.SITE_PI_PAIR, Lens.PROJECT_PI_SITE)
    )))
    collaborator_pii = _on_submission(lens_filter(user, Lens.VIEWER, roles={VaAccessRoles.collaborator_pii}))
    # Registration-number values (decision 14): ASSIGNED field reach (the
    # interviewer grant a self-coding coder is implied confers none),
    # supervision, the PII lenses (data manager / In-charge / project PI) and
    # collaborator_pii; never a row reached by coding or a plain collaborator
    # alone.
    field_scopes = identifier_field_scopes(user)
    value_field = sa.or_(*(c for c in field_scopes if c is not None)) if any(
        c is not None for c in field_scopes) else sa.false()
    pi_lenses = _on_submission(sa.or_(*(
        lens_filter(user, lens) for lens in (Lens.DM, Lens.SITE_PI_PAIR, Lens.PROJECT_PI_SITE)
    )))
    return _Reach(
        scope=sa.or_(via_field, supervised, via_submission),
        supervised=supervised,
        via_field=via_field,
        # Names: field roles on their reach and collaborator_pii as always;
        # supervising roles and admin only with personal-data access
        # (owner, 2026-10-21: admin is a PII holder, with no scope bypass). A coder, reviewer,
        # plain collaborator, PI or data manager (through the submissions
        # scope alone) gets none.
        can_name=sa.or_(via_field, collaborator_pii, sa.and_(pii, sa.or_(admin, supervised))),
        # Everything but a row reached by coding alone.
        can_unit=sa.or_(admin, via_field, supervised, other_lenses),
        can_staff=sa.and_(pii, sa.or_(admin, supervised, dm_lens)),
        can_identifiers=sa.or_(admin, value_field, supervised, collaborator_pii, pi_lenses),
        can_edit_identifiers=identifier_edit_condition(user, field_scopes),
    )


# ---------------------------------------------------------------------------
# Filters, order and keyset cursors
# ---------------------------------------------------------------------------


def _identifier_presence(f: CaseFilters):
    """``identifier=has|missing``: the case holds a number of an active type of
    its project (of the type ``identifier_type`` names), or holds none. A
    case of a project with no such active type is neither (its badge shows
    nothing). EXISTS on ``map_death_identifier``; no value is read."""
    active = [MasDeathIdentifierType.is_active.is_(True), MasDeathIdentifierType.project_id == VaDeathRegister.project_id]
    if f.identifier_type:
        active.append(MasDeathIdentifierType.code == f.identifier_type)
    holds = sa.exists(
        sa.select(1).select_from(MapDeathIdentifier)
        .join(MasDeathIdentifierType, MasDeathIdentifierType.identifier_type_id == MapDeathIdentifier.identifier_type_id)
        .where(MapDeathIdentifier.death_id == VaDeathRegister.death_id, *active)
    )
    if f.identifier == "has":
        return holds
    return sa.and_(sa.exists(sa.select(1).select_from(MasDeathIdentifierType).where(*active)), ~holds)


def _identifier_number_match(user: VaUsers, reach: _Reach, f: CaseFilters):
    """``identifier_number``: cases holding exactly this number (normalised as
    on a write), found by blind index (``ix_map_death_identifier_type_bidx``)
    per active type, narrowed by ``project_id`` and ``identifier_type``. Only
    projects where the caller sees values count, and only rows where they see
    the value (``can_identifiers``); anywhere else the search matches nothing,
    never an error that says why. The number is never logged."""
    number = normalise_identifier(f.identifier_number)
    if number is None:
        return sa.false()
    active = [MasDeathIdentifierType.is_active.is_(True)]
    if f.project_id:
        active.append(MasDeathIdentifierType.project_id == f.project_id)
    if f.identifier_type:
        active.append(MasDeathIdentifierType.code == f.identifier_type)
    projects = set(db.session.scalars(sa.select(MasDeathIdentifierType.project_id).where(*active).distinct()))
    visible = identifier_values_visible(user, projects)
    if not visible:
        return sa.false()
    # Every active type of a visible project, a keyset page at a time: the
    # chunks are OR-ed, so a large deployment misses no type.
    matches, last = [], None
    while True:
        query = (sa.select(MasDeathIdentifierType.identifier_type_id)
                 .where(*active, MasDeathIdentifierType.project_id.in_(visible))
                 .order_by(MasDeathIdentifierType.identifier_type_id).limit(_NUMBER_TYPES_CHUNK))
        if last is not None:
            query = query.where(MasDeathIdentifierType.identifier_type_id > last)
        type_ids = db.session.scalars(query).all()
        if not type_ids:
            break
        last = type_ids[-1]
        pairs = [(type_id, pii_crypto.blind_index(type_id.bytes, number)) for type_id in type_ids]
        matches.append(sa.exists().where(
            MapDeathIdentifier.death_id == VaDeathRegister.death_id,
            sa.tuple_(MapDeathIdentifier.identifier_type_id, MapDeathIdentifier.value_blind_index).in_(pairs),
        ))
    if not matches:
        return sa.false()
    return sa.and_(reach.can_identifiers, sa.or_(*matches))


def _filter_conditions(user: VaUsers, reach: _Reach, preset: str, f: CaseFilters) -> list:
    """Every filter except status and attention, which counts ignore."""
    conditions = []
    if f.project_id:
        conditions.append(VaDeathRegister.project_id == f.project_id)
    if f.site_id:
        conditions.append(VaDeathRegister.site_id == f.site_id)
    if f.org_unit_id:
        # Filtering by a unit the caller cannot see would reveal membership: match nothing.
        conditions.append(sa.and_(reach.can_unit, VaDeathRegister.org_unit_id.in_(subtree_select({f.org_unit_id}))))
    if f.states:
        conditions.append(VaDeathRegister.status.in_(f.states))
    if f.dod_from:
        conditions.append(VaDeathRegister.date_of_death >= f.dod_from)
    if f.dod_to:
        conditions.append(VaDeathRegister.date_of_death <= f.dod_to)
    # The end day is inclusive; the bounds stay sargable on ix_..._created.
    # Dates are UTC days (owner-pending: the client's "last 30 days" is local).
    if f.reported_from:
        conditions.append(VaDeathRegister.created_at >= datetime.combine(f.reported_from, datetime.min.time(), UTC))
    if f.reported_to:
        conditions.append(
            VaDeathRegister.created_at < datetime.combine(f.reported_to + timedelta(days=1), datetime.min.time(), UTC)
        )
    if f.sex:
        conditions.append(VaDeathRegister.deceased_sex == f.sex)
    if f.age_min is not None:
        conditions.append(VaDeathRegister.age_years >= f.age_min)
    if f.age_max is not None:
        conditions.append(VaDeathRegister.age_years <= f.age_max)
    if f.identifier:
        conditions.append(_identifier_presence(f))
    if f.identifier_number:
        conditions.append(_identifier_number_match(user, reach, f))
    if f.visit_note:
        conditions.append(sa.and_(reach.supervised, sa.exists().where(
            VaSubmissions.va_sid == VaDeathRegister.va_sid, has_visit_note_condition(),
        )))
    return conditions


def _status_conditions(preset: str, f: CaseFilters, status) -> list:
    """The status filter; absent, the preset's default. An explicit status
    replaces the default, duplicate and cancelled exclusion included."""
    if f.statuses:
        return [status.in_(f.statuses)]
    if preset in _STATUS_DEFAULTS:
        return [status.in_(_STATUS_DEFAULTS[preset])]
    if preset == "deaths":
        return [status.not_in(_HIDDEN_BY_DEFAULT)]
    return []


def _attention_condition(preset: str, f: CaseFilters):
    if preset != "supervision":
        return None
    name = f.attention or "needs_decision"
    return None if name == "total" else supervision_attention_conditions()[name]


def _encode_cursor(sort: str, row) -> str:
    at = row.created_at if sort == "reported" else row.updated_at
    micros = (at - _EPOCH) // timedelta(microseconds=1)
    return base64.urlsafe_b64encode(f"{sort}.{micros}.{row.death_id}".encode()).decode().rstrip("=")


def _after_cursor(sort: str, raw: str):
    try:
        kind, micros, death_id = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("ascii").split(".", 2)
        at, death_uuid = _EPOCH + timedelta(microseconds=int(micros)), uuid.UUID(death_id)
    except (ValueError, OverflowError, UnicodeDecodeError):
        raise WebIntakeError("Invalid cursor.") from None
    if kind != sort:  # a cursor never crosses orders
        raise WebIntakeError("Invalid cursor.")
    column = VaDeathRegister.created_at if sort == "reported" else VaDeathRegister.updated_at
    keyset = sa.tuple_(column, VaDeathRegister.death_id)
    return keyset > (at, death_uuid) if sort == "oldest" else keyset < (at, death_uuid)


def _order(sort: str) -> tuple:
    if sort == "oldest":
        return VaDeathRegister.updated_at.asc(), VaDeathRegister.death_id.asc()
    column = VaDeathRegister.created_at if sort == "reported" else VaDeathRegister.updated_at
    return column.desc(), VaDeathRegister.death_id.desc()


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------


def _base_scope(preset: str, reach: _Reach):
    return reach.supervised if preset == "supervision" else reach.scope


def _row_conditions(user: VaUsers, reach: _Reach, preset: str, f: CaseFilters, status) -> list:
    """Scope and every filter of a listing, the one list the page and the
    export (``export_summary``) both apply."""
    conditions = [_base_scope(preset, reach), *_filter_conditions(user, reach, preset, f),
                  *_status_conditions(preset, f, status)]
    attention = _attention_condition(preset, f)
    if attention is not None:
        conditions.append(attention)
    return conditions


def _page_statement(user: VaUsers, preset: str, f: CaseFilters, cursor: str | None, limit: int,
                    with_names: bool = True):
    reach = _reach(user)
    status = combined_status_case()
    sort = f.sort or _PRESET_SORT[preset]
    conditions = _row_conditions(user, reach, preset, f, status)
    if cursor:
        conditions.append(_after_cursor(sort, cursor))

    registrant, starter, coder = aliased(VaUsers), aliased(VaUsers), aliased(VaUsers)
    alloc = aliased(VaAllocations)
    latest_coder = (
        sa.select(alloc.va_allocated_to)
        .where(alloc.va_sid == VaDeathRegister.va_sid, alloc.va_allocation_for == VaAllocation.coding,
               alloc.va_allocation_status == VaStatuses.active)
        .order_by(alloc.va_allocation_createdat.desc()).limit(1).scalar_subquery()
    )
    coder_name = sa.select(coder.name).where(coder.user_id == latest_coder).scalar_subquery()
    columns = [
        VaDeathRegister.death_id, VaDeathRegister.unique_id, VaDeathRegister.project_id, VaDeathRegister.site_id,
        VaDeathRegister.org_unit_id, VaDeathRegister.deceased_sex, VaDeathRegister.age_years,
        VaDeathRegister.date_of_death, VaDeathRegister.source, VaDeathRegister.created_at,
        VaDeathRegister.updated_at, VaDeathRegister.registered_by, VaDeathRegister.started_by_user_id,
        VaDeathRegister.has_location,
        VaDeathRegister.status.label("register_state"), status.label("status"),
        # Hidden values never leave the database: the CASE is NULL for them.
        # The sealed blob (name and fix) rides under the name's visibility
        # (via_field, the only reach that shows the fix, implies can_name);
        # ``list_cases`` opens it for the page's rows.
        sa.case((reach.can_name, VaDeathRegister.deceased_name)).label("deceased_name"),
        sa.case((reach.via_field, VaDeathRegister.latitude)).label("latitude"),
        sa.case((reach.via_field, VaDeathRegister.longitude)).label("longitude"),
        sa.case((reach.can_unit, sa.func.coalesce(MasOrgUnit.unit_name, VaSiteMaster.site_name))).label("unit_name"),
        sa.case((reach.can_staff, registrant.name)).label("reporter_name"),
        sa.case((reach.can_staff, starter.name)).label("interviewer_name"),
        sa.case((reach.can_staff, coder_name)).label("coder_name"),
        latest_coder.label("coder_id"),
        reach.can_name.label("can_name"), reach.can_unit.label("can_unit"),
        reach.can_staff.label("can_staff"), reach.via_field.label("via_field"),
        reach.can_identifiers.label("can_identifiers"),
        reach.can_edit_identifiers.label("can_edit_identifiers"),
    ]
    if with_names:
        columns += [
            sa.case((reach.can_name, VaDeathRegister.pii_sealed)).label("pii_sealed"),
            sa.case((reach.can_name, VaDeathRegister.pii_dek_wrapped)).label("pii_dek_wrapped"),
        ]
    if preset == "supervision":
        attention_sql = supervision_attention_conditions()
        columns += [
            VaDeathRegister.pending_flag, VaDeathRegister.next_visit_at, VaDeathRegister.va_sid,
            VaDeathRegister.duplicate_of_death_id, _has_candidate().label("other_complete_interview"),
            sa.case(
                (VaDeathRegister.pending_flag.is_not(None), "resolve_flag"),
                (_has_candidate(), "choose_interview"),
                (VaDeathRegister.status.in_(_HIDDEN_BY_DEFAULT), "reopen"),
                (attention_sql["overdue"], "overdue"),
                (attention_sql["stuck"], "stuck"),
            ).label("reason"),
        ]
    return (
        sa.select(*columns)
        .select_from(VaDeathRegister)
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == VaDeathRegister.org_unit_id)
        .outerjoin(VaSiteMaster, VaSiteMaster.site_id == VaDeathRegister.site_id)
        .outerjoin(registrant, registrant.user_id == VaDeathRegister.registered_by)
        .outerjoin(starter, starter.user_id == VaDeathRegister.started_by_user_id)
        .outerjoin(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaDeathRegister.va_sid)
        .where(*conditions)
        .order_by(*_order(sort))
        .limit(limit + 1)
    ), sort


def _counts_statement(user: VaUsers, preset: str, f: CaseFilters):
    """Rows per combined status over the scope and every filter but status
    and attention, in one aggregate query: the status tabs' numbers."""
    reach = _reach(user)
    status = combined_status_case()
    return (
        sa.select(
            *(sa.func.count().filter(status == name).label(name) for name in COMBINED_STATUSES),
            sa.func.count().label("total"),
        )
        .select_from(VaDeathRegister)
        .outerjoin(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaDeathRegister.va_sid)
        .where(_base_scope(preset, reach), *_filter_conditions(user, reach, preset, f))
    )


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _serialize(user: VaUsers, row, preset: str, show_location: bool, identifiers: list,
               register: dict | None = None) -> dict:
    # ``register``: the row's opened name and fix (``list_cases``); None when not opened.
    register = register or {}
    mine_reported = row.registered_by == user.user_id
    mine_started = row.started_by_user_id == user.user_id
    out = {
        "death_id": str(row.death_id),
        "unique_id": row.unique_id,
        "project_id": row.project_id,
        "site_id": row.site_id,
        "status": row.status,
        "register_state": row.register_state,
        "source": row.source,
        "age_years": row.age_years,
        "deceased_sex": row.deceased_sex,
        "date_of_death": _iso(row.date_of_death),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
        "registered_by_me": mine_reported,
        "started_by_me": mine_started,
        "identifiers": identifiers,
        "can_edit_identifiers": bool(row.can_edit_identifiers),
    }
    # created_at is the report time only for a register case (module docstring).
    if row.source == "register":
        out["reported_at"] = out["created_at"]
    if row.can_name and "deceased_name" in register:
        out["deceased_name"] = register["deceased_name"]
    if row.can_unit:
        out["org_unit_id"] = str(row.org_unit_id) if row.org_unit_id else None
        out["unit_name"] = row.unit_name
    # Staff names: the whole staff identity, else only the caller's own part.
    if row.can_staff:
        out.update(reporter_name=row.reporter_name, interviewer_name=row.interviewer_name,
                   coder_name=row.coder_name)
    else:
        for mine, key in ((mine_reported, "reporter_name"), (mine_started, "interviewer_name"),
                          (row.coder_id == user.user_id, "coder_name")):
            if mine:
                out[key] = user.name
    if show_location:
        out["latitude"] = register.get("latitude")
        out["longitude"] = register.get("longitude")
    if preset == "supervision":
        out.update(
            reason=row.reason, pending_flag=row.pending_flag, next_visit_at=_iso(row.next_visit_at),
            # Time waiting runs from the last change to the case.
            waiting_since=row.updated_at.isoformat(), va_sid=row.va_sid,
            duplicate_of_death_id=str(row.duplicate_of_death_id) if row.duplicate_of_death_id else None,
            other_complete_interview=bool(row.other_complete_interview),
        )
    return out


def _no_scope(user: VaUsers) -> bool:
    """The caller holds no grant: nothing to query (still consults authz)."""
    scope_filter(user, Action.VIEW)
    grants = resolve_grants(user)
    return not grants.is_admin and not grants.grants


def identifier_value_death_ids(user: VaUsers, death_ids) -> set[uuid.UUID]:
    """The subset of *death_ids* whose registration-number VALUES *user* sees:
    ``can_identifiers``, the list's own row rule, for callers that build a
    single case or another list (``identifier_payloads``). One query."""
    ids = list(death_ids)
    if not ids:
        return set()
    return set(db.session.scalars(
        sa.select(VaDeathRegister.death_id).where(
            VaDeathRegister.death_id.in_(ids), _reach(user).can_identifiers)
    ))


def case_in_scope(user: VaUsers, death_id: uuid.UUID) -> bool:
    """Whether the shared case list would list this case for *user* (their
    scope, not a field: the 404-or-403 test of a case-level action)."""
    if _no_scope(user):
        return False
    return bool(db.session.scalar(
        sa.select(sa.exists().where(VaDeathRegister.death_id == death_id, _reach(user).scope))
    ))


def _open_page(page, show_location: dict) -> dict:
    """``{death_id: {attr: value}}``: the deceased name of each row the caller
    may see by name (``can_name``) and the fix of each row in *show_location*,
    one unwrap per sealed row. A row is a query row, not an entity: it carries
    the blob (``pii_sealed``, ``pii_dek_wrapped``) only when ``can_name``, so a
    hidden row's blob never left the database and is not opened here."""
    opened = {}
    for with_fix in (False, True):
        rows = [
            SimpleNamespace(death_id=r.death_id, pii_sealed=r.pii_sealed, pii_dek_wrapped=r.pii_dek_wrapped,
                            deceased_name=r.deceased_name, latitude=r.latitude, longitude=r.longitude)
            for r in page if r.can_name and show_location[r.death_id] == with_fix
        ]
        only = ("deceased_name", "latitude", "longitude") if with_fix else ("deceased_name",)
        opened.update(register_pii_accessor.open_register_pii(rows, only=only))
    return opened


def list_cases(user: VaUsers, *, preset: str, filters: CaseFilters, cursor: str | None = None,
               limit: int = WORKLIST_PAGE_DEFAULT, with_identifiers: bool = True,
               identifier_projects: set | None = None, with_names: bool = True) -> dict:
    """``{"cases": [row, ...], "next_cursor": str | None}``: one page of the
    caller's cases for *preset*, hidden fields omitted per row. *limit* is
    clamped to ``WORKLIST_PAGE_MAX``. Empty scope is an empty page.

    Location (``latitude``/``longitude``) per policy decision 6, as
    ``worklist_page``: an organization project, and the caller has personal
    data access (``should_redact_pii``) or registered the case; and only on
    a row the caller's interviewer or reporter reach opens (coders hold PII
    grants but code masked). Never on the supervision preset. *with_identifiers*
    False skips the registration numbers (no query, no decryption);
    *identifier_projects* limits the decrypted values to rows of those projects
    (the export's audited set), the others stay badges. *with_names* False
    skips the deceased name and the location (both sealed): the blob is not
    selected and nothing is decrypted (the export has neither column).
    """
    if preset not in PRESETS:
        raise WebIntakeError("Unknown preset.")
    if _no_scope(user):
        return {"cases": [], "next_cursor": None}
    limit = max(1, min(int(limit), WORKLIST_PAGE_MAX))
    statement, sort = _page_statement(user, preset, filters, cursor, limit, with_names)
    rows = db.session.execute(statement).all()
    page = rows[:limit]
    org_projects = set()
    redact = True
    if with_names and preset != "supervision" and any(r.via_field and r.has_location for r in page):
        org_projects = org_grant_service.projects_with_org_tree({r.project_id for r in page})
        redact = should_redact_pii(user)
    # The export without number columns asks for none: nothing is decrypted.
    identifiers = identifier_payloads(
        user, page, values_for={r.death_id for r in page if r.can_identifiers
                    and (identifier_projects is None or r.project_id in identifier_projects)}
    ) if with_identifiers else {r.death_id: [] for r in page}
    show_location = {
        r.death_id: bool(with_names and r.via_field and r.has_location and r.project_id in org_projects
                         and (not redact or r.registered_by == user.user_id))
        for r in page
    }
    opened = _open_page(page, show_location) if with_names else {}
    cases = [
        _serialize(user, row, preset, show_location=show_location[row.death_id],
                   identifiers=identifiers[row.death_id], register=opened.get(row.death_id))
        for row in page
    ]
    return {"cases": cases, "next_cursor": _encode_cursor(sort, page[-1]) if len(rows) > limit else None}


def case_list_counts(user: VaUsers, *, preset: str, filters: CaseFilters) -> dict:
    """``{"counts": {status: n, ..., "total": n}}`` ignoring the status filter
    (duplicate and cancelled are counted in every preset), plus ``"tiles"``
    (``supervision_tiles`` over the supervised cases, every filter ignored)
    only for a caller with supervision scope."""
    zero = {name: 0 for name in (*COMBINED_STATUSES, "total")}
    if _no_scope(user):
        return {"counts": zero}
    # JIT compilation is most of these two seq scans' cost (704 -> 247 ms and
    # 304 -> 70 ms at 200k rows, docs/kb/case-list-query-plans.md): off for
    # them only. SET LOCAL lasts to the end of the transaction, so the
    # caller's value is put back; an error rolls the transaction back, which
    # drops the setting too.
    previous = db.session.scalar(sa.text("SELECT current_setting('jit')"))
    db.session.execute(sa.text("SET LOCAL jit = off"))
    counts = dict(db.session.execute(_counts_statement(user, preset, filters)).one()._mapping)
    result = {"counts": counts}
    supervised = _reach(user).supervised
    if not isinstance(supervised, sa.sql.elements.False_):
        result["tiles"] = supervision_tiles(supervised)
    db.session.execute(sa.text("SELECT set_config('jit', :previous, true)"), {"previous": previous})
    return result


def export_summary(user: VaUsers, *, preset: str, filters: CaseFilters) -> tuple[int, set[str]]:
    """``(row count, project ids)`` of the cases ``list_cases`` would page
    through for these arguments: one aggregate over the same scope and
    filters. The export's audit row and its header need both before the
    first byte is written."""
    if _no_scope(user):
        return 0, set()
    reach = _reach(user)
    count, projects = db.session.execute(
        sa.select(sa.func.count(), sa.func.array_agg(sa.distinct(VaDeathRegister.project_id)))
        .select_from(VaDeathRegister)
        .outerjoin(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaDeathRegister.va_sid)
        .where(*_row_conditions(user, reach, preset, filters, combined_status_case()))
    ).one()
    return count, set(projects or ())


def case_list_page(user: VaUsers, args) -> dict:
    """The ``GET /api/v1/cases`` reply: ``{cases, counts, [tiles,] next_cursor}``;
    ``counts`` and ``tiles`` only without a ``cursor`` (the first page)."""
    query = parse_query(args)
    page = list_cases(user, **query)
    # Counts and tiles are seq scans (docs/kb/case-list-query-plans.md): the
    # first page only; a client keeps them while it pages.
    counts = {} if query["cursor"] else case_list_counts(user, preset=query["preset"], filters=query["filters"])
    return {"cases": page["cases"], **counts, "next_cursor": page["next_cursor"]}


# ---------------------------------------------------------------------------
# Filter options
# ---------------------------------------------------------------------------


def filter_options(user: VaUsers) -> dict:
    """Projects, sites and units that appear in the caller's scoped
    cases, so an option never names anything outside the caller's reach. Units
    only on rows the caller may see a unit for. Each list holds at most ``OPTIONS_MAX``."""
    empty = {"projects": [], "sites": [], "units": []}
    if _no_scope(user):
        return empty
    reach = _reach(user)
    scoped = [reach.scope]
    pairs = db.session.execute(
        sa.select(VaDeathRegister.project_id, VaDeathRegister.site_id).where(*scoped).distinct().limit(OPTIONS_MAX)
    ).all()
    unit_ids = db.session.scalars(
        sa.select(VaDeathRegister.org_unit_id).where(*scoped, reach.can_unit, VaDeathRegister.org_unit_id.is_not(None))
        .distinct().limit(OPTIONS_MAX)
    ).all()
    projects = {p for p, _ in pairs}
    sites = {s for _, s in pairs}
    project_rows = db.session.execute(
        sa.select(VaProjectMaster.project_id, VaProjectMaster.project_name).where(VaProjectMaster.project_id.in_(projects))
        .order_by(VaProjectMaster.project_name)
    ).all() if projects else []
    site_names = dict(db.session.execute(
        sa.select(VaSiteMaster.site_id, VaSiteMaster.site_name).where(VaSiteMaster.site_id.in_(sites))
    ).all()) if sites else {}
    unit_rows = db.session.execute(
        sa.select(MasOrgUnit.org_unit_id, MasOrgUnit.project_id, MasOrgUnit.unit_name)
        .where(MasOrgUnit.org_unit_id.in_(unit_ids)).order_by(MasOrgUnit.unit_name)
    ).all() if unit_ids else []
    return {
        "projects": [{"project_id": pid, "project_name": name} for pid, name in project_rows],
        "sites": [{"project_id": p, "site_id": s, "site_name": site_names.get(s)} for p, s in sorted(pairs)],
        "units": [{"org_unit_id": str(uid), "project_id": pid, "unit_name": name} for uid, pid, name in unit_rows],
    }
