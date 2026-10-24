"""Idle sign-out for cookie sessions (docs/policy/auth-decorator-rbac.md, section 5).

A cookie session signs out after ``PERMANENT_SESSION_LIFETIME`` without user
activity. ``last_activity_at`` (UTC epoch seconds) is set at sign-in and moved
by cookie requests that are not background (header ``X-DigitVA-Background: 1``,
sent by the web client's automatic polls); it moves at most every 30 seconds so
the session store is not written on every request. A session without the
stamp (signed in before this rule) is stamped, not signed out. Bearer
requests never reach the cookie session and are skipped.

Also retires "Remember me": a remember cookie is never honoured and is
cleared, so nothing signs a user back in silently.
"""

import time

from flask import current_app, flash, jsonify, redirect, request, session, url_for
from flask_login import logout_user

from app.decorators.role_required import API_PATH_PREFIXES
from app.services.device_auth_service import request_bearer_token

BACKGROUND_HEADER = "X-DigitVA-Background"
IDLE_MESSAGE = "Signed out after 30 minutes of inactivity."
#: The stamp moves at most this often, so sign-out comes 29 to 30 minutes after
#: the last activity (the web client pings at most every 30 s while the user is active).
_STAMP_GRAIN_SECONDS = 30


def stamp_activity() -> None:
    session["last_activity_at"] = int(time.time())


def enforce_idle_timeout():
    """``before_request`` hook; returns a response to refuse an idle session."""
    if request_bearer_token(request) is not None:
        return None
    # Flask-Login skips the remember cookie when the session says "clear", and
    # deletes the cookie on the response.
    if current_app.config.get("REMEMBER_COOKIE_NAME", "remember_token") in request.cookies:
        session["_remember"] = "clear"
    if "_user_id" not in session:
        return None

    now = int(time.time())
    last = session.get("last_activity_at")
    lifetime = int(current_app.config["PERMANENT_SESSION_LIFETIME"].total_seconds())
    if last is not None and now - last > lifetime:
        return _refuse_idle()
    background = (
        request.headers.get(BACKGROUND_HEADER) == "1"
        or request.path.startswith("/static/")
        or request.path == "/health"
    )
    if last is None or (not background and now - last >= _STAMP_GRAIN_SECONDS):
        session["last_activity_at"] = now
    return None


def _refuse_idle():
    logout_user()
    remember = session.get("_remember")
    session.clear()
    if remember:
        session["_remember"] = remember
    if (
        request.path.startswith(API_PATH_PREFIXES)
        or request.is_json
        or request.headers.get("HX-Request") == "true"
        or request.accept_mimetypes.best == "application/json"
    ):
        return jsonify({"error": IDLE_MESSAGE, "code": "session_idle"}), 401
    flash(IDLE_MESSAGE, "warning")
    return redirect(url_for("va_auth.va_login"))
