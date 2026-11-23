import uuid
from time import perf_counter

from flask import flash, g, jsonify, redirect, request, session, url_for
from flask_login import current_user


def register_force_password_update(app):
    """Request timers, the temporary IP ban, the maintenance cutoff and the
    password/terms gate, in that order, as one before_request hook."""
    timed_prefixes = (
        "/data-management",
        "/api/v1/data-management",
        "/api/v1/analytics",
    )

    @app.before_request
    def force_password_update():
        from app import db

        if request.path.startswith("/static") or request.path == "/health":
            return
        if request.path.startswith(timed_prefixes):
            g._request_started_at = perf_counter()
        g._slow_started_at = perf_counter()
        # g outlives the request when an app context is already pushed (tests).
        g._sql_count, g._sql_ms = 0, 0.0

        from app.services.request_abuse_service import (
            abuse_ban_message,
            get_temporary_ban,
        )

        temporary_ban = get_temporary_ban(request.remote_addr)
        if temporary_ban is not None:
            app.logger.warning(
                "blocked_temporarily_banned_ip ip=%s method=%s path=%s remaining_seconds=%s",
                request.remote_addr,
                request.method,
                request.path,
                temporary_ban["remaining_seconds"],
            )
            message = abuse_ban_message()
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

        from app.models import VaUsers
        from app.services.device_auth_service import request_bearer_token

        # A bearer request has no session: its user is the one
        # authenticate_bearer pinned. The gates below answer it in JSON.
        is_bearer = request_bearer_token(request) is not None
        if is_bearer:
            if not g.get("bearer_auth"):
                return
            fresh_user = current_user._get_current_object()
        else:
            # A cookie whose session version no longer matches (password
            # reset) resolves to anonymous: no gating, so login can run.
            if not current_user.is_authenticated:
                return
            current_user_id = session.get("_user_id")
            if not current_user_id:
                return
            # Flask-Login's session value is VaUsers.get_id(), "<uuid>" or
            # "<uuid>:<version>" once a session version is set — see
            # VaUsers.get_id / load_user.
            raw_uid, _sep, _version = current_user_id.rpartition(":")
            try:
                current_user_id = uuid.UUID(raw_uid or current_user_id)
            except (TypeError, ValueError):
                return

            fresh_user = db.session.get(VaUsers, current_user_id)
            if fresh_user is None or not fresh_user.is_active:
                return

        from flask_login import logout_user

        from app.services.site_maintenance_service import should_block_non_admin_after_cutoff

        if not fresh_user.is_admin() and should_block_non_admin_after_cutoff():
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

        allowed_endpoints = {
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
        }
        if fresh_user.pw_reset_t_and_c is False and request.endpoint not in allowed_endpoints:
            if is_bearer:
                return jsonify({
                    "error": "Accept the terms of use to continue.",
                    "code": "terms_required",
                }), 403
            from app.decorators.role_required import API_PATH_PREFIXES

            # Every JSON path gets terms_required (onboarding policy 5.4).
            if request.path.startswith(API_PATH_PREFIXES):
                code = "terms_required"
            else:
                return redirect(url_for('profile.force_password_change'))
            response = jsonify({
                "error": "Accept the terms of use to continue.",
                "code": code,
                "redirect_url": url_for('profile.force_password_change'),
            })
            response.status_code = 403
            response.headers["Cache-Control"] = "no-store"
            # A browser client with pending terms cannot reach me/access for
            # its CSRF token, so the refusal carries one for POST me/terms.
            from flask_wtf.csrf import generate_csrf

            response.headers["X-CSRFToken"] = generate_csrf()
            return response
