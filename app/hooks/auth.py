from flask import g, jsonify, request

from app import login
from app.models.va_users import load_user_from_device_token
from app.services import device_auth_service
from app.services.icd11_client_auth import PATH_PREFIX as ICD11_CLIENT_PREFIX


def register_authenticate_bearer(app):
    # /api/v1/ takes a session cookie or a device bearer token. Runs before
    # every other hook (the logger, the limiter's key functions and the
    # gates below all read the user): a bearer is authenticated alone, so the
    # cookie on the same request is ignored, and a bad one is refused rather
    # than falling back to the cookie.
    @app.before_request
    def authenticate_bearer():
        g.bearer_auth = False
        g.pop("device_session", None)
        # The ICD-11 client API authenticates its own token in each view: no
        # cookie or device user ever counts there (icd11-client-api.md section 12).
        if request.path.startswith(ICD11_CLIENT_PREFIX):
            g._login_user = login.anonymous_user()
            return None
        if device_auth_service.request_bearer_token(request) is None:
            return None
        # Sign-in endpoints take no token: a client may still send its stale one.
        if request.endpoint in device_auth_service.UNAUTHENTICATED_ENDPOINTS:
            return None
        user = load_user_from_device_token(request)
        if user is None:
            g._login_user = login.anonymous_user()  # no second lookup from the response logger
            return jsonify({"error": "Authentication required.", "code": "unauthorized"}), 401
        g._login_user = user  # Flask-Login's per-request cache: skips the cookie loaders
        g.bearer_auth = True
        return None
