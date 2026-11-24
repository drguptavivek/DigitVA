import uuid
from time import perf_counter

from flask import flash, g, jsonify, redirect, request, session, url_for
from flask_login import current_user, logout_user
from flask_wtf.csrf import generate_csrf

from app import db
from app.decorators.role_required import API_PATH_PREFIXES
from app.models import VaUsers

# Modules, not names: tests patch get_temporary_ban, request_bearer_token and
# should_block_non_admin_after_cutoff at their source, read here per call.
from app.services import device_auth_service, request_abuse_service, site_maintenance_service

#: Paths whose responses carry Server-Timing / X-Response-Time.
_TIMED_PREFIXES = (
    "/data-management",
    "/api/v1/data-management",
    "/api/v1/analytics",
)

#: Endpoints a user with pending terms may still reach.
_TERMS_EXEMPT_ENDPOINTS = frozenset({
    'static',
    'profile.force_password_change',
    'va_auth.va_logout',
    'va_auth.va_login',
    'va_auth.forgot_password',
    'va_auth.reset_password',
    'va_auth.verify_email',
    'va_auth.resend_verification',
    'api_v1.profile_api.accept_terms',
    'api_v1.me_api.accept_terms',
    # Sign-out must work while the terms are pending (onboarding
    # policy 5.4); accepting is me_api.accept_terms above.
    'api_v1.auth_api.end_session',
})


def register_force_password_update(app):
    """Request timers, the temporary IP ban, the maintenance cutoff and the
    password/terms gate, in that order, as one before_request hook."""

    @app.before_request
    def force_password_update():
        if request.path.startswith("/static") or request.path == "/health":
            return
        _start_request_timers()
        ban_refusal = _temporary_ban_refusal(app)
        if ban_refusal is not None:
            return ban_refusal
        gated = _gated_user()
        if gated is None:
            return
        fresh_user, is_bearer = gated
        maintenance_refusal = _maintenance_refusal(fresh_user, is_bearer)
        if maintenance_refusal is not None:
            return maintenance_refusal
        return _terms_refusal(fresh_user, is_bearer)


def _start_request_timers():
    """Start the timers apply_static_cache_headers reads (app/hooks/cache_headers.py)."""
    if request.path.startswith(_TIMED_PREFIXES):
        g._request_started_at = perf_counter()
    g._slow_started_at = perf_counter()
    # g outlives the request when an app context is already pushed (tests).
    g._sql_count, g._sql_ms = 0, 0.0


def _temporary_ban_refusal(app):
    """A 403 with Retry-After for a temporarily banned IP, else None."""
    temporary_ban = request_abuse_service.get_temporary_ban(request.remote_addr)
    if temporary_ban is None:
        return None
    app.logger.warning(
        "blocked_temporarily_banned_ip ip=%s method=%s path=%s remaining_seconds=%s",
        request.remote_addr,
        request.method,
        request.path,
        temporary_ban["remaining_seconds"],
    )
    message = request_abuse_service.abuse_ban_message()
    if request.path.startswith("/api/") or request.path.startswith("/admin/api/"):
        response = jsonify({"error": message, "code": "temporarily_blocked"})
    else:
        response = app.response_class(
            f"{message}\n",
            status=403,
            mimetype="text/plain",
        )
    response.status_code = 403
    response.headers["Retry-After"] = str(
        temporary_ban["remaining_seconds"]
    )
    return response


def _gated_user():
    """``(user, is_bearer)`` for the user the gates below check, or None when
    the request is not gated (anonymous, unpinned bearer, unknown or
    inactive user)."""
    # A bearer request has no session: its user is the one
    # authenticate_bearer pinned. The gates below answer it in JSON.
    is_bearer = device_auth_service.request_bearer_token(request) is not None
    if is_bearer:
        if not g.get("bearer_auth"):
            return None
        return current_user._get_current_object(), True
    # A cookie whose session version no longer matches (password
    # reset) resolves to anonymous: no gating, so login can run.
    if not current_user.is_authenticated:
        return None
    current_user_id = session.get("_user_id")
    if not current_user_id:
        return None
    # Flask-Login's session value is VaUsers.get_id(), "<uuid>" or
    # "<uuid>:<version>" once a session version is set — see
    # VaUsers.get_id / load_user.
    raw_uid, _sep, _version = current_user_id.rpartition(":")
    try:
        current_user_id = uuid.UUID(raw_uid or current_user_id)
    except (TypeError, ValueError):
        return None

    fresh_user = db.session.get(VaUsers, current_user_id)
    if fresh_user is None or not fresh_user.is_active:
        return None
    return fresh_user, False


def _maintenance_refusal(fresh_user, is_bearer):
    """Refuse a non-admin after the maintenance cutoff, else None. A cookie
    session is signed out first."""
    if fresh_user.is_admin() or not site_maintenance_service.should_block_non_admin_after_cutoff():
        return None
    if is_bearer:
        return jsonify({"error": "Site is under maintenance.", "code": "maintenance"}), 403
    logout_user()
    flash(
        "Site is under maintenance. Only admin login is allowed right now.",
        "warning",
    )
    if (
        request.path.startswith("/api/")
        or request.path.startswith("/admin/api/")
        or request.path.startswith("/api/v1/")
    ):
        return jsonify(
            {
                "error": "Site is under maintenance. Only admin login is allowed right now.",
                "code": "maintenance",
            }
        ), 401
    return redirect(url_for("va_auth.va_login"))


def _terms_refusal(fresh_user, is_bearer):
    """Refuse a user with pending terms outside the exempt endpoints, else None."""
    if fresh_user.pw_reset_t_and_c is not False or request.endpoint in _TERMS_EXEMPT_ENDPOINTS:
        return None
    if is_bearer:
        return jsonify({
            "error": "Accept the terms of use to continue.",
            "code": "terms_required",
        }), 403
    # Every JSON path gets terms_required (onboarding policy 5.4).
    if not request.path.startswith(API_PATH_PREFIXES):
        return redirect(url_for('profile.force_password_change'))
    response = jsonify({
        "error": "Accept the terms of use to continue.",
        "code": "terms_required",
        "redirect_url": url_for('profile.force_password_change'),
    })
    response.status_code = 403
    response.headers["Cache-Control"] = "no-store"
    # A browser client with pending terms cannot reach me/access for
    # its CSRF token, so the refusal carries one for POST me/terms.
    response.headers["X-CSRFToken"] = generate_csrf()
    return response
