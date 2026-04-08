"""Shared password strength validator.

Rules:
  - Minimum 8 characters
  - At least one uppercase letter (A-Z)
  - At least one digit (0-9)
  - At least one special character (!@#$%^&*()_+-=[]{}|;':",.<>?/`~\\)

Returns a list of unmet rule strings (empty = valid).
"""

from __future__ import annotations

from functools import lru_cache
import hashlib
import re

import requests
from flask import current_app, has_app_context

_SPECIAL = r"[!@#$%^&*()\-_=+\[\]{}|;':\",./<>?`~\\]"

_HIBP_RANGE_URL = "https://api.pwnedpasswords.com/range/{prefix}"
_HIBP_USER_AGENT = "DigitVA password breach checks"
_HIBP_DEFAULT_TIMEOUT_SECONDS = 5.0

RULES = [
    (lambda p: len(p) >= 12,         "at least 12 characters"),
    (lambda p: bool(re.search(r"[A-Z]", p)),   "at least one uppercase letter"),
    (lambda p: bool(re.search(r"\d", p)),       "at least one digit"),
    (lambda p: bool(re.search(_SPECIAL, p)),    "at least one special character"),
]


def validate_password_strength(password: str) -> list[str]:
    """Return a list of unmet rule descriptions. Empty list means password is valid."""
    return [msg for check, msg in RULES if not check(password)]


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
        return "Password breach check is temporarily unavailable. Please try again."

    for line in payload.splitlines():
        candidate_suffix, _, _count = line.partition(":")
        if candidate_suffix.strip().upper() == suffix:
            return "Password has been found in known breach data. Choose a different password."
    return None


def password_error_message(password: str) -> str | None:
    """Return a single human-readable error string, or None if valid."""
    failures = validate_password_strength(password)
    if not failures:
        breach_error = password_breach_error_message(password)
        if breach_error:
            return breach_error
        return None
    return "Password must have " + ", ".join(failures) + "."
