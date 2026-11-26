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
included. Terms and maintenance gates are the app-level ones in app/hooks/terms_gate.py.
"""

import functools
import logging
from datetime import UTC, datetime

from flask import Blueprint, abort, current_app, g, jsonify, request
from flask_limiter.util import get_remote_address
from flask_login import current_user, login_required
from werkzeug.exceptions import RequestEntityTooLarge

from app.utils.limit_keys import keyed_digest
from app import csrf, db, limiter
from app.models import VaProjectMaster
from app.routes.api.request_helpers import error as _error
from app.routes.api.request_helpers import parse_body
from app.services import device_auth_service as devices
from app.services import device_signing_service as signing
from app.services import email_service, mobile_sign_in_service, public_demo_service
from app.services import sign_in_qr_service as sign_in_qr
from app.services import user_account_service as accounts
from app.services.access_summary_service import build_access_summary
from app.services.pow_captcha_service import issue_challenge, verify_challenge
from app.services.site_maintenance_service import should_block_non_admin_after_cutoff
from app.services.user_account_service import canonical_mobile

bp = Blueprint("auth_api", __name__)
log = logging.getLogger(__name__)

#: The state-changing views that skip CSRF, named one by one so a new route in
#: this blueprint is CSRF-checked unless it is added here on purpose (policy:
#: api-v1.md rule 5). Each takes its credential from the body or a bearer, never
#: the cookie session, and none signs the browser in; the three bearer-only ones
#: refuse a cookie before reading the body.
CSRF_EXEMPT_VIEWS = (
    "enroll", "open_session", "password_enroll", "redeem_sign_in_code",
    "forgot_password", "redeem_sign_in_qr", "demo_enroll", "demo_signup",
    "record_profile_deletion", "refresh_session",
    "set_device_signing_key", "set_device_project", "end_session",
)
for _view in CSRF_EXEMPT_VIEWS:
    csrf.exempt(f"{__name__}.{_view}")

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
        # Canonicalise before truncating: a padded number cut at 128 would no
        # longer parse and would get a fresh bucket per spacing variant.
        text = str(value).strip().lower()[:512] if value else ""
        if name in {"email", "identifier"} and text and "@" not in text:
            text = canonical_mobile(text) or text
        return f"device-{name}:{text[:128]}"
    return key


#: A typed mobile number is at most 16 characters ("+91 98765 43210" is 15);
#: anything longer is refused before it is read (owner 2026-11-19).
MOBILE_MAX_CHARS = 16


def _mobile_too_long(value) -> bool:
    """A sign-in identifier without "@" that is longer than a mobile number."""
    return isinstance(value, str) and "@" not in value and len(value.strip()) > MOBILE_MAX_CHARS


def _mobile_too_long_error(field):
    return _error(f"A mobile number has at most {MOBILE_MAX_CHARS} characters.", "invalid_request", 400,
                  fields=[field])


_keyed_digest = keyed_digest


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
    return _error(str(exc), exc.code, exc.status_code, **(exc.extra or {}), **extra)


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


def _enrolment_reply(device, secret) -> dict:
    """``{device_id, device_secret, project, server_time}``, the reply every
    enrolment route starts from; old APKs read these keys. Each route adds its
    own extras (``signing_key_id``, ``projects``, session tokens)."""
    project = db.session.get(VaProjectMaster, device.project_id)
    return {
        "device_id": str(device.device_id),
        "device_secret": secret,
        "project": {"project_id": project.project_id, "name": project.project_name},
        "server_time": datetime.now(UTC).isoformat(),
    }


def _demo_only(view):
    """404 unless the public demo is enabled; innermost decorator, so the
    limiter and body-size checks still run first."""
    @functools.wraps(view)
    def wrapper(*args, **kwargs):
        if not public_demo_service.enabled():
            abort(404)
        return view(*args, **kwargs)
    return wrapper


def _parse_signing_key(p):
    """The optional ``signing_public_key`` of an enrolment body, parsed (None if absent)."""
    if p.get("signing_public_key") is None:
        return None
    return signing.parse_public_key(p["signing_public_key"])


@bp.post("/enroll")
@limiter.limit("10 per minute")
def enroll():
    """Optional ``signing_public_key`` (base64url Ed25519, 32 bytes): checked
    before the code is consumed, so a bad key never burns a single-use code;
    the reply then adds ``signing_key_id``. Optional ``client_device_uuid``
    (Collect Plus install UUID): validated the same way, stored on the device."""
    p = _body()
    client_uuid = devices.parse_client_device_uuid(p.get("client_device_uuid"))
    public_key = _parse_signing_key(p)
    device, secret = devices.enrol_device(
        p.get("code"), device_name=p.get("device_name"), platform=p.get("platform"),
        app_version=p.get("app_version"), client_device_uuid=client_uuid,
    )
    extra = {}
    if public_key is not None:
        extra["signing_key_id"] = signing.set_signing_key(device, public_key, via="enroll")
    reply = {**_enrolment_reply(device, secret), **extra}
    db.session.commit()
    return jsonify(reply), 201


@bp.post("/sessions")
@limiter.limit("10 per minute")
@limiter.limit("10 per minute", key_func=_body_key("device_id"))
@limiter.limit("20 per hour", key_func=_keyed_digest(_body_key("email")))
def open_session():
    """Worker sign-in on an enrolled device (interviewer, death reporter, coder,
    coding tester, reviewer or interview supervisor, ``has_device_access``); the ``email`` field takes an
    email or a mobile number (docs/policy/mobile-sign-in.md), and on a
    ``PUBLIC_DEMO_ENABLED`` deployment a public-demo username
    (``user_account_service.sign_in_identifier``). Rate limits match the web
    password step (docs/policy/authentication-factors.md section 1), per IP,
    per device and per account; the device credential replaces the CAPTCHA.
    Optional ``replace_device_id``: at the device cap, the phone to sign out
    (``devices.check_device_slot``; mobile-sign-in.md)."""
    p = _body()
    # Public-demo usernames have no "@" either; the mobile rule is for real accounts.
    if not public_demo_service.enabled() and _mobile_too_long(p.get("email")):
        return _mobile_too_long_error("email")
    issued, user = devices.open_session(
        device_id=p.get("device_id"), device_secret=p.get("device_secret"),
        email=p.get("email"), password=p.get("password"), replace_device_id=p.get("replace_device_id"),
    )
    devices.record_app_version(issued.session, p.get("app_version"))
    # Build the reply before committing: a failure here must not leave a session
    # the phone never received.
    body = _session_body(issued, user)
    db.session.commit()
    return jsonify(body), 201


def _refused(response) -> bool:
    """A refused password or a sign-in code that did not match (401): the
    only replies the failure-only limits count."""
    return response.status_code == 401


@bp.post("/password-enroll")
# A training room of ~30 phones shares one address (field sign-in 2026-11-16),
# so per IP all requests are only a flood guard; wrong passwords have their own
# tighter per-IP budget against spraying one password across many accounts.
@limiter.limit("120 per minute")
@limiter.limit("60 per 10 minutes", deduct_when=_refused)
@limiter.limit("20 per hour", key_func=_keyed_digest(_body_key("identifier")))
def password_enroll():
    """Enrol and sign in with an email/mobile identifier and password.

    Accepts ``identifier, password, device_name, platform, app_version?``,
    ``client_device_uuid?`` and ``replace_device_id?`` (at the device cap, the
    phone to sign out; ``devices.check_device_slot``). Returns the combined QR enrolment/session body
    plus ``projects`` (every eligible home; ``project`` stays the default);
    any refusal rolls back both device and session (mobile-sign-in.md).
    404 on the public-demo deployment, which has its own enrolment flow.
    """
    if public_demo_service.enabled():
        abort(404)
    p = _body()
    if _mobile_too_long(p.get("identifier")):
        return _mobile_too_long_error("identifier")
    device, secret, issued, user = devices.enrol_with_password(
        identifier=p.get("identifier"), password=p.get("password"),
        device_name=p.get("device_name"), platform=p.get("platform"),
        app_version=p.get("app_version"), client_device_uuid=p.get("client_device_uuid"),
        replace_device_id=p.get("replace_device_id"),
    )
    body = {
        **_enrolment_reply(device, secret),
        "projects": devices.eligible_device_projects(user),
        **_session_body(issued, user),
    }
    db.session.commit()
    return jsonify(body), 201


@bp.post("/sign-in-code/redeem")
# Per IP loose on purpose: a training room of ~30 phones shares one Wi-Fi
# address (field sign-in 2026-11-16). The five-attempt void per code and the
# per-identifier hour are the guess limits (docs/policy/mobile-sign-in.md s.3).
@limiter.limit("200 per minute")
# Wrong codes only: bounds guessing and the breach check each request makes
# before the code is read, without throttling a room's successful redeems.
@limiter.limit("100 per 10 minutes", deduct_when=_refused)
# Mismatches only, so a stranger cannot keep a trainee locked out with 400s,
# and a correct code is never refused for someone else's typos.
@limiter.limit("10 per hour", key_func=_keyed_digest(_body_key("identifier")), deduct_when=_refused)
def redeem_sign_in_code():
    """"I have a sign-in code" in the app (docs/policy/mobile-sign-in.md
    section 3): ``{identifier, code, accept_terms}``, the web page's
    redemption (``redeem_code_and_accept_terms``) without its CAPTCHA.
    ``accept_terms`` must be ``true``, as the web form requires the box;
    otherwise, or for a missing or oversized field, 400 ``invalid_request``
    before anything is read or counted. 200 ``{password}`` once, no-store;
    the app then signs in through ``/password-enroll``. Every mismatch is one
    401 ``invalid_code``; a breach-check outage is 503
    ``breach_check_unavailable`` with nothing counted. 404 on the public-demo
    deployment, which has no password enrolment.
    """
    if public_demo_service.enabled():
        abort(404)
    p = _body()
    identifier, code = p.get("identifier"), p.get("code")
    if _mobile_too_long(identifier):
        return _mobile_too_long_error("identifier")
    bad = [name for name, value, cap in (("identifier", identifier, 128), ("code", code, 32))
           if not isinstance(value, str) or not value.strip() or len(value) > cap]
    if p.get("accept_terms") is not True:
        bad.append("accept_terms")
    if bad:
        return _error("Enter your email or mobile number and code, and accept the terms.",
                      "invalid_request", 400, fields=bad)
    try:
        password = mobile_sign_in_service.redeem_code_and_accept_terms(identifier, code)
    except mobile_sign_in_service.PasswordGenerationUnavailable as exc:
        return _error(exc.message, "breach_check_unavailable", 503)
    if password is None:
        return _error("That email or mobile number and code do not match.", "invalid_code", 401)
    response = jsonify({"password": password})
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response, 200


@bp.post("/forgot-password")
@limiter.limit("3 per hour")
@limiter.limit("3 per hour", key_func=_keyed_digest(_body_key("identifier")))
def forgot_password():
    """"Forgot password" in the app (account-onboarding-and-passwords.md
    section 6): ``{identifier}``, an email or mobile number (1..254), else 400
    ``invalid_request`` before anything is read. The web page's request
    (``request_password_reset``): a reset link only to a verified email; 200
    ``{message}``, one per kind of identifier whether or not an account
    matches. 404 on the public-demo deployment, which has no passwords to reset.
    """
    if public_demo_service.enabled():
        abort(404)
    identifier = _body().get("identifier")
    if not isinstance(identifier, str) or not identifier.strip() or len(identifier) > 254:
        return _error("Enter your email or mobile number.", "invalid_request", 400, fields=["identifier"])
    if _mobile_too_long(identifier):
        return _mobile_too_long_error("identifier")
    return jsonify({"message": accounts.request_password_reset(identifier)}), 200


@bp.post("/sign-in-qr/redeem")
@limiter.limit("10 per minute")
@limiter.limit("5 per minute", key_func=lambda: sign_in_qr.token_limit_key(_safe_body().get("token")))
def redeem_sign_in_qr():
    """Scan a sign-in QR (docs/policy/mobile-sign-in.md section 8): ``{token,
    device_name, platform, app_version?, signing_public_key?, client_device_uuid?,
    replace_device_id?}`` (at the device cap, the phone to sign out). Enrols the
    device and opens that user's device session in one step; the reply is
    ``/enroll``'s plus ``/sessions``'s: 201 ``{device_id, device_secret,
    signing_key_id?, project, server_time, ...tokens, access}``. Every
    failure (unknown, used, expired, revoked, user no longer eligible) is one
    404 ``sign_in_qr_invalid``. Limits: per IP and per token digest (there is
    no device yet to key on). The user's email, if any, gets a notice."""
    p = _body()
    client_uuid = devices.parse_client_device_uuid(p.get("client_device_uuid"))
    public_key = _parse_signing_key(p)
    device, secret, issued, user = sign_in_qr.redeem(
        p.get("token"), device_name=p.get("device_name"), platform=p.get("platform"),
        app_version=p.get("app_version"), client_device_uuid=client_uuid,
        replace_device_id=p.get("replace_device_id"),
    )
    extra = {}
    if public_key is not None:
        extra["signing_key_id"] = signing.set_signing_key(device, public_key, via="enroll")
    body = {
        **_enrolment_reply(device, secret),
        **extra,
        "projects": devices.eligible_device_projects(user),
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
@limiter.limit("20 per hour", key_func=_keyed_digest(_body_key("username")))
@_demo_only
def demo_enroll():
    """Enrol the app on the public demo without a QR code (docs/policy/
    public-demo.md section 10): ``{username, password, device_name, platform,
    app_version?, replace_device_id?}``. The credentials are checked as ``POST /sessions`` checks
    them, with its uniform answer: 401 ``invalid_credentials`` for an unknown
    name, a wrong password or an account that is not a public-demo account.
    Then a device is enrolled on the demo project and the reply is
    ``/enroll``'s: 201 ``{device_id, device_secret, project, server_time}``
    (the secret is shown once). At most ``PUBLIC_DEMO_DEVICES_PER_ACCOUNT``
    live devices per account: 429 ``demo_limit``. 404 unless
    ``PUBLIC_DEMO_ENABLED``; 503 ``wrong_database`` on a database that holds
    another project. At the three-phone cap 409 ``device_limit`` lists the
    account's phones; ``replace_device_id`` signs one out as ``/sessions``
    does. The app then signs in through ``POST /sessions``."""
    p = _body()
    client_uuid = devices.parse_client_device_uuid(p.get("client_device_uuid"))
    try:
        public_demo_service.require_demo_database()
    except public_demo_service.PublicDemoError as exc:
        return _error(exc.message, exc.code, exc.status_code)
    device, secret = devices.enrol_demo_device(
        username=p.get("username"), password=p.get("password"), device_name=p.get("device_name"),
        platform=p.get("platform"), app_version=p.get("app_version"), client_device_uuid=client_uuid,
        replace_device_id=p.get("replace_device_id"),
    )
    reply = _enrolment_reply(device, secret)
    db.session.commit()
    return jsonify(reply), 201


@bp.get("/demo-signup/challenge")
@limiter.limit("30 per minute", key_func=public_demo_service.signup_remote_key)
@_demo_only
def demo_signup_challenge():
    """A fresh proof-of-work challenge for ``POST /demo-signup``
    (``pow_captcha_service.issue_challenge``, the web form's challenge): 200
    ``{salt, difficulty, expires, signature}``. Stateless and signed, valid
    for five minutes, spent by one successful verification. 404 unless
    ``PUBLIC_DEMO_ENABLED``."""
    return jsonify(issue_challenge()), 200


@bp.post("/demo-signup")
@limiter.limit("10 per minute", key_func=public_demo_service.signup_remote_key)
@_demo_only
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


@bp.post("/profile-deletions")
@limiter.limit("10 per minute")
@limiter.limit("10 per minute", key_func=_body_key("device_id"))
def record_profile_deletion():
    """The phone deleted one profile (docs/policy/mobile-sign-in.md section
    10). Device credentials, not a bearer, so a retry after the sessions end
    still answers: ``{device_id, device_secret, user_id, unsent_count (int or
    null when unknown), loss_confirmed}``. 201 ``{recorded: true}``, 200
    ``{recorded: false}`` on a retry; 400 ``invalid_request`` /
    ``confirmation_required``, 401 ``device_invalid``, 403
    ``profile_not_on_device``, 409 ``unsent_work``."""
    p = _body()
    recorded = devices.record_profile_deletion(
        device_id=p.get("device_id"), device_secret=p.get("device_secret"),
        user_id=p.get("user_id"), unsent_count=p.get("unsent_count"),
        loss_confirmed=p.get("loss_confirmed", False),
    )
    db.session.commit()
    return jsonify({"recorded": recorded}), 201 if recorded else 200


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
    # Build the reply before committing: a failure here must not commit a
    # rotation the phone never received (its retry would hit refresh_retry_race).
    body = _session_body(issued, user)
    db.session.commit()
    return jsonify(body), 200


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


@bp.post("/devices/current/project")
@login_required
@limiter.limit("10 per minute")
def set_device_project():
    """Set the calling device's home project: ``{project_id}``, one of the
    ``projects`` the enrolment reply listed (docs/policy/mobile-sign-in.md).
    200 ``{project: {project_id, name}}``; 403 ``project_not_eligible``; a
    browser cookie has no device: 403 ``device_session_required``."""
    session = g.get("device_session")
    if session is None:
        return _error("Only a device session sets a home project.", "device_session_required", 403)
    device = devices.set_device_project(session.device_id, current_user, _body().get("project_id"))
    project = db.session.get(VaProjectMaster, device.project_id)
    db.session.commit()
    return jsonify({"project": {"project_id": project.project_id, "name": project.project_name}}), 200


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
