"""The one phone-number rule of the VA form (web intake validation and the
register's blind index). ASCII digits only: the same number written in
Devanagari or Arabic-Indic digits is not a phone number here, so it cannot
get a different blind index."""

import re

_PHONE_RE = re.compile(r"^(?:\+91|91|0)?([0-9]{10})$")
_PHONE_SEPARATORS_RE = re.compile(r"[\s()-]")


def normalise_phone(value: str) -> str | None:
    """The 10 digits of *value*, or None. Spaces, hyphens and parentheses are
    ignored; a leading ``+91``, ``91`` or ``0`` is dropped when 10 digits
    remain."""
    match = _PHONE_RE.match(_PHONE_SEPARATORS_RE.sub("", value))
    return match.group(1) if match else None
