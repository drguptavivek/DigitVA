"""Sign-in routes for every client, under /api/v1/auth.

Enrol a device, open and refresh a device session, end it. Rules live in
``device_auth_service`` (enrolment, sessions, tokens); this layer parses and
serializes. The sign-in and refresh replies carry ``access``, the exact body of
``GET /api/v1/me/access`` (docs/current-state/api-v1.md), so a client learns
everything the user may do in one call. Policy:
docs/policy/field-data-collection.md, docs/policy/api-v1.md.

Errors are ``{"error": ..., "code": ...}``. Request bodies are capped
(``_body_limit``) before anything reads them, the rate limiter's key functions
included. Terms and maintenance gates are the app-level ones in app/__init__.py.
"""

from datetime import UTC, datetime

from flask import Blueprint, g, jsonify, request
from flask_login import login_required
from werkzeug.exceptions import RequestEntityTooLarge

from app import csrf, db, limiter
from app.models import VaProjectMaster
from app.routes.api.request_helpers import error as _error
from app.routes.api.request_helpers import parse_body
from app.services import device_auth_service as devices
from app.services.access_summary_service import build_access_summary
from app.services.user_account_service import canonical_mobile

bp = Blueprint("auth_api", __name__)
csrf.exempt(bp)

#: Request body caps: the refresh call (it may carry the outstanding-work
#: report: up to OUTSTANDING_MAX_IDS case ids, draft UUIDs and registration
#: UUIDs, about 150 KB at worst); every other (small) call.
REPORT_MAX_BYTES = 256 * 1024
BODY_MAX_BYTES = 16 * 1024
_REPORT_ENDPOINTS = frozenset({"refresh_session"})


def _body_limit() -> int:
    """Cap this request's body (idempotent). Runs before the first read,
    wherever that is: the limiter's key functions read the body in an
    app-level hook that runs before this blueprint's own."""
    endpoint = (request.endpoint or "").rsplit(".", 1)[-1]
    limit = REPORT_MAX_BYTES if endpoint in _REPORT_ENDPOINTS else BODY_MAX_BYTES
    request.max_content_length = limit
    return limit


def _body() -> dict:
    _body_limit()
    return parse_body()


def _body_key(name):
    """Rate-limit key from a JSON body field (per device, per account). An
    oversized body gives an empty key here; the blueprint hook answers 413.
    A sign-in identifier without ``@`` keys on its canonical mobile number,
    so spacing or a ``+91`` prefix does not buy a fresh bucket."""
    def key():
        try:
            value = _body().get(name)
        except RequestEntityTooLarge:
            value = None
        text = str(value).strip().lower()[:128] if value else ""
        if name == "email" and text and "@" not in text:
            text = canonical_mobile(text) or text
        return f"device-{name}:{text}"
    return key


@bp.before_request
def _refuse_oversized_body():
    limit = _body_limit()
    if request.content_length is not None and request.content_length > limit:
        return _error("The request body is too large.", "payload_too_large", 413)
    return None


@bp.errorhandler(RequestEntityTooLarge)
def _too_large(_exc):
    return _error("The request body is too large.", "payload_too_large", 413)


@bp.errorhandler(devices.DeviceAuthError)
def _device_auth_error(exc):
    db.session.rollback()
    return _error(str(exc), exc.code, exc.status_code)


# ---------------------------------------------------------------------------
# Enrolment and sessions (no bearer token yet)
# ---------------------------------------------------------------------------


def _session_body(issued, user) -> dict:
    """The token reply plus ``access``. Display-only, so a user with pending
    terms still gets it; the terms gate is a request hook, not this service."""
    return {**devices.serialize_tokens(issued, user), "access": build_access_summary(user)}


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
    """Interviewer sign-in on an enrolled device; the ``email`` field takes an
    email or a mobile number (docs/policy/mobile-sign-in.md). Rate limits match the web
    password step (docs/policy/authentication-factors.md section 1), per IP,
    per device and per account; the device credential replaces the CAPTCHA."""
    p = _body()
    issued, user = devices.open_session(
        device_id=p.get("device_id"), device_secret=p.get("device_secret"),
        email=p.get("email"), password=p.get("password"), otp=p.get("otp"),
    )
    db.session.commit()
    return jsonify(_session_body(issued, user)), 201


@bp.post("/sessions/refresh")
@limiter.limit("30 per minute")
def refresh_session():
    """Rotate the refresh token, presented with the device's id and secret;
    optional ``count``/``unique_ids``/``client_draft_ids``/``client_death_ids`` record the
    outstanding-work report in the same call. The session lasts while the
    worker has an interviewer grant in at least one project."""
    p = _body()
    issued, user = devices.refresh_session(
        p.get("refresh_token"), device_id=p.get("device_id"), device_secret=p.get("device_secret"),
    )
    # Pending terms refuse data calls (policy 5.4); the report is one.
    if "count" in p and user.pw_reset_t_and_c:
        devices.record_outstanding(
            issued.session, p.get("count"), p.get("unique_ids"), p.get("client_draft_ids"), p.get("client_death_ids")
        )
    db.session.commit()
    return jsonify(_session_body(issued, user)), 200


# ---------------------------------------------------------------------------
# Bearer-authenticated
# ---------------------------------------------------------------------------


@bp.delete("/sessions/current")
@login_required
def end_session():
    """Sign-out. ``login_required``, not the interviewer role: an interviewer
    whose grant was withdrawn must still be able to sign out."""
    session = g.get("device_session")
    if session is None:  # a browser cookie has no device session to end
        return _error("Authentication required.", "unauthorized", 401)
    devices.end_session(session)
    db.session.commit()
    return "", 204
