from flask import jsonify, request
from flask_login import current_user


def register_csrf_protect_cookie_requests(app):
    """Register after ``csrf.init_app`` with ``WTF_CSRF_CHECK_DEFAULT`` off:
    this hook takes the slot of CSRFProtect's own and skips bearer requests
    (no ambient credential, nothing to forge)."""

    @app.before_request
    def csrf_protect_cookie_requests():
        from app import csrf
        from app.services.device_auth_service import request_bearer_token

        # Mirrors flask_wtf.csrf.CSRFProtect's hook minus the bearer case.
        if (
            not app.config["WTF_CSRF_ENABLED"]
            or request.method not in app.config["WTF_CSRF_METHODS"]
            or not request.endpoint
            or request_bearer_token(request) is not None
            or app.blueprints.get(request.blueprint) in csrf._exempt_blueprints
        ):
            return None
        view = app.view_functions.get(request.endpoint)
        if f"{view.__module__}.{view.__name__}" in csrf._exempt_views:
            return None
        # A dead cookie session on /api/v1 is a sign-in problem, not a CSRF
        # one: answer 401 so the client re-authenticates (digitva-fvbc).
        if (
            request.path.startswith("/api/v1/")
            and not request.path.startswith("/api/v1/doris-demo/")
            and not current_user.is_authenticated
        ):
            return jsonify({"error": "Authentication required.", "code": "unauthorized"}), 401
        csrf.protect()
        return None
