"""Bound and normalize WHO death certificates before mortality processing."""

from __future__ import annotations

import copy
import json
import re
from calendar import monthrange
from dataclasses import dataclass

from app.services.who_icd_api import DEFAULT_ICD11_RELEASE, get_icd11_codeinfo

MAX_REQUEST_BYTES = 32 * 1024
MAX_PART1_LINES = 5
MAX_CONDITIONS_PER_LINE = 8
MAX_TOTAL_CONDITIONS = 20
MAX_TEXT_LENGTH = 500

_CERTIFICATE_KEYS = {
    "ICDVersion",
    "ICDMinorVersion",
    "AdministrativeData",
    "Part1",
    "Part2",
    "Surgery",
    "Autopsy",
    "MannerOfDeath",
    "FetalOrInfantDeath",
    "MaternalDeath",
}
_CONDITION_KEYS = {"Text", "Code", "LinearizationURI", "FoundationURI", "Interval"}
_UNKNOWN_MEASUREMENTS = {"BirthWeight", "PregnancyWeeks", "AgeMother"}
_EXPRESSION_SEPARATOR = re.compile(r"\s*([&/])\s*")
_DATE_RE = re.compile(
    r"^(?P<year>\d{4})"
    r"(?:-(?P<month>\d{2})(?:-(?P<day>\d{2}))?)?"
    r"(?:T(?P<hour>\d{2}):(?P<minute>\d{2})"
    r"(?::(?P<second>\d{2})(?:\.\d+)?)?"
    r"(?P<timezone>Z|[+-]\d{2}:\d{2})?)?$"
)
_DURATION_RE = re.compile(
    r"^P(?:(?:(?:\d+(?:\.\d+)?Y)?(?:\d+(?:\.\d+)?M)?"
    r"(?:\d+(?:\.\d+)?D)?)(?:T(?:\d+(?:\.\d+)?H)?"
    r"(?:\d+(?:\.\d+)?M)?(?:\d+(?:\.\d+)?S)?)?"
    r"|\d+(?:\.\d+)?W)?$"
)

_YES_NO_UNKNOWN = {0, 1, 9}
_SEX_VALUES = {1, 2, 9}
_MANNER_OF_DEATH_VALUES = {0, 1, 2, 3, 4, 5, 6, 7, 9}
_PLACE_OF_OCCURRENCE_VALUES = set(range(10))
_MATERNAL_TIMING_VALUES = {0, 1, 2, 3, 9}


@dataclass(frozen=True)
class DorisFieldError:
    path: str
    message: str


class DorisCertificateError(ValueError):
    def __init__(self, fields: list[DorisFieldError]):
        super().__init__("The DORIS certificate is invalid.")
        self.fields = fields


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _error(path: str, message: str) -> DorisCertificateError:
    return DorisCertificateError([DorisFieldError(path, message)])


def _validate_condition(condition: object, path: str) -> dict:
    if not isinstance(condition, dict):
        raise _error(path, "Must be an object.")
    unknown = set(condition) - _CONDITION_KEYS
    if unknown:
        raise _error(path, "Contains unsupported fields.")

    result = copy.deepcopy(condition)
    text = result.get("Text")
    if not isinstance(text, str) or not text.strip():
        raise _error(f"{path}.Text", "Enter condition text.")
    if len(text) > MAX_TEXT_LENGTH:
        raise _error(f"{path}.Text", "Must be 500 characters or fewer.")
    result["Text"] = text.strip()

    code = result.get("Code")
    uri = result.get("LinearizationURI")
    if (code is None) != (uri is None):
        raise _error(path, "Code and LinearizationURI must be supplied together.")
    if code is not None:
        if not isinstance(code, str) or not code.strip() or len(code) > 128:
            raise _error(f"{path}.Code", "Must be a valid ICD-11 expression.")
        if not isinstance(uri, str) or not uri.strip() or len(uri) > 2048:
            raise _error(f"{path}.LinearizationURI", "Must be a valid WHO URI.")
        result["Code"] = code.strip()
        result["LinearizationURI"] = uri.strip()

    for key in ("FoundationURI", "Interval"):
        value = result.get(key)
        if value is not None and not isinstance(value, str):
            raise _error(f"{path}.{key}", "Must be text.")
        if isinstance(value, str):
            result[key] = value.strip()
    if result.get("Interval"):
        result["Interval"] = _duration(result["Interval"], f"{path}.Interval")
    return result


def _normalize_conditions(raw: object, path: str) -> list[dict]:
    if not isinstance(raw, list) or not raw:
        raise _error(path, "Enter at least one condition.")
    if len(raw) > MAX_CONDITIONS_PER_LINE:
        raise _error(path, "A line may contain at most 8 conditions.")
    conditions = [_validate_condition(item, f"{path}[{i}]") for i, item in enumerate(raw)]
    intervals = {item.get("Interval") for item in conditions}
    if len(intervals) > 1:
        raise _error(path, "All conditions on a line must use the same interval.")
    return conditions


def _integer(value: object, path: str, *, values: set[int] | None = None,
             minimum: int | None = None, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(path, "Must be an integer.")
    if values is not None and value not in values:
        raise _error(path, "Contains an unsupported value.")
    if minimum is not None and value < minimum:
        raise _error(path, f"Must be at least {minimum}.")
    if maximum is not None and value > maximum:
        raise _error(path, f"Must be at most {maximum}.")
    return value


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _error(path, "Must be non-empty text.")
    if len(value) > MAX_TEXT_LENGTH:
        raise _error(path, f"Must be {MAX_TEXT_LENGTH} characters or fewer.")
    return value.strip()


def _date(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise _error(path, "Must be a valid date.")
    value = value.strip()
    match = _DATE_RE.fullmatch(value)
    if match is None:
        raise _error(path, "Must be a valid date.")

    parts = {
        name: int(raw)
        for name, raw in match.groupdict().items()
        if raw is not None and name != "timezone"
    }
    if parts["year"] < 1:
        raise _error(path, "Must be a valid date.")
    month = parts.get("month")
    day = parts.get("day")
    if month is not None and not 1 <= month <= 12:
        raise _error(path, "Must be a valid date.")
    if day is not None and (month is None or day < 1 or day > monthrange(parts["year"], month)[1]):
        raise _error(path, "Must be a valid date.")
    if parts.get("hour") is not None and not 0 <= parts["hour"] <= 23:
        raise _error(path, "Must be a valid date.")
    if parts.get("minute") is not None and not 0 <= parts["minute"] <= 59:
        raise _error(path, "Must be a valid date.")
    if parts.get("second") is not None and not 0 <= parts["second"] <= 59:
        raise _error(path, "Must be a valid date.")
    timezone = match.group("timezone")
    if timezone not in {None, "Z"} and (
        int(timezone[-5:-3]) > 23 or int(timezone[-2:]) > 59
    ):
        raise _error(path, "Must be a valid date.")
    if "T" in value and day is None:
        raise _error(path, "Must be a valid date.")
    return value


def _duration(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise _error(path, "Must be a valid ISO 8601 duration.")
    value = value.strip()
    if _DURATION_RE.fullmatch(value) is None:
        raise _error(path, "Must be a valid ISO 8601 duration.")
    return value


def _nested_object(value: object, path: str, fields: dict[str, object]) -> dict:
    if not isinstance(value, dict):
        raise _error(path, "Must be an object.")
    unknown = set(value) - set(fields)
    if unknown:
        raise _error(path, "Contains unsupported fields.")
    normalized = {}
    for key, raw in value.items():
        validator = fields[key]
        normalized[key] = validator(raw, f"{path}.{key}")
    return normalized


def _normalize_administrative_data(value: object, path: str) -> dict:
    return _nested_object(
        value,
        path,
        {
            "DateBirth": _date,
            "DateDeath": _date,
            "Sex": lambda item, item_path: _integer(
                item, item_path, values=_SEX_VALUES
            ),
            "EstimatedAge": _duration,
        },
    )


def _normalize_surgery(value: object, path: str) -> dict:
    return _nested_object(
        value,
        path,
        {
            "WasPerformed": lambda item, item_path: _integer(
                item, item_path, values=_YES_NO_UNKNOWN
            ),
            "Date": _date,
            "Reason": _text,
        },
    )


def _normalize_autopsy(value: object, path: str) -> dict:
    return _nested_object(
        value,
        path,
        {
            "WasRequested": lambda item, item_path: _integer(
                item, item_path, values=_YES_NO_UNKNOWN
            ),
            "Findings": lambda item, item_path: _integer(
                item, item_path, values=_YES_NO_UNKNOWN
            ),
        },
    )


def _normalize_manner_of_death(value: object, path: str) -> dict:
    return _nested_object(
        value,
        path,
        {
            "MannerOfDeath": lambda item, item_path: _integer(
                item, item_path, values=_MANNER_OF_DEATH_VALUES
            ),
            "DateOfExternalCauseOrPoisoning": _date,
            "DescriptionExternalCause": _text,
            "PlaceOfOccuranceExternalCause": lambda item, item_path: _integer(
                item, item_path, values=_PLACE_OF_OCCURRENCE_VALUES
            ),
        },
    )


def _normalize_fetal_or_infant_death(value: object, path: str) -> dict:
    if not isinstance(value, dict):
        raise _error(path, "Must be an object.")
    unknown = set(value) - {
        "MultiplePregnancy",
        "Stillborn",
        "DeathWithin24h",
        "BirthWeight",
        "PregnancyWeeks",
        "AgeMother",
        "PerinatalDescription",
    }
    if unknown:
        raise _error(path, "Contains unsupported fields.")
    normalized = {}
    validators = {
        "MultiplePregnancy": lambda item, item_path: _integer(
            item, item_path, values=_YES_NO_UNKNOWN
        ),
        "Stillborn": lambda item, item_path: _integer(
            item, item_path, values=_YES_NO_UNKNOWN
        ),
        "DeathWithin24h": lambda item, item_path: _integer(
            item, item_path, minimum=0, maximum=24
        ),
        "BirthWeight": lambda item, item_path: _integer(
            item, item_path, minimum=1, maximum=9999
        ),
        "PregnancyWeeks": lambda item, item_path: _integer(
            item, item_path, minimum=1, maximum=50
        ),
        "AgeMother": lambda item, item_path: _integer(
            item, item_path, minimum=10, maximum=80
        ),
        "PerinatalDescription": _text,
    }
    for key, raw in value.items():
        # WHO's exchange format represents unknown fetal measurements by
        # omission. Preserve the established normalization for these fields.
        if key in _UNKNOWN_MEASUREMENTS and (raw is None or raw == ""):
            continue
        normalized[key] = validators[key](raw, f"{path}.{key}")
    return normalized


def _normalize_maternal_death(value: object, path: str) -> dict:
    return _nested_object(
        value,
        path,
        {
            "WasPregnant": lambda item, item_path: _integer(
                item, item_path, values=_YES_NO_UNKNOWN
            ),
            "TimeFromPregnancy": lambda item, item_path: _integer(
                item, item_path, values=_MATERNAL_TIMING_VALUES
            ),
            "PregnancyContribute": lambda item, item_path: _integer(
                item, item_path, values=_YES_NO_UNKNOWN
            ),
        },
    )


def normalize_certificate(certificate: object, release: str = DEFAULT_ICD11_RELEASE) -> dict:
    """Return a bounded copy suitable for WHO, without mutating caller data."""

    if not isinstance(certificate, dict):
        raise _error("certificate", "Must be an object.")
    if set(certificate) - _CERTIFICATE_KEYS:
        raise _error("certificate", "Contains unsupported fields.")
    if certificate.get("ICDVersion") != "ICD11":
        raise _error("certificate.ICDVersion", "Must be ICD11.")
    supplied_release = certificate.get("ICDMinorVersion")
    if supplied_release not in {None, release}:
        raise _error("certificate.ICDMinorVersion", "Must match the configured release.")

    result = copy.deepcopy(certificate)
    result["ICDMinorVersion"] = release
    nested_normalizers = {
        "AdministrativeData": _normalize_administrative_data,
        "Surgery": _normalize_surgery,
        "Autopsy": _normalize_autopsy,
        "MannerOfDeath": _normalize_manner_of_death,
        "FetalOrInfantDeath": _normalize_fetal_or_infant_death,
        "MaternalDeath": _normalize_maternal_death,
    }
    for key, normalizer in nested_normalizers.items():
        if key in result:
            result[key] = normalizer(result[key], f"certificate.{key}")

    part1 = result.get("Part1")
    if not isinstance(part1, list) or not part1:
        raise _error("certificate.Part1", "Enter at least one Part I line.")
    if len(part1) > MAX_PART1_LINES:
        raise _error("certificate.Part1", "Part I may contain at most 5 lines.")
    normalized_lines = []
    total = 0
    for index, line in enumerate(part1):
        path = f"certificate.Part1[{index}]"
        if not isinstance(line, dict) or set(line) != {"Conditions"}:
            raise _error(path, "Must contain only Conditions.")
        conditions = _normalize_conditions(line["Conditions"], f"{path}.Conditions")
        total += len(conditions)
        normalized_lines.append({"Conditions": conditions})
    result["Part1"] = normalized_lines

    part2 = result.get("Part2")
    if part2 is not None:
        if not isinstance(part2, dict) or set(part2) != {"Conditions"}:
            raise _error("certificate.Part2", "Must contain only Conditions.")
        raw_part2 = part2["Conditions"]
        if not isinstance(raw_part2, list):
            raise _error("certificate.Part2.Conditions", "Must be a list.")
        if raw_part2:
            conditions = _normalize_conditions(raw_part2, "certificate.Part2.Conditions")
            total += len(conditions)
            result["Part2"] = {"Conditions": conditions}
        else:
            result["Part2"] = {"Conditions": []}
    if total > MAX_TOTAL_CONDITIONS:
        raise _error("certificate", "A certificate may contain at most 20 conditions.")

    if len(canonical_json_bytes(result)) > MAX_REQUEST_BYTES:
        raise _error("certificate", "The certificate is too large.")
    return result


def expected_expression_uri(code: str, release: str = DEFAULT_ICD11_RELEASE) -> str | None:
    """Resolve the canonical release-pinned URI expression through WHO codeinfo."""

    parts = _EXPRESSION_SEPARATOR.split(code)
    expression_info = get_icd11_codeinfo(code, release=release)
    if not isinstance(expression_info, dict) or expression_info.get("code") != code:
        return None
    if len(parts) == 1:
        uri = expression_info.get("stemId")
        return uri if isinstance(uri, str) and uri else None

    uris = []
    for token in parts[::2]:
        info = get_icd11_codeinfo(token, release=release)
        if not isinstance(info, dict) or info.get("code") != token:
            return None
        uri = info.get("stemId")
        if not isinstance(uri, str) or not uri:
            return None
        uris.append(uri)
    separators = parts[1::2]
    expected = uris[0]
    for separator, uri in zip(separators, uris[1:], strict=True):
        expected += f" {separator} {uri}"
    return expected


def verify_certificate_codes(certificate: dict, release: str = DEFAULT_ICD11_RELEASE) -> None:
    """Verify every supplied complete code and URI against pinned codeinfo."""

    groups = [
        (f"certificate.Part1[{index}].Conditions", line["Conditions"])
        for index, line in enumerate(certificate["Part1"])
    ]
    part2 = certificate.get("Part2", {}).get("Conditions", [])
    if part2:
        groups.append(("certificate.Part2.Conditions", part2))
    for group_path, conditions in groups:
        for index, condition in enumerate(conditions):
            code = condition.get("Code")
            if code is None:
                continue
            expected = expected_expression_uri(code, release)
            if expected != condition["LinearizationURI"]:
                raise _error(
                    f"{group_path}[{index}].LinearizationURI",
                    "Does not match the selected ICD-11 code.",
                )
