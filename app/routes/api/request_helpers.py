"""Request parsing shared by the sign-in and intake API blueprints.

Both answer ``{"error", "code"}``; both name the interviewer's project in the
request, never taken from the device's enrolment.
"""

from flask import jsonify, request
from flask_login import current_user

from app.services import device_auth_service as devices
from app.services import web_intake_service as intake_svc

#: WebIntakeError carries a status only; the contract wants a machine code.
INTAKE_CODES = {400: "invalid_request", 403: "forbidden", 404: "not_found", 409: "conflict", 422: "invalid_interview"}


def error(message, code, status_code, **extra):
    """``{"error", "code"}`` plus any *extra* body keys (a 409 that carries the stored result)."""
    return jsonify({"error": message, "code": code, **extra}), status_code


def intake_error(exc: intake_svc.WebIntakeError):
    return error(str(exc), exc.code or INTAKE_CODES.get(exc.status_code, "invalid_request"), exc.status_code)


def parse_body() -> dict:
    """The JSON object body, ``{}`` when absent, malformed or not an object."""
    try:
        body = request.get_json(silent=True)
    except RecursionError:  # absurdly nested JSON within the size cap
        return {}
    return body if isinstance(body, dict) else {}


def interviewer_context() -> list[dict]:
    """``interviewer_context`` of the caller, computed once per request. Kept
    in the WSGI environ, not ``g``, which can outlive the request (as
    ``authz.resolve_grants``)."""
    context = request.environ.get("digitva.interviewer_context")
    if context is None:
        context = request.environ["digitva.interviewer_context"] = intake_svc.interviewer_context(current_user)
    return context


def require_project(project_id: str) -> str:
    """*project_id* must be one of the interviewer's projects (403
    ``project_forbidden``, alike whether it exists or not)."""
    if not any(e["project_id"] == project_id for e in interviewer_context()):
        raise devices.DeviceAuthError("You have no interviewer access in that project.", "project_forbidden", 403)
    return project_id


def request_project_id(p: dict | None = None, *, required: bool = True) -> str | None:
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
    return require_project(raw.strip())
