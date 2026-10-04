"""A session interface that keeps bearer requests away from the cookie.

Wraps the app's real session interface (Flask-Session). On an ``/api/v1/``
request carrying ``Authorization: Bearer`` it never reads the session cookie
(so a cookie cannot supply, or leak into, a bearer request) and never writes
one (so a bearer response carries no ``Set-Cookie``, whatever a route does to
``session``: ``generate_csrf()`` and friends write to a throwaway dict).
Every other request goes to the wrapped interface untouched.
"""

from flask import request as flask_request
from flask.sessions import SecureCookieSession, SessionInterface

from app.services.device_auth_service import request_bearer_token


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
        return self._inner.save_session(app, session, response)

    def __getattr__(self, name):
        # e.g. va_auth's current_app.session_interface.regenerate(session)
        return getattr(self._inner, name)
