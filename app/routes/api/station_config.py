"""Offline station onboarding and the signed station config (beads
digitva-gb8w.4, digitva-gb8w.8).

Browser (admin, project PI or project-scoped data manager; state changes
need ``X-CSRFToken``), under ``/api/v1/projects/<project_id>/stations/<device_id>``:

- ``GET``: custodian, roster, the config in force (no file).
- ``PUT .../custodian``, ``PUT .../roster``: set them (audited).
- ``POST /api/v1/projects/<project_id>/station-config?device_id=``: issue a
  new signed config; it is the one in force from then on.
- ``GET /api/v1/projects/<project_id>/station-config?device_id=``: download
  the config in force (contract 3.8, ``not for devices``).

Device: ``GET /api/v1/intake/station-config``, the station's own bearer
only: the same bytes as the download, ``ETag`` / 304, 60 per hour per
device. Contract docs/policy/offline-api-contract.md 3.8 and 4.1; file
format docs/policy/offline-bundle-and-transfer.md 6.4.
"""

from flask import Blueprint, Response, g, jsonify, request
from flask_limiter.util import get_remote_address
from flask_login import current_user, login_required

from app import db, limiter
from app.decorators import role_required
from app.routes.api.request_helpers import browser_session_only, parse_body
from app.routes.api.request_helpers import error as api_error
from app.services import identifier_type_service
from app.services import station_config_service as service

bp = Blueprint("station_config_api", __name__)

_FILE_TYPE = "application/vnd.digitva.station-config"


@bp.errorhandler(identifier_type_service.IdentifierTypeError)
def _not_configurable(exc):
    db.session.rollback()
    return api_error(str(exc), exc.code, exc.status)


@bp.errorhandler(service.StationConfigError)
def _refused(exc):
    db.session.rollback()
    return api_error(str(exc), exc.code, exc.status, **({"fields": exc.fields} if exc.fields else {}))


def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def _browser_only():
    refused = browser_session_only()
    if refused is not None:
        raise service.StationConfigError("This endpoint requires a browser session.", "cookie_session_required", 403)


#: A full roster (50 members, 10 roles each) with room to spare.
BODY_MAX_BYTES = 64 * 1024


def _project(project_id: str) -> str:
    _browser_only()
    request.max_content_length = BODY_MAX_BYTES
    return identifier_type_service.normalise_project_id(project_id)


def _file(row, filename: str | None = None):
    """The stored file with its strong ETag; 304 when the client has it."""
    etag = row.text_sha256
    if etag in request.if_none_match:
        response = Response(status=304)
    else:
        response = Response(row.signed_text, mimetype=_FILE_TYPE)
        if filename:
            response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.set_etag(etag)
    return _no_store(response)


@bp.get("/projects/<project_id>/stations/<device_id>")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("120 per minute")
def get_station(project_id: str, device_id: str):
    project_id = _project(project_id)
    return _no_store(jsonify(service.serialize_station(current_user, project_id, device_id)))


@bp.put("/projects/<project_id>/stations/<device_id>/custodian")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("30 per minute")
def put_custodian(project_id: str, device_id: str):
    project_id = _project(project_id)
    service.set_custodian(current_user, project_id, device_id, parse_body())
    db.session.commit()
    return _no_store(jsonify(service.serialize_station(current_user, project_id, device_id)))


@bp.put("/projects/<project_id>/stations/<device_id>/roster")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("30 per minute")
def put_roster(project_id: str, device_id: str):
    project_id = _project(project_id)
    service.set_roster(current_user, project_id, device_id, parse_body())
    db.session.commit()
    return _no_store(jsonify(service.serialize_station(current_user, project_id, device_id)))


@bp.post("/projects/<project_id>/station-config")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("30 per minute")
def issue_station_config(project_id: str):
    project_id = _project(project_id)
    row = service.issue_config(current_user, project_id, request.args.get("device_id", ""))
    db.session.commit()
    return _no_store(jsonify(service.serialize_station(current_user, project_id, row.device_id))), 201


@bp.get("/projects/<project_id>/station-config")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("60 per minute")
def download_station_config(project_id: str):
    project_id = _project(project_id)
    row = service.browser_config(current_user, project_id, request.args.get("device_id", ""))
    return _file(row, f"station-config-{row.device_id}.digitva-station.json")


def _device_limit_key() -> str:
    session = g.get("device_session")
    return f"station-config:{session.device_id}" if session is not None else get_remote_address()


@bp.get("/intake/station-config")
@login_required
@limiter.limit("60 per hour", key_func=_device_limit_key)
def device_station_config():
    """The caller's own station config. The device is the bearer session's,
    never named in the request; a browser cookie has none: 403
    ``device_session_required``."""
    session = g.get("device_session")
    if session is None:
        return api_error("Only a station's device session fetches its config.", "device_session_required", 403)
    return _file(service.device_config(session.device_id))
