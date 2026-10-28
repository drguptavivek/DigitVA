"""Sign-in routes for every client, under /api/v1/auth.

Enrol a device, open and refresh a device session, end it, set the device's
bundle-signing key. Rules live in ``device_auth_service`` (enrolment, sessions,
tokens) and ``device_signing_service`` (signing keys); this layer parses and
serializes. Sign-in and refresh replies carry ``access`` with native worker
grants, matching bearer ``GET /api/v1/me/access`` (docs/current-state/api-v1.md).
Cookie requests to that endpoint retain full account access. Policy:
docs/policy/field-data-collection.md, docs/policy/api-v1.md.

Errors are ``{"error": ..., "code": ...}`` plus ``fields`` when the refusal
names the inputs to fix. Request bodies are capped
(``_body_limit``) before anything reads them, the rate limiter's key functions
included. Terms and maintenance gates are the app-level ones in app/__init__.py.
"""

import logging
from datetime import UTC, datetime

from flask import Blueprint, abort, g, jsonify, request
from flask_limiter.util import get_remote_address
from flask_login import login_required
from werkzeug.exceptions import RequestEntityTooLarge

from app import csrf, db, limiter
from app.models import VaProjectMaster
from app.routes.api.request_helpers import error as _error
from app.routes.api.request_helpers import parse_body
from app.services import device_auth_service as devices
from app.services import device_signing_service as signing
from app.services import email_service, public_demo_service
from app.services import sign_in_qr_service as sign_in_qr
from app.services.access_summary_service import build_access_summary
from app.services.pow_captcha_service import issue_challenge, verify_challenge
from app.services.site_maintenance_service import should_block_non_admin_after_cutoff
from app.services.user_account_service import canonical_mobile

bp = Blueprint("auth_api", __name__)
log = logging.getLogger(__name__)
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


def _safe_body() -> dict:
    try:
        return _body()
    except RequestEntityTooLarge:
        return {}


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
        if name in {"email", "identifier"} and text and "@" not in text:
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
    extra = {"fields": exc.fields} if exc.fields else {}
    return _error(str(exc), exc.code, exc.status_code, **extra)


# ---------------------------------------------------------------------------
# Enrolment and sessions (no bearer token yet)
# ---------------------------------------------------------------------------


def _session_body(issued, user) -> dict:
    """The token reply plus ``access``. Display-only, so a user with pending
    terms still gets it; the terms gate is a request hook, not this service."""
    # Session replies are issued to the native app, so their access summary
    # must use the same device credential projection as bearer requests.  A
    # mixed admin/collector account must not receive admin or data-manager
    # reach merely because this response is built before bearer auth exists.
    return {
        **devices.serialize_tokens(issued, user),
        "access": build_access_summary(user, native=True),
    }


@bp.post("/enroll")
@limiter.limit("10 per minute")
def enroll():
    """Optional ``signing_public_key`` (base64url Ed25519, 32 bytes): checked
    before the code is consumed, so a bad key never burns a single-use code;
    the reply then adds ``signing_key_id``. Optional ``client_device_uuid``
    (Collect Plus install UUID): validated the same way, stored on the device."""
    p = _body()
    client_uuid = devices.parse_client_device_uuid(p.get("client_device_uuid"))
    public_key = None
    if p.get("signing_public_key") is not None:
        public_key = signing.parse_public_key(p["signing_public_key"])
    device, secret = devices.enrol_device(
        p.get("code"), device_name=p.get("device_name"), platform=p.get("platform"),
        app_version=p.get("app_version"), client_device_uuid=client_uuid,
    )
    reply = {
        "device_id": str(device.device_id),
        "device_secret": secret,
    }
    if public_key is not None:
        reply["signing_key_id"] = signing.set_signing_key(device, public_key, via="enroll")
    project = db.session.get(VaProjectMaster, device.project_id)
    db.session.commit()
    return jsonify({
        **reply,
        "project": {"project_id": project.project_id, "name": project.project_name},
        "server_time": datetime.now(UTC).isoformat(),
    }), 201


@bp.post("/sessions")
@limiter.limit("10 per minute")
@limiter.limit("10 per minute", key_func=_body_key("device_id"))
@limiter.limit("20 per hour", key_func=_body_key("email"))
def open_session():
    """Worker sign-in on an enrolled device (interviewer, coder, coding tester or
    reviewer, ``has_device_access``); the ``email`` field takes an
    email or a mobile number (docs/policy/mobile-sign-in.md), and on a
    ``PUBLIC_DEMO_ENABLED`` deployment a public-demo username
    (``user_account_service.sign_in_identifier``). Rate limits match the web
    password step (docs/policy/authentication-factors.md section 1), per IP,
    per device and per account; the device credential replaces the CAPTCHA."""
    p = _body()
    issued, user = devices.open_session(
        device_id=p.get("device_id"), device_secret=p.get("device_secret"),
        email=p.get("email"), password=p.get("password"),
    )
    devices.record_app_version(issued.session, p.get("app_version"))
    db.session.commit()
    return jsonify(_session_body(issued, user)), 201


@bp.post("/password-enroll")
@limiter.limit("10 per minute")
@limiter.limit("20 per hour", key_func=_body_key("identifier"))
def password_enroll():
    """Enrol and sign in with an email/mobile identifier and password.

    Accepts ``identifier, password, device_name, platform, app_version?`` and
    ``client_device_uuid?``. Returns the combined QR enrolment/session body;
    any refusal rolls back both device and session (mobile-sign-in.md).
    404 on the public-demo deployment, which has its own enrolment flow.
    """
    if public_demo_service.enabled():
        abort(404)
    p = _body()
    device, secret, issued, user = devices.enrol_with_password(
        identifier=p.get("identifier"), password=p.get("password"),
        device_name=p.get("device_name"), platform=p.get("platform"),
        app_version=p.get("app_version"), client_device_uuid=p.get("client_device_uuid"),
    )
    project = db.session.get(VaProjectMaster, device.project_id)
    body = {
        "device_id": str(device.device_id),
        "device_secret": secret,
        "project": {"project_id": project.project_id, "name": project.project_name},
        "server_time": datetime.now(UTC).isoformat(),
        **_session_body(issued, user),
    }
    db.session.commit()
    return jsonify(body), 201


@bp.post("/sign-in-qr/redeem")
@limiter.limit("10 per minute")
@limiter.limit("5 per minute", key_func=lambda: sign_in_qr.token_limit_key(_safe_body().get("token")))
def redeem_sign_in_qr():
    """Scan a sign-in QR (docs/policy/mobile-sign-in.md section 8): ``{token,
    device_name, platform, app_version?, signing_public_key?, client_device_uuid?}``. Enrols the
    device and opens that user's device session in one step; the reply is
    ``/enroll``'s plus ``/sessions``'s: 201 ``{device_id, device_secret,
    signing_key_id?, project, server_time, ...tokens, access}``. Every
    failure (unknown, used, expired, revoked, user no longer eligible) is one
    404 ``sign_in_qr_invalid``. Limits: per IP and per token digest (there is
    no device yet to key on). The user's email, if any, gets a notice."""
    p = _body()
    client_uuid = devices.parse_client_device_uuid(p.get("client_device_uuid"))
    public_key = None
    if p.get("signing_public_key") is not None:
        public_key = signing.parse_public_key(p["signing_public_key"])
    device, secret, issued, user = sign_in_qr.redeem(
        p.get("token"), device_name=p.get("device_name"), platform=p.get("platform"),
        app_version=p.get("app_version"), client_device_uuid=client_uuid,
    )
    reply = {"device_id": str(device.device_id), "device_secret": secret}
    if public_key is not None:
        reply["signing_key_id"] = signing.set_signing_key(device, public_key, via="enroll")
    project = db.session.get(VaProjectMaster, device.project_id)
    body = {
        **reply,
        "project": {"project_id": project.project_id, "name": project.project_name},
        "server_time": datetime.now(UTC).isoformat(),
        **_session_body(issued, user),
    }
    db.session.commit()
    try:
        email_service.send_sign_in_qr_redeemed_notice(user)
    except Exception as exc:  # the notice never fails a completed sign-in
        log.warning("sign-in QR notice failed: %s | user_id=%s", type(exc).__name__, user.user_id)
    return jsonify(body), 201


@bp.post("/demo-enroll")
@limiter.limit("10 per minute", key_func=public_demo_service.signup_remote_key)
@limiter.limit("20 per hour", key_func=_body_key("username"))
def demo_enroll():
    """Enrol the app on the public demo without a QR code (docs/policy/
    public-demo.md section 10): ``{username, password, device_name, platform,
    app_version?}``. The credentials are checked as ``POST /sessions`` checks
    them, with its uniform answer: 401 ``invalid_credentials`` for an unknown
    name, a wrong password or an account that is not a public-demo account.
    Then a device is enrolled on the demo project and the reply is
    ``/enroll``'s: 201 ``{device_id, device_secret, project, server_time}``
    (the secret is shown once). At most ``PUBLIC_DEMO_DEVICES_PER_ACCOUNT``
    live devices per account: 429 ``demo_limit``. 404 unless
    ``PUBLIC_DEMO_ENABLED``; 503 ``wrong_database`` on a database that holds
    another project. The app then signs in through ``POST /sessions``."""
    if not public_demo_service.enabled():
        abort(404)
    p = _body()
    client_uuid = devices.parse_client_device_uuid(p.get("client_device_uuid"))
    try:
        public_demo_service.require_demo_database()
    except public_demo_service.PublicDemoError as exc:
        return _error(exc.message, exc.code, exc.status_code)
    device, secret = devices.enrol_demo_device(
        username=p.get("username"), password=p.get("password"), device_name=p.get("device_name"),
        platform=p.get("platform"), app_version=p.get("app_version"), client_device_uuid=client_uuid,
    )
    project = db.session.get(VaProjectMaster, device.project_id)
    db.session.commit()
    return jsonify({
        "device_id": str(device.device_id),
        "device_secret": secret,
        "project": {"project_id": project.project_id, "name": project.project_name},
        "server_time": datetime.now(UTC).isoformat(),
    }), 201


@bp.get("/demo-signup/challenge")
@limiter.limit("30 per minute", key_func=public_demo_service.signup_remote_key)
def demo_signup_challenge():
    """A fresh proof-of-work challenge for ``POST /demo-signup``
    (``pow_captcha_service.issue_challenge``, the web form's challenge): 200
    ``{salt, difficulty, expires, signature}``. Stateless and signed, valid
    for five minutes, spent by one successful verification. 404 unless
    ``PUBLIC_DEMO_ENABLED``."""
    if not public_demo_service.enabled():
        abort(404)
    return jsonify(issue_challenge()), 200


@bp.post("/demo-signup")
@limiter.limit("10 per minute", key_func=public_demo_service.signup_remote_key)
def demo_signup():
    """Public-demo sign-up for the Android app (docs/policy/public-demo.md
    sections 2 and 10): ``{username, password, captcha}``, where ``captcha``
    is a challenge from ``GET /demo-signup/challenge`` plus its ``solution``
    (``{salt, difficulty, expires, signature, solution}``), checked by
    ``pow_captcha_service.verify_challenge`` exactly as the web form's; a
    missing or wrong one is 400 ``captcha_failed``. 404 unless
    ``PUBLIC_DEMO_ENABLED``. The per-client (IPv6 per /64) and demo-wide
    quotas are spent atomically on success before the commit
    (``hit_signup_quota``; a spent quota answers the limiter's 429), and the
    global account cap bounds it. 201 ``{user_id, username}`` and no session;
    the app then signs in through ``POST /sessions``. Refusals are
    ``{error, code, fields}`` with ``public_demo_service.create_account``'s
    codes."""
    if not public_demo_service.enabled():
        abort(404)
    p = _body()
    if should_block_non_admin_after_cutoff():
        return _error("Site is under maintenance.", "maintenance", 503)
    captcha = p.get("captcha")
    if not isinstance(captcha, dict) or not verify_challenge(
        salt=captcha.get("salt"), difficulty=captcha.get("difficulty"),
        expires=captcha.get("expires"), signature=captcha.get("signature"),
        solution=captcha.get("solution"),
    ):
        return _error("We couldn't verify that request. Please try again.", "captcha_failed", 400,
                      fields=["captcha"])
    try:
        user = public_demo_service.create_account(p.get("username"), p.get("password"), via="api")
    except public_demo_service.PublicDemoError as exc:
        db.session.rollback()
        extra = {"fields": [exc.field]} if exc.field else {}
        return _error(exc.message, exc.code, exc.status_code, **extra)
    if not public_demo_service.hit_signup_quota(get_remote_address()):
        db.session.rollback()
        abort(429)
    db.session.commit()
    return jsonify({"user_id": str(user.user_id), "username": user.username}), 201


@bp.post("/sessions/refresh")
@limiter.limit("30 per minute")
def refresh_session():
    """Rotate the refresh token, presented with the device's id and secret;
    optional ``count``/``unique_ids``/``client_draft_ids``/``client_death_ids`` record the
    outstanding-work report in the same call. The session lasts while
    ``has_device_access`` holds for the worker."""
    p = _body()
    issued, user = devices.refresh_session(
        p.get("refresh_token"), device_id=p.get("device_id"), device_secret=p.get("device_secret"),
    )
    devices.record_app_version(issued.session, p.get("app_version"))
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


@bp.post("/devices/current/signing-key")
@login_required
@limiter.limit("10 per minute")
def set_device_signing_key():
    """Set the calling device's Ed25519 bundle-signing key, once. The device
    is the bearer session's, never named in the body; a browser cookie has
    none: 403 ``device_session_required``."""
    session = g.get("device_session")
    if session is None:
        return _error("Only a device session sets a signing key.", "device_session_required", 403)
    key_id = signing.set_current_device_key(session.device_id, _body().get("signing_public_key"))
    db.session.commit()
    return jsonify({"signing_key_id": key_id}), 200


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
