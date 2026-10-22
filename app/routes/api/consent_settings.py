"""Respondent consent configuration — /api/v1/projects/<project_id>/consent-settings
and /consent-notices.

Admin, or a live project_pi / project-scoped data_manager grant (the
identifier-type rule), sets whether the project requires consent, its
contacts and retention, and adds notice versions. Notice versions are never
edited or deleted; ``.../seed`` creates version 1 from the policy draft and
an admin marks a version legally reviewed (``.../approve``). Browser session
only; state changes need ``X-CSRFToken``. Every change writes a
``map_consent_audit`` row. Project Setup's Respondent consent section
(digitva-athy) is the screen. Contract:
docs/policy/offline-api-contract.md section 5.
"""

from flask import Blueprint, jsonify, request
from flask_login import current_user

from app import db, limiter
from app.decorators import role_required
from app.routes.api.request_helpers import browser_session_only, parse_body
from app.routes.api.request_helpers import error as api_error
from app.services import consent_service as service
from app.services import identifier_type_service

bp = Blueprint("consent_settings_api", __name__)

#: A notice text (at most 20,000 characters, up to 4 bytes each) and its purposes.
BODY_MAX_BYTES = 96 * 1024


@bp.before_request
def _require_browser_session():
    return browser_session_only()


@bp.errorhandler(identifier_type_service.IdentifierTypeError)
def _not_configurable(exc):
    db.session.rollback()
    return api_error(str(exc), exc.code, exc.status)


@bp.errorhandler(service.ConsentError)
def _refused(exc):
    db.session.rollback()
    return api_error(str(exc), exc.code, exc.status_code, **({"fields": exc.fields} if exc.fields else {}))


def _body() -> dict:
    request.max_content_length = BODY_MAX_BYTES
    return parse_body()


def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/<project_id>/consent-settings")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("120 per minute")
def get_consent_settings(project_id: str):
    project_id = identifier_type_service.normalise_project_id(project_id)
    service.configuring_role(current_user, project_id)
    return _no_store(jsonify(service.serialize_settings(project_id)))


@bp.put("/<project_id>/consent-settings")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("30 per minute")
def put_consent_settings(project_id: str):
    project_id = identifier_type_service.normalise_project_id(project_id)
    service.save_settings(current_user, project_id, _body())
    db.session.commit()
    return _no_store(jsonify(service.serialize_settings(project_id)))


@bp.post("/<project_id>/consent-notices")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("30 per minute")
def create_consent_notice(project_id: str):
    project_id = identifier_type_service.normalise_project_id(project_id)
    row = service.create_notice_version(current_user, project_id, _body())
    db.session.commit()
    return _no_store(jsonify({"notice_version": service.serialize_version(row)})), 201


@bp.post("/<project_id>/consent-notices/seed")
@role_required("admin", "project_pi", "data_manager")
@limiter.limit("10 per minute")
def seed_consent_notices(project_id: str):
    """Version 1 in English and Hindi from the policy draft, for a project
    with no notice yet (409 ``conflict`` otherwise). Pending legal review."""
    project_id = identifier_type_service.normalise_project_id(project_id)
    rows = service.seed_notice_versions(current_user, project_id)
    db.session.commit()
    return _no_store(jsonify({"notice_versions": [service.serialize_version(row) for row in rows]})), 201


@bp.post("/<project_id>/consent-notices/<notice_version_id>/approve")
@role_required("admin")
@limiter.limit("30 per minute")
def approve_consent_notice(project_id: str, notice_version_id: str):
    """Mark a notice version legally reviewed (admin only, once, audited)."""
    project_id = identifier_type_service.normalise_project_id(project_id)
    service.approve_notice_version(current_user, project_id, notice_version_id)
    db.session.commit()
    return _no_store(jsonify(service.serialize_settings(project_id)))
