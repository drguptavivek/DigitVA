"""Convert an ODK XLSForm into the questionnaire package's instrument JSON.

Why
---
DigitVA collects the WHO VA 2022 questionnaire through two paths: ODK Central,
and its own clients driven by the vendored `who-va-2022` package. PHMRC and the
Ballabgarh form will be authored as ODK XLSForms too, so without a converter
each new questionnaire would have to be hand-built a second time for the app.

This builder makes the XLSForm the single authoring source: publish it to ODK
Central for ODK collection, and generate the instrument from the same workbook
for the DigitVA clients.

How it can work at all
----------------------
The package's engine evaluates ODK's own expression language. Every expression
in an instrument is stored as its raw XLSForm source —
`selected(${Id10020}, 'yes')`, `. <= today()`, `if(...)` — with an optional
pre-parsed `ast` that the runtime derives from the source when absent. So
relevance, constraint and calculation expressions pass through unchanged and
this converter never has to understand them.

Fidelity
--------
`tests/services/test_xlsform_instrument_builder.py` rebuilds the WHO 2022
instrument from `vendor/who-va-2022/whova2022_xls_form_for_odk.xlsx` and
compares it to the hand-audited `who-va-2022.instrument.json` that ships with
the package, so conversion accuracy is measured against a known-good target
rather than asserted.

Type coverage
-------------
Supported, matching DigitVA's engine (``vendor/who-va-2022``): text, integer,
decimal, date, time, datetime, select_one, select_multiple, barcode, range,
geopoint, note, calculate, acknowledge/trigger, image, audio, file, hidden, and
the metadata types (start, end, today, deviceid, username, phonenumber, email,
audit).

Refused, deliberately and by name: `begin repeat`, geotrace, geoshape,
start-geopoint, video, background-audio and rank. Each raises with the engine
work it would need. Refusing beats mapping a type onto a near-enough control —
a decimal silently stored as an integer, or a geopoint as text, discards what
the interviewer entered and only surfaces downstream. When the engine gains a
control, move the type from ``PLANNED_TYPES`` into ``TYPE_MAP``.

`tooling/who-va-2022 && npm run check:types` exercises the engine side of that
contract.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)


class XlsFormConversionError(RuntimeError):
    """The workbook cannot be represented as an instrument."""


# XLSForm question type -> (control, dataType), matching DigitVA's engine
# (vendor/who-va-2022). Selection types are handled separately because they
# carry a list name.
TYPE_MAP: dict[str, tuple[str, str]] = {
    "text": ("text", "string"),
    "integer": ("integer", "number"),
    "decimal": ("decimal", "decimal"),
    "date": ("date", "date"),
    "time": ("time", "time"),
    "datetime": ("datetime", "dateTime"),
    "barcode": ("barcode", "string"),
    "range": ("range", "number"),
    "geopoint": ("geopoint", "geopoint"),
    "calculate": ("calculated", "calculated"),
    "note": ("note", "none"),
    "trigger": ("confirm", "boolean"),
    "acknowledge": ("confirm", "boolean"),
    "audio": ("audio", "attachment"),
    "image": ("image", "attachment"),
    "file": ("file", "attachment"),
    # A hidden field holds a default or calculated value and is never shown,
    # which is what the calculated control already does.
    "hidden": ("calculated", "calculated"),
    # Metadata questions the client fills in itself.
    "start": ("system", "dateTime"),
    "end": ("system", "dateTime"),
    "today": ("system", "date"),
    "audit": ("system", "audit"),
    "deviceid": ("system", "string"),
    "username": ("system", "string"),
    "phonenumber": ("system", "string"),
    "email": ("system", "string"),
}

# In scope for DigitVA, but the engine has no control for them yet. These are
# refused rather than mapped onto a near-enough control: silently turning a
# decimal into an integer or a geopoint into text loses data the interviewer
# entered, and the loss would only surface downstream. Each entry names the
# engine work that would let the converter accept it.
PLANNED_TYPES: dict[str, str] = {
    "geotrace": "a geotrace control",
    "geoshape": "a geoshape control",
    "start-geopoint": "background geopoint capture",
    "video": "a video attachment control",
    "background-audio": "background audio capture",
    "rank": "a rank control",
}

GROUP_OPEN = "begin group"
GROUP_CLOSE = "end group"
REPEAT_OPEN = "begin repeat"
REPEAT_CLOSE = "end repeat"

# "label::English (en)" -> "en"; a bare "label" means the default language.
_LOCALE_RE = re.compile(r"^(?P<field>[a-z_]+)(?:::.*\((?P<code>[A-Za-z0-9-]+)\))?$")

# pandas gives the header row index 0, so a DataFrame row maps to this sheet row.
_SHEET_ROW_OFFSET = 2


def _text(value: Any) -> str | None:
    """Return a stripped string, or None for NaN/blank."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    return text or None


def _flag(value: Any) -> bool:
    """XLSForm truthiness: yes/true/1, in any case.

    Numeric cells matter: openpyxl reads a bare 1 in read_only as 1.0, which
    must not read as false.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return not pd.isna(value) and float(value) != 0.0
    text = _text(value)
    return text is not None and text.lower() in {"yes", "true", "1"}


def _localized(row: pd.Series, field: str, columns: dict[str, dict[str, str]]) -> dict[str, str]:
    """Collect one logical field across its per-language columns."""
    out: dict[str, str] = {}
    for locale, column in columns.get(field, {}).items():
        text = _text(row.get(column))
        if text is not None:
            out[locale] = text
    return out


def _language_columns(frame: pd.DataFrame, default_language: str) -> dict[str, dict[str, str]]:
    """Map {logical field: {locale: column name}} from the sheet's headers."""
    columns: dict[str, dict[str, str]] = {}
    for column in frame.columns:
        match = _LOCALE_RE.match(str(column).strip())
        if not match:
            continue
        field = match.group("field")
        locale = match.group("code") or default_language
        columns.setdefault(field, {})[locale] = column
    return columns


def _restrict_locales(
    columns: dict[str, dict[str, str]], locales: set[str] | None
) -> dict[str, dict[str, str]]:
    """Drop every locale not in `locales`; None keeps everything unchanged."""
    if locales is None:
        return columns
    return {
        field: {locale: column for locale, column in locale_map.items() if locale in locales}
        for field, locale_map in columns.items()
    }


def _expression(value: Any) -> dict[str, str] | None:
    """Keep an XLSForm expression as its source; the runtime parses it."""
    source = _text(value)
    return {"source": source} if source else None


def _read_settings(path: Path) -> dict[str, str]:
    frame = pd.read_excel(path, sheet_name="settings")
    if frame.empty:
        raise XlsFormConversionError("The settings sheet is empty.")
    row = frame.iloc[0]
    return {
        "id": _text(row.get("form_id")) or path.stem,
        "title": _text(row.get("form_title")) or path.stem,
        "version": _text(row.get("version")) or "",
        # Kept verbatim ("English (en)"), as the package's own instrument does.
        # Locale *keys* use the bare code parsed out of the column headers.
        "defaultLanguage": _text(row.get("default_language")) or "en",
        "defaultLocale": _default_language(_text(row.get("default_language"))),
    }


def _default_language(raw: str | None) -> str:
    """'English (en)' -> 'en'; a bare code passes through; default 'en'."""
    if not raw:
        return "en"
    match = re.search(r"\(([A-Za-z0-9-]+)\)\s*$", raw)
    return match.group(1) if match else raw


def _read_choices(
    path: Path, default_language: str, locales: set[str] | None = None
) -> dict[str, list[dict]]:
    frame = pd.read_excel(path, sheet_name="choices")
    columns = _restrict_locales(_language_columns(frame, default_language), locales)
    lists: dict[str, list[dict]] = {}
    for index, row in frame.iterrows():
        list_name = _text(row.get("list_name"))
        value = _text(row.get("name"))
        if not list_name or value is None:
            continue
        lists.setdefault(list_name, []).append(
            {
                "value": value,
                "label": _localized(row, "label", columns),
                "sourceRow": int(index) + _SHEET_ROW_OFFSET,
            }
        )
    return lists


def build_instrument_from_xlsform(
    path: str | Path,
    *,
    form_type_code: str | None = None,
    locales: set[str] | None = None,
) -> dict:
    """Return the instrument definition for an ODK XLSForm workbook.

    ``form_type_code`` is DigitVA's own stable identifier for the
    questionnaire (``mas_form_types.form_type_code``, e.g. ``WHO_2022_VA``).
    It is supplied by the caller and never derived from the workbook: the
    settings sheet's ``form_id``/``version`` belong to whoever authored the
    XLSForm and change between revisions, so binding field and choice mappings
    to them would silently re-point a project's mappings on the next form
    republish. Those values are still recorded, under ``source``, as the audit
    trail of which workbook produced this instrument.

    ``locales`` restricts which locale columns are emitted into every label,
    hint, guidance, constraint message and choice label (e.g. ``{"en"}`` for
    an English-only instrument). Defaults to ``None``, which keeps every
    locale the workbook carries -- the behaviour every existing caller
    already depends on.
    """
    path = Path(path)
    if not path.exists():
        raise XlsFormConversionError(f"XLSForm not found: {path}")

    settings = _read_settings(path)
    default_language = settings["defaultLocale"]
    choice_lists = _read_choices(path, default_language, locales)

    survey = pd.read_excel(path, sheet_name="survey")
    columns = _restrict_locales(_language_columns(survey, default_language), locales)

    sections: list[dict] = []
    questions: list[dict] = []
    section_stack: list[str] = []
    order = -1  # 0-based over emitted sections and questions

    for index, row in survey.iterrows():
        raw_type = _text(row.get("type"))
        if not raw_type:
            continue
        source_row = int(index) + _SHEET_ROW_OFFSET
        name = _text(row.get("name"))
        parts = raw_type.split()
        head = parts[0]
        lowered = raw_type.lower()

        if lowered.startswith(REPEAT_OPEN) or lowered.startswith(REPEAT_CLOSE):
            raise XlsFormConversionError(
                f"Row {source_row}: repeat groups are not supported by the "
                "instrument model; the engine has no repeat semantics."
            )

        if lowered.startswith(GROUP_OPEN):
            if not name:
                raise XlsFormConversionError(f"Row {source_row}: a group needs a name.")
            order += 1
            section = {
                "name": name,
                "sourceRow": source_row,
                "order": order,
                "label": _localized(row, "label", columns),
                "ageGroup": _text(row.get("agegroup")),
                "parent": section_stack[-1] if section_stack else None,
            }
            group_relevance = _expression(row.get("relevant"))
            if group_relevance:
                section["relevant"] = group_relevance
            sections.append(section)
            section_stack.append(name)
            continue

        if lowered.startswith(GROUP_CLOSE):
            if not section_stack:
                raise XlsFormConversionError(f"Row {source_row}: unmatched end group.")
            section_stack.pop()
            # An end-group row emits nothing but still consumes an order slot,
            # so `order` stays aligned with the survey sheet's own sequence.
            order += 1
            continue

        if not name:
            continue

        list_name = None
        if head in {"select_one", "select_multiple"}:
            if len(parts) < 2:
                raise XlsFormConversionError(
                    f"Row {source_row}: {head} is missing its choice list name."
                )
            list_name = parts[1]
            control = "singleChoice" if head == "select_one" else "multipleChoice"
            data_type = "string" if head == "select_one" else "string[]"
        else:
            mapped = TYPE_MAP.get(head)
            if mapped is None:
                if head in PLANNED_TYPES:
                    raise XlsFormConversionError(
                        f"Row {source_row}: '{head}' is in scope for DigitVA but the "
                        f"engine cannot render it yet — it needs {PLANNED_TYPES[head]}. "
                        "Refusing rather than mapping it onto a near-enough control, "
                        "which would lose what the interviewer entered."
                    )
                raise XlsFormConversionError(
                    f"Row {source_row}: unsupported XLSForm type '{raw_type}'."
                )
            control, data_type = mapped

        order += 1
        constraint = _expression(row.get("constraint"))
        constraint_message = _localized(row, "constraint_message", columns)
        required = _flag(row.get("required"))

        question: dict[str, Any] = {
            "name": name,
            "order": order,
            "sourceRow": source_row,
            "sourceType": raw_type,
            "dataType": data_type,
            "control": control,
            "label": _localized(row, "label", columns),
            "hint": _localized(row, "hint", columns),
            "guidance": _localized(row, "guidance_hint", columns),
            "required": required,
            "readOnly": _flag(row.get("read_only")),
            "constraintMessage": constraint_message,
            "validation": {
                "required": required,
                "dataType": data_type,
                **({"constraint": constraint} if constraint else {}),
                "constraintMessage": constraint_message,
            },
            "sectionPath": list(section_stack),
            "ageGroup": _text(row.get("agegroup")),
        }

        relevant = _expression(row.get("relevant"))
        if relevant:
            question["relevant"] = relevant
        if constraint:
            question["constraint"] = constraint
        calculation = _expression(row.get("calculation"))
        if calculation:
            question["calculation"] = calculation
        appearance = _text(row.get("appearance"))
        if appearance:
            question["appearance"] = appearance
        default_value = _text(row.get("default"))
        if default_value is not None:
            question["defaultValue"] = default_value
        parameters = _text(row.get("parameters"))
        if parameters:
            question["parameters"] = parameters
        if list_name:
            question["listName"] = list_name
            if list_name not in choice_lists:
                raise XlsFormConversionError(
                    f"Row {source_row}: choice list '{list_name}' is not in the choices sheet."
                )
            question["choices"] = choice_lists[list_name]
            question["validation"]["choiceValues"] = [
                choice["value"] for choice in choice_lists[list_name]
            ]

        questions.append(question)

    if section_stack:
        raise XlsFormConversionError(
            f"Unclosed group(s) at end of survey: {', '.join(section_stack)}"
        )

    log.info(
        "xlsform -> instrument | %s | %d sections | %d questions",
        path.name,
        len(sections),
        len(questions),
    )
    instrument = {
        "id": settings["id"],
        "title": settings["title"],
        "version": settings["version"],
        "defaultLanguage": settings["defaultLanguage"],
        "sourceFile": path.name,
        # Provenance, for audit only. Never use these to look up a mapping.
        "source": {
            "formId": settings["id"],
            "formTitle": settings["title"],
            "formVersion": settings["version"],
            "file": path.name,
        },
        "sections": sections,
        "questions": questions,
    }
    if form_type_code:
        # The key DigitVA binds field and choice mappings to.
        instrument["formTypeCode"] = form_type_code.strip().upper()
    else:
        log.warning(
            "xlsform -> instrument | %s | no form_type_code supplied; the "
            "instrument carries no DigitVA mapping key and cannot be bound to "
            "a form type",
            path.name,
        )
    return instrument
