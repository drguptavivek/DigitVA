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

For API routes (any path under API_PATH_PREFIXES): JSON response.
For web routes: redirect to login (401) or flash + abort(403).

This decorator subsumes @login_required — do not stack both.

Role names are checked against _ROLE_METHODS when the decorator is applied, so
an unknown or misspelled name fails at import rather than turning into a route
that silently 403s everyone.

The wrapper is stamped with ROLE_MARKER_ATTR (``__digitva_roles__``) carrying
the tuple of gated roles, so tests/test_route_auth_coverage.py can walk
app.url_map and prove each endpoint is guarded. A missing decorator fails open,
and __wrapped__ cannot stand in for the marker: every functools.wraps decorator
sets it.
"""

import logging
from functools import wraps

from flask import jsonify, redirect, request, url_for
from flask_login import current_user, logout_user

from app.models import VaStatuses
from app.utils.va_permission.va_permission_01_abortwithflash import (
    va_permission_abortwithflash,
)

log = logging.getLogger(__name__)

_ROLE_METHODS = {
    "admin":          lambda u: u.is_admin(),
    "coder":          lambda u: u.is_coder(),
    "coding_tester":  lambda u: u.is_coding_tester(),
    "reviewer":       lambda u: u.is_reviewer(),
    "data_manager":   lambda u: u.is_data_manager(),
    "site_pi":        lambda u: u.is_site_pi(),
    "project_pi":     lambda u: u.is_project_pi(),
    "interviewer":    lambda u: u.is_interviewer(),
    # collaborator / collaborator_pii: identical reach, so both spellings
    # gate on the same check. What differs (PII visibility) is decided by
    # viewer_pii_service.should_redact_pii, not by route access.
    "collaborator":     lambda u: u.is_viewer(),
    "collaborator_pii": lambda u: u.is_viewer(),
}


# Request paths under these prefixes get a JSON error body instead of an HTML
# redirect/flash. base.js only shows the "Session Expired" modal for a JSON 401,
# so an API blueprint mounted outside this tuple fails silently: the tab stops
# refreshing and nothing tells the user why. tests/test_route_auth_coverage.py
# asserts every registered api-ish rule matches one of these.
API_PATH_PREFIXES = (
    "/api/",
    "/admin/api/",
    "/data-management/api/",
    "/intake/api/",
)

# Attribute stamped on the wrapper this decorator returns, holding the tuple of
# roles it gates on. It exists so a test can prove a route is guarded: every
# functools.wraps decorator sets __wrapped__, so the presence of __wrapped__
# proves nothing about authentication. Do not rename without updating
# tests/test_route_auth_coverage.py.
ROLE_MARKER_ATTR = "__digitva_roles__"


def role_required(*roles):
    """Gate a route by role. OR semantics — user must hold at least one role.

    Role names are validated at decoration time (i.e. at import). An unknown
    name raises ValueError rather than being silently dropped from the check —
    otherwise a typo, or a role that exists in ``VaAccessRoles`` but has no
    predicate here yet, produces a route that 403s every user including admins
    while logging the bogus name as if it were real.

    ``_ROLE_METHODS`` is deliberately NOT derived from ``VaAccessRoles``: a role
    becomes routable only when someone adds an explicit predicate for it.
    """
    if not roles:
        raise ValueError(
            "role_required() requires at least one role name; a bare "
            "role_required() would deny every user including admins. "
            f"Valid roles: {', '.join(sorted(_ROLE_METHODS))}."
        )

    unknown = [role for role in roles if role not in _ROLE_METHODS]
    if unknown:
        raise ValueError(
            "role_required() got unknown role name(s): "
            f"{', '.join(repr(r) for r in unknown)}. "
            f"Valid roles: {', '.join(sorted(_ROLE_METHODS))}. "
            "A role in VaAccessRoles is not routable until it has an explicit "
            "predicate in _ROLE_METHODS."
        )

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            is_api = request.path.startswith(API_PATH_PREFIXES)

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
            if current_user.user_status != VaStatuses.active:
                log.warning(
                    "Access denied — inactive user: user=%s path=%s ip=%s",
                    current_user.get_id(), request.path, request.remote_addr,
                )
                logout_user()
                if is_api:
                    return jsonify({"error": "Authentication required."}), 401
                return redirect(url_for("va_auth.va_login"))

            # ── Layer 3: Role check ──────────────────────────────────────────
            if not any(_ROLE_METHODS[role](current_user) for role in roles):
                role_label = " or ".join(roles)
                log.warning(
                    "Access denied — insufficient role: user=%s required=%s path=%s ip=%s",
                    current_user.get_id(), role_label, request.path, request.remote_addr,
                )
                if is_api:
                    return jsonify({"error": f"{role_label} access is required."}), 403
                va_permission_abortwithflash(f"{role_label} access is required.", 403)

            return f(*args, **kwargs)

        # Declare the guard on the wrapper itself. functools.wraps has already
        # copied f.__dict__ across at this point, so this assignment is what
        # the route-coverage test reads, not something inherited from f.
        setattr(decorated_function, ROLE_MARKER_ATTR, tuple(roles))
        return decorated_function
    return decorator
