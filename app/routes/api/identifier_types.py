"""Identifier type configuration — /api/v1/projects/<project_id>/identifier-types.

Admin, or a live project_pi / data_manager grant on that project, defines
which registration identifiers a project collects and how each is validated.
No DELETE: a type is deactivated. Browser session only (a configuration
screen, not a device call); state changes need ``X-CSRFToken``. A project the
caller has no grant in is 404; a grant without a configuring role is 403.
Policy: docs/policy/death-registration-identifiers.md.
"""

from flask import Blueprint, jsonify, request
from flask_login import current_user

from app import db, limiter
from app.decorators import role_required
from app.routes.api.request_helpers import browser_session_only, parse_body
from app.routes.api.request_helpers import error as api_error
from app.services import identifier_type_service as service

bp = Blueprint("identifier_types_api", __name__)

#: A type definition is a dozen small fields.
BODY_MAX_BYTES = 8 * 1024


@bp.before_request
def _require_browser_session():
    return browser_session_only()


@bp.errorhandler(service.IdentifierTypeError)
def _refused(exc):
    db.session.rollback()
    return api_error(str(exc), exc.code, exc.status)


def _body() -> dict:
    request.max_content_length = BODY_MAX_BYTES
    return parse_body()


@bp.get("/<project_id>/identifier-types")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("120 per minute")
def list_identifier_types(project_id: str):
    project_id = service.normalise_project_id(project_id)
    service.configuring_role(current_user, project_id)
    response = jsonify({
        "project_id": project_id,
        "identifier_types": [service.serialize_type(t) for t in service.list_types(project_id)],
    })
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.post("/<project_id>/identifier-types")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("30 per minute")
def create_identifier_type(project_id: str):
    project_id = service.normalise_project_id(project_id)
    row = service.create_type(current_user, project_id, _body())
    db.session.commit()
    return jsonify({"identifier_type": service.serialize_type(row)}), 201


@bp.put("/<project_id>/identifier-types/<uuid:type_id>")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("30 per minute")
def update_identifier_type(project_id: str, type_id):
    project_id = service.normalise_project_id(project_id)
    row = service.update_type(current_user, project_id, type_id, _body())
    db.session.commit()
    return jsonify({"identifier_type": service.serialize_type(row)})
