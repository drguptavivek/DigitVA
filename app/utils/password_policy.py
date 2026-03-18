"""Shared password strength validator.

Rules:
  - Minimum 8 characters
  - At least one uppercase letter (A-Z)
  - At least one digit (0-9)
  - At least one special character (!@#$%^&*()_+-=[]{}|;':",.<>?/`~\\)

Returns a list of unmet rule strings (empty = valid).
"""

from __future__ import annotations

import re

_SPECIAL = r"[!@#$%^&*()\-_=+\[\]{}|;':\",./<>?`~\\]"

RULES = [
    (lambda p: len(p) >= 12,         "at least 12 characters"),
    (lambda p: bool(re.search(r"[A-Z]", p)),   "at least one uppercase letter"),
    (lambda p: bool(re.search(r"\d", p)),       "at least one digit"),
    (lambda p: bool(re.search(_SPECIAL, p)),    "at least one special character"),
]


def validate_password_strength(password: str) -> list[str]:
    """Return a list of unmet rule descriptions. Empty list means password is valid."""
    return [msg for check, msg in RULES if not check(password)]


def password_error_message(password: str) -> str | None:
    """Return a single human-readable error string, or None if valid."""
    failures = validate_password_strength(password)
    if not failures:
        return None
    return "Password must have " + ", ".join(failures) + "."
