"""Password breach check (Have I Been Pwned, k-anonymity range API).

Passwords are server-generated (docs/policy/account-onboarding-and-passwords.md),
so there is no strength validator; every generated password is checked here
(docs/policy/password-breach-checks.md).
"""

from __future__ import annotations

from functools import lru_cache
import hashlib

import requests
from flask import current_app, has_app_context

_HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/{prefix}"
_HIBP_USER_AGENT = "DigitVA password breach checks"
_HIBP_DEFAULT_TIMEOUT_SECONDS = 5.0

BREACH_CHECK_UNAVAILABLE_MESSAGE = (
    "Password breach check is temporarily unavailable. Please try again."
)


def _password_breach_check_enabled() -> bool:
    if not has_app_context():
        return False
    return bool(current_app.config.get("HIBP_PASSWORD_BREACH_CHECK_ENABLED", True))


def _password_breach_check_timeout_seconds() -> float:
    if not has_app_context():
        return _HIBP_DEFAULT_TIMEOUT_SECONDS
    return float(
        current_app.config.get(
            "HIBP_PASSWORD_BREACH_CHECK_TIMEOUT_SECONDS",
            _HIBP_DEFAULT_TIMEOUT_SECONDS,
        )
    )


@lru_cache(maxsize=4096)
def _hibp_range_query(prefix: str) -> str:
    """Return the raw HIBP suffix list for a SHA-1 prefix."""
    response = requests.get(
        _HIBP_RANGE_URL.format(prefix=prefix),
        headers={
            "Add-Padding": "true",
            "User-Agent": _HIBP_USER_AGENT,
        },
        timeout=_password_breach_check_timeout_seconds(),
    )
    response.raise_for_status()
    return response.text


def password_breach_error_message(password: str) -> str | None:
    """Return a breach-policy error string, or None if the password is not breached."""
    if not password or not _password_breach_check_enabled():
        return None

    sha1_hex = hashlib.sha1(password.encode("utf-8")).hexdigest().upper()
    prefix, suffix = sha1_hex[:5], sha1_hex[5:]

    try:
        payload = _hibp_range_query(prefix)
    except requests.RequestException:
        return BREACH_CHECK_UNAVAILABLE_MESSAGE

    for line in payload.splitlines():
        candidate_suffix, _, _count = line.partition(":")
        if candidate_suffix.strip().upper() == suffix:
            return "Password has been found in known breach data. Choose a different password."
    return None

