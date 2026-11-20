"""Mentor view JSON API (docs/policy/mentor-view.md, digitva-oux5).

Web-only, cookie session (``browser_session_only``). Every request re-derives
the caller's districts in ``mentor_view_service``: no district at all is 403
(a coder-only user), a district, coder, case or note out of reach is 404.
POSTs carry ``X-CSRFToken`` (the app-wide CSRFProtect). The coder table names
no respondent; the drill-down lists case ids and COD only.
"""

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app import limiter
from app.routes.api.request_helpers import browser_session_only
from app.routes.api.request_helpers import error as api_error
from app.services import mentor_view_service as mentor
from app.services.area_dashboard_service import DEFAULT_PERIOD, PERIOD_DAYS

bp = Blueprint("mentor_api", __name__)


@bp.before_request
def _require_browser_session():
    return browser_session_only()


@bp.errorhandler(mentor.MentorViewNotFound)
def _not_found(_exc):
    return api_error("Not found.", status_code=404)


@bp.errorhandler(mentor.MentorViewForbidden)
def _forbidden(exc):
    return api_error(str(exc), status_code=403)


def _period():
    period = (request.args.get("period") or DEFAULT_PERIOD).strip()
    return period if period in PERIOD_DAYS else None


def _after():
    after = request.args.get("after") or None
    if after is not None:
        try:
            mentor.parse_cursor(after)
        except ValueError:
            return False
    return after


@bp.get("/districts")
@login_required
@limiter.limit("120 per minute")
def districts():
    found = mentor.viewer_districts(current_user)
    if not found:
        raise mentor.MentorViewForbidden(
            "The mentor view is for mentoring institutes, district data managers and In-charges."
        )
    return jsonify({"districts": [mentor.district_summary(d) for d in found]})


@bp.get("/coders")
@login_required
@limiter.limit("120 per minute")
def coders():
    period = _period()
    if period is None:
        return api_error("Unknown period.", status_code=400)
    return jsonify(mentor.coder_table(current_user, request.args.get("district"), period))


@bp.get("/coders/<coder_id>/cases")
@login_required
@limiter.limit("120 per minute")
def coder_cases(coder_id):
    period, after = _period(), _after()
    if period is None or after is False:
        return api_error("Unknown period or cursor.", status_code=400)
    return jsonify(mentor.coder_cases(
        current_user, request.args.get("district"), coder_id, period, after,
    ))


@bp.post("/cases/<va_sid>/notes")
@login_required
@limiter.limit("30 per hour")
def create_note(va_sid):
    payload = request.get_json(silent=True)
    body = payload.get("body") if isinstance(payload, dict) else None
    try:
        return jsonify(mentor.create_note(current_user, va_sid, body)), 201
    except ValueError as exc:
        return api_error(str(exc), status_code=400)


@bp.post("/notes/<note_id>/retract")
@login_required
@limiter.limit("120 per minute")
def retract_note(note_id):
    return jsonify(mentor.retract_note(current_user, note_id))


@bp.get("/feedback/mine")
@login_required
@limiter.limit("120 per minute")
def my_feedback():
    after = _after()
    if after is False:
        return api_error("Unknown cursor.", status_code=400)
    sid = (request.args.get("sid") or "").strip()[:64] or None
    return jsonify(mentor.my_feedback(current_user, va_sid=sid, after=after))


@bp.post("/feedback/<note_id>/read")
@login_required
@limiter.limit("120 per minute")
def mark_read(note_id):
    return jsonify(mentor.mark_read(current_user, note_id))
