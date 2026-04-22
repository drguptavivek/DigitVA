"""role_required — single decorator for RBAC gating across all blueprints.

Replaces the three ad-hoc patterns that existed before:
  - @login_required + inline is_coder() / is_reviewer() / is_data_manager() checks
  - admin's require_api_role() + _request_user()
  - admin's _require_admin_ui_access() boilerplate

Usage::

    @bp.get("/some-route")
    @role_required("coder")
    def my_view():
        ...

    # OR-semantics: passes if the user holds ANY of the listed roles
    @bp.get("/some-route")
    @role_required("coder", "admin")
    def my_view():
        ...

HTTP status contract (must match base.js interceptor expectations):
  - Not authenticated          → 401  (base.js shows Session Expired modal)
  - User deactivated           → 401  (logout_user() first, then 401)
  - Authenticated, wrong role  → 403  (normal permission error, no modal)

For API routes (/api/* or /admin/api/*): JSON response.
For web routes: redirect to login (401) or flash + abort(403).

This decorator subsumes @login_required — do not stack both.
"""

import logging
from functools import wraps

from flask import jsonify, redirect, request, url_for
from flask_login import current_user, logout_user

from app.authz.scope import user_has_role, user_is_active
from app.utils.va_permission.va_permission_01_abortwithflash import (
    va_permission_abortwithflash,
)

log = logging.getLogger(__name__)

def role_required(*roles):
    """Gate a route by role. OR semantics — user must hold at least one role."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            is_api = (
                request.path.startswith("/api/")
                or request.path.startswith("/admin/api/")
                or request.path.startswith("/data-management/api/")
            )

            # ── Layer 1: Authentication ──────────────────────────────────────
            if not current_user.is_authenticated:
                log.warning(
                    "Access denied — unauthenticated: path=%s method=%s ip=%s",
                    request.path, request.method, request.remote_addr,
                )
                if is_api:
                    return jsonify({"error": "Authentication required."}), 401
                return redirect(url_for("va_auth.va_login", next=request.url))

            # ── Layer 2: Active-status ────────────────────────────────────────
            if not user_is_active(current_user):
                log.warning(
                    "Access denied — inactive user: user=%s path=%s ip=%s",
                    current_user.get_id(), request.path, request.remote_addr,
                )
                logout_user()
                if is_api:
                    return jsonify({"error": "Authentication required."}), 401
                return redirect(url_for("va_auth.va_login"))

            # ── Layer 3: Role check ──────────────────────────────────────────
            if not any(
                user_has_role(current_user, role)
                for role in roles
            ):
                role_label = " or ".join(roles)
                log.warning(
                    "Access denied — insufficient role: user=%s required=%s path=%s ip=%s",
                    current_user.get_id(), role_label, request.path, request.remote_addr,
                )
                if is_api:
                    return jsonify({"error": f"{role_label} access is required."}), 403
                va_permission_abortwithflash(f"{role_label} access is required.", 403)

            return f(*args, **kwargs)

        return decorated_function
    return decorator
