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

Collaborator register reach (owner, 2026-11-04, docs/policy/case-list-views.md):
a ``collaborator`` / ``collaborator_pii`` grant also reaches the register rows
of its grant area (``_collaborator_area``), pending deaths included, read-only:
the unit name to both, the name through a ``collaborator_pii`` grant only, and
no field, staff, identifier-value or edit right.

Opening a case (``can_open``, owner 2026-11-04): True where the row has a
submission the caller may view (``scope_filter(user, Action.VIEW)``, or
admin); the row then carries its ``va_sid``, and no other row of the
``deaths`` / ``interview`` / ``coding`` presets does. ``source`` filters on
``VaDeathRegister.source`` (``CASE_SOURCES``), counts included.

Submissions with no register row (``unregistered=1``, owner 2026-11-04): the
``deaths``, ``interview`` and ``coding`` presets (``UNREGISTERED_PRESETS``)
then also list the submissions of the caller's ``Action.VIEW`` scope that no
register row names (projects without a death register, ODK-only work),
retired ones and those of an inactive project-site left out, as a second
branch of one UNION ALL with ``death_id`` NULL, ``source`` ``odk``, the status from the workflow alone
(``unregistered_status_case``), and no name, location, register state,
reporter or registration numbers; ``va_sid`` always (they open by scope).
Paging keys on ``(sort time, row_key)``: the death id as text, or ``s:`` +
the submission id, in "C" collation. A register-only filter (state, date of
death, identifier, visit note) or a ``source`` without ``odk`` leaves them
out; ``reported_*`` bounds their submission day. Without the flag every
statement is the register-only one. The CSV export stays register-only.
With the flag those presets also leave out the register rows of an inactive
project-site (one rule with the unregistered rows; supervision, the phones
and flag-off callers keep them). ``interviewed=1`` keeps only cases with a
submission. ``stage_counts`` gives the Statistics Overview and Projects
numbers, each a tab's total, from the same conditions.

Waiting and overdue (``waiting``, shared with ``area_dashboard_service``):
a death waits for its interview (combined status ``reported``,
``interview_pending``, ``interview_in_progress``) since its date of death, or
the UTC day it was reported when that is missing; an interview waits for its
coding (``submitted_awaiting_coding``, ``in_coding``) since its submission day.
More than ``OVERDUE_INTERVIEW_DAYS`` / ``OVERDUE_CODING_DAYS`` before the
server's UTC today is overdue (exactly the threshold is not).
"""
from __future__ import annotations

import base64
import re
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import sqlalchemy as sa
from flask import current_app
from sqlalchemy.orm import aliased

from app import db
from app.models import (
    MapDeathIdentifier,
    MasDeathIdentifierType,
    MasOrgUnit,
    VaAccessRoles,
    VaAccessScopeTypes,
    VaAllocations,
    VaDeathRegister,
    VaFinalCodAuthority,
    VaForms,
    VaProjectMaster,
    VaProjectSites,
    VaSiteMaster,
    VaStatuses,
    VaSubmissions,
    VaSubmissionWorkflow,
    VaUsers,
    VaWebIntakeDraft,
)
from app.models.va_selectives import VaAllocation
from app.models.va_web_intake import CASE_SOURCES, CASE_STATES, DEATH_SEX_VALUES
from app.services import org_grant_service, register_pii_accessor, training_scope
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
from app.services.odk_retirement_service import submission_is_in_odk
from app.services.viewer_pii_service import PiiScope, pii_scope
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
OVERDUE = ("interview", "coding")
#: Days a death may wait for its interview, and an interview for its coding,
#: before it is overdue (owner, 2026-11-04; a per-project setting later if wanted).
OVERDUE_INTERVIEW_DAYS = 60
OVERDUE_CODING_DAYS = 15
_AWAITING_INTERVIEW = ("reported", "interview_pending", "interview_in_progress")
_AWAITING_CODING = ("submitted_awaiting_coding", "in_coding")
#: Most ``project_id`` values one request may name.
PROJECTS_MAX = 100
#: The case's submission and final-COD authority, joined on ``va_sid``. Aliased:
#: the reach's EXISTS subqueries on ``va_submissions`` must not correlate to it.
CASE_SUBMISSION = aliased(VaSubmissions, name="case_submission")
_CASE_AUTHORITY = aliased(VaFinalCodAuthority, name="case_authority")
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


def combined_status_case(register=VaDeathRegister.status):
    """The one SQL CASE for the combined status (module docstring). Needs
    ``VaSubmissionWorkflow`` outer-joined on ``va_sid``. *register*: the
    register state; an unregistered submission passes ``'submitted'``."""
    workflow = VaSubmissionWorkflow.workflow_state
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


def waiting(status, today: date | None = None, *, submission=CASE_SUBMISSION,
            registered: bool = True) -> SimpleNamespace:
    """``(interview, coding, days_waiting)`` as SQL for the overdue rules
    (module docstring) over the combined *status* CASE: the two overdue
    conditions and the whole days waited (NULL when the case waits for
    neither, or has no submission date). Needs *submission* (``CASE_SUBMISSION``
    unless given) and the workflow, for *status*, outer-joined on ``va_sid``.
    *today*: the server's UTC date unless given. *registered* False: a
    submission with no register row, which never waits for an interview;
    nothing then reads ``VaDeathRegister``, so it is not cross-joined in."""
    today = today or datetime.now(UTC).date()
    coding_since = sa.cast(submission.va_submission_date, sa.Date)
    awaiting_coding = status.in_(_AWAITING_CODING)
    day = sa.literal(today, sa.Date)
    # The same test as ``coding_since < day``, kept sargable on the submission-date index.
    coding = sa.and_(awaiting_coding, submission.va_submission_date
                     < datetime.combine(today - timedelta(days=OVERDUE_CODING_DAYS), datetime.min.time()))
    coding_days = (sa.and_(awaiting_coding, coding_since.is_not(None)), sa.func.greatest(day - coding_since, 0))
    if not registered:
        return SimpleNamespace(interview=sa.false(), coding=coding,
                               days_waiting=sa.type_coerce(sa.case(coding_days), sa.Integer))
    reported_day = sa.cast(sa.func.timezone("UTC", VaDeathRegister.created_at), sa.Date)
    interview_since = sa.func.coalesce(VaDeathRegister.date_of_death, reported_day)
    awaiting_interview = status.in_(_AWAITING_INTERVIEW)
    return SimpleNamespace(
        interview=sa.and_(awaiting_interview,
                          interview_since < today - timedelta(days=OVERDUE_INTERVIEW_DAYS)),
        coding=coding,
        # date - date is an integer in PostgreSQL. Never negative (a date of
        # death in the future waits 0 days); GREATEST per branch, since
        # GREATEST(NULL, 0) is 0 and a case waiting for neither stays NULL.
        days_waiting=sa.type_coerce(sa.case(
            (awaiting_interview, sa.func.greatest(day - interview_since, 0)),
            coding_days,
        ), sa.Integer),
    )


# ---------------------------------------------------------------------------
# The request: parsed and validated at the boundary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CaseFilters:
    #: ``project_id``, repeatable or a comma list: any of these projects.
    project_ids: tuple[str, ...] = ()
    site_id: str | None = None
    org_unit_id: uuid.UUID | None = None
    statuses: tuple[str, ...] = ()
    states: tuple[str, ...] = ()
    #: ``source``, repeatable or a comma list: ``register``, ``direct``, ``odk``.
    sources: tuple[str, ...] = ()
    dod_from: date | None = None
    dod_to: date | None = None
    reported_from: date | None = None
    reported_to: date | None = None
    #: The submission's UTC day; either one leaves out cases with no submission.
    submitted_from: date | None = None
    submitted_to: date | None = None
    #: ``interview`` / ``coding``: overdue by ``waiting``.
    overdue: str | None = None
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
    #: ``unregistered=1``: also list submissions with no register row
    #: (``UNREGISTERED_PRESETS`` only; module docstring), and leave out the
    #: register rows of an inactive project-site there.
    unregistered: bool = False
    #: ``interviewed=1``: only cases with a submission (a register row whose
    #: ``va_sid`` names one; every row with no register row has one).
    interviewed: bool = False


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


def _projects(args) -> tuple[str, ...]:
    """``project_id``, repeatable (``project_id=A&project_id=B``) or a comma
    list; each id at most 64 characters, at most ``PROJECTS_MAX`` of them.
    Not checked against the caller's projects: the scope already narrows an
    unreachable one to no rows."""
    values = [p.strip() for raw in args.getlist("project_id") for p in raw.split(",") if p.strip()]
    if any(len(v) > 64 for v in values) or len(values) > PROJECTS_MAX:
        raise WebIntakeError("project_id is not valid.")
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
    overdue = _one(args, "overdue")
    if overdue is not None and overdue not in OVERDUE:
        raise WebIntakeError("overdue must be interview or coding.")
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
        project_ids=_projects(args), site_id=_text(args, "site_id"),
        org_unit_id=_uuid(args, "org_unit_id"),
        statuses=_choices(args, "status", COMBINED_STATUSES), states=_choices(args, "state", CASE_STATES),
        sources=_choices(args, "source", CASE_SOURCES),
        dod_from=_date(args, "dod_from"), dod_to=_date(args, "dod_to"),
        reported_from=_date(args, "reported_from"), reported_to=_date(args, "reported_to"),
        submitted_from=_date(args, "submitted_from"), submitted_to=_date(args, "submitted_to"),
        overdue=overdue, sex=sex, age_min=_age(args, "age_min"), age_max=_age(args, "age_max"),
        attention=attention,
        visit_note=_boolean(args, "visit_note"), sort=sort,
        identifier=identifier, identifier_type=identifier_type, identifier_number=identifier_number,
        unregistered=_boolean(args, "unregistered"), interviewed=_boolean(args, "interviewed"),
    )
    for low, high, what in ((filters.dod_from, filters.dod_to, "dod"), (filters.reported_from, filters.reported_to, "reported"),
                            (filters.submitted_from, filters.submitted_to, "submitted"),
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
    can_open: object
    #: The same reach as predicates on ``VaSubmissions`` itself, for the rows
    #: of submissions with no register row: their scope (``Action.VIEW``),
    #: unit and staff visibility.
    submission_scope: object
    submission_unit: object
    submission_staff: object
    #: Where the caller has personal-data access (``pii_scope``): per row
    #: by project (digitva-ssg7.3), never once per caller.
    pii: PiiScope


def _on_submission(condition):
    return sa.exists().where(VaSubmissions.va_sid == VaDeathRegister.va_sid, condition)


def _collaborator_area(user: VaUsers, grants) -> object:
    """The register rows *grants*' ``collaborator`` / ``collaborator_pii``
    grants reach, with or without a submission: a project grant its project,
    a site grant its project-site, a unit grant the unit's subtree (one ltree
    select for every unit grant). Only rows on an active project-site, where
    the viewer lens stops too. Demo-training grants and public-demo accounts
    reach nothing here. ``sa.false()`` when no such grant applies."""
    if getattr(user, "is_public_demo", False):
        return sa.false()
    clauses, units = [], set()
    for grant in grants.of((VaAccessRoles.collaborator, VaAccessRoles.collaborator_pii), virtual=False):
        if grant.scope_type == VaAccessScopeTypes.project:
            clauses.append(VaDeathRegister.project_id == grant.project_id)
        elif grant.scope_type == VaAccessScopeTypes.project_site:
            clauses.append(sa.and_(VaDeathRegister.project_id == grant.project_id,
                                   VaDeathRegister.site_id == grant.site_id))
        elif grant.scope_type == VaAccessScopeTypes.org_unit and grant.org_unit_id:
            units.add(grant.org_unit_id)
    if units:
        clauses.append(VaDeathRegister.org_unit_id.in_(subtree_select(units)))
    if not clauses:
        return sa.false()
    return sa.and_(sa.or_(*clauses), active_project_site(VaDeathRegister.project_id, VaDeathRegister.site_id))


def active_project_site(project_id, site_id):
    """EXISTS: the ``(project_id, site_id)`` pair is active in ``va_project_sites``."""
    return sa.exists().where(
        VaProjectSites.project_id == project_id,
        VaProjectSites.site_id == site_id,
        VaProjectSites.project_site_status == VaStatuses.active,
    )


def _reach(user: VaUsers, *, assigned_only: bool = False) -> _Reach:
    grants = resolve_grants(user)
    interviewer = _worklist_scope(user, assigned_only=assigned_only)
    reporter = _worklist_scope(user, None, _DEATH_REPORTER)
    # A reporter's reach is its own registrations only (``list_worklist``).
    if reporter is not None:
        reporter = sa.and_(reporter, VaDeathRegister.registered_by == user.user_id)
    field = [c for c in (interviewer, reporter) if c is not None]
    via_field = sa.or_(*field) if field else sa.false()
    # A site_pi counts only as the In-charge (``ResolvedGrants.oversees``:
    # at a unit, not held by an active mentoring-institute member).
    oversees = any(
        grants.oversees(g) if g.role == VaAccessRoles.site_pi
        else g.role in SUPERVISING_ROLES or g.role == VaAccessRoles.project_pi
        for g in grants.grants if not g.virtual
    )
    # The Expo scope (training vs real work) bounds every reach below. Kept a
    # bare ``false`` when the caller supervises nothing: ``case_list_counts``
    # tests for it.
    training = training_scope.conditions(VaDeathRegister.project_id)
    supervised = sa.and_(supervised_case_condition(user), *training) if oversees else sa.false()
    # scope_filter marks the request consulted by authz; it is also the
    # coder, reviewer, data manager and collaborator reach.
    submissions = scope_filter(user, Action.VIEW, _grants=grants)
    via_submission = _on_submission(submissions)

    admin = sa.true() if grants.is_admin else sa.false()
    # Per row by project (digitva-ssg7.3): a PII grant in another project
    # does not count. One grant read; the project list is a constant.
    pii_projects = pii_scope(user, _grants=grants)
    pii = pii_projects.condition(VaDeathRegister.project_id)
    dm_lens_raw = lens_filter(user, Lens.DM, _grants=grants)
    dm_lens = _on_submission(dm_lens_raw)
    other_lenses_raw = sa.or_(*(
        lens_filter(user, lens, _grants=grants) for lens in (Lens.DM, Lens.VIEWER, Lens.SITE_PI_PAIR, Lens.PROJECT_PI_SITE)
    ))
    other_lenses = _on_submission(other_lenses_raw)
    pii_viewer_grants = replace(
        grants,
        grants=tuple(
            g for g in grants.grants
            if grants.is_pii_grant(g) and g.role == VaAccessRoles.collaborator_pii
        ),
    )
    collaborator_pii = (
        _on_submission(
            lens_filter(
                user,
                Lens.VIEWER,
                roles={VaAccessRoles.collaborator_pii},
                _grants=pii_viewer_grants,
            )
        )
        if pii_viewer_grants.grants
        else sa.false()
    )
    # Collaborators' register rows (module docstring): scope and the unit name
    # for both roles, the name only through a PII collaborator_pii grant.
    collaborator_area = _collaborator_area(user, grants)
    collaborator_pii_area = _collaborator_area(user, pii_viewer_grants) if pii_viewer_grants.grants else sa.false()
    # Registration-number values (decision 14): ASSIGNED field reach (the
    # interviewer grant a self-coding coder is implied confers none),
    # supervision, the PII lenses (data manager / In-charge / project PI) and
    # collaborator_pii; never a row reached by coding or a plain collaborator
    # alone.
    field_scopes = identifier_field_scopes(user)
    value_field = sa.or_(*(c for c in field_scopes if c is not None)) if any(
        c is not None for c in field_scopes) else sa.false()
    pi_lenses = _on_submission(sa.or_(*(
        lens_filter(user, lens, _grants=grants) for lens in (Lens.DM, Lens.SITE_PI_PAIR, Lens.PROJECT_PI_SITE)
    )))
    in_system_coder_grants = replace(
        grants,
        grants=tuple(
            g for g in grants.grants
            if grants.is_pii_grant(g)
            and g.scope_type == VaAccessScopeTypes.org_unit
            and g.role in (VaAccessRoles.coder, VaAccessRoles.reviewer)
        ),
    )
    in_system_coder_raw = (
        sa.or_(
            lens_filter(user, Lens.VIEW_CODER, _grants=in_system_coder_grants),
            lens_filter(user, Lens.VIEW_REVIEWER, _grants=in_system_coder_grants),
        )
        if in_system_coder_grants.grants
        else sa.false()
    )
    in_system_coder = _on_submission(in_system_coder_raw) if in_system_coder_grants.grants else sa.false()
    return _Reach(
        scope=sa.and_(sa.or_(via_field, supervised, via_submission, collaborator_area), *training),
        supervised=supervised,
        via_field=via_field,
        # Names: field roles on their reach and collaborator_pii as always;
        # supervising roles, in-system unit doctors, and admin only with
        # personal-data access (Tier 3 / Admin). Tier 1 (project-scope roles)
        # and Tier 2 (Mentoring Institute roles) get none.
        can_name=sa.or_(
            via_field,
            collaborator_pii,
            collaborator_pii_area,
            sa.and_(pii, sa.or_(admin, supervised, in_system_coder)),
        ),
        # Everything but a row reached by non-PII coding alone. Identifier
        # values below stay off the collaborator register reach.
        can_unit=sa.or_(admin, via_field, supervised, other_lenses, in_system_coder, collaborator_area),
        can_staff=sa.and_(pii, sa.or_(admin, supervised, dm_lens)),
        can_identifiers=sa.or_(
            admin,
            value_field,
            collaborator_pii,
            sa.and_(pii, sa.or_(supervised, pi_lenses, in_system_coder)),
        ),
        can_edit_identifiers=identifier_edit_condition(user, field_scopes),
        # The submission itself opens: its VIEW scope, or admin. An EXISTS on
        # the submission, so a pending death (no submission) is always false.
        can_open=_on_submission(sa.or_(admin, submissions)),
        # No field, supervision or collaborator-area reach applies to a
        # submission with no register row: the VIEW scope alone; the unit as
        # can_unit's lenses give it; staff as can_staff's.
        submission_scope=sa.or_(admin, submissions),
        submission_unit=sa.or_(admin, other_lenses_raw, in_system_coder_raw),
        submission_staff=sa.and_(pii_projects.condition(VaForms.project_id), sa.or_(admin, dm_lens_raw)),
        pii=pii_projects,
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
    if f.project_ids:
        active.append(MasDeathIdentifierType.project_id.in_(f.project_ids))
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


def _day_bounds(column, low: date | None, high: date | None, tz=None) -> list:
    """*column* within the UTC days *low* .. *high* (inclusive; either may be
    None), as a half-open range that stays sargable on the column's index.
    *tz*: ``UTC`` for an aware column, None for a naive UTC one
    (``va_submission_date``). The one period rule of the list, its counts and
    ``stage_counts``. Dates are UTC days (owner-pending: the client's "last
    30 days" is local)."""
    bounds = []
    if low:
        bounds.append(column >= datetime.combine(low, datetime.min.time(), tz))
    if high:
        bounds.append(column < datetime.combine(high + timedelta(days=1), datetime.min.time(), tz))
    return bounds


def _filter_conditions(user: VaUsers, reach: _Reach, preset: str, f: CaseFilters) -> list:
    """Every filter except status and attention, which counts ignore (the
    overdue filter included: counts honour it). Needs ``CASE_SUBMISSION``
    and the workflow outer-joined."""
    conditions = []
    if f.project_ids:
        conditions.append(VaDeathRegister.project_id.in_(f.project_ids))
    if f.site_id:
        conditions.append(VaDeathRegister.site_id == f.site_id)
    if f.unregistered and preset in UNREGISTERED_PRESETS:
        # The Statistics listing (owner, 2026-11-04): a deactivated
        # project-site's register rows leave with its unregistered ones.
        # Supervision, the phones and flag-off callers still list them.
        conditions.append(active_project_site(VaDeathRegister.project_id, VaDeathRegister.site_id))
    if f.interviewed:
        conditions.append(CASE_SUBMISSION.va_sid.is_not(None))
    if f.org_unit_id:
        # Filtering by a unit the caller cannot see would reveal membership: match nothing.
        conditions.append(sa.and_(reach.can_unit, VaDeathRegister.org_unit_id.in_(subtree_select({f.org_unit_id}))))
    if f.states:
        conditions.append(VaDeathRegister.status.in_(f.states))
    if f.sources:
        conditions.append(VaDeathRegister.source.in_(f.sources))
    if f.dod_from:
        conditions.append(VaDeathRegister.date_of_death >= f.dod_from)
    if f.dod_to:
        conditions.append(VaDeathRegister.date_of_death <= f.dod_to)
    conditions += _day_bounds(VaDeathRegister.created_at, f.reported_from, f.reported_to, UTC)
    conditions += _day_bounds(CASE_SUBMISSION.va_submission_date, f.submitted_from, f.submitted_to)
    if f.overdue:
        conditions.append(getattr(waiting(combined_status_case()), f.overdue))
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


def _encode_cursor(sort: str, row, key=None) -> str:
    """*key*: the row's tiebreaker, its ``death_id`` unless given (``row_key``)."""
    at = row.created_at if sort == "reported" else row.updated_at
    micros = (at - _EPOCH) // timedelta(microseconds=1)
    key = row.death_id if key is None else key
    return base64.urlsafe_b64encode(f"{sort}.{micros}.{key}".encode()).decode().rstrip("=")


def _decode_cursor(sort: str, raw: str) -> tuple[datetime, str]:
    """``(at, key)`` of a cursor of *sort*; a 400 for anything else."""
    try:
        kind, micros, key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("ascii").split(".", 2)
        at = _EPOCH + timedelta(microseconds=int(micros))
    except (ValueError, OverflowError, UnicodeDecodeError):
        raise WebIntakeError("Invalid cursor.") from None
    if kind != sort:  # a cursor never crosses orders
        raise WebIntakeError("Invalid cursor.")
    return at, key


def _after_cursor(sort: str, raw: str):
    at, key = _decode_cursor(sort, raw)
    try:
        death_uuid = uuid.UUID(key)
    except ValueError:
        raise WebIntakeError("Invalid cursor.") from None
    column = VaDeathRegister.created_at if sort == "reported" else VaDeathRegister.updated_at
    keyset = sa.tuple_(column, VaDeathRegister.death_id)
    return keyset > (at, death_uuid) if sort == "oldest" else keyset < (at, death_uuid)


#: The ``row_key`` prefix of a submission with no register row. A register
#: row's key is its ``death_id`` as text; under "C" collation every uuid
#: (hex digits, lowercase letters, dashes) sorts before ``s:``.
_SUBMISSION_KEY = "s:"


def _row_key_cursor(sort: str, raw: str) -> tuple[datetime, str]:
    """``(at, row_key)`` of a cursor of the listing with unregistered
    submissions: a death id cursor (also one from the register-only list)
    or ``s:`` + a submission id."""
    at, key = _decode_cursor(sort, raw)
    if key.startswith(_SUBMISSION_KEY):
        if not 2 < len(key) <= 2 + 64:
            raise WebIntakeError("Invalid cursor.")
        return at, key
    try:
        return at, str(uuid.UUID(key))
    except ValueError:
        raise WebIntakeError("Invalid cursor.") from None


def _after_key(sort: str, column, key_expr, at: datetime, key: str):
    """``(column, key_expr)`` past ``(at, key)`` in *sort*'s direction, with
    *key_expr* compared as "C" text. Written with ``column <= at`` (``>=``)
    first so the condition stays a range on *column*'s index."""
    key_expr = key_expr.collate("C")
    if sort == "oldest":
        return sa.and_(column >= at, sa.or_(column > at, key_expr > key))
    return sa.and_(column <= at, sa.or_(column < at, key_expr < key))


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
                    with_names: bool = True, reach: _Reach | None = None):
    """``(statement, sort)`` of one page (``limit + 1`` rows). With
    unregistered submissions (``_lists_unregistered``) the statement is the
    union of the register rows and theirs, each row with a ``row_key``."""
    reach = reach or _reach(user)
    status = combined_status_case()
    wait = waiting(status)
    sort = f.sort or _PRESET_SORT[preset]
    mixed = _lists_unregistered(preset, f)
    after = _row_key_cursor(sort, cursor) if mixed and cursor else None
    conditions = _row_conditions(user, reach, preset, f, status)
    if after:
        column = VaDeathRegister.created_at if sort == "reported" else VaDeathRegister.updated_at
        conditions.append(_after_key(sort, column, sa.cast(VaDeathRegister.death_id, sa.Text), *after))
    elif cursor:
        conditions.append(_after_cursor(sort, cursor))

    registrant, starter = aliased(VaUsers), aliased(VaUsers)
    latest_coder, coder_name = _latest_coder(VaDeathRegister.va_sid)
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
        reach.can_open.label("can_open"),
        sa.case((reach.can_open, VaDeathRegister.va_sid)).label("open_sid"),
        CASE_SUBMISSION.va_submission_date.label("submitted_at"),
        _coded_at().label("coded_at"),
        sa.case((wait.interview, "interview"), (wait.coding, "coding")).label("overdue"),
        wait.days_waiting.label("days_waiting"),
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
    if mixed:
        columns.append(sa.cast(VaDeathRegister.death_id, sa.Text).label("row_key"))
    statement = (
        sa.select(*columns)
        .select_from(VaDeathRegister)
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == VaDeathRegister.org_unit_id)
        .outerjoin(VaSiteMaster, VaSiteMaster.site_id == VaDeathRegister.site_id)
        .outerjoin(registrant, registrant.user_id == VaDeathRegister.registered_by)
        .outerjoin(starter, starter.user_id == VaDeathRegister.started_by_user_id)
        .outerjoin(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaDeathRegister.va_sid)
        .outerjoin(CASE_SUBMISSION, CASE_SUBMISSION.va_sid == VaDeathRegister.va_sid)
        .outerjoin(_CASE_AUTHORITY, _CASE_AUTHORITY.va_sid == VaDeathRegister.va_sid)
        .where(*conditions)
        .order_by(*_order(sort))
        .limit(limit + 1)
    )
    if not mixed:
        return statement, sort
    return _with_unregistered_rows(statement, reach, preset, f, sort, after, limit), sort


def _latest_coder(va_sid):
    """``(coder id, coder name)`` scalar subqueries: the user of the
    submission *va_sid*'s latest active coding allocation."""
    coder, alloc = aliased(VaUsers), aliased(VaAllocations)
    latest = (
        sa.select(alloc.va_allocated_to)
        .where(alloc.va_sid == va_sid, alloc.va_allocation_for == VaAllocation.coding,
               alloc.va_allocation_status == VaStatuses.active)
        .order_by(alloc.va_allocation_createdat.desc()).limit(1).scalar_subquery()
    )
    return latest, sa.select(coder.name).where(coder.user_id == latest).scalar_subquery()


def _coded_at():
    """When the final COD took authority; needs ``_CASE_AUTHORITY`` outer-joined."""
    return sa.case((
        sa.or_(_CASE_AUTHORITY.authoritative_final_assessment_id.is_not(None),
               _CASE_AUTHORITY.authoritative_reviewer_final_assessment_id.is_not(None)),
        sa.func.coalesce(_CASE_AUTHORITY.effective_at, _CASE_AUTHORITY.created_at),
    ))


# ---------------------------------------------------------------------------
# Submissions with no register row (``unregistered=1``)
# ---------------------------------------------------------------------------

#: The presets that list them on request; supervision stays one row per death.
UNREGISTERED_PRESETS = ("deaths", "interview", "coding")
#: Filters on register-only data: any of them set leaves these rows out.
_REGISTER_ONLY_FILTERS = ("states", "dod_from", "dod_to", "identifier", "identifier_number", "visit_note")


def _lists_unregistered(preset: str, f: CaseFilters) -> bool:
    """Whether the listing also holds submissions with no register row: asked
    for, a preset that lists them, ``odk`` among the sources (their source),
    and no register-only filter."""
    return (f.unregistered and preset in UNREGISTERED_PRESETS
            and (not f.sources or "odk" in f.sources)
            and not any(getattr(f, name) for name in _REGISTER_ONLY_FILTERS))


def unregistered_status_case():
    """The combined status of a submission with no register row: as a
    register row in state ``submitted``, from its workflow alone."""
    return combined_status_case(register=sa.literal("submitted"))


def _submission_age():
    """Whole years: the normalised age, else the form's own age field. The
    normalised value is numeric and may hold ``NaN`` (which sorts above
    every number) or junk: only ``0 <= years <= AGE_MAX`` is taken."""
    years = VaSubmissions.va_deceased_age_normalized_years
    return sa.func.coalesce(
        sa.case((sa.and_(years >= 0, years <= AGE_MAX), sa.cast(sa.func.floor(years), sa.Integer))),
        VaSubmissions.va_deceased_age,
    )


def _unregistered_conditions(reach: _Reach, f: CaseFilters, status) -> list:
    """Scope and every filter but status, on ``VaSubmissions`` (the
    statement's root, so the authz predicates apply to it directly) joined to
    ``VaForms`` and the workflow. No register row for the submission; not
    retired from ODK and on an active project-site (as the analytics counts
    the Statistics Overview shows, admin included); the caller's
    ``Action.VIEW`` scope; the Expo training scope on the form's project."""
    sub = VaSubmissions
    return [
        ~sa.exists().where(VaDeathRegister.va_sid == sub.va_sid),
        submission_is_in_odk(sub),
        active_project_site(VaForms.project_id, VaForms.site_id),
        reach.submission_scope,
        *training_scope.conditions(VaForms.project_id),
        *_unregistered_filters(reach, f, status),
    ]


def _unregistered_filters(reach: _Reach, f: CaseFilters, status) -> list:
    """The filters of ``_unregistered_conditions``. ``reported_*`` bounds the
    submission day, as ``submitted_*``: the interview is the first the system
    knows of such a death. ``interviewed`` holds for every such row."""
    sub = VaSubmissions
    conditions = []
    if f.project_ids:
        conditions.append(VaForms.project_id.in_(f.project_ids))
    if f.site_id:
        conditions.append(VaForms.site_id == f.site_id)
    if f.org_unit_id:
        conditions.append(sa.and_(reach.submission_unit, sub.org_unit_id.in_(subtree_select({f.org_unit_id}))))
    conditions += _day_bounds(sub.va_submission_date, f.reported_from, f.reported_to)
    conditions += _day_bounds(sub.va_submission_date, f.submitted_from, f.submitted_to)
    if f.overdue:
        conditions.append(getattr(waiting(status, submission=sub, registered=False), f.overdue))
    if f.sex:
        conditions.append(sa.func.lower(sub.va_deceased_gender) == f.sex)
    if f.age_min is not None:
        conditions.append(_submission_age() >= f.age_min)
    if f.age_max is not None:
        conditions.append(_submission_age() <= f.age_max)
    return conditions


def _with_unregistered_rows(register, reach: _Reach, preset: str, f: CaseFilters, sort: str,
                            after: tuple[datetime, str] | None, limit: int):
    """The page of *register* (the register rows' statement, ``limit + 1``
    rows in order, with ``row_key``) merged with the submissions with no
    register row: the same labelled columns (typed NULL where they have no
    value), each branch ordered and limited on its own index, then the union
    ordered by ``(sort column, row_key)`` in "C" collation and limited."""
    sub = VaSubmissions
    status = unregistered_status_case()
    wait = waiting(status, submission=sub, registered=False)
    conditions = [*_unregistered_conditions(reach, f, status), *_status_conditions(preset, f, status)]
    # Keyset and order on the raw naive column (its index); the row carries it as UTC.
    raw = sub.va_created_at if sort == "reported" else sub.va_updated_at
    key = sa.literal(_SUBMISSION_KEY, sa.Text) + sub.va_sid
    if after:
        at, after_key = after
        conditions.append(_after_key(sort, raw, key, at.astimezone(UTC).replace(tzinfo=None), after_key))
    latest_coder, coder_name = _latest_coder(sub.va_sid)
    values = {
        "unique_id": sub.va_uniqueid_masked,
        "project_id": VaForms.project_id,
        "site_id": VaForms.site_id,
        "org_unit_id": sub.org_unit_id,
        "deceased_sex": sa.func.lower(sub.va_deceased_gender),
        "age_years": _submission_age(),
        "source": sa.literal("odk", sa.String),
        "created_at": sa.func.timezone("UTC", sub.va_created_at),
        "updated_at": sa.func.timezone("UTC", sub.va_updated_at),
        "has_location": sa.false(),
        "status": status,
        "unit_name": sa.case((reach.submission_unit, sa.func.coalesce(MasOrgUnit.unit_name, VaSiteMaster.site_name))),
        "interviewer_name": sa.case((reach.submission_staff, sub.va_data_collector)),
        "coder_name": sa.case((reach.submission_staff, coder_name)),
        "coder_id": latest_coder,
        "can_name": sa.false(),
        "can_unit": reach.submission_unit,
        "can_staff": reach.submission_staff,
        "via_field": sa.false(),
        "can_identifiers": sa.false(),
        "can_edit_identifiers": sa.false(),
        # In scope by Action.VIEW, so the submission always opens.
        "can_open": sa.true(),
        "open_sid": sub.va_sid,
        "submitted_at": sub.va_submission_date,
        "coded_at": _coded_at(),
        "overdue": sa.case((wait.interview, "interview"), (wait.coding, "coding")),
        "days_waiting": wait.days_waiting,
        "row_key": key,
    }
    columns = [
        (values[c.key] if c.key in values else sa.cast(sa.null(), c.type)).label(c.key)
        for c in register.selected_columns
    ]
    direction = sa.asc if sort == "oldest" else sa.desc
    submissions = (
        sa.select(*columns)
        .select_from(sub)
        .join(VaForms, VaForms.form_id == sub.va_form_id)
        .outerjoin(MasOrgUnit, MasOrgUnit.org_unit_id == sub.org_unit_id)
        .outerjoin(VaSiteMaster, VaSiteMaster.site_id == VaForms.site_id)
        .outerjoin(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == sub.va_sid)
        .outerjoin(_CASE_AUTHORITY, _CASE_AUTHORITY.va_sid == sub.va_sid)
        .where(*conditions)
        .order_by(direction(raw), direction(sub.va_sid.collate("C")))
        .limit(limit + 1)
    )
    cases = sa.union_all(
        sa.select(register.subquery("register_rows")), sa.select(submissions.subquery("submission_rows")),
    ).subquery("cases")
    column = cases.c.created_at if sort == "reported" else cases.c.updated_at
    return (
        sa.select(cases)
        .order_by(direction(column), direction(cases.c.row_key.collate("C")))
        .limit(limit + 1)
    )


def _unregistered_counts_statement(reach: _Reach, f: CaseFilters):
    """``_counts_statement`` for the submissions with no register row."""
    status = unregistered_status_case()
    return (
        sa.select(
            *(sa.func.count().filter(status == name).label(name) for name in COMBINED_STATUSES),
            sa.func.count().label("total"),
        )
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .outerjoin(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .where(*_unregistered_conditions(reach, f, status))
    )


def _counts_statement(user: VaUsers, preset: str, f: CaseFilters, reach: _Reach | None = None):
    """Rows per combined status over the scope and every filter but status
    and attention, in one aggregate query: the status tabs' numbers."""
    reach = reach or _reach(user)
    status = combined_status_case()
    return (
        sa.select(
            *(sa.func.count().filter(status == name).label(name) for name in COMBINED_STATUSES),
            sa.func.count().label("total"),
        )
        .select_from(VaDeathRegister)
        .outerjoin(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaDeathRegister.va_sid)
        .outerjoin(CASE_SUBMISSION, CASE_SUBMISSION.va_sid == VaDeathRegister.va_sid)
        .where(_base_scope(preset, reach), *_filter_conditions(user, reach, preset, f))
    )


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _utc_iso(value) -> str | None:
    """A naive UTC timestamp (submission, final COD authority) as ISO with its offset."""
    if value is None:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def _serialize(user: VaUsers, row, preset: str, show_location: bool, identifiers: list,
               register: dict | None = None, pii: bool = False) -> dict:
    # ``register``: the row's opened name and fix (``list_cases``); None when not opened.
    # ``pii``: the caller's personal-data access in this row's project (``_Reach.pii``).
    register = register or {}
    mine_reported = row.registered_by == user.user_id
    mine_started = row.started_by_user_id == user.user_id
    out = {
        "death_id": str(row.death_id) if row.death_id else None,
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
        "submitted_at": _utc_iso(row.submitted_at),
        "coded_at": _utc_iso(row.coded_at),
        "overdue": row.overdue,
        "days_waiting": row.days_waiting,
        "can_open": bool(row.can_open),
    }
    # The submission id only where it opens (the supervision preset below
    # keeps its own va_sid, as before).
    if row.can_open:
        out["va_sid"] = row.open_sid
    # created_at is the report time only for a register case (module docstring).
    if row.source == "register":
        out["reported_at"] = out["created_at"]
    if row.can_name and "deceased_name" in register:
        out["deceased_name"] = register["deceased_name"]
    # "No name was recorded", said only where it reveals nothing hidden: a
    # name the caller may see is empty, or (to a caller with personal-data
    # access) a submission with no register row, which never holds one.
    if ("deceased_name" in out and not out["deceased_name"]) or (row.death_id is None and pii):
        out["name_recorded"] = False
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


def coding_names(user: VaUsers, va_sids) -> dict[str, str]:
    """``{va_sid: deceased name}`` for the coding screens' rows the caller may
    see by name, one query and one sealed-blob open per such row.

    Policy: docs/policy/coding-workflow-state-machine.md, "Names on the
    coding screens". A row qualifies on ``can_name`` (the case list's rule)
    computed without the interviewer grant a self-coding coder is implied,
    which would otherwise name every case of the project; or, in a
    self-coding project, when the caller submitted the case (owns its
    submitted draft, as ``allocate_own_case``). A submission with no register
    row, or no name, is absent. No audit row: opening a name in a list is not
    audited anywhere (``list_cases``).
    """
    sids = [s for s in dict.fromkeys(va_sids) if s]
    if not sids:
        return {}
    submitted = sa.and_(
        VaProjectMaster.self_coding_enabled.is_(True),
        VaProjectMaster.web_intake_mode != "off",
        sa.exists().where(
            VaWebIntakeDraft.va_sid == VaDeathRegister.va_sid,
            VaWebIntakeDraft.user_id == user.user_id,
            VaWebIntakeDraft.status == "submitted",
        ),
    )
    rows = db.session.execute(
        sa.select(
            VaDeathRegister.death_id, VaDeathRegister.va_sid, VaDeathRegister.deceased_name,
            VaDeathRegister.pii_sealed, VaDeathRegister.pii_dek_wrapped,
        )
        .join(VaProjectMaster, VaProjectMaster.project_id == VaDeathRegister.project_id)
        .where(VaDeathRegister.va_sid.in_(sids),
               sa.or_(_reach(user, assigned_only=True).can_name, submitted))
        .order_by(VaDeathRegister.created_at)
    ).all()
    # One name per submission; a duplicate register row does not replace the first.
    names: dict[str, str] = {}
    for r in rows:
        try:
            name = register_pii_accessor.open_register_pii([r], only=("deceased_name",))[r.death_id]["deceased_name"]
        except pii_crypto.PiiCryptoError:
            # One unreadable row must not fail the page; the row id only, no PII.
            current_app.logger.error("coding_names: register row %s did not open", r.death_id)
            continue
        if name:
            names.setdefault(r.va_sid, name)
    return names


def list_cases(user: VaUsers, *, preset: str, filters: CaseFilters, cursor: str | None = None,
               limit: int = WORKLIST_PAGE_DEFAULT, with_identifiers: bool = True,
               identifier_projects: set | None = None, with_names: bool = True,
               reach: _Reach | None = None) -> dict:
    """``{"cases": [row, ...], "next_cursor": str | None}``: one page of the
    caller's cases for *preset*, hidden fields omitted per row. *limit* is
    clamped to ``WORKLIST_PAGE_MAX``. Empty scope is an empty page.

    Location (``latitude``/``longitude``) per policy decision 6, as
    ``worklist_page``: an organization project, and the caller has personal
    data access in the case's project (``pii_scope``) or registered the case; and only on
    a row the caller's interviewer or reporter reach opens (coders hold PII
    grants but code masked). Never on the supervision preset. *with_identifiers*
    False skips the registration numbers (no query, no decryption);
    *identifier_projects* limits the decrypted values to rows of those projects
    (the export's audited set), the others stay badges. *with_names* False
    skips the deceased name and the location (both sealed): the blob is not
    selected and nothing is decrypted (the export has neither column).
    *reach* is a ``_reach(user)`` the caller already built (one per request).
    """
    if preset not in PRESETS:
        raise WebIntakeError("Unknown preset.")
    if _no_scope(user):
        return {"cases": [], "next_cursor": None}
    limit = max(1, min(int(limit), WORKLIST_PAGE_MAX))
    reach = reach or _reach(user)
    statement, sort = _page_statement(user, preset, filters, cursor, limit, with_names, reach)
    rows = db.session.execute(statement).all()
    page = rows[:limit]
    org_projects = set()
    if with_names and preset != "supervision" and any(r.via_field and r.has_location for r in page):
        org_projects = org_grant_service.projects_with_org_tree({r.project_id for r in page})
    # The export without number columns asks for none: nothing is decrypted.
    # A submission with no register row (death_id NULL) holds no numbers.
    registered = [r for r in page if r.death_id is not None]
    identifiers = identifier_payloads(
        user, registered, values_for={r.death_id for r in registered if r.can_identifiers
                          and (identifier_projects is None or r.project_id in identifier_projects)}
    ) if with_identifiers else {}
    show_location = {
        r.death_id: bool(with_names and r.via_field and r.has_location and r.project_id in org_projects
                         and (reach.pii.sees(r.project_id) or r.registered_by == user.user_id))
        for r in page
    }
    opened = _open_page(page, show_location) if with_names else {}
    cases = [
        _serialize(user, row, preset, show_location=show_location[row.death_id],
                   identifiers=identifiers.get(row.death_id, []), register=opened.get(row.death_id),
                   pii=reach.pii.sees(row.project_id))
        for row in page
    ]
    key = page[-1].row_key if _lists_unregistered(preset, filters) and page else None
    return {"cases": cases, "next_cursor": _encode_cursor(sort, page[-1], key) if len(rows) > limit else None}


def case_list_counts(user: VaUsers, *, preset: str, filters: CaseFilters, reach: _Reach | None = None) -> dict:
    """``{"counts": {status: n, ..., "total": n}}`` ignoring the status filter
    (duplicate and cancelled are counted in every preset), plus ``"tiles"``
    (``supervision_tiles`` over the supervised cases, every filter ignored)
    only for a caller with supervision scope. *reach*: as ``list_cases``.
    With unregistered submissions (``_lists_unregistered``) a second
    aggregate counts theirs, summed in per status."""
    zero = {name: 0 for name in (*COMBINED_STATUSES, "total")}
    if _no_scope(user):
        return {"counts": zero}
    reach = reach or _reach(user)
    with _jit_off():
        counts = dict(db.session.execute(_counts_statement(user, preset, filters, reach)).one()._mapping)
        if _lists_unregistered(preset, filters):
            extra = db.session.execute(_unregistered_counts_statement(reach, filters)).one()._mapping
            counts = {name: counts[name] + extra[name] for name in counts}
        result = {"counts": counts}
        supervised = reach.supervised
        if not isinstance(supervised, sa.sql.elements.False_):
            result["tiles"] = supervision_tiles(supervised)
    return result


@contextmanager
def _jit_off():
    """JIT compilation is most of the count seq scans' cost (704 -> 247 ms and
    304 -> 70 ms at 200k rows, docs/kb/case-list-query-plans.md): off for
    them only. SET LOCAL lasts to the end of the transaction, so the caller's
    value is put back after; an error rolls the transaction back, which drops
    the setting too."""
    previous = db.session.scalar(sa.text("SELECT current_setting('jit')"))
    db.session.execute(sa.text("SET LOCAL jit = off"))
    yield
    db.session.execute(sa.text("SELECT set_config('jit', :previous, true)"), {"previous": previous})


# ---------------------------------------------------------------------------
# Stage counts: the Statistics Overview and Projects numbers
# ---------------------------------------------------------------------------

#: The Interviews tab's "All": every status a case with a submission can hold
#: but duplicate and cancelled (owner, 2026-11-04: refused included).
INTERVIEWED_STATUSES = ("submitted_awaiting_coding", "in_coding", "coded", "not_codeable", "refused")
#: The Codings tab's "All".
CODING_STATUSES = ("submitted_awaiting_coding", "in_coding", "coded", "not_codeable")
STAGES = ("reported", "interviewed", "coded", "overdue_interview", "overdue_coding")


def _stage_queries(f: CaseFilters) -> dict[str, tuple[str, CaseFilters]]:
    """``{stage: (preset, filters)}``: the Statistics tab query each stage is
    the total of, period and statuses included (src/web/stats/view.ts
    ``casesQuery``), the area filters and the flag left to the caller.
    reported: Deaths "All"; interviewed: Interviews "All"; coded: Codings'
    Coded chip; the overdue ones: Deaths and Codings with ``overdue`` (no
    period: an overdue list is live)."""
    submitted = {"interviewed": True, "submitted_from": f.submitted_from, "submitted_to": f.submitted_to}
    return {
        "reported": ("deaths", CaseFilters(reported_from=f.reported_from, reported_to=f.reported_to)),
        "interviewed": ("interview", CaseFilters(statuses=INTERVIEWED_STATUSES, **submitted)),
        "coded": ("coding", CaseFilters(statuses=("coded",), **submitted)),
        "overdue_interview": ("deaths", CaseFilters(overdue="interview")),
        "overdue_coding": ("coding", CaseFilters(statuses=CODING_STATUSES, interviewed=True, overdue="coding")),
    }


def _stage_statements(user: VaUsers, reach: _Reach, f: CaseFilters) -> tuple:
    """The register and the unregistered statement of ``stage_counts``: one
    ``count(*) FILTER`` per stage, grouped by project. The WHERE is the
    listing's scope and area filters with ``unregistered`` on (the inactive
    project-site rule with them); each FILTER is that stage's own filters and
    statuses, built by the list's own functions so the two cannot drift."""
    area = CaseFilters(project_ids=f.project_ids, site_id=f.site_id, org_unit_id=f.org_unit_id, unregistered=True)
    stages = _stage_queries(f)
    status = combined_status_case()
    register = (
        sa.select(VaDeathRegister.project_id, *(
            sa.func.count().filter(sa.and_(*_filter_conditions(user, reach, preset, sf),
                                           *_status_conditions(preset, sf, status))).label(name)
            for name, (preset, sf) in stages.items()))
        .select_from(VaDeathRegister)
        .outerjoin(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaDeathRegister.va_sid)
        .outerjoin(CASE_SUBMISSION, CASE_SUBMISSION.va_sid == VaDeathRegister.va_sid)
        .where(reach.scope, *_filter_conditions(user, reach, "deaths", area))
        .group_by(VaDeathRegister.project_id)
    )
    status = unregistered_status_case()
    unregistered = (
        sa.select(VaForms.project_id, *(
            sa.func.count().filter(sa.and_(*_unregistered_filters(reach, sf, status),
                                           *_status_conditions(preset, sf, status))).label(name)
            for name, (preset, sf) in stages.items()))
        .select_from(VaSubmissions)
        .join(VaForms, VaForms.form_id == VaSubmissions.va_form_id)
        .outerjoin(VaSubmissionWorkflow, VaSubmissionWorkflow.va_sid == VaSubmissions.va_sid)
        .where(*_unregistered_conditions(reach, area, status))
        .group_by(VaForms.project_id)
    )
    return register, unregistered


def stage_counts(user: VaUsers, args) -> dict:
    """The ``GET /api/v1/cases/stage-counts`` reply: ``{"projects": {project_id:
    {stage: n}}, "total": {stage: n}, "thresholds": {...}}`` over the caller's
    listing with ``unregistered=1``, each stage equal to its Statistics tab's
    total (``_stage_queries``). Query: ``project_id``, ``site_id``,
    ``org_unit_id``, ``reported_from`` / ``reported_to`` (the reported stage)
    and ``submitted_from`` / ``submitted_to`` (interviewed and coded), parsed
    as ``/cases``; other list parameters are ignored. A project with no case
    in reach is absent. Two statements, none per project."""
    f = parse_query(args)["filters"]
    projects: dict[str, dict[str, int]] = {}
    if not _no_scope(user):
        reach = _reach(user)
        with _jit_off():
            for statement in _stage_statements(user, reach, f):
                for row in db.session.execute(statement):
                    counts = projects.setdefault(row.project_id, dict.fromkeys(STAGES, 0))
                    for name in STAGES:
                        counts[name] += row._mapping[name]
    return {
        "projects": projects,
        "total": {name: sum(counts[name] for counts in projects.values()) for name in STAGES},
        "thresholds": {"interview_days": OVERDUE_INTERVIEW_DAYS, "coding_days": OVERDUE_CODING_DAYS},
    }


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
        .outerjoin(CASE_SUBMISSION, CASE_SUBMISSION.va_sid == VaDeathRegister.va_sid)
        .where(*_row_conditions(user, reach, preset, filters, combined_status_case()))
    ).one()
    return count, set(projects or ())


def case_list_page(user: VaUsers, args) -> dict:
    """The ``GET /api/v1/cases`` reply: ``{cases, counts, [tiles,] next_cursor}``;
    ``counts`` and ``tiles`` only without a ``cursor`` (the first page)."""
    query = parse_query(args)
    # One build for the page and the counts; none for an empty scope.
    reach = None if _no_scope(user) else _reach(user)
    page = list_cases(user, **query, reach=reach)
    # Counts and tiles are seq scans (docs/kb/case-list-query-plans.md): the
    # first page only; a client keeps them while it pages.
    counts = {} if query["cursor"] else case_list_counts(
        user, preset=query["preset"], filters=query["filters"], reach=reach)
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
