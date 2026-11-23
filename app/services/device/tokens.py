"""Bearer parsing, token hashing and issue primitives, and the device
refusal type (``DeviceAuthError``). Part of ``device_auth_service``; see
``app/services/device/__init__.py``."""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from flask import current_app

from app.models import AuthDeviceSession, VaUsers

# The public module's name, so log routing and ``assertLogs(devices.log.name)``
# see the same logger as before the split.
log = logging.getLogger("app.services.device_auth_service")


API_V1_PREFIX = "/api/v1/"
#: Sign-in endpoints (full endpoint names) that create a session, so carry no valid bearer token.
UNAUTHENTICATED_ENDPOINTS = frozenset({
    "api_v1.auth_api.enroll", "api_v1.auth_api.open_session", "api_v1.auth_api.refresh_session",
    "api_v1.auth_api.demo_enroll", "api_v1.auth_api.redeem_sign_in_qr",
    "api_v1.auth_api.password_enroll", "api_v1.auth_api.redeem_sign_in_code",
    "api_v1.auth_api.forgot_password",
})


ACCESS_TTL = timedelta(minutes=15)
DEFAULT_REFRESH_TTL_DAYS = 30
DEFAULT_SESSION_MAX_DAYS = 90


class DeviceAuthError(Exception):
    """A refused device call: ``code`` is the contract's machine code;
    ``fields`` names the inputs to fix, when the refusal names any;
    ``extra`` holds further reply keys (the ``devices`` of a ``device_limit``)."""

    def __init__(self, message: str, code: str, status_code: int, fields: list[str] | None = None,
                 extra: dict | None = None):
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.fields = fields
        self.extra = extra


@dataclass
class IssuedTokens:
    access_token: str
    refresh_token: str
    session: AuthDeviceSession


def request_bearer_token(request) -> str | None:
    """The token of an ``Authorization: Bearer`` header on an ``/api/v1/``
    path ("" when the header names Bearer with no token), else None.

    One definition of "a bearer request" for the credential pre-step, the
    CSRF hook and the session interface. A header with another scheme, or
    any path outside ``/api/v1/``, is not one: the cookie rules apply.
    """
    if not request.path.startswith(API_V1_PREFIX):
        return None
    scheme, _sep, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        return None
    return token.strip()


def _now() -> datetime:
    return datetime.now(UTC)


def _new_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _refresh_ttl() -> timedelta:
    return timedelta(days=int(current_app.config.get("DEVICE_REFRESH_TTL_DAYS") or DEFAULT_REFRESH_TTL_DAYS))


def _session_max_age() -> timedelta:
    return timedelta(days=int(current_app.config.get("DEVICE_SESSION_MAX_DAYS") or DEFAULT_SESSION_MAX_DAYS))


def serialize_tokens(issued: IssuedTokens, user: VaUsers) -> dict:
    return {
        "access_token": issued.access_token,
        "access_expires_at": issued.session.access_expires_at.isoformat(),
        "refresh_token": issued.refresh_token,
        "refresh_expires_at": issued.session.refresh_expires_at.isoformat(),
        "user": {"user_id": str(user.user_id), "name": user.name, "email": user.email},
        "terms_required": not user.pw_reset_t_and_c,
    }
