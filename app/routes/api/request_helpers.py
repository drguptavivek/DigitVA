"""Request parsing shared by the sign-in and intake API blueprints.

Both answer ``{"error", "code"}``; both name the interviewer's project in the
request, never taken from the device's enrolment.
"""

from flask import jsonify, request
from flask_login import current_user

from app.models import VaAccessRoles
from app.services import device_auth_service as devices
from app.services import web_intake_service as intake_svc
from app.services.authz.actions import DEATH_REGISTERING_ROLES

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


def intake_error(exc: intake_svc.WebIntakeError):
    return error(str(exc), exc.code or INTAKE_CODES.get(exc.status_code, "invalid_request"), exc.status_code)


def parse_body() -> dict:
    """The JSON object body, ``{}`` when absent, malformed or not an object."""
    try:
        body = request.get_json(silent=True)
    except RecursionError:  # absurdly nested JSON within the size cap
        return {}
    return body if isinstance(body, dict) else {}


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
