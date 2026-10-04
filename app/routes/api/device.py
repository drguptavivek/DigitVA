"""Device API for the Android collection app (Path B), under /api/v1/device.

Contract: .tasks/2026-09-30-android-collection-app.md ("API contract").
Policy: docs/policy/field-data-collection.md. Rules live in
``device_auth_service`` (enrolment, sessions, tokens) and
``web_intake_service`` (uploads); this layer parses and serializes.

No cookies: every call after sign-in carries ``Authorization: Bearer``,
authenticated by the ``authenticate_bearer`` hook in app/__init__.py (the
same credential every /api/v1 route accepts), and this blueprint refuses
any other kind of authentication (a browser's session cookie included). Errors are
``{"error": ..., "code": ...}``. Request bodies are capped (``_body_limit``)
before anything reads them, the rate limiter's key functions included.
"""

from datetime import UTC, datetime

from flask import Blueprint, g, jsonify, request
from flask_login import current_user, login_required
from werkzeug.exceptions import RequestEntityTooLarge

from app import csrf, db, limiter
from app.decorators import role_required
from app.models import VaProjectMaster
from app.routes.api.instruments import translations_response
from app.routes.api.organization import (
    form_options_payload,
    served_instrument_locales,
    units_payload,
)
from app.routes.api.request_helpers import error as _error
from app.routes.api.request_helpers import intake_error as _intake_error_body
from app.routes.api.request_helpers import interviewer_context as _interviewer_context
from app.routes.api.request_helpers import parse_body
from app.routes.api.request_helpers import request_project_id as _request_project_id
from app.services import device_auth_service as devices
from app.services import web_intake_service as intake_svc
from app.services.site_maintenance_service import should_block_non_admin_after_cutoff
from app.services.user_account_service import canonical_mobile
from app.utils.who_va_bundle import who_va_bundle_version

bp = Blueprint("device", __name__)
csrf.exempt(bp)

#: Endpoints reachable without a device session (they create one).
_UNAUTHENTICATED = devices.UNAUTHENTICATED_ENDPOINTS
#: Bearer endpoints open while the terms are pending (onboarding policy 5.4).
_TERMS_EXEMPT = frozenset({"end_session", "accept_terms"})

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
    if not user.pw_reset_t_and_c and endpoint not in _TERMS_EXEMPT:
        return _error("Accept the terms of use to continue.", "terms_required", 403)
    return None


@bp.errorhandler(RequestEntityTooLarge)
def _too_large(_exc):
    return _error("The request body is too large.", "payload_too_large", 413)


@bp.errorhandler(devices.DeviceAuthError)
def _device_auth_error(exc):
    db.session.rollback()
    return _error(str(exc), exc.code, exc.status_code)


@bp.errorhandler(intake_svc.WebIntakeError)
def _intake_error(exc):
    db.session.rollback()
    return _intake_error_body(exc)


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
    return jsonify(devices.serialize_tokens(issued, user)), 201


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


@bp.post("/terms")
@login_required
@limiter.limit("5 per minute", key_func=lambda: str(g.device_session.user_id))
def accept_terms():
    """The app's terms screen (onboarding policy 5.4): records the acceptance
    exactly as the web terms page does. Body ``{"accept_terms": true}``;
    anything else is 400 ``invalid_request``. ``login_required`` like
    sign-out: open to any signed-in account, before any role check."""
    from app.services.user_account_service import accept_terms as record_acceptance

    if _body().get("accept_terms") is not True:
        return _error("Please accept the terms of use.", "invalid_request", 400)
    record_acceptance(current_user._get_current_object(), via="device")
    db.session.commit()
    return jsonify({"message": "Terms accepted.", "terms_accepted": True})


@bp.get("/bootstrap")
@role_required("interviewer")
def bootstrap():
    """The intake bootstrap: ``projects`` has one entry per project this
    interviewer may collect in, with its sites, form options and offline
    prefill policy. Every other call names one of them as ``project_id``.
    No CSRF fields: there is no cookie session here."""
    by_project: dict[str, list] = {}
    for entry in _interviewer_context():
        by_project.setdefault(entry["project_id"], []).append(entry)
    projects = []
    for project_id, sites in by_project.items():
        # Already in the session's identity map: interviewer_context loaded it.
        authorized = db.session.get(VaProjectMaster, project_id)
        projects.append({
            "project_id": project_id,
            "project_name": authorized.project_name,
            "web_intake_mode": sites[0]["web_intake_mode"],
            "sites": sites,
            "form_options": form_options_payload(authorized),
            "prefill_policy": intake_svc.prefill_policy(current_user, project_id),
        })
    return jsonify({
        "user": {"user_id": str(current_user.user_id), "name": current_user.name},
        "instrument_version": who_va_bundle_version(),
        "projects": projects,
    })


@bp.get("/units")
@role_required("interviewer")
@limiter.limit("120 per minute")
def units():
    """The request project's organization units this interviewer may pick
    (``project_id``, required):
    the ``/api/v1/organization/<project>/units?role=interviewer`` body, scoped
    by interviewer grants only (a unit grant sees its subtree, plus ancestors
    as ``selectable: false`` context; a project grant or a site grant the whole
    tree, the same rule as the create-time check, ``intake_svc.reachable_unit_ids``)."""
    project_id = _request_project_id()
    reachable = intake_svc.reachable_unit_ids(current_user, project_id)
    if reachable is not None and not reachable:
        return _error("You have no organization units in this project.", "forbidden", 403)
    return jsonify(units_payload(project_id, reachable))


@bp.get("/instruments/<instrument_code>/translations/<locale>")
@role_required("interviewer")
@limiter.limit("120 per minute")
def instrument_translations(instrument_code, locale):
    """One locale's questionnaire strings: the ``/api/v1/instruments`` body
    and ETag, only for the instrument and locales the request project
    serves (its form options' default form type and ``available_locales``);
    ``project_id`` required."""
    code = (instrument_code or "").strip().upper()
    locale = (locale or "").strip()
    project = db.session.get(VaProjectMaster, _request_project_id())
    served_code, served_locales = served_instrument_locales(project)
    if code != served_code or locale not in served_locales:
        return _error("Translation not found.", "not_found", 404)
    response = translations_response(code, locale)
    if isinstance(response, tuple):  # the shared endpoint's 404
        return _error("Translation not found.", "not_found", 404)
    return response
