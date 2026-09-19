"""Import, serve and edit the display translations of a standard instrument.

Policy: docs/policy/va-form-project-configuration.md ("Translation sources")
and docs/policy/va-web-form-options.md ("Adding a language").

A translation is data. The instrument's structure is pre-built from the curated
reference form and never changes here: every string an import writes is keyed
to an item the reference already has, so a deployed project workbook can supply
Hindi for a question but can never add one. What the reference lacks is
reported, not stored.

Two rules this module exists to enforce:

* **One documented source workbook per language.** Which workbook is a
  language's source is policy, recorded in the "Translation sources" table of
  ``docs/policy/va-form-project-configuration.md``. This module parses that
  table rather than keeping a second copy, so changing a source means editing
  the doc. Any other workbook is refused unless the caller asks for a
  cross-check, which reports differences and writes nothing.
* **A locale is served only once it is covered.** An import activates a locale
  when its coverage of the reference's survey labels reaches
  ``TRANSLATION_COVERAGE_THRESHOLD``; below that it refuses to activate unless
  forced, and the forcing is logged.
"""

from __future__ import annotations

import hashlib
import logging
import re
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

#: The base locale of every bundled instrument: always served, never imported.
BASE_LOCALE = "en"

#: The standard instrument DigitVA bundles today.
BASE_INSTRUMENT_CODE = "WHO_2022_VA"

#: Fraction of the reference's survey labels a locale must translate before it
#: may be activated. The owner may change this; every caller reads it here.
TRANSLATION_COVERAGE_THRESHOLD = 0.95

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
    """What one import (or cross-check) found and did."""

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
    activated: bool = False
    forced: bool = False

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
            "activated": self.activated,
            "forced": self.forced,
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
def _reference_items_cached(path: str) -> dict[tuple[str, str, str], str]:
    items, _ = read_workbook_items(path)
    english = items.get(BASE_LOCALE)
    if not english:
        raise InstrumentTranslationError(
            f"{Path(path).name} carries no English strings; it cannot be the "
            "structural reference."
        )
    return english


def reference_items(
    instrument_code: str = BASE_INSTRUMENT_CODE,
) -> dict[tuple[str, str, str], str]:
    """The curated reference form's English strings, keyed by item.

    Cached: the workbook is committed reference material and does not change
    between requests, and reading it costs three pandas passes.
    """
    if (instrument_code or "").strip().upper() != BASE_INSTRUMENT_CODE:
        raise InstrumentTranslationError(
            f"No reference form is bundled for instrument {instrument_code!r}."
        )
    return _reference_items_cached(str(REFERENCE_WORKBOOK))


def reference_label_keys(
    instrument_code: str = BASE_INSTRUMENT_CODE,
) -> set[tuple[str, str, str]]:
    """The survey-label items coverage is measured over."""
    return {
        key
        for key in reference_items(instrument_code)
        if key[0] == ITEM_KIND_QUESTION and key[2] == FIELD_LABEL
    }


def split_packed(value: str, english: str | None) -> str:
    """Unpack a cell that carries English and the target language together.

    The deployed workbooks sometimes put both in one cell separated by a
    newline ("VA interviewer\\nवीए साक्षात्कारकर्ता"). Only a half that is
    *exactly* the reference English is dropped: anything looser would silently
    truncate a translation that happens to start with an English word.
    """
    if not english or "\n" not in value:
        return value
    parts = [part.strip() for part in value.split("\n")]
    parts = [part for part in parts if part]
    if len(parts) < 2:
        return value
    if parts[0] == english:
        return "\n".join(parts[1:])
    if parts[-1] == english:
        return "\n".join(parts[:-1])
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
    force: bool = False,
    actor_id=None,
    doc_path: Path | None = None,
) -> ImportReport:
    """Import one language from one workbook, or cross-check it.

    ``cross_check`` reads and reports without writing a single row, and is the
    only way to look at a workbook that is not the documented source for this
    locale. ``force`` activates a locale whose coverage is below the threshold.
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

    locale_row.source_document = path.name
    locale_row.source_sha256 = report.sha256
    locale_row.imported_at = now
    locale_row.updated_at = now
    locale_row.version = (locale_row.version or 0) + 1

    if report.coverage >= TRANSLATION_COVERAGE_THRESHOLD:
        locale_row.is_active = True
        report.activated = True
    elif force:
        locale_row.is_active = True
        report.activated = True
        report.forced = True
        log.warning(
            "instrument locale activated below threshold | %s/%s | coverage=%.3f "
            "| threshold=%.2f | forced by=%s",
            instrument_code, locale_code, report.coverage,
            TRANSLATION_COVERAGE_THRESHOLD, actor_id,
        )
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


def _coverage_by_locale(instrument_code: str) -> dict[str, int]:
    """``{locale: translated survey-label count}`` in one grouped query."""
    rows = db.session.execute(
        sa.select(
            MapInstrumentTranslations.locale_code,
            sa.func.count().label("n"),
        )
        .where(
            MapInstrumentTranslations.instrument_code == instrument_code,
            MapInstrumentTranslations.item_kind == ITEM_KIND_QUESTION,
            MapInstrumentTranslations.field == FIELD_LABEL,
        )
        .group_by(MapInstrumentTranslations.locale_code)
    ).all()
    return {row.locale_code: row.n for row in rows}


def locale_status(instrument_code: str = BASE_INSTRUMENT_CODE) -> list[dict]:
    """Every locale of one instrument with coverage, version and source.

    ``en`` leads the list: it is the base locale, always active, and needs no
    rows. Two queries regardless of how many locales exist.
    """
    instrument_code = (instrument_code or "").strip().upper()
    reference_labels = len(reference_label_keys(instrument_code))
    translated = _coverage_by_locale(instrument_code)
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
            "source_document": REFERENCE_WORKBOOK.name,
            "source_sha256": None,
            "imported_at": None,
            "is_base": True,
        }
    ]
    for row in rows:
        if row.locale_code == BASE_LOCALE:
            continue
        count = translated.get(row.locale_code, 0)
        out.append(
            {
                "locale_code": row.locale_code,
                "language_name": row.language_name,
                "is_active": row.is_active,
                "version": row.version,
                "coverage": round(count / reference_labels, 4) if reference_labels else 0.0,
                "translated_labels": count,
                "reference_labels": reference_labels,
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
    instrument_code: str, locale_code: str, active: bool, *, force: bool = False,
    actor_id=None,
) -> dict:
    """Activate or deactivate a locale; activation respects the coverage gate."""
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
    reference_labels = len(reference_label_keys(instrument_code))
    translated = _coverage_by_locale(instrument_code).get(locale_code, 0)
    coverage = translated / reference_labels if reference_labels else 0.0
    if active and coverage < TRANSLATION_COVERAGE_THRESHOLD and not force:
        raise InstrumentTranslationError(
            f"{locale_code!r} covers {coverage:.1%} of the reference's survey "
            f"labels, below the {TRANSLATION_COVERAGE_THRESHOLD:.0%} threshold. "
            "Import a more complete workbook, or force the activation."
        )
    row.is_active = bool(active)
    row.updated_at = datetime.now(UTC)
    db.session.flush()
    log.info(
        "instrument locale %s | %s/%s | coverage=%.3f | forced=%s | by=%s",
        "activated" if active else "deactivated",
        instrument_code, locale_code, coverage,
        bool(active and coverage < TRANSLATION_COVERAGE_THRESHOLD), actor_id,
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
