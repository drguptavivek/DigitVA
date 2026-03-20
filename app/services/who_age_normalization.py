"""WHO 2022 age normalization helpers shared by sync and analytics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


_DAYS_PER_MONTH = Decimal("30.4375")
_DAYS_PER_YEAR = Decimal("365.25")
_TRUE_VALUES = {"1", "1.0", "true", "True"}


@dataclass(frozen=True)
class NormalizedWhoAge:
    """Normalized age selected from WHO 2022 age fields."""

    legacy_age_years: int
    normalized_age_days: Decimal | None
    normalized_age_years: Decimal | None
    normalized_age_source: str | None


def _parse_decimal(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))

    raw = str(value).strip()
    if not raw:
        return None
    try:
        return Decimal(raw)
    except InvalidOperation:
        return None


def _flag_is_true(value) -> bool:
    return str(value).strip() in _TRUE_VALUES


def normalize_who_2022_age(va_submission: dict | None) -> NormalizedWhoAge:
    """Choose one WHO 2022 age source using policy precedence."""
    payload = va_submission or {}

    age_neonate_hours = _parse_decimal(payload.get("age_neonate_hours"))
    age_neonate_days = _parse_decimal(payload.get("age_neonate_days"))
    age_in_days = _parse_decimal(payload.get("ageInDays"))
    age_in_months = _parse_decimal(payload.get("ageInMonths"))
    age_in_years = _parse_decimal(payload.get("ageInYears"))
    age_in_years2 = _parse_decimal(payload.get("ageInYears2"))
    final_age_years = _parse_decimal(payload.get("finalAgeInYears"))

    normalized_age_source = None
    if age_neonate_hours is not None:
        normalized_age_source = "age_neonate_hours"
    elif age_neonate_days is not None:
        normalized_age_source = "age_neonate_days"
    elif _flag_is_true(payload.get("isNeonatal")) and age_in_days is not None:
        normalized_age_source = "ageInDays"
    elif _flag_is_true(payload.get("isChild")) and age_in_days is not None:
        normalized_age_source = "ageInDays"
    elif _flag_is_true(payload.get("isChild")) and age_in_months is not None:
        normalized_age_source = "ageInMonths"
    elif _flag_is_true(payload.get("isChild")) and age_in_years is not None:
        normalized_age_source = "ageInYears"
    elif _flag_is_true(payload.get("isChild")) and age_in_years2 is not None:
        normalized_age_source = "ageInYears2"
    elif _flag_is_true(payload.get("isChild")) and final_age_years is not None:
        normalized_age_source = "finalAgeInYears"
    elif _flag_is_true(payload.get("isAdult")) and age_in_years is not None:
        normalized_age_source = "ageInYears"
    elif _flag_is_true(payload.get("isAdult")) and age_in_years2 is not None:
        normalized_age_source = "ageInYears2"
    elif _flag_is_true(payload.get("isAdult")) and final_age_years is not None:
        normalized_age_source = "finalAgeInYears"
    elif age_in_years is not None:
        normalized_age_source = "ageInYears"
    elif age_in_days is not None:
        normalized_age_source = "ageInDays"
    elif age_in_months is not None:
        normalized_age_source = "ageInMonths"
    elif age_in_years2 is not None:
        normalized_age_source = "ageInYears2"
    elif final_age_years is not None:
        normalized_age_source = "finalAgeInYears"

    normalized_age_days = None
    normalized_age_years = None
    if normalized_age_source == "age_neonate_hours":
        normalized_age_days = Decimal("0")
        normalized_age_years = Decimal("0")
    elif normalized_age_source == "age_neonate_days":
        normalized_age_days = age_neonate_days
        normalized_age_years = age_neonate_days / _DAYS_PER_YEAR
    elif normalized_age_source == "ageInDays":
        normalized_age_days = age_in_days
        normalized_age_years = age_in_days / _DAYS_PER_YEAR
    elif normalized_age_source == "ageInMonths":
        normalized_age_days = age_in_months * _DAYS_PER_MONTH
        normalized_age_years = age_in_months / Decimal("12")
    elif normalized_age_source == "ageInYears":
        normalized_age_days = age_in_years * _DAYS_PER_YEAR
        normalized_age_years = age_in_years
    elif normalized_age_source == "ageInYears2":
        normalized_age_days = age_in_years2 * _DAYS_PER_YEAR
        normalized_age_years = age_in_years2
    elif normalized_age_source == "finalAgeInYears":
        normalized_age_days = final_age_years * _DAYS_PER_YEAR
        normalized_age_years = final_age_years

    legacy_age_years = int(final_age_years) if final_age_years is not None else 0
    return NormalizedWhoAge(
        legacy_age_years=legacy_age_years,
        normalized_age_days=normalized_age_days,
        normalized_age_years=normalized_age_years,
        normalized_age_source=normalized_age_source,
    )
