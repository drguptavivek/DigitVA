"""Browser bootstrap for the Expo client (``/api/v1/client/``).

The browser client uses the ordinary Flask-Login session cookie.  This small
endpoint exposes only navigation data and a CSRF token; workflow endpoints
remain responsible for their own authorization and scope checks.
"""

from flask import Blueprint, jsonify, url_for
from flask_login import current_user
from flask_wtf.csrf import generate_csrf

from app.services.authz import effective_roles

bp = Blueprint("client_api", __name__)

@bp.after_request
def _disable_caching(response):
    """Never cache identity, CSRF or capability information."""
    response.headers["Cache-Control"] = "no-store"
    return response


@bp.get("/bootstrap")
def bootstrap():
    """Return the session bootstrap contract for the Expo browser client."""
    login_url = url_for("va_auth.va_login", next="/app/")
    if not current_user.is_authenticated or not current_user.is_active:
        return jsonify({"code": "authentication_required", "login_url": login_url}), 401

    roles = effective_roles(current_user)
    return jsonify(
        {
            "user": {
                "id": str(current_user.user_id),
                "name": current_user.name,
            },
            "csrf": {
                "header": "X-CSRFToken",
                "token": generate_csrf(),
            },
            "capabilities": {
                "intake": "interviewer" in roles,
                "coding": bool({"coder", "coding_tester"} & roles),
                "reviewing": "reviewer" in roles,
            },
            "links": {
                "login": login_url,
                "logout": url_for("va_auth.va_logout"),
                "intakeCases": "/api/v1/intake/cases",
                "intakeDrafts": "/api/v1/intake/drafts",
                "coding": "/coding/",
                "reviewing": "/reviewing/",
            },
        }
    )
