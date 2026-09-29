"""Device API for the Android collection app (Path B), under /api/v1/device.

Contract: .tasks/2026-09-30-android-collection-app.md ("API contract").
Policy: docs/policy/field-data-collection.md. Rules live in
``device_auth_service`` (enrolment, sessions, tokens) and
``web_intake_service`` (uploads); this layer parses and serializes.

No cookies: every call after sign-in carries ``Authorization: Bearer``,
resolved by the request loader in app/models/va_users.py, and this
blueprint refuses any other kind of authentication (a browser's session
cookie included), which is what makes exempting it from CSRF safe. Errors are
``{"error": ..., "code": ...}``.
"""

import uuid
from datetime import UTC, datetime

from flask import Blueprint, g, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from app import csrf, db, limiter
from app.decorators import role_required
from app.models import AuthDevice, VaProjectMaster
from app.routes.api.organization import form_options_payload
from app.services import device_auth_service as devices
from app.services import web_intake_service as intake_svc
from app.services.site_maintenance_service import should_block_non_admin_after_cutoff
from app.utils.who_va_bundle import who_va_bundle_version

bp = Blueprint("device", __name__)
csrf.exempt(bp)

#: Endpoints reachable without a device session (they create one).
_UNAUTHENTICATED = frozenset({"enroll", "open_session", "refresh_session"})

#: WebIntakeError carries a status only; the contract wants a machine code.
_INTAKE_CODES = {400: "invalid_request", 403: "forbidden", 404: "not_found", 409: "conflict", 422: "invalid_interview"}


def _error(message, code, status_code):
    return jsonify({"error": message, "code": code}), status_code


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _body_key(name):
    """Rate-limit key from a JSON body field (per device, per account)."""
    def key():
        value = _body().get(name)
        return f"device-{name}:{str(value).strip().lower()[:128]}" if value else f"device-{name}:"
    return key


@bp.before_request
def _require_device_session():
    endpoint = (request.endpoint or "").rsplit(".", 1)[-1]
    if endpoint in _UNAUTHENTICATED:
        return None
    user = current_user._get_current_object()  # runs the bearer request loader
    session = g.get("device_session")
    if session is None or not user.is_authenticated or user.user_id != session.user_id:
        return _error("Authentication required.", "unauthorized", 401)
    if not user.is_admin() and should_block_non_admin_after_cutoff():
        return _error("Site is under maintenance.", "maintenance", 403)
    return None


@bp.errorhandler(devices.DeviceAuthError)
def _device_auth_error(exc):
    db.session.rollback()
    return _error(str(exc), exc.code, exc.status_code)


@bp.errorhandler(intake_svc.WebIntakeError)
def _intake_error(exc):
    db.session.rollback()
    return _error(str(exc), _INTAKE_CODES.get(exc.status_code, "invalid_request"), exc.status_code)


# ---------------------------------------------------------------------------
# Enrolment and sessions (no bearer token yet)
# ---------------------------------------------------------------------------


@bp.post("/enroll")
@limiter.limit("10 per minute")
def enroll():
    p = _body()
    device, secret = devices.enrol_device(
        p.get("code"), device_name=p.get("device_name"), platform=p.get("platform"),
        app_version=p.get("app_version"),
    )
    project = db.session.get(VaProjectMaster, device.project_id)
    db.session.commit()
    return jsonify({
        "device_id": str(device.device_id),
        "device_secret": secret,
        "project": {"project_id": project.project_id, "name": project.project_name},
        "server_time": datetime.now(UTC).isoformat(),
    }), 201


@bp.post("/sessions")
@limiter.limit("10 per minute")
@limiter.limit("10 per minute", key_func=_body_key("device_id"))
@limiter.limit("20 per hour", key_func=_body_key("email"))
def open_session():
    """Interviewer sign-in on an enrolled device. Rate limits match the web
    password step (docs/policy/authentication-factors.md section 1), per IP,
    per device and per account; the device credential replaces the CAPTCHA."""
    p = _body()
    issued, user = devices.open_session(
        device_id=p.get("device_id"), device_secret=p.get("device_secret"),
        email=p.get("email"), password=p.get("password"), otp=p.get("otp"),
    )
    db.session.commit()
    return jsonify(devices.serialize_tokens(issued, user)), 201


@bp.post("/sessions/refresh")
@limiter.limit("30 per minute")
def refresh_session():
    """Rotate the refresh token; optional ``count``/``unique_ids`` record the
    outstanding-work report in the same call."""
    p = _body()
    issued, user = devices.refresh_session(p.get("refresh_token"))
    if "count" in p:
        devices.record_outstanding(issued.session, p.get("count"), p.get("unique_ids"))
    db.session.commit()
    return jsonify(devices.serialize_tokens(issued, user)), 200


# ---------------------------------------------------------------------------
# Bearer-authenticated
# ---------------------------------------------------------------------------


@bp.delete("/sessions/current")
@login_required
def end_session():
    """Sign-out. ``login_required``, not the interviewer role: an interviewer
    whose grant was withdrawn must still be able to sign out."""
    devices.end_session(g.device_session)
    db.session.commit()
    return "", 204


@bp.get("/bootstrap")
@role_required("interviewer")
def bootstrap():
    """The intake bootstrap for this interviewer, scoped to the device's
    project, plus that project's form options and the served instrument
    bundle version. No CSRF fields: there is no cookie session here."""
    device = db.session.get(AuthDevice, g.device_session.device_id)
    project = db.session.get(VaProjectMaster, device.project_id)
    context = [
        entry for entry in intake_svc.interviewer_context(current_user)
        if entry["project_id"] == device.project_id
    ]
    return jsonify({
        "user": {"user_id": str(current_user.user_id), "name": current_user.name},
        "context": context,
        "form_options": form_options_payload(project),
        "instrument_version": who_va_bundle_version(),
    })


@bp.post("/submissions")
@role_required("interviewer")
def submit_interview():
    """One completed interview, idempotent on ``client_draft_id``: a resend
    returns the first result with 200."""
    p = _body()
    try:
        client_draft_id = uuid.UUID(str(p.get("client_draft_id")))
    except ValueError:
        return _error("client_draft_id must be a UUID.", "invalid_request", 400)
    site_id = p.get("site_id")
    if not isinstance(site_id, str) or not site_id.strip():
        return _error("site_id is required.", "invalid_request", 400)
    envelope = p.get("draft")
    completion = p.get("completion")
    if not isinstance(completion, dict):
        # The package's completion result carries valid/issues beside data.
        completion = envelope if isinstance(envelope, dict) else {}

    existing = intake_svc.find_device_upload(current_user, client_draft_id)
    if existing is not None:
        return jsonify(intake_svc.serialize_device_upload(existing)), 200
    device = db.session.get(AuthDevice, g.device_session.device_id)
    try:
        draft = intake_svc.submit_device_interview(
            current_user,
            project_id=device.project_id,
            client_draft_id=client_draft_id,
            site_id=site_id.strip(),
            org_unit_id=p.get("org_unit_id") or None,
            death_id=p.get("death_id") or None,
            envelope=envelope,
            completion=completion,
            device_id=device.device_id,
        )
        db.session.commit()
    except IntegrityError:
        # A concurrent resend of the same client_draft_id won the unique index.
        db.session.rollback()
        existing = intake_svc.find_device_upload(current_user, client_draft_id)
        if existing is None:
            raise
        return jsonify(intake_svc.serialize_device_upload(existing)), 200
    return jsonify(intake_svc.serialize_device_upload(draft)), 201


@bp.post("/outstanding")
@role_required("interviewer")
def report_outstanding():
    p = _body()
    devices.record_outstanding(g.device_session, p.get("count"), p.get("unique_ids"))
    db.session.commit()
    return "", 204
