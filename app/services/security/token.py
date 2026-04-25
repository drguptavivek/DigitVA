"""Token service — URL-safe timed tokens for password reset and email verification.

Uses itsdangerous URLSafeTimedSerializer (bundled with Flask) to generate
and validate tamper-proof, expiring tokens. No database table needed.
"""

from __future__ import annotations

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

TOKEN_PURPOSES = {
    "password_reset": {
        "salt": "digitva-password-reset",
        "max_age": 3600,       # 1 hour
    },
    "email_verify": {
        "salt": "digitva-email-verify",
        "max_age": 86400,      # 24 hours
    },
}


def _serializer() -> URLSafeTimedSerializer:
    from flask import current_app
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"])


def generate_token(user_id, purpose: str) -> str:
    """Generate a URL-safe timed token for the given user and purpose.

    Args:
        user_id: The user's UUID (as string).
        purpose: One of ``"password_reset"`` or ``"email_verify"``.

    Returns:
        URL-safe token string.
    """
    if purpose not in TOKEN_PURPOSES:
        raise ValueError(f"Unknown token purpose: {purpose}")
    return _serializer(). dumps(
        {"user_id": str(user_id), "purpose": purpose},
        salt=TOKEN_PURPOSES[purpose]["salt"],
    )


def validate_token(token: str, purpose: str) -> str | None:
    """Validate a token and return the user_id if valid.

    Args:
        token: The token string from the URL.
        purpose: Expected purpose (``"password_reset"`` or ``"email_verify"``).

    Returns:
        The user_id string if valid, or ``None`` if expired/invalid.
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

    if data.get("purpose") != purpose:
        return None

    return data.get("user_id")
