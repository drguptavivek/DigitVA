"""Import, serve and edit the display translations of a standard instrument.

Policy: docs/policy/va-form-project-configuration.md ("Translation sources")
and docs/policy/va-web-form-options.md ("Adding a language").

A translation is data. The instrument's structure is pre-built from the curated
reference form and never changes here: every string an import writes is keyed
to an item the reference already has, so a deployed project workbook can supply
Hindi for a question but can never add one. What the reference lacks is
reported, not stored.

The reference an import is checked against is the curated WHO workbook
**plus** the DigitVA layer questions (``consent_mode``, ``md_im1``..30,
``ds_*``, ``narr_language``, ``abha_*`` and so on), which exist only in the
TypeScript instrument builder. ``tooling/who-va-2022/build-layer-reference.mjs``
serializes their English strings to the committed
``vendor/who-va-2022/src/generated/digitva-layers.reference.json`` artifact;
this module reads it rather than duplicating the layer definitions in Python.

Two rules this module exists to enforce:

* **One documented source workbook per language.** Which workbook is a
  language's source is policy, recorded in the "Translation sources" table of
  ``docs/policy/va-form-project-configuration.md``. This module parses that
  table rather than keeping a second copy, so changing a source means editing
  the doc. Any other workbook is refused unless the caller asks for a
  cross-check, which reports differences and writes nothing.
* **A layer item never overwrites a WHO base item.** The WHO base and the
  DigitVA layers are disjoint namespaces today; a collision is a bug in one of
  the two sources, so it raises rather than silently letting one shadow the
  other.

Locale activation (whether a language is served to forms) is an explicit
administrative action, independent of coverage (decided 2026-09-19: English
fallback is per-string, so a coverage percentage is not a serving decision).
Coverage is still computed and reported everywhere it was before.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd
import sqlalchemy as sa

from app import db
from app.models.mas_instrument_locales import (
    FIELD_GUIDANCE,
    FIELD_HINT,
    FIELD_LABEL,
    ITEM_KIND_CHOICE,
    ITEM_KIND_QUESTION,
    SOURCE_EDITED,
    SOURCE_IMPORTED,
    MapInstrumentTranslations,
    MasInstrumentLocales,
)
from app.services.xlsform_instrument_builder import (
    _default_language,
    _language_columns,
    _text,
)

log = logging.getLogger(__name__)

#: Repository root, so every path this module names is repo-relative.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: The curated reference form. Structure comes from here and nowhere else:
#: a project's deployed workbook is a translation overlay, never a schema.
REFERENCE_WORKBOOK = (
    REPO_ROOT / "docs/kb/WHO_VA_2022_Docs/whova2022_xls_form_for_odk.xlsx"
)

#: The policy document whose "Translation sources" table is the source rule.
SOURCE_POLICY_DOC = REPO_ROOT / "docs/policy/va-form-project-configuration.md"

#: Where a documented source workbook is looked up by file name.
WORKBOOK_DIR = REPO_ROOT / "docs/kb/WHO_VA_2022_Docs"

#: Generated artifact carrying the DigitVA-only delta (layer questions,
#: choices and hints) that the TypeScript instrument builder owns. Produced by
#: ``tooling/who-va-2022/build-layer-reference.mjs``; this module only reads
#: it. Each entry: ``itemKind`` ("question"|"choice"), ``itemKey``, ``field``,
#: ``text`` (English) and ``extensions`` (the layer name(s) it belongs to).
LAYER_REFERENCE_PATH = (
    REPO_ROOT / "vendor/who-va-2022/src/generated/digitva-layers.reference.json"
)

#: The base locale of every bundled instrument: always served, never imported.
BASE_LOCALE = "en"

#: The standard instrument DigitVA bundles today.
BASE_INSTRUMENT_CODE = "WHO_2022_VA"

#: Cap on one page of the admin string list, applied server-side.
MAX_STRING_PAGE_SIZE = 200
# A label, hint or guidance note; the longest reference string is well under
# a thousand characters, so this bounds an edit without constraining prose.
MAX_TRANSLATION_TEXT_CHARS = 4000

#: "label::Hindi (hi)" -> ("label", "Hindi", "hi").
_HEADER_RE = re.compile(
    r"^(?P<field>[a-z_]+)::(?P<name>.+?)\s*\((?P<code>[A-Za-z0-9-]+)\)$"
)

#: The XLSForm columns a translation may carry, and nothing else.
_TRANSLATABLE_FIELDS = (FIELD_LABEL, FIELD_HINT, FIELD_GUIDANCE)

#: How much of a string reaches the log. Translations hold no PII, but an edit
#: log line is an audit record, not a copy of the questionnaire.
_LOG_TEXT_LIMIT = 120


class InstrumentTranslationError(RuntimeError):
    """The import or edit cannot be performed as asked."""


@dataclass(frozen=True)
class DocumentedSource:
    """One row of the policy doc's "Translation sources" table."""

    locale_code: str
    language_name: str
    workbook: str
    project: str
    odk_form_id: str
    download_date: str
    assigned_by: str


@dataclass
class ImportReport:
    """What one import (or cross-check) found and did.

    Activation is a separate, explicit administrative action
    (:func:`set_locale_active`); an import never sets or refuses it, so this
    report carries no ``activated``/``forced`` outcome. Coverage stays
    informational: computed and reported, never a gate.
    """

    instrument_code: str
    locale_code: str
    workbook: str
    sha256: str
    cross_check: bool
    reference_labels: int = 0
    translated_labels: int = 0
    written: int = 0
    kept_edited: int = 0
    missing_from_workbook: list[str] = dataclass_field(default_factory=list)
    unknown_in_workbook: list[str] = dataclass_field(default_factory=list)
    #: ``{extension: {"translated": n, "total": n}}`` for the layer question
    #: labels this locale carries. Empty when the reference has no layers yet.
    extension_coverage: dict[str, dict[str, int]] = dataclass_field(default_factory=dict)

    @property
    def coverage(self) -> float:
        if not self.reference_labels:
            return 0.0
        return self.translated_labels / self.reference_labels

    def as_dict(self) -> dict:
        return {
            "instrument_code": self.instrument_code,
            "locale_code": self.locale_code,
            "workbook": self.workbook,
            "sha256": self.sha256,
            "cross_check": self.cross_check,
            "coverage": round(self.coverage, 4),
            "reference_labels": self.reference_labels,
            "translated_labels": self.translated_labels,
            "written": self.written,
            "kept_edited": self.kept_edited,
            # Capped: a workbook missing everything would otherwise return the
            # whole reference as a JSON body.
            "missing_from_workbook": self.missing_from_workbook[:50],
            "missing_from_workbook_count": len(self.missing_from_workbook),
            "unknown_in_workbook": self.unknown_in_workbook[:50],
            "unknown_in_workbook_count": len(self.unknown_in_workbook),
            "extension_coverage": {
                name: {
                    "translated": counts["translated"],
                    "total": counts["total"],
                    "coverage": round(counts["translated"] / counts["total"], 4)
                    if counts["total"]
                    else 0.0,
                }
                for name, counts in sorted(self.extension_coverage.items())
            },
        }


# ---------------------------------------------------------------------------
# The documented-source rule
# ---------------------------------------------------------------------------


def _cell(value: str) -> str:
    """One markdown table cell as plain text: backticks and emphasis removed."""
    return value.strip().strip("`").strip("*").strip()


def documented_sources(doc_path: Path | None = None) -> dict[str, DocumentedSource]:
    """``{locale_code: DocumentedSource}`` from the policy doc's table.

    The doc is the source of this rule, so it is parsed rather than mirrored in
    code: a second copy here would let the two disagree, and the doc is what a
    reviewer reads. A malformed or missing table raises -- refusing to import
    beats importing against a rule nobody can see.
    """
    path = Path(doc_path) if doc_path else SOURCE_POLICY_DOC
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise InstrumentTranslationError(
            f"The translation-sources policy {path} could not be read: {exc}"
        ) from exc

    heading = re.compile(r"^#{2,4}\s+Translation sources\s*$", re.IGNORECASE)
    start = next((i for i, line in enumerate(lines) if heading.match(line)), None)
    if start is None:
        raise InstrumentTranslationError(
            f"{path} has no 'Translation sources' section; a language's source "
            "workbook is policy and must be documented before it is imported."
        )

    header: list[str] | None = None
    sources: dict[str, DocumentedSource] = {}
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        if not stripped.startswith("|"):
            # The sources table is the first table in the section; once it
            # has ended, a later table (an inventory, a layer list) must not
            # be read as more sources.
            if header is not None and sources:
                break
            continue
        cells = [_cell(c) for c in stripped.strip("|").split("|")]
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if all(set(c) <= {"-", ":"} for c in cells if c):
            continue
        row = dict(zip(header, cells))
        locale = row.get("locale", "").lower()
        if not locale:
            continue
        sources[locale] = DocumentedSource(
            locale_code=locale,
            language_name=row.get("language", ""),
            workbook=row.get("source workbook", ""),
            project=row.get("project", ""),
            odk_form_id=row.get("odk form id", ""),
            download_date=row.get("download date", ""),
            assigned_by=row.get("assigned by", ""),
        )
    if not sources:
        raise InstrumentTranslationError(
            f"{path}'s 'Translation sources' table has no rows."
        )
    return sources


# ---------------------------------------------------------------------------
# Reading workbooks
# ---------------------------------------------------------------------------


def _locale_names(frame: pd.DataFrame) -> dict[str, str]:
    """``{locale code: language name}`` from a sheet's ``field::Name (code)``."""
    names: dict[str, str] = {}
    for column in frame.columns:
        match = _HEADER_RE.match(str(column).strip())
        if match:
            names.setdefault(match.group("code"), match.group("name").strip())
    return names


def _collect(
    frame: pd.DataFrame,
    default_locale: str,
    *,
    key_of,
    fields: tuple[str, ...],
    item_kind: str,
    out: dict[str, dict[tuple[str, str, str], str]],
) -> None:
    """Accumulate one sheet's per-locale strings into ``out``."""
    columns = _language_columns(frame, default_locale)
    for _, row in frame.iterrows():
        key = key_of(row)
        if key is None:
            continue
        for logical in fields:
            for locale, column in columns.get(logical, {}).items():
                text = _text(row.get(column))
                if text is None:
                    continue
                out.setdefault(locale, {})[(item_kind, key, logical)] = text


def read_workbook_items(
    path: Path | str,
) -> tuple[dict[str, dict[tuple[str, str, str], str]], dict[str, str]]:
    """Every localized string in an XLSForm, by locale.

    Returns ``({locale: {(item_kind, item_key, field): text}}, {locale: name})``.
    Item keys match the instrument: a question's ``name``, or a choice's
    ``list_name`` + ``/`` + ``name``.
    """
    path = Path(path)
    if not path.exists():
        raise InstrumentTranslationError(f"Workbook not found: {path}")
    try:
        settings = pd.read_excel(path, sheet_name="settings")
        survey = pd.read_excel(path, sheet_name="survey")
        choices = pd.read_excel(path, sheet_name="choices")
    except (ValueError, OSError) as exc:
        raise InstrumentTranslationError(
            f"{path.name} could not be read as an XLSForm: {exc}"
        ) from exc

    raw_default = _text(settings.iloc[0].get("default_language")) if not settings.empty else None
    default_locale = _default_language(raw_default)

    items: dict[str, dict[tuple[str, str, str], str]] = {}
    _collect(
        survey,
        default_locale,
        key_of=lambda row: _text(row.get("name")) if _text(row.get("type")) else None,
        fields=_TRANSLATABLE_FIELDS,
        item_kind=ITEM_KIND_QUESTION,
        out=items,
    )

    def choice_key(row):
        list_name = _text(row.get("list_name"))
        value = _text(row.get("name"))
        return f"{list_name}/{value}" if list_name and value else None

    _collect(
        choices,
        default_locale,
        key_of=choice_key,
        fields=(FIELD_LABEL,),
        item_kind=ITEM_KIND_CHOICE,
        out=items,
    )

    names = {**_locale_names(survey), **_locale_names(choices)}
    return items, names


@lru_cache(maxsize=4)
def _layer_entries_cached(path: str) -> tuple[dict, ...]:
    """The DigitVA layer artifact's ``entries``, or an empty tuple.

    A missing file is treated as "no layers yet" rather than an error: the
    artifact is generated by a separate TypeScript pipeline
    (``tooling/who-va-2022/build-layer-reference.mjs``) and a fresh checkout or
    a test fixture may legitimately not have built it.
    """
    text_path = Path(path)
    if not text_path.exists():
        return ()
    try:
        data = json.loads(text_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InstrumentTranslationError(
            f"{text_path.name} could not be read as the DigitVA layer "
            f"reference: {exc}"
        ) from exc
    return tuple(data.get("entries", ()))


def _layer_key(entry: dict) -> tuple[str, str, str]:
    return (entry["itemKind"], entry["itemKey"], entry["field"])


@lru_cache(maxsize=4)
def _reference_items_cached(
    workbook_path: str, layer_path: str
) -> dict[tuple[str, str, str], str]:
    items, _ = read_workbook_items(workbook_path)
    english = items.get(BASE_LOCALE)
    if not english:
        raise InstrumentTranslationError(
            f"{Path(workbook_path).name} carries no English strings; it "
            "cannot be the structural reference."
        )
    merged = dict(english)
    for entry in _layer_entries_cached(layer_path):
        key = _layer_key(entry)
        if key in merged:
            raise InstrumentTranslationError(
                f"Layer entry {key[0]}:{key[1]}:{key[2]} collides with a WHO "
                f"base reference item; the WHO base and the DigitVA layers "
                "must name disjoint items."
            )
        merged[key] = entry["text"]
    return merged


def reference_items(
    instrument_code: str = BASE_INSTRUMENT_CODE,
) -> dict[tuple[str, str, str], str]:
    """The curated reference form's English strings, keyed by item.

    This is the WHO base workbook plus the DigitVA layer questions from
    ``LAYER_REFERENCE_PATH`` -- everything a translation may be supplied for.
    Cached: both sources are committed reference material and do not change
    between requests, and reading the workbook costs three pandas passes.
    """
    if (instrument_code or "").strip().upper() != BASE_INSTRUMENT_CODE:
        raise InstrumentTranslationError(
            f"No reference form is bundled for instrument {instrument_code!r}."
        )
    return _reference_items_cached(str(REFERENCE_WORKBOOK), str(LAYER_REFERENCE_PATH))


@lru_cache(maxsize=4)
def _reference_extensions_cached(
    layer_path: str,
) -> dict[tuple[str, str, str], frozenset[str]]:
    return {
        _layer_key(entry): frozenset(entry["extensions"])
        for entry in _layer_entries_cached(layer_path)
    }


def reference_item_extensions(
    instrument_code: str = BASE_INSTRUMENT_CODE,
) -> dict[tuple[str, str, str], frozenset[str]]:
    """``{reference key: frozenset of extension names}`` for every item.

    A WHO base item maps to an empty set: it belongs to no extension and is
    always present. Pure over the same cached sources ``reference_items``
    reads; nothing here queries the database.
    """
    reference = reference_items(instrument_code)
    by_key = _reference_extensions_cached(str(LAYER_REFERENCE_PATH))
    return {key: by_key.get(key, frozenset()) for key in reference}


def reference_label_keys(
    instrument_code: str = BASE_INSTRUMENT_CODE,
) -> set[tuple[str, str, str]]:
    """The WHO base survey-label items coverage is measured over.

    Deliberately excludes layer question labels -- base coverage keeps its
    original meaning even though ``reference_items`` now also carries layers.
    Per-layer coverage is reported separately (:func:`extension_label_keys`).
    """
    extensions = reference_item_extensions(instrument_code)
    return {
        key
        for key in reference_items(instrument_code)
        if key[0] == ITEM_KIND_QUESTION
        and key[2] == FIELD_LABEL
        and not extensions.get(key)
    }


def extension_label_keys(
    instrument_code: str = BASE_INSTRUMENT_CODE,
) -> dict[str, set[tuple[str, str, str]]]:
    """``{extension name: {question-label keys it owns}}``.

    An item belonging to more than one extension (the generator allows it)
    counts toward each. Used to compute per-extension coverage alongside the
    base coverage from :func:`reference_label_keys`.
    """
    out: dict[str, set[tuple[str, str, str]]] = {}
    for key, extensions in reference_item_extensions(instrument_code).items():
        if key[0] != ITEM_KIND_QUESTION or key[2] != FIELD_LABEL:
            continue
        for name in extensions:
            out.setdefault(name, set()).add(key)
    return out


def _extension_coverage(
    instrument_code: str, translated: set[tuple[str, str, str]]
) -> dict[str, dict[str, int]]:
    """``{extension: {"translated": n, "total": n}}`` for one locale.

    ``translated`` is the locale's set of question-label keys that carry
    text; each extension's count is how many of its own labels are in it.
    """
    return {
        name: {"translated": len(keys & translated), "total": len(keys)}
        for name, keys in extension_label_keys(instrument_code).items()
    }


#: The " / "-separated packing convention seen in choice labels, e.g.
#: "Minutes / मिनट".
_PACKED_SLASH_SEPARATOR = " / "

#: The "English (Translation)" parenthetical convention, e.g. "Hindi (हिन्दी)".
#: A bare, non-nested parenthetical at the end of the cell only -- this must
#: not match a translation that legitimately ends in its own parenthetical
#: aside.
_PACKED_PAREN_RE = re.compile(r"^(?P<head>.+?)\s*\((?P<paren>[^()]+)\)$")


def _normalize_ws(text: str) -> str:
    """Collapse whitespace runs for an exact-match *comparison* only.

    Used solely to decide whether an English half matches the reference, so
    a workbook's stray double space does not defeat a split that is
    otherwise exact. Never applied to the text that gets kept -- that is
    still stored exactly as the workbook wrote it.
    """
    return re.sub(r"\s+", " ", text).strip()


def _interleaves_english_lines(value_lines: list[str], english: str) -> bool:
    """True when every line of the reference English shows up verbatim among
    ``value_lines``, e.g. sa05's hint, which alternates an English bullet
    with its "*"-prefixed Hindi counterpart line by line. That shape has no
    single English/translation boundary to cut at -- it is not a prefix, a
    suffix, or a two-part separator -- so it is not "splittable" at all.
    """
    english_lines = [line for line in (p.strip() for p in english.split("\n")) if line]
    if len(english_lines) < 2:
        return False
    value_norm = {_normalize_ws(line) for line in value_lines}
    return all(_normalize_ws(line) in value_norm for line in english_lines)


def split_packed(value: str, english: str | None) -> str:
    """Unpack a cell that carries English and the target language together.

    The deployed workbooks pack both languages into one cell using one of
    three conventions:

    * newline-separated -- "VA interviewer\\nवीए साक्षात्कारकर्ता"
    * " / "-separated choice labels -- "Minutes / मिनट"
    * an "English (Translation)" parenthetical -- "Hindi (हिन्दी)"

    A half is dropped only when it matches the reference English exactly
    (whitespace runs collapsed for the comparison only, never for the text
    kept -- see :func:`_normalize_ws`). Anything looser would risk silently
    truncating a translation that happens to start or end with an English
    word, so a cell that does not match one of these shapes exactly is
    returned unchanged rather than guessed at.

    A cell that interleaves the two languages line by line has no such
    boundary at all -- see :func:`_interleaves_english_lines`. That shape
    returns "" rather than the mixed blob, so the caller's existing
    "equal to the reference English" check (which also fires here, since ""
    is falsy) treats the item as untranslated instead of storing a value
    that is neither English nor a clean translation.
    """
    if not english or not value:
        return value

    if "\n" in value:
        parts = [part for part in (p.strip() for p in value.split("\n")) if part]
        if len(parts) >= 2:
            ref_norm = _normalize_ws(english)
            if _normalize_ws(parts[0]) == ref_norm:
                return "\n".join(parts[1:])
            if _normalize_ws(parts[-1]) == ref_norm:
                return "\n".join(parts[:-1])
            if _interleaves_english_lines(parts, english):
                return ""
        return value

    if _PACKED_SLASH_SEPARATOR in value:
        parts = [part.strip() for part in value.split(_PACKED_SLASH_SEPARATOR)]
        parts = [part for part in parts if part]
        if len(parts) == 2:
            ref_norm = _normalize_ws(english)
            if _normalize_ws(parts[0]) == ref_norm:
                return parts[1]
            if _normalize_ws(parts[1]) == ref_norm:
                return parts[0]
        return value

    match = _PACKED_PAREN_RE.match(value)
    if match and _normalize_ws(match.group("head")) == _normalize_ws(english):
        return match.group("paren").strip()

    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def _resolve_workbook(workbook: Path | str) -> Path:
    """A bare file name resolves inside the reference workbook folder."""
    path = Path(workbook)
    if not path.is_absolute() and not path.exists():
        candidate = WORKBOOK_DIR / path.name
        if candidate.exists():
            return candidate
    return path


def import_translations(
    instrument_code: str,
    locale_code: str,
    workbook: Path | str,
    *,
    cross_check: bool = False,
    actor_id=None,
    doc_path: Path | None = None,
) -> ImportReport:
    """Import one language from one workbook, or cross-check it.

    ``cross_check`` reads and reports without writing a single row, and is the
    only way to look at a workbook that is not the documented source for this
    locale. This never activates or deactivates the locale: activation is a
    separate, explicit administrative action (:func:`set_locale_active`),
    independent of coverage.
    """
    instrument_code = (instrument_code or "").strip().upper()
    locale_code = (locale_code or "").strip()
    if locale_code == BASE_LOCALE:
        raise InstrumentTranslationError(
            f"{BASE_LOCALE!r} is the instrument's base locale; it is always "
            "served and has no translation rows."
        )

    path = _resolve_workbook(workbook)
    if not path.exists():
        raise InstrumentTranslationError(f"Workbook not found: {path}")

    sources = documented_sources(doc_path)
    documented = sources.get(locale_code)
    if documented is None:
        raise InstrumentTranslationError(
            f"{locale_code!r} has no row in the 'Translation sources' table of "
            f"{SOURCE_POLICY_DOC.relative_to(REPO_ROOT)}. Adding a language is a "
            "policy change: document its source workbook first."
        )
    if not cross_check and path.name != documented.workbook:
        raise InstrumentTranslationError(
            f"{path.name} is not the documented source for {locale_code!r} "
            f"({documented.workbook}). Edit the policy doc to change the source, "
            "or re-run with --cross-check to report differences without writing."
        )

    reference = reference_items(instrument_code)
    label_keys = reference_label_keys(instrument_code)
    workbook_items, names = read_workbook_items(path)
    incoming_raw = workbook_items.get(locale_code, {})

    report = ImportReport(
        instrument_code=instrument_code,
        locale_code=locale_code,
        workbook=path.name,
        sha256=_sha256(path),
        cross_check=cross_check,
    )
    report.reference_labels = len(label_keys)
    report.unknown_in_workbook = sorted(
        f"{kind}:{key}:{fld}" for (kind, key, fld) in incoming_raw if (kind, key, fld) not in reference
    )

    # "Equal to the reference English" belongs here, not in split_packed:
    # split_packed's job is the mechanical unpacking of one cell, with no
    # opinion on what counts as a translation; this loop already holds the
    # reference text and is building the "translated" set, so it is the one
    # place that can decide a cell -- whether never packed at all (a group
    # label left untranslated) or packed but not cleanly splittable (an
    # interleaved hint, which split_packed reports as "") -- is not a
    # translation and must not inflate coverage.
    incoming: dict[tuple[str, str, str], str] = {}
    for key, value in incoming_raw.items():
        if key not in reference:
            continue
        text = split_packed(value, reference.get(key))
        if text and text != reference[key]:
            incoming[key] = text

    report.missing_from_workbook = sorted(
        f"{kind}:{key}:{fld}" for (kind, key, fld) in label_keys if (kind, key, fld) not in incoming
    )

    if cross_check:
        report.translated_labels = len(label_keys & set(incoming))
        report.extension_coverage = _extension_coverage(instrument_code, set(incoming))
        log.info(
            "instrument translations cross-check | %s/%s | workbook=%s | "
            "coverage=%.3f | missing=%d | unknown=%d",
            instrument_code, locale_code, path.name, report.coverage,
            len(report.missing_from_workbook), len(report.unknown_in_workbook),
        )
        return report

    locale_row = _get_or_create_locale(
        instrument_code,
        locale_code,
        names.get(locale_code) or documented.language_name or locale_code,
    )
    existing = {
        (row.item_kind, row.item_key, row.field): row
        for row in db.session.scalars(
            sa.select(MapInstrumentTranslations).where(
                MapInstrumentTranslations.instrument_code == instrument_code,
                MapInstrumentTranslations.locale_code == locale_code,
            )
        )
    }
    now = datetime.now(UTC)
    for key, text in incoming.items():
        row = existing.get(key)
        if row is not None and row.source == SOURCE_EDITED:
            # An administrator's correction outranks the workbook.
            report.kept_edited += 1
            continue
        if row is None:
            kind, item_key, fld = key
            row = MapInstrumentTranslations(
                instrument_code=instrument_code,
                locale_code=locale_code,
                item_kind=kind,
                item_key=item_key,
                field=fld,
            )
            db.session.add(row)
            existing[key] = row
        elif row.text == text:
            continue
        row.text = text
        row.source = SOURCE_IMPORTED
        row.updated_by = actor_id
        row.updated_at = now
        report.written += 1

    translated = {key for key, row in existing.items() if row.text}
    report.translated_labels = len(label_keys & translated)
    report.extension_coverage = _extension_coverage(instrument_code, translated)

    locale_row.source_document = path.name
    locale_row.source_sha256 = report.sha256
    locale_row.imported_at = now
    locale_row.updated_at = now
    locale_row.version = (locale_row.version or 0) + 1
    db.session.flush()

    log.info(
        "instrument translations imported | %s/%s | workbook=%s | version=%d | "
        "coverage=%.3f | written=%d | kept_edited=%d | active=%s",
        instrument_code, locale_code, path.name, locale_row.version,
        report.coverage, report.written, report.kept_edited, locale_row.is_active,
    )
    return report


def _get_or_create_locale(
    instrument_code: str, locale_code: str, language_name: str
) -> MasInstrumentLocales:
    row = db.session.get(MasInstrumentLocales, (instrument_code, locale_code))
    if row is None:
        row = MasInstrumentLocales(
            instrument_code=instrument_code,
            locale_code=locale_code,
            language_name=language_name[:64],
            is_active=False,
            version=0,
            updated_at=datetime.now(UTC),
        )
        db.session.add(row)
        db.session.flush()
    return row


# ---------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------


def get_locale(instrument_code: str, locale_code: str) -> MasInstrumentLocales | None:
    return db.session.get(
        MasInstrumentLocales,
        ((instrument_code or "").strip().upper(), (locale_code or "").strip()),
    )


def export_translations(instrument_code: str, locale_code: str) -> dict:
    """The one delivery contract every frontend reads.

    ``en`` is the instrument's own language: it is always served, carries
    version 0 and no strings, because the bundle already holds them.
    """
    instrument_code = (instrument_code or "").strip().upper()
    locale_code = (locale_code or "").strip()
    if locale_code == BASE_LOCALE:
        return {
            "instrument_code": instrument_code,
            "locale": BASE_LOCALE,
            "version": 0,
            "questions": {},
            "choices": {},
        }
    row = get_locale(instrument_code, locale_code)
    if row is None:
        raise InstrumentTranslationError(
            f"No {locale_code!r} translation exists for {instrument_code}."
        )
    questions: dict[str, dict[str, str]] = {}
    choices: dict[str, dict[str, str]] = {}
    for item in db.session.scalars(
        sa.select(MapInstrumentTranslations).where(
            MapInstrumentTranslations.instrument_code == instrument_code,
            MapInstrumentTranslations.locale_code == locale_code,
        )
    ):
        bucket = questions if item.item_kind == ITEM_KIND_QUESTION else choices
        bucket.setdefault(item.item_key, {})[item.field] = item.text
    return {
        "instrument_code": instrument_code,
        "locale": locale_code,
        "version": row.version,
        "questions": questions,
        "choices": choices,
    }


def _translated_label_keys_by_locale(
    instrument_code: str,
) -> dict[str, set[tuple[str, str, str]]]:
    """``{locale: {question-label keys with text}}`` in one grouped query.

    Keys, not counts: a count alone cannot tell a WHO base label from a layer
    label apart, and both base and per-extension coverage need to intersect
    against their own subset of keys.
    """
    rows = db.session.execute(
        sa.select(
            MapInstrumentTranslations.locale_code,
            MapInstrumentTranslations.item_key,
        ).where(
            MapInstrumentTranslations.instrument_code == instrument_code,
            MapInstrumentTranslations.item_kind == ITEM_KIND_QUESTION,
            MapInstrumentTranslations.field == FIELD_LABEL,
        )
    ).all()
    out: dict[str, set[tuple[str, str, str]]] = {}
    for row in rows:
        out.setdefault(row.locale_code, set()).add(
            (ITEM_KIND_QUESTION, row.item_key, FIELD_LABEL)
        )
    return out


def locale_status(instrument_code: str = BASE_INSTRUMENT_CODE) -> list[dict]:
    """Every locale of one instrument with coverage, version and source.

    ``en`` leads the list: it is the base locale, always active, and needs no
    rows. Coverage (base and per-extension) is informational -- it decides
    nothing about whether a locale is served; see :func:`set_locale_active`.
    One query regardless of how many locales exist.
    """
    instrument_code = (instrument_code or "").strip().upper()
    label_keys = reference_label_keys(instrument_code)
    reference_labels = len(label_keys)
    ext_keys = extension_label_keys(instrument_code)
    translated_by_locale = _translated_label_keys_by_locale(instrument_code)
    rows = db.session.scalars(
        sa.select(MasInstrumentLocales)
        .where(MasInstrumentLocales.instrument_code == instrument_code)
        .order_by(MasInstrumentLocales.locale_code)
    ).all()
    out = [
        {
            "locale_code": BASE_LOCALE,
            "language_name": "English",
            "is_active": True,
            "version": 0,
            "coverage": 1.0,
            "translated_labels": reference_labels,
            "reference_labels": reference_labels,
            "extension_coverage": {
                name: {"translated": len(keys), "total": len(keys), "coverage": 1.0}
                for name, keys in ext_keys.items()
            },
            "source_document": REFERENCE_WORKBOOK.name,
            "source_sha256": None,
            "imported_at": None,
            "is_base": True,
        }
    ]
    for row in rows:
        if row.locale_code == BASE_LOCALE:
            continue
        translated = translated_by_locale.get(row.locale_code, set())
        count = len(label_keys & translated)
        extension_coverage = {
            name: {"translated": len(keys & translated), "total": len(keys)}
            for name, keys in ext_keys.items()
        }
        out.append(
            {
                "locale_code": row.locale_code,
                "language_name": row.language_name,
                "is_active": row.is_active,
                "version": row.version,
                "coverage": round(count / reference_labels, 4) if reference_labels else 0.0,
                "translated_labels": count,
                "reference_labels": reference_labels,
                "extension_coverage": {
                    name: {
                        "translated": counts["translated"],
                        "total": counts["total"],
                        "coverage": round(counts["translated"] / counts["total"], 4)
                        if counts["total"]
                        else 0.0,
                    }
                    for name, counts in sorted(extension_coverage.items())
                },
                "source_document": row.source_document,
                "source_sha256": row.source_sha256,
                "imported_at": row.imported_at.isoformat() if row.imported_at else None,
                "is_base": False,
            }
        )
    return out


def list_strings(
    instrument_code: str,
    locale_code: str,
    *,
    search: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict:
    """One page of a locale's strings with the English reference alongside.

    Paginated over the *reference* items, so an untranslated item is visible
    and editable rather than invisible until something writes it. The page size
    is clamped here, not by the caller.
    """
    instrument_code = (instrument_code or "").strip().upper()
    locale_code = (locale_code or "").strip()
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 50), MAX_STRING_PAGE_SIZE))

    reference = reference_items(instrument_code)
    translations = {
        (row.item_kind, row.item_key, row.field): row
        for row in db.session.scalars(
            sa.select(MapInstrumentTranslations).where(
                MapInstrumentTranslations.instrument_code == instrument_code,
                MapInstrumentTranslations.locale_code == locale_code,
            )
        )
    }

    needle = (search or "").strip().lower()
    keys = sorted(reference)
    if needle:
        keys = [
            key
            for key in keys
            if needle in key[1].lower()
            or needle in reference[key].lower()
            or (key in translations and needle in translations[key].text.lower())
        ]

    total = len(keys)
    start = (page - 1) * page_size
    items = []
    for kind, item_key, fld in keys[start : start + page_size]:
        row = translations.get((kind, item_key, fld))
        items.append(
            {
                "item_kind": kind,
                "item_key": item_key,
                "field": fld,
                "english": reference[(kind, item_key, fld)],
                "text": row.text if row else None,
                "source": row.source if row else None,
                "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
            }
        )
    return {
        "instrument_code": instrument_code,
        "locale": locale_code,
        "page": page,
        "page_size": page_size,
        "total": total,
        "items": items,
    }


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def _trim(text: str | None) -> str:
    if text is None:
        return ""
    return text if len(text) <= _LOG_TEXT_LIMIT else text[:_LOG_TEXT_LIMIT] + "…"


def update_string(
    instrument_code: str,
    locale_code: str,
    *,
    item_kind: str,
    item_key: str,
    field: str,
    text: str,
    actor_id=None,
) -> dict:
    """Set one string, mark it ``edited`` and bump the locale's version.

    Refuses an item the curated reference does not have: an edit may correct
    what a question says, never invent a question.
    """
    instrument_code = (instrument_code or "").strip().upper()
    locale_code = (locale_code or "").strip()
    if locale_code == BASE_LOCALE:
        raise InstrumentTranslationError(
            f"{BASE_LOCALE!r} is the instrument's own language and is not edited here."
        )
    text = (text or "").strip()
    if not text:
        raise InstrumentTranslationError("A translation cannot be empty.")
    if len(text) > MAX_TRANSLATION_TEXT_CHARS:
        raise InstrumentTranslationError(
            f"A translation may not exceed {MAX_TRANSLATION_TEXT_CHARS} characters."
        )
    key = (item_kind, item_key, field)
    if key not in reference_items(instrument_code):
        raise InstrumentTranslationError(
            f"{item_kind} {item_key!r} has no {field} in the reference form."
        )
    locale_row = get_locale(instrument_code, locale_code)
    if locale_row is None:
        raise InstrumentTranslationError(
            f"No {locale_code!r} translation exists for {instrument_code}."
        )

    row = db.session.get(
        MapInstrumentTranslations,
        (instrument_code, locale_code, item_kind, item_key, field),
    )
    old = row.text if row else None
    if row is None:
        row = MapInstrumentTranslations(
            instrument_code=instrument_code,
            locale_code=locale_code,
            item_kind=item_kind,
            item_key=item_key,
            field=field,
        )
        db.session.add(row)
    row.text = text
    row.source = SOURCE_EDITED
    row.updated_by = actor_id
    row.updated_at = datetime.now(UTC)
    locale_row.version = (locale_row.version or 0) + 1
    locale_row.updated_at = row.updated_at
    db.session.flush()

    # The audit record of the edit: who changed which item, from what to what.
    log.info(
        "instrument translation edited | %s/%s | item=%s:%s:%s | by=%s | "
        "old=%r | new=%r | version=%d",
        instrument_code, locale_code, item_kind, item_key, field, actor_id,
        _trim(old), _trim(text), locale_row.version,
    )
    return {
        "item_kind": item_kind,
        "item_key": item_key,
        "field": field,
        "old_text": old,
        "text": text,
        "source": row.source,
        "version": locale_row.version,
    }


def set_locale_active(
    instrument_code: str, locale_code: str, active: bool, *, actor_id=None,
) -> dict:
    """Activate or deactivate a locale.

    An explicit administrative action, independent of coverage (decided
    2026-09-19): English fallback is per-string, so a coverage percentage is
    never a serving decision. Coverage is reported here for context, not
    consulted.
    """
    instrument_code = (instrument_code or "").strip().upper()
    locale_code = (locale_code or "").strip()
    if locale_code == BASE_LOCALE:
        raise InstrumentTranslationError(
            f"{BASE_LOCALE!r} is the base locale and is always active."
        )
    row = get_locale(instrument_code, locale_code)
    if row is None:
        raise InstrumentTranslationError(
            f"No {locale_code!r} translation exists for {instrument_code}."
        )
    label_keys = reference_label_keys(instrument_code)
    reference_labels = len(label_keys)
    locale_translated = _translated_label_keys_by_locale(instrument_code).get(
        locale_code, set()
    )
    translated = len(label_keys & locale_translated)
    coverage = translated / reference_labels if reference_labels else 0.0
    row.is_active = bool(active)
    row.updated_at = datetime.now(UTC)
    db.session.flush()
    log.info(
        "instrument locale %s | %s/%s | coverage=%.3f | by=%s",
        "activated" if active else "deactivated",
        instrument_code, locale_code, coverage, actor_id,
    )
    return {
        "locale_code": locale_code,
        "is_active": row.is_active,
        "coverage": round(coverage, 4),
        "version": row.version,
    }


def active_locale_versions(instrument_code: str) -> dict[str, int]:
    """``{locale: version}`` for every locale a form may be served in.

    ``en`` is included at version 0: it is always available and never has rows,
    and a client that revalidates must see it listed rather than infer it.
    """
    instrument_code = (instrument_code or "").strip().upper()
    versions = {BASE_LOCALE: 0}
    for row in db.session.execute(
        sa.select(MasInstrumentLocales.locale_code, MasInstrumentLocales.version)
        .where(
            MasInstrumentLocales.instrument_code == instrument_code,
            MasInstrumentLocales.is_active.is_(True),
        )
        .order_by(MasInstrumentLocales.locale_code)
    ).all():
        versions[row.locale_code] = row.version
    return versions


# ---------------------------------------------------------------------------
# XLIFF 2.0 — the interchange format
# ---------------------------------------------------------------------------
#
# Policy: docs/policy/va-form-project-configuration.md ("Interchange format").
# XLIFF 2.0 is what a translator's CAT tool reads and writes, so a language can
# be corrected outside this application and brought back without anyone
# exchanging spreadsheets. The workbook importer stays the seeding path; XLIFF
# neither creates a locale nor changes the coverage gate.

#: The OASIS XLIFF 2.0 document namespace, and the only one accepted.
XLIFF_NAMESPACE = "urn:oasis:names:tc:xliff:document:2.0"

#: The only ``version`` this module writes or accepts.
XLIFF_VERSION = "2.0"

#: ``<segment state>`` per stored row. ``edited`` rows are an administrator's
#: correction, which is what XLIFF calls ``reviewed``; an absent row is
#: ``initial`` with an empty target, which is how a translator's tool shows
#: "not started" -- and is exactly the item the form falls back to English for.
_STATE_BY_SOURCE = {SOURCE_IMPORTED: "translated", SOURCE_EDITED: "reviewed"}
_STATE_UNTRANSLATED = "initial"

#: Longest field first, so ``.guidance_hint`` is never read as ``.hint``.
_FIELD_SUFFIXES = tuple(
    sorted(_TRANSLATABLE_FIELDS, key=len, reverse=True)
)

#: Accepted upload extensions, and the media type an export is served as.
XLIFF_EXTENSIONS = (".xlf", ".xliff")
XLIFF_MEDIA_TYPE = "application/xliff+xml"


def resource_id(item_kind: str, item_key: str, field: str) -> str:
    """The canonical XLIFF ``<unit id>`` for one stored string.

    ``question.<name>.<field>`` for a survey row (a question or a group), and
    ``choice.<list_name>.<choice_name>.label`` for a choice -- the item key of a
    choice is stored as ``<list_name>/<choice_name>`` and is mapped to and from
    the dotted form here.

    **Names must not contain a dot.** The id is parsed back by splitting on
    dots, so a dot inside a question name, list name or choice name would make
    two different items share an id. No name in the curated reference form
    contains one (checked over all 1,292 reference strings on 2026-09-19), and
    XLSForm names are conventionally ``[A-Za-z0-9_-]``. A name that does
    contain one raises here rather than emitting an id that cannot be parsed
    back.
    """
    if field not in _TRANSLATABLE_FIELDS:
        raise InstrumentTranslationError(f"{field!r} is not a translatable field.")
    if item_kind == ITEM_KIND_QUESTION:
        parts = [item_key]
    elif item_kind == ITEM_KIND_CHOICE:
        list_name, sep, choice_name = (item_key or "").partition("/")
        if not sep or not list_name or not choice_name:
            raise InstrumentTranslationError(
                f"Choice key {item_key!r} is not '<list_name>/<choice_name>'."
            )
        parts = [list_name, choice_name]
    else:
        raise InstrumentTranslationError(f"{item_kind!r} is not a translatable item kind.")
    for part in parts:
        if "." in part:
            raise InstrumentTranslationError(
                f"{item_kind} name {part!r} contains a dot, which a resource id "
                "cannot represent unambiguously."
            )
    return ".".join([item_kind, *parts, field])


def parse_resource_id(rid: str) -> tuple[str, str, str]:
    """``(item_kind, item_key, field)`` from a canonical resource id.

    The inverse of :func:`resource_id`, and the only way a ``<unit id>`` from
    an uploaded document becomes an item key. It is a syntax check, not an
    existence check: the caller still has to find the key in the reference.
    """
    text = (rid or "").strip()
    item_kind, sep, rest = text.partition(".")
    if not sep or item_kind not in (ITEM_KIND_QUESTION, ITEM_KIND_CHOICE):
        raise InstrumentTranslationError(f"{rid!r} is not a resource id.")
    for candidate in _FIELD_SUFFIXES:
        if rest.endswith(f".{candidate}"):
            field = candidate
            body = rest[: -len(candidate) - 1]
            break
    else:
        raise InstrumentTranslationError(f"{rid!r} names no translatable field.")
    if not body:
        raise InstrumentTranslationError(f"{rid!r} names no item.")
    if item_kind == ITEM_KIND_QUESTION:
        return item_kind, body, field
    list_name, sep, choice_name = body.rpartition(".")
    if not sep or not list_name or not choice_name:
        raise InstrumentTranslationError(
            f"{rid!r} is not 'choice.<list_name>.<choice_name>.<field>'."
        )
    return item_kind, f"{list_name}/{choice_name}", field


@lru_cache(maxsize=4)
def _reference_notes_cached(path: str) -> dict[tuple[str, str], str]:
    """``{(item_kind, item_key): translator note}`` from the reference form.

    A question's note is the English label of the group that encloses it, a
    choice's note is its list name. Both exist only to tell a translator what
    they are looking at; nothing reads them back.
    """
    settings = pd.read_excel(path, sheet_name="settings")
    survey = pd.read_excel(path, sheet_name="survey")
    choices = pd.read_excel(path, sheet_name="choices")

    raw_default = _text(settings.iloc[0].get("default_language")) if not settings.empty else None
    default_locale = _default_language(raw_default)
    label_column = _language_columns(survey, default_locale).get(FIELD_LABEL, {}).get(
        BASE_LOCALE
    )

    notes: dict[tuple[str, str], str] = {}
    stack: list[str] = []
    for _, row in survey.iterrows():
        row_type = (_text(row.get("type")) or "").strip().lower().replace(" ", "_")
        name = _text(row.get("name"))
        label = _text(row.get(label_column)) if label_column else None
        if row_type.startswith(("begin_group", "begin_repeat")):
            if name:
                notes[(ITEM_KIND_QUESTION, name)] = stack[-1] if stack else (label or name)
            stack.append(label or name or "")
            continue
        if row_type.startswith(("end_group", "end_repeat")):
            if stack:
                stack.pop()
            continue
        if row_type and name and stack and stack[-1]:
            notes[(ITEM_KIND_QUESTION, name)] = stack[-1]

    for _, row in choices.iterrows():
        list_name = _text(row.get("list_name"))
        value = _text(row.get("name"))
        if list_name and value:
            notes[(ITEM_KIND_CHOICE, f"{list_name}/{value}")] = list_name
    return notes


@lru_cache(maxsize=4)
def _layer_notes_cached(layer_path: str) -> dict[tuple[str, str], str]:
    """``{(item_kind, item_key): translator note}`` naming the extension(s).

    A layer item has no enclosing workbook section to name, so its note names
    the extension(s) it belongs to instead -- still "what a translator is
    looking at", just from the other source.
    """
    extensions_by_item: dict[tuple[str, str], set[str]] = {}
    for entry in _layer_entries_cached(layer_path):
        item = (entry["itemKind"], entry["itemKey"])
        extensions_by_item.setdefault(item, set()).update(entry["extensions"])
    return {item: ", ".join(sorted(exts)) for item, exts in extensions_by_item.items()}


def reference_notes(
    instrument_code: str = BASE_INSTRUMENT_CODE,
) -> dict[tuple[str, str], str]:
    """Cached translator notes for every reference item, base and layer."""
    if (instrument_code or "").strip().upper() != BASE_INSTRUMENT_CODE:
        raise InstrumentTranslationError(
            f"No reference form is bundled for instrument {instrument_code!r}."
        )
    notes = dict(_reference_notes_cached(str(REFERENCE_WORKBOOK)))
    for item, note in _layer_notes_cached(str(LAYER_REFERENCE_PATH)).items():
        notes.setdefault(item, note)
    return notes


def _xliff_locale(instrument_code: str, locale_code: str) -> tuple[str, str, MasInstrumentLocales]:
    """Normalize the pair and return the locale row, or refuse."""
    instrument_code = (instrument_code or "").strip().upper()
    locale_code = (locale_code or "").strip()
    if locale_code == BASE_LOCALE:
        raise InstrumentTranslationError(
            f"{BASE_LOCALE!r} is the instrument's own language: it is the XLIFF "
            "source, never its target."
        )
    row = get_locale(instrument_code, locale_code)
    if row is None:
        raise InstrumentTranslationError(
            f"No {locale_code!r} translation exists for {instrument_code}. A "
            "language is seeded by importing its documented source workbook; "
            "XLIFF exchanges the strings of a language that already exists."
        )
    return instrument_code, locale_code, row


def export_xliff(instrument_code: str, locale_code: str) -> str:
    """One locale as an XLIFF 2.0 document, one ``<unit>`` per reference item.

    Every item the reference has is emitted, translated or not: an untranslated
    item is an empty ``<target>`` in state ``initial``, which is both what a
    CAT tool needs to show the work left and an honest statement that the form
    shows English there.
    """
    instrument_code, locale_code, _row = _xliff_locale(instrument_code, locale_code)
    reference = reference_items(instrument_code)
    notes = reference_notes(instrument_code)
    stored = {
        (item.item_kind, item.item_key, item.field): item
        for item in db.session.scalars(
            sa.select(MapInstrumentTranslations).where(
                MapInstrumentTranslations.instrument_code == instrument_code,
                MapInstrumentTranslations.locale_code == locale_code,
            )
        )
    }

    # The namespace is declared once as an ordinary attribute on the root and
    # the tags are written unprefixed, which is what ``xmlns`` means. Building
    # the tree with ``{uri}tag`` names instead would force ElementTree to
    # either prefix everything or refuse the document's unqualified attributes
    # (``version``, ``srcLang``); this way the output is the plain, default-
    # namespaced form a CAT tool expects.
    root = ET.Element(
        "xliff",
        {
            "xmlns": XLIFF_NAMESPACE,
            "version": XLIFF_VERSION,
            "srcLang": BASE_LOCALE,
            "trgLang": locale_code,
        },
    )
    file_el = ET.SubElement(root, "file", {"id": instrument_code})

    for key in sorted(reference):
        item_kind, item_key, field = key
        unit = ET.SubElement(file_el, "unit", {"id": resource_id(*key)})
        note_text = notes.get((item_kind, item_key))
        if note_text:
            note = ET.SubElement(
                ET.SubElement(unit, "notes"), "note", {"category": "reference"}
            )
            note.text = note_text
        row = stored.get(key)
        state = _STATE_BY_SOURCE.get(row.source, "translated") if row else _STATE_UNTRANSLATED
        segment = ET.SubElement(unit, "segment", {"state": state})
        ET.SubElement(segment, "source").text = reference[key]
        target = ET.SubElement(segment, "target")
        if row:
            target.text = row.text

    return ET.tostring(root, encoding="unicode", xml_declaration=True)


def xliff_filename(instrument_code: str, locale_code: str) -> str:
    """The download name of an export: ``WHO_2022_VA-hi.xlf``."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", f"{instrument_code}-{locale_code}")
    return f"{safe}.xlf"


def _document_element(xliff_text: str) -> ET.Element:
    """Parse one XLIFF document, refusing anything with a DOCTYPE.

    ``defusedxml`` is not a dependency of this application, so the stdlib
    parser is used with the one attack it does not close off -- an internal
    entity declaration, which needs a DOCTYPE -- refused outright before
    parsing. The stdlib parser never resolves *external* entities, so with no
    DOCTYPE there is nothing left to expand.
    """
    if re.search(r"<!\s*DOCTYPE", xliff_text, re.IGNORECASE):
        raise InstrumentTranslationError(
            "The document declares a DOCTYPE. XLIFF needs none, and entity "
            "declarations are refused."
        )
    try:
        return ET.fromstring(xliff_text, parser=ET.XMLParser())
    except ET.ParseError as exc:
        raise InstrumentTranslationError(f"The document is not valid XML: {exc}") from exc


def _target_text(unit: ET.Element) -> str:
    """One unit's target text, with any inline markup flattened."""
    parts = [
        "".join(target.itertext())
        for target in unit.iterfind(
            f"{{{XLIFF_NAMESPACE}}}segment/{{{XLIFF_NAMESPACE}}}target"
        )
    ]
    return "".join(parts).strip()


def import_xliff(
    instrument_code: str,
    locale_code: str,
    xliff_text: str,
    *,
    actor_id=None,
    mark_as: str = SOURCE_IMPORTED,
) -> dict:
    """Write the targets of an XLIFF 2.0 document back into one locale.

    The same rule the workbook importer enforces holds here: a unit whose id is
    not a reference item is reported and skipped, never created. An empty
    target is "not translated yet" and leaves whatever is stored alone --
    deleting a string is not something an exchange format does. ``mark_as``
    decides the row ``source``: ``imported`` for a bulk hand-back, which leaves
    an administrator's ``edited`` corrections standing, and ``edited`` for a
    reviewed file that is meant to outrank them.

    Coverage and activation are untouched: a locale becomes servable by the
    same gate as before.
    """
    if mark_as not in (SOURCE_IMPORTED, SOURCE_EDITED):
        raise InstrumentTranslationError(
            f"mark_as must be {SOURCE_IMPORTED!r} or {SOURCE_EDITED!r}."
        )
    instrument_code, locale_code, locale_row = _xliff_locale(instrument_code, locale_code)

    root = _document_element(xliff_text)
    if root.tag != f"{{{XLIFF_NAMESPACE}}}xliff":
        raise InstrumentTranslationError(
            f"The document root is not an XLIFF {XLIFF_VERSION} <xliff> element "
            f"in {XLIFF_NAMESPACE}."
        )
    if (root.get("version") or "").strip() != XLIFF_VERSION:
        raise InstrumentTranslationError(
            f"Only XLIFF {XLIFF_VERSION} is accepted; this document is version "
            f"{root.get('version')!r}."
        )
    src_lang = (root.get("srcLang") or "").strip().lower()
    if src_lang != BASE_LOCALE:
        raise InstrumentTranslationError(
            f"The source language must be {BASE_LOCALE!r}; this document says {src_lang!r}."
        )
    trg_lang = (root.get("trgLang") or "").strip()
    if trg_lang.lower() != locale_code.lower():
        raise InstrumentTranslationError(
            f"The document's target language is {trg_lang!r}, not {locale_code!r}."
        )

    reference = reference_items(instrument_code)
    existing = {
        (item.item_kind, item.item_key, item.field): item
        for item in db.session.scalars(
            sa.select(MapInstrumentTranslations).where(
                MapInstrumentTranslations.instrument_code == instrument_code,
                MapInstrumentTranslations.locale_code == locale_code,
            )
        )
    }

    units = 0
    written = 0
    unchanged = 0
    skipped_empty = 0
    kept_edited = 0
    skipped_unknown: list[str] = []
    skipped_too_long: list[str] = []
    now = datetime.now(UTC)

    for unit in root.iter(f"{{{XLIFF_NAMESPACE}}}unit"):
        units += 1
        rid = unit.get("id") or ""
        try:
            key = parse_resource_id(rid)
        except InstrumentTranslationError:
            skipped_unknown.append(rid)
            continue
        if key not in reference:
            skipped_unknown.append(rid)
            continue
        text = _target_text(unit)
        if not text:
            skipped_empty += 1
            continue
        if len(text) > MAX_TRANSLATION_TEXT_CHARS:
            # Skipped rather than truncated, and rather than failing the whole
            # document: the rest of a translator's file is still good.
            skipped_too_long.append(rid)
            continue
        row = existing.get(key)
        if row is not None and row.source == SOURCE_EDITED and mark_as == SOURCE_IMPORTED:
            # An administrator's correction outranks a bulk hand-back, exactly
            # as it outranks a workbook re-import.
            kept_edited += 1
            continue
        if row is not None and row.text == text and row.source == mark_as:
            unchanged += 1
            continue
        if row is None:
            item_kind, item_key, field = key
            row = MapInstrumentTranslations(
                instrument_code=instrument_code,
                locale_code=locale_code,
                item_kind=item_kind,
                item_key=item_key,
                field=field,
            )
            db.session.add(row)
            existing[key] = row
        row.text = text
        row.source = mark_as
        row.updated_by = actor_id
        row.updated_at = now
        written += 1

    if written:
        locale_row.version = (locale_row.version or 0) + 1
        locale_row.updated_at = now
    db.session.flush()

    log.info(
        "instrument translations xliff imported | %s/%s | mark_as=%s | by=%s | "
        "units=%d | written=%d | unchanged=%d | empty=%d | unknown=%d | "
        "too_long=%d | kept_edited=%d | version=%d",
        instrument_code, locale_code, mark_as, actor_id, units, written, unchanged,
        skipped_empty, len(skipped_unknown), len(skipped_too_long), kept_edited,
        locale_row.version,
    )
    return {
        "instrument_code": instrument_code,
        "locale_code": locale_code,
        "mark_as": mark_as,
        "units": units,
        "written": written,
        "unchanged": unchanged,
        "kept_edited": kept_edited,
        "skipped_empty": skipped_empty,
        # Capped: a document keyed to the wrong instrument would otherwise
        # return every one of its ids as a JSON body.
        "skipped_unknown": skipped_unknown[:50],
        "skipped_unknown_count": len(skipped_unknown),
        "skipped_too_long": skipped_too_long[:50],
        "skipped_too_long_count": len(skipped_too_long),
        "version": locale_row.version,
    }
