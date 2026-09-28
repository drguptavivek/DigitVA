"""Token service — URL-safe timed tokens for password reset and email verification.

Uses itsdangerous URLSafeTimedSerializer (bundled with Flask) to generate
and validate tamper-proof, expiring tokens. No database table needed.

Password-reset tokens are single-use: they carry a fingerprint of the user's
stored password hash, so setting a new password invalidates every reset token
issued before it. Factor-reset tokens (the break-glass CLI's magic link,
docs/policy/authentication-factors.md section 8) are single-use the same way,
but fingerprint the password hash *and* ``auth_session_version`` together, so
either setting a new password or any other factor reset invalidates them.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

TOKEN_PURPOSES = {
    "password_reset": {
        "salt": "digitva-password-reset",
        "max_age": 3600,       # 1 hour
    },
    "email_verify": {
        "salt": "digitva-email-verify",
        "max_age": 86400,      # 24 hours
    },
    "factor_reset": {
        "salt": "digitva-factor-reset",
        "max_age": 3600,       # 1 hour
    },
}


def _serializer() -> URLSafeTimedSerializer:
    from flask import current_app
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def _load_user(user_id):
    from app import db
    from app.models import VaUsers

    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        return None
    return db.session.get(VaUsers, uid)


def _password_fingerprint(user) -> str:
    """Short digest of the stored password hash; changes whenever the password does."""
    return hashlib.sha256((user.password or "").encode()).hexdigest()[:16]


def _factor_reset_fingerprint(user) -> str:
    """Digest of the password hash *and* the session version, so a
    factor-reset token is invalidated by either a password change (which
    bumps the version too) or any other factor reset."""
    raw = f"{user.password or ''}:{user.auth_session_version or 0}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# Purposes whose token carries a fingerprint tying it to current user state,
# so using it once (or any other event that changes that state) invalidates
# every other outstanding token for the same purpose.
_FINGERPRINT_FNS = {
    "password_reset": _password_fingerprint,
    "factor_reset": _factor_reset_fingerprint,
}


def generate_token(user_id, purpose: str) -> str:
    """Generate a URL-safe timed token for the given user and purpose.

    Args:
        user_id: The user's UUID (as string).
        purpose: One of ``"password_reset"`` or ``"email_verify"``.

    Returns:
        URL-safe token string.

    Raises:
        ValueError: unknown purpose, or a password_reset token for a user
            that does not exist.
    """
    if purpose not in TOKEN_PURPOSES:
        raise ValueError(f"Unknown token purpose: {purpose}")
    payload = {"user_id": str(user_id), "purpose": purpose}
    fingerprint_fn = _FINGERPRINT_FNS.get(purpose)
    if fingerprint_fn is not None:
        user = _load_user(user_id)
        if user is None:
            raise ValueError(f"Unknown user for {purpose} token")
        payload["fp"] = fingerprint_fn(user)
    return _serializer().dumps(payload, salt=TOKEN_PURPOSES[purpose]["salt"])


def validate_token(token: str, purpose: str) -> str | None:
    """Validate a token and return the user_id if valid.

    Args:
        token: The token string from the URL.
        purpose: Expected purpose (``"password_reset"`` or ``"email_verify"``).

    Returns:
        The user_id string if valid, or ``None`` if expired/invalid. A
        password_reset token is also invalid once the user's password has
        changed since it was issued (or the user no longer exists).
    """
    if purpose not in TOKEN_PURPOSES:
        return None

    config = TOKEN_PURPOSES[purpose]
    try:
        data = _serializer().loads(
            token,
            salt=config["salt"],
            max_age=config["max_age"],
        )
    except (BadSignature, SignatureExpired):
        return None

    if not isinstance(data, dict) or data.get("purpose") != purpose:
        return None

    fingerprint_fn = _FINGERPRINT_FNS.get(purpose)
    if fingerprint_fn is not None:
        user = _load_user(data.get("user_id"))
        fp = data.get("fp")
        if user is None or not isinstance(fp, str):
            return None
        if not hmac.compare_digest(fp, fingerprint_fn(user)):
            return None

    return data.get("user_id")
