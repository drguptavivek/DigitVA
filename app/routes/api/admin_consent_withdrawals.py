"""Admin list of consent withdrawals (docs/policy/consent-withdrawal.md, digitva-4gu7).

Web-only, cookie session, admin only. Rows carry the case id, project, dates,
channel and recorder; never the respondent text, which only the sealed case
detail shows. Undone records are left out unless ``include_undone=1``.
"""

from flask import Blueprint, jsonify, request

from app import limiter
from app.decorators import role_required
from app.routes.api.request_helpers import browser_session_only
from app.routes.api.request_helpers import error as api_error
from app.services import consent_withdrawal_service as withdrawal_svc

bp = Blueprint("admin_consent_withdrawals_api", __name__)


@bp.before_request
def _require_browser_session():
    return browser_session_only()


@bp.get("/consent-withdrawals")
@role_required("admin")
@limiter.limit("60 per minute")
def list_consent_withdrawals():
    """``?project_id&include_undone=1&limit(<=100)&cursor`` ->
    ``{"withdrawals": [...], "next_cursor"}``, newest recorded first."""
    try:
        limit = int(request.args.get("limit", withdrawal_svc.LIST_LIMIT_MAX))
    except ValueError:
        return api_error("limit must be a number.", "invalid_request", 400)
    cursor = request.args.get("cursor") or None
    try:
        if cursor:
            withdrawal_svc.parse_cursor(cursor)
    except ValueError:
        return api_error("cursor is not valid.", "invalid_request", 400)
    return jsonify(withdrawal_svc.list_withdrawals(
        project_id=(request.args.get("project_id") or "").strip() or None,
        include_undone=request.args.get("include_undone") == "1",
        cursor=cursor,
        limit=limit,
    ))
