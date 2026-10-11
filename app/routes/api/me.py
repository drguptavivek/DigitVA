"""The signed-in user's own access (docs/policy/api-v1.md), either credential."""
from flask import Blueprint, g, jsonify, request
from flask_login import current_user, login_required
from flask_wtf.csrf import generate_csrf

from app import limiter
from app.routes.api import profile
from app.routes.api.request_helpers import error
from app.services import notification_service
from app.services.access_summary_service import build_access_summary

bp = Blueprint("me_api", __name__)


@bp.get("/access")
@login_required
@limiter.limit("120 per minute")
def access():
    """Everything about the caller's access in one body
    (docs/current-state/api-v1.md). JSON 401 when signed out. A cookie
    request gets full account access and a CSRF token in ``X-CSRFToken``.
    A bearer request gets native worker grants only and no CSRF token,
    since generating one writes the session."""
    response = jsonify(build_access_summary(current_user._get_current_object()))
    if not g.get("bearer_auth"):
        response.headers["X-CSRFToken"] = generate_csrf()
    return response


@bp.get("/notifications")
@login_required
@limiter.limit("120 per minute")
def notifications():
    """The caller's own notifications after the cursor ``after`` (default 0),
    oldest first, at most 100: ``{notifications, next_cursor}``
    (docs/current-state/api-v1.md). A nudge to sync, never the truth; zero
    database queries when Redis says nothing is newer. 400 ``invalid_request``
    for an ``after`` that is not a non-negative integer."""
    raw = request.args.get("after", "0")
    if not raw.isascii() or not raw.isdigit() or int(raw) > notification_service.BIGINT_MAX:
        return error("after must be a non-negative integer.", "invalid_request", 400)
    return jsonify(notification_service.poll(current_user.user_id, int(raw)))


# The terms screen's call, same view as POST /api/v1/profile/terms: one
# acceptance rule, one audit event, whichever URL a client uses.
bp.add_url_rule("/terms", view_func=profile.accept_terms, methods=["POST"])
