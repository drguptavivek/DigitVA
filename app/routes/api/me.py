"""The signed-in user's own access (docs/policy/api-v1.md), either credential."""
from flask import Blueprint, g, jsonify
from flask_login import current_user, login_required
from flask_wtf.csrf import generate_csrf

from app import limiter
from app.routes.api import profile
from app.services.access_summary_service import build_access_summary

bp = Blueprint("me_api", __name__)


@bp.get("/access")
@login_required
@limiter.limit("120 per minute")
def access():
    """Everything about the caller's access in one body
    (docs/current-state/api-v1.md). JSON 401 when signed out. A cookie
    request also gets the CSRF token in the ``X-CSRFToken`` header (the body
    is the same for both credentials); a bearer request never does, since
    generating one writes the session."""
    response = jsonify(build_access_summary(current_user._get_current_object()))
    if not g.get("bearer_auth"):
        response.headers["X-CSRFToken"] = generate_csrf()
    return response


# The terms screen's call, same view as POST /api/v1/profile/terms: one
# acceptance rule, one audit event, whichever URL a client uses.
bp.add_url_rule("/terms", view_func=profile.accept_terms, methods=["POST"])
