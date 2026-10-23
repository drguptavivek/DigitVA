"""A session interface that keeps bearer requests away from the cookie.

Wraps the app's real session interface (Flask-Session). On an ``/api/v1/``
request carrying ``Authorization: Bearer`` it never reads the session cookie
(so a cookie cannot supply, or leak into, a bearer request) and never writes
one (so a bearer response carries no ``Set-Cookie``, whatever a route does to
``session``: ``generate_csrf()`` and friends write to a throwaway dict).
Every other request goes to the wrapped interface, except that a cookie
session is only re-saved to the store once per ``SESSION_REFRESH_WINDOW_SECONDS``
unless its data changed (see ``save_session``).
"""

import time

from flask import request as flask_request
from flask.sessions import SecureCookieSession, SessionInterface

from app.services.device_auth_service import request_bearer_token


#: A cookie session that has not changed is re-saved (stored expiry and
#: cookie slid forward) at most this often. Flask refreshes a permanent
#: session on every request, which was one SELECT + UPDATE + COMMIT of the
#: session row per request. The idle timeout stays PERMANENT_SESSION_LIFETIME
#: measured to the minute (29-30 minutes). Policy: docs/policy/auth-decorator-rbac.md, section 5.
SESSION_REFRESH_WINDOW_SECONDS = 60


class BearerBlindSessionInterface(SessionInterface):
    def __init__(self, inner):
        self._inner = inner

    def open_session(self, app, request):
        if request_bearer_token(request) is not None:
            return SecureCookieSession()
        return self._inner.open_session(app, request)

    def save_session(self, app, session, response):
        if request_bearer_token(flask_request) is not None:
            return None
        # An empty session is never stamped: that would create a row and a
        # cookie for an anonymous visitor, and logout's deletion must reach
        # the store. A session left holding only the stamp counts as empty,
        # so Flask-Session deletes its row and cookie as it did before.
        if "_refreshed_at" in session and set(session) <= {"_permanent", "_refreshed_at"}:
            session.pop("_refreshed_at")
        if session:
            now = int(time.time())
            # A stamp ahead of this clock (skew, a clock step) is not fresh.
            age = now - session.get("_refreshed_at", 0)
            if not session.modified and 0 <= age < SESSION_REFRESH_WINDOW_SECONDS:
                if session.accessed:
                    response.vary.add("Cookie")
                return None
            session["_refreshed_at"] = now
        return self._inner.save_session(app, session, response)

    def __getattr__(self, name):
        # e.g. va_auth's current_app.session_interface.regenerate(session)
        return getattr(self._inner, name)
