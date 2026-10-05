"""Readers of a WHO VA 2022 flat answer payload shared by every consumer of
the interview's date of birth and age (the DORIS certificate prefill and the
web intake case sync), so both read the same ``Id10020`` / ``dob_precision``
/ ``age_group`` branches the same way.

Pure functions over ``dict``; range, bound and storage rules stay with each
caller. Values may arrive as strings or numbers (``"9.0"``, ``9.0``); dates
take the calendar date as recorded, without a time-zone shift.
"""

from __future__ import annotations

import math
import re
from datetime import date

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_CHILD_UNITS = ("days", "months", "years")


def text(payload: dict, key: str) -> str:
    value = payload.get(key)
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def choice(payload: dict, key: str) -> str:
    return text(payload, key).lower()


def number(payload: dict, key: str) -> float | None:
    value = payload.get(key)
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        try:
            value = float(str(value).strip())
        except ValueError:
            return None
    return float(value) if math.isfinite(value) else None


def whole(payload: dict, key: str, low: int | None = None, high: int | None = None) -> int | None:
    """An integer answer, within ``low..high`` when given, else ``None``."""
    value = number(payload, key)
    if value is None or not value.is_integer():
        return None
    if (low is not None and value < low) or (high is not None and value > high):
        return None
    return int(value)


def calendar_date(payload: dict, key: str) -> date | None:
    """The calendar date as recorded (``2025-08-04T00:00:00+05:30`` -> 4 Aug)."""
    match = _ISO_DATE.match(text(payload, key))
    if match is None:
        return None
    try:
        return date(int(match[1]), int(match[2]), int(match[3]))
    except ValueError:
        return None


def birth_answer(payload: dict) -> tuple[str, str, date] | None:
    """The answered date of birth as ``(precision, answer key, date)``, or
    ``None``: ``exact`` (``Id10020`` = yes, ``Id10021``), ``month_year``
    (``dob_month_year``) or ``year`` (``dob_year``), the last two under
    ``Id10020`` = no or ref and the matching ``dob_precision``. The partial
    ones are stored by the form as the first of the month or year."""
    known = choice(payload, "Id10020")
    if known == "yes":
        born = calendar_date(payload, "Id10021")
        return ("exact", "Id10021", born) if born else None
    if known in ("no", "ref"):
        precision = choice(payload, "dob_precision")
        if precision in ("month_year", "year"):
            key = f"dob_{precision}"
            partial = calendar_date(payload, key)
            return (precision, key, partial) if partial else None
    return None


def age_field(payload: dict) -> tuple[str, str, str] | None:
    """Where the estimated age is answered, as ``(group, unit, answer key)``,
    or ``None``: ``age_group`` neonate (days, ``age_neonate_days``), child
    (``age_child_unit`` days, months or years, ``age_child_<unit>``) or adult
    (years, ``age_adult``). The value is the caller's to read and bound."""
    group = choice(payload, "age_group")
    if group == "neonate":
        return group, "days", "age_neonate_days"
    if group == "child":
        unit = choice(payload, "age_child_unit")
        return (group, unit, f"age_child_{unit}") if unit in _CHILD_UNITS else None
    if group == "adult":
        return group, "years", "age_adult"
    return None
