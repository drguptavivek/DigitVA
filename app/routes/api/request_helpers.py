"""Request parsing shared by the sign-in and intake API blueprints.

Both answer ``{"error", "code"}``; both name the interviewer's project in the
request, never taken from the device's enrolment.
"""

import re
import uuid
from datetime import date

import sqlalchemy as sa
from flask import current_app, jsonify, request
from flask_login import current_user
from sqlalchemy.exc import IntegrityError

from app import _rate_limit_key, db, limiter
from app.models import VaAccessRoles, VaForms, VaSubmissions
from app.services import device_auth_service as devices
from app.services import web_intake_service as intake_svc
from app.services.authz import subtree_select
from app.services.authz.actions import DEATH_REGISTERING_ROLES
from app.services.queue_card_service import QUEUE_SORTS, QueueFilters
from app.services.viewer_pii_service import pii_scope
from app.utils import va_local_date, va_user_timezone_name

#: Interviewer reach alone, the default of every intake route; the register
#: routes pass ``authz.actions.DEATH_REGISTERING_ROLES`` (a death_reporter
#: registers too).
INTERVIEWER = frozenset({VaAccessRoles.interviewer})

#: WebIntakeError carries a status only; the contract wants a machine code.
INTAKE_CODES = {400: "invalid_request", 403: "forbidden", 404: "not_found", 409: "conflict", 422: "invalid_interview"}


#: Machine code of an error that names none, by HTTP status. The one table:
#: ``error`` and the app error handler (``va_logger``) both read it.
STATUS_CODES = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "unprocessable",
    429: "rate_limited",
    502: "bad_gateway",
    503: "unavailable",
    504: "gateway_timeout",
}


def status_code_name(status_code: int) -> str:
    """Default machine code for *status_code*: the table, else ``server_error``
    for any 5xx and ``invalid_request`` for any other 4xx."""
    return STATUS_CODES.get(status_code) or ("server_error" if status_code >= 500 else "invalid_request")


def error(message, code=None, status_code=400, **extra):
    """``{"error", "code"}`` plus any *extra* body keys (a 409 that carries the
    stored result). *code* defaults from *status_code* (``STATUS_CODES``)."""
    return jsonify({"error": message, "code": code or status_code_name(status_code), **extra}), status_code


def browser_session_only():
    """Refuse device credentials on browser-only APIs.

    The bearer authentication hook has already established the user when this
    runs.  A separate guard keeps read-only APIs from accidentally accepting a
    mixed account's native token as a browser credential.
    """
    if devices.request_bearer_token(request) is not None:
        return error(
            "This endpoint requires a browser session.",
            "cookie_session_required",
            403,
        )
    return None


#: Page-size ceiling of the optional-paging list routes (``GET /coding/available``,
#: ``/coding/history``, ``/workflow/events/<sid>``); ``limit`` is clamped by
#: refusal (400), not silently.
MAX_PAGE_LIMIT = 200
_MAX_PAGE_OFFSET = 1_000_000
_MAX_PROJECT_ID = 64


class BadQuery(ValueError):
    """A query parameter a list route refuses: answer 400 ``invalid_request``."""


def _int_arg(name: str, low: int, high: int) -> int | None:
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        raise BadQuery(f"{name} must be a whole number.") from None
    if not low <= value <= high:
        raise BadQuery(f"{name} must be between {low} and {high}.")
    return value


def clamped_int_arg(name: str, default: int, high: int) -> int | None:
    """Positive int query arg clamped to *high*; ``None`` when not a whole number >= 1."""
    try:
        value = int(request.args.get(name, default))
    except ValueError:
        return None
    return min(value, high) if value >= 1 else None


def optional_page_args() -> tuple[int | None, int]:
    """``(limit, offset)`` of a route whose paging is opt-in.

    ``limit`` (1..``MAX_PAGE_LIMIT``) switches paging on; without it the route
    answers its unpaged body, so ``offset`` alone is refused rather than
    guessed at. Raises ``BadQuery``.
    """
    limit = _int_arg("limit", 1, MAX_PAGE_LIMIT)
    offset = _int_arg("offset", 0, _MAX_PAGE_OFFSET)
    if limit is None and offset is not None:
        raise BadQuery("offset requires limit.")
    return limit, offset or 0


def project_filter_arg() -> str | None:
    """The optional ``project_id`` filter, upper-cased as ``/coding/stats`` reads it."""
    project_id = (request.args.get("project_id") or "").strip().upper() or None
    if project_id and len(project_id) > _MAX_PROJECT_ID:
        raise BadQuery("project_id is too long.")
    return project_id


_SITE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def place_filter_arg() -> list:
    """The optional "Site and unit" filter of the queue lists, as SQL conditions.

    ``site_id`` matches the form's site; ``org_unit_id`` (a UUID) the unit and
    every active unit under it (``authz.subtree_select``). Both may be given
    (both must hold); neither answers ``[]``, so the route is unchanged. The
    conditions are ANDed onto the caller's own authorized query, so the filter
    only narrows: a place outside the caller's reach answers nothing extra.
    Each statement must already join ``VaForms`` and ``VaSubmissions``.
    Raises ``BadQuery`` for a malformed value.

    A place filter also limits the rows to projects where the caller sees
    personal data (``pii_scope``): filtering by unit would otherwise tell a
    non-PII caller which unit each listable case is in, which
    docs/policy/case-list-views.md forbids. Such a caller gets no rows and
    zero counts for a place; the client offers no place there (pii_visible).
    """
    conditions = []
    site_id = (request.args.get("site_id") or "").strip()
    if site_id:
        if not _SITE_ID.fullmatch(site_id):
            raise BadQuery("site_id is not a site id.")
        conditions.append(VaForms.site_id == site_id)
    org_unit_id = (request.args.get("org_unit_id") or "").strip()
    if org_unit_id:
        try:
            unit = uuid.UUID(org_unit_id)
        except ValueError:
            raise BadQuery("org_unit_id is not a unit id.") from None
        conditions.append(VaSubmissions.org_unit_id.in_(subtree_select([unit])))
    if conditions:
        conditions.append(pii_scope(current_user).condition(VaForms.project_id))
    return conditions


#: ``state`` values per queue list: each list's own pill words (owner
#: 2026-11-27, docs/policy/case-list-views.md, "Code and Review queue sort and
#: filter"). A list whose rows all show one pill offers none (Coding,
#: Available; Reviewed by me), so any value there is refused.
QUEUE_STATES = {
    "coding_available": frozenset(),
    "coding_history": frozenset({"coded", "recoded", "not_codeable"}),
    "review_available": frozenset({"coded", "recoded"}),
    "review_history": frozenset(),
}
_SEXES = ("female", "male")
#: Age groups by normalized days, the WHO 2022 boundaries of
#: ``icd_coding_policy.coding_age_group_for_submission`` (infant inside child).
_CHILD_FROM_DAYS, _ADULT_FROM_DAYS = 28, 12 * 365.25
_AGE_GROUPS = ("neonate", "child", "adult")
_LANGUAGE = re.compile(r"[A-Za-z0-9_-]{1,32}")
_MAX_REPEATS = 20
_MAX_TEXT = 128


def _one_of(name: str, allowed) -> str | None:
    value = (request.args.get(name) or "").strip().lower() or None
    if value is not None and value not in allowed:
        raise BadQuery(f"{name} must be one of: {', '.join(allowed)}.")
    return value


def _many_of(name: str, allowed=None, pattern=None) -> list[str]:
    values = [v.strip().lower() for v in request.args.getlist(name) if v.strip()]
    if len(values) > _MAX_REPEATS:
        raise BadQuery(f"{name} is given too many times.")
    for value in values:
        if (allowed is not None and value not in allowed) or (pattern is not None and not pattern.fullmatch(value)):
            raise BadQuery(f"{name} has an unknown value.")
    return list(dict.fromkeys(values))


def _date_arg(name: str) -> date | None:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise BadQuery(f"{name} must be an ISO date (YYYY-MM-DD).") from None


def _text_arg(name: str) -> str | None:
    value = (request.args.get(name) or "").strip() or None
    if value is not None and len(value) > _MAX_TEXT:
        raise BadQuery(f"{name} is too long.")
    return value


def queue_filter_args(list_kind: str) -> QueueFilters:
    """The optional "Sort and filter" parameters of one queue list
    (*list_kind*, a ``QUEUE_STATES`` key) as ``QueueFilters``.

    Every condition is SQL on ``VaSubmissions`` / ``VaForms`` ANDed onto the
    caller's own authorized query, so it only narrows. Absent or blank
    parameters add nothing (the list answers as before). Raises ``BadQuery``.

    - ``sex``, ``age_group`` (repeatable; unknown age matches none),
      ``interviewed_from`` / ``interviewed_to`` (inclusive ISO dates of the
      interview in the caller's time zone, the date the card shows).
    - ``language`` (repeatable): the narration language, intersected with the
      caller's coding languages; one outside them matches nothing.
    - ``interviewer`` and the interviewer part of ``q`` match only in projects
      where the caller sees personal data (``pii_scope``), else nothing, so
      narrowing never reveals a hidden interviewer. The case-id part of ``q``
      (``va_uniqueid_masked``) matches for everyone. The deceased's name is
      not searched (owner 2026-11-27): it can be sealed at rest
      (``REGISTER_PII_SPLIT_ENABLED``), so SQL cannot match it.
    - ``state`` (repeatable): the list's own pill words (``QUEUE_STATES``);
      the list's service turns them into SQL.
    """
    sort = _one_of("sort", QUEUE_SORTS)
    states = frozenset(_many_of("state", QUEUE_STATES[list_kind]))
    sex = _one_of("sex", _SEXES)
    age_groups = _many_of("age_group", _AGE_GROUPS)
    languages = _many_of("language", pattern=_LANGUAGE)
    interviewed_from = _date_arg("interviewed_from")
    interviewed_to = _date_arg("interviewed_to")
    if interviewed_from and interviewed_to and interviewed_from > interviewed_to:
        raise BadQuery("interviewed_from must not be after interviewed_to.")
    interviewer = _text_arg("interviewer")
    q = _text_arg("q")

    conditions = []
    if sex:
        conditions.append(sa.func.lower(VaSubmissions.va_deceased_gender) == sex)
    if age_groups:
        days = VaSubmissions.va_deceased_age_normalized_days
        bands = {
            "neonate": days < _CHILD_FROM_DAYS,
            "child": sa.and_(days >= _CHILD_FROM_DAYS, days < _ADULT_FROM_DAYS),
            "adult": days >= _ADULT_FROM_DAYS,
        }
        conditions.append(sa.or_(*(bands[group] for group in age_groups)))
    if languages:
        mine = {str(code).strip().lower() for code in (current_user.vacode_language or [])}
        allowed = sorted(set(languages) & mine)
        conditions.append(
            sa.func.lower(VaSubmissions.va_narration_language).in_(allowed) if allowed else sa.false()
        )
    if interviewed_from or interviewed_to:
        local_day = va_local_date(VaSubmissions.va_submission_date, va_user_timezone_name(current_user))
        if interviewed_from:
            conditions.append(local_day >= interviewed_from)
        if interviewed_to:
            conditions.append(local_day <= interviewed_to)
    if interviewer or q:
        sees_staff = pii_scope(current_user).condition(VaForms.project_id)
        if interviewer:
            conditions.append(sa.and_(sees_staff, VaSubmissions.va_data_collector.icontains(interviewer, autoescape=True)))
        if q:
            conditions.append(sa.or_(
                VaSubmissions.va_uniqueid_masked.icontains(q, autoescape=True),
                sa.and_(sees_staff, VaSubmissions.va_data_collector.icontains(q, autoescape=True)),
            ))
    return QueueFilters(conditions=tuple(conditions), sort=sort, states=states)


def identifier_rate_limit(carries, *, search=False):
    """A route decorator: the per-user budget of registration-number requests.
    Writes (``IDENTIFIER_RATE_LIMIT``, 30 an hour) share one bucket across
    every route that carries numbers; a number SEARCH (*search*) has its own
    (``IDENTIFIER_SEARCH_RATE_LIMIT``, 120 an hour). A request for which
    *carries()* is false is not counted and the app's default limits still
    apply. Takes effect before the route runs, so a refused request reads and
    writes nothing."""
    setting = "IDENTIFIER_SEARCH_RATE_LIMIT" if search else "IDENTIFIER_RATE_LIMIT"
    return limiter.shared_limit(
        lambda: current_app.config[setting], scope="identifier-search" if search else "identifier-numbers",
        key_func=_rate_limit_key, exempt_when=lambda: not carries(), override_defaults=False,
    )


def intake_error(exc: intake_svc.WebIntakeError):
    """The error reply of a refused intake action; ``fields`` joins the body
    only when the error names the questions to fix."""
    extra = {"fields": exc.fields} if exc.fields else {}
    return error(str(exc), exc.code or INTAKE_CODES.get(exc.status_code, "invalid_request"), exc.status_code, **extra)


def idempotent_create(create, refind):
    """``(row, True)`` from *create()*, which writes and commits; when a
    concurrent resend of the same client id won the unique index instead
    (``IntegrityError``), rolls back and returns ``(refind(), False)``. A
    refind that finds nothing (None) re-raises the IntegrityError: the
    conflict was not that resend."""
    try:
        return create(), True
    except IntegrityError:
        db.session.rollback()
        existing = refind()
        if existing is None:
            raise
        return existing, False


def parse_body() -> dict:
    """The JSON object body, ``{}`` when absent, malformed or not an object."""
    try:
        body = request.get_json(silent=True)
    except RecursionError:  # absurdly nested JSON within the size cap
        return {}
    return body if isinstance(body, dict) else {}


def optional_object_body() -> dict | None:
    """The JSON object body, ``{}`` when absent or malformed; None when it is
    JSON but not an object (a list, a number, a string), which the caller
    answers 400 ``invalid_request``. Unlike ``parse_body`` it does not read a
    list as ``{}``: on a route where ``{}`` means "do the default" (allocate at
    random, clear a pin) that would act on a bad request."""
    try:
        body = request.get_json(silent=True)
    except RecursionError:  # absurdly nested JSON within the size cap
        return None
    if body is None:
        return {}
    return body if isinstance(body, dict) else None


def interviewer_context(roles: frozenset = INTERVIEWER) -> list[dict]:
    """``interviewer_context`` of the caller for *roles* (interviewer alone by
    default), computed once per request and roleset. Kept in the WSGI environ,
    not ``g``, which can outlive the request (as ``authz.resolve_grants``)."""
    cache = request.environ.setdefault("digitva.interviewer_context", {})
    if roles not in cache:
        cache[roles] = intake_svc.interviewer_context(current_user, roles)
    return cache[roles]


def require_project(project_id: str, roles: frozenset = INTERVIEWER) -> str:
    """*project_id* must be one of the caller's projects for *roles* (403
    ``project_forbidden``, alike whether it exists or not)."""
    if not any(e["project_id"] == project_id for e in interviewer_context(roles)):
        message = (
            "You have no access to register deaths in that project."
            if roles == DEATH_REGISTERING_ROLES
            else "You have no interviewer access in that project."
        )
        raise devices.DeviceAuthError(message, "project_forbidden", 403)
    return project_id


def request_project_id(p: dict | None = None, *, required: bool = True, roles: frozenset = INTERVIEWER) -> str | None:
    """The ``project_id`` the request names (query string, or the JSON body
    *p* of a POST), checked by ``require_project``. Missing is 400
    ``invalid_request`` when *required*, else None."""
    raw = (request.args if p is None else p).get("project_id")
    if raw in (None, ""):
        if required:
            raise devices.DeviceAuthError("project_id is required.", "invalid_request", 400)
        return None
    if not isinstance(raw, str):
        raise devices.DeviceAuthError("project_id must be text.", "invalid_request", 400)
    return require_project(raw.strip(), roles)


def other_conditions_list(body: dict) -> list[str] | None:
    """Step 1 ``other_conditions``: a list of choices, or one text split on ``|``.

    Raises ValueError for any other type. Shared by coding and reviewing so
    the web (text) and the phone (list) send the same field either way."""
    value = body.get("other_conditions")
    if value is None:
        return None
    if isinstance(value, str):
        return [part.strip() for part in value.split("|") if part.strip()]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    raise ValueError("other_conditions must be text or a list of text.")
