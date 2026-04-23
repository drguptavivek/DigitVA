"""Public home pages and legacy entrypoints."""

from flask import Blueprint, render_template

from app.authz.access import action_authorized
from app.authz.resources import submission_from_kwarg

va_main = Blueprint("va_main", __name__)


@va_main.route("/")
@va_main.route("/index")
@va_main.route("/vaindex")
def va_index():
    return render_template("va_frontpages/va_index.html")


@va_main.get("/vacta/vadata/vaview/<path:va_sid>")
@action_authorized("dm_submission_view", resource_resolver=submission_from_kwarg("va_sid"))
def legacy_data_manager_view_submission(va_sid):
    from app.routes.operations.data_management import view_submission

    return view_submission.__wrapped__(va_sid=va_sid)
