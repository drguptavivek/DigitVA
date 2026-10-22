"""Offline bundle (.dvb) ingest (bead digitva-gb8w.2).

- ``POST /api/v1/intake/bundles``: ingest one bundle; 201 with the report,
  200 with the stored report for a replay of the same bundle, 409
  ``conflict`` while another request is ingesting it; a resend of an
  interrupted ingest resumes it (201).
- ``POST /api/v1/intake/bundles/validate``: the same checks and service
  calls inside a transaction that is rolled back; stores nothing and queues
  no SmartVA run. Death-number sequence values it draws are not returned
  (``nextval`` is not transactional), leaving gaps.
- ``GET /api/v1/intake/bundles/<bundle_id>``: the stored report, with a
  held coding result's final outcome once the applier has run.
- ``GET /api/v1/intake/bundles/<bundle_id>/receipt``: the signed two-line
  receipt the station deletes records on.

Callers: the station's own device bearer (its device must be the
manifest's) or a browser session of an admin, or a data manager or
interview supervisor of the bundle's project (``X-CSRFToken`` on POST).
Body: the raw file, ``Content-Type: application/vnd.digitva.bundle``, a
declared ``Content-Length`` of at most 50 MiB (413 before reading). Every
reply is ``no-store``; errors are ``{error, code}``. Rules:
app/services/bundle_ingest_service.py; policy
docs/policy/offline-bundle-and-transfer.md 5.
"""
from flask import Blueprint, Response, g, jsonify, request
from flask_login import current_user

from app import db, limiter
from app.decorators import role_required
from app.routes.api.request_helpers import error as api_error
from app.services import bundle_ingest_service as service
from app.services import station_config_service

bp = Blueprint("bundles_api", __name__)

#: Who may call at all; the per-bundle rule is the service's.
_UPLOADS = frozenset({"ingest_bundle", "validate_bundle"})


def _bearer_device_id():
    session = g.get("device_session")
    return session.device_id if session is not None else None


def _uploader_key() -> str:
    """Rate-limit key: the station for a bearer, else the browser user."""
    device_id = _bearer_device_id()
    return f"bundle:device:{device_id}" if device_id else f"bundle:user:{current_user.get_id()}"


@bp.before_request
def _refuse_oversized_body():
    if (request.endpoint or "").rsplit(".", 1)[-1] not in _UPLOADS:
        return None
    request.max_content_length = service.MAX_BYTES
    if request.content_length is None or request.content_length > service.MAX_BYTES:
        return api_error("A bundle needs a Content-Length of at most 50 MiB.", "payload_too_large", 413)
    return None


@bp.after_request
def _no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.errorhandler(service.BundleRefusal)
def _refused(exc):
    db.session.rollback()
    return api_error(str(exc), exc.code, exc.status)


@bp.errorhandler(station_config_service.StationConfigError)
def _unsigned(exc):
    db.session.rollback()
    return api_error(str(exc), exc.code, exc.status)


def _upload(dry_run: bool):
    if request.mimetype != service.MEDIA_TYPE:
        return api_error(f"Send the bundle as {service.MEDIA_TYPE}.", "unsupported_media_type", 415)
    raw = request.get_data(cache=False)
    try:
        status, report = service.ingest_bundle(
            raw, uploader=current_user, bearer_device_id=_bearer_device_id(), dry_run=dry_run)
    except service.BundleRefusal as refusal:
        db.session.rollback()
        service.record_refusal(refusal, raw[:service.MAX_MANIFEST_BYTES], current_user)
        db.session.commit()
        raise
    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()
    return jsonify(report), status


@bp.post("/intake/bundles")
@role_required("admin", "data_manager", "interview_supervisor", "interviewer", "death_reporter", "coder")
@limiter.limit("10 per hour", key_func=_uploader_key)
def ingest_bundle():
    return _upload(dry_run=False)


@bp.post("/intake/bundles/validate")
@role_required("admin", "data_manager", "interview_supervisor", "interviewer", "death_reporter", "coder")
@limiter.limit("10 per hour", key_func=_uploader_key)
def validate_bundle():
    return _upload(dry_run=True)


@bp.get("/intake/bundles/<bundle_id>")
@role_required("admin", "data_manager", "interview_supervisor", "interviewer", "death_reporter", "coder")
@limiter.limit("120 per minute")
def bundle_report(bundle_id):
    row = service.stored_ingest(bundle_id, user=current_user, bearer_device_id=_bearer_device_id())
    return jsonify(row.report)


@bp.get("/intake/bundles/<bundle_id>/receipt")
@role_required("admin", "data_manager", "interview_supervisor", "interviewer", "death_reporter", "coder")
@limiter.limit("120 per minute")
def bundle_receipt(bundle_id):
    row = service.stored_ingest(bundle_id, user=current_user, bearer_device_id=_bearer_device_id())
    response = Response(service.receipt_text(row), mimetype=service.RECEIPT_MEDIA_TYPE)
    response.headers["Content-Disposition"] = f'attachment; filename="receipt-{row.bundle_id}.dvr"'
    return response
