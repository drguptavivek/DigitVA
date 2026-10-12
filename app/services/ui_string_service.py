"""Corrections to the Expo UI strings, served without a new build (digitva-fsjz).

Policy: docs/policy/ui-strings.md. The reference (``en``) and the bundled
texts of each locale are read from the served Expo export
(``<EXPO_CLIENT_DIST>/ui-strings/<locale>.json``, copied in by
``npm run export:web``). An administrator's correction is a row in
``mas_ui_string_override``; the public API serves those rows, and the export
folds them into the bundled file.

Checks and versioning follow ``instrument_translation_service``: the same
markup and control-character rules, the same length cap, a version that moves
on every edit and an audit line per change.
"""

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models.mas_ui_string_override import MasUiStringOverride
from app.routes.expo_client import _dist_root
from app.services.instrument_translation_service import (
    BASE_LOCALE,
    MAX_STRING_PAGE_SIZE,
    MAX_TRANSLATION_TEXT_CHARS,
    InvalidTranslationText,
    validate_translation_text,
)

log = logging.getLogger(__name__)

STATUS_CORRECTED = "corrected"
STATUS_BUNDLED = "bundled"
STATUS_MISSING = "missing"
#: Filters the admin page offers. ``bundled`` is a status, not a filter.
FILTERS = ("all", STATUS_CORRECTED, STATUS_MISSING)

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
_LOG_TEXT_LIMIT = 120


class UiStringError(RuntimeError):
    """The edit or read cannot be performed as asked."""


class InvalidUiStringText(UiStringError):
    """The text itself is unsafe or would break a placeholder (422 on the API)."""


# ---------------------------------------------------------------------------
# Bundled files
# ---------------------------------------------------------------------------

#: Parsed bundle per file path, re-read only when the file's mtime moves, so a
#: rebuilt export is seen without a restart. Keyed by path, so a test that
#: points EXPO_CLIENT_DIST elsewhere gets its own entry.
_bundle_cache: dict[str, tuple[int, dict]] = {}


def _ui_dir() -> Path:
    return _dist_root() / "ui-strings"


def _read_bundle(path: Path) -> dict:
    mtime = path.stat().st_mtime_ns
    cached = _bundle_cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    data = json.loads(path.read_text(encoding="utf-8"))
    _bundle_cache[str(path)] = (mtime, data)
    return data


def _shipped_codes() -> set[str]:
    folder = _ui_dir()
    if not folder.is_dir():
        return set()
    return {p.stem for p in folder.glob("*.json")}


def locales() -> list[str]:
    """Bundled locales a reader may correct: every shipped file except ``en``."""
    return sorted(_shipped_codes() - {BASE_LOCALE})


def _bundle(locale: str) -> dict:
    """The bundled strings of a shipped locale, ``en`` included."""
    # Membership first: the locale names a file, so it must be one the export
    # really ships, never a raw URL value.
    if locale not in _shipped_codes():
        raise UiStringError(f"No bundled strings for {locale!r}.")
    return _read_bundle(_ui_dir() / f"{locale}.json")


def _editable(locale: str) -> None:
    if locale == BASE_LOCALE:
        raise UiStringError(f"{BASE_LOCALE!r} is the reference and is not edited here.")
    if locale not in locales():
        raise UiStringError(f"Unknown locale {locale!r}.")


def _english(key: str) -> str:
    reference = _bundle(BASE_LOCALE)
    if key not in reference:
        raise UiStringError(f"{key!r} is not a UI string.")
    return reference[key]


# ---------------------------------------------------------------------------
# Corrections in the database
# ---------------------------------------------------------------------------


def _corrections(locale: str) -> dict[str, str]:
    rows = db.session.execute(
        sa.select(MasUiStringOverride.string_key, MasUiStringOverride.text).where(
            MasUiStringOverride.locale_code == locale
        )
    ).all()
    return dict(rows)


def _version(locale: str) -> str:
    """A stable token for the locale's corrections: their count and newest edit.

    One query. Every set moves the newest edit time; every revert lowers the
    count. Both are needed: a revert of an older row leaves the newest time as
    it was.
    """
    count, newest = db.session.execute(
        sa.select(
            sa.func.count(),
            sa.func.max(MasUiStringOverride.updated_at),
        ).where(MasUiStringOverride.locale_code == locale)
    ).one()
    stamp = newest.isoformat() if newest is not None else "none"
    return f"{count}.{stamp}"


def _status(bundled: str | None, corrected: str | None) -> str:
    if corrected is not None:
        return STATUS_CORRECTED
    if not bundled or not bundled.strip():
        return STATUS_MISSING
    return STATUS_BUNDLED


def _placeholders(text: str) -> set[str]:
    return set(_PLACEHOLDER_RE.findall(text))


def _trim(text: str | None) -> str:
    if text is None:
        return ""
    return text if len(text) <= _LOG_TEXT_LIMIT else text[:_LOG_TEXT_LIMIT] + "…"


def set_override(locale: str, key: str, text: str, actor_id) -> dict:
    """Correct one string. Refuses what would break the form or mislead a reader."""
    _editable(locale)
    english = _english(key)
    text = (text or "").strip()
    if not text:
        raise UiStringError("A translation cannot be empty.")
    if len(text) > MAX_TRANSLATION_TEXT_CHARS:
        raise UiStringError(
            f"A translation may not exceed {MAX_TRANSLATION_TEXT_CHARS} characters."
        )
    try:
        validate_translation_text(text, english)
    except InvalidTranslationText as exc:
        raise InvalidUiStringText(str(exc)) from None
    # Equality, not subset: a dropped {count} hides a value, an extra one names
    # nothing the reader's app fills in.
    if _placeholders(text) != _placeholders(english):
        names = sorted(_placeholders(english))
        listed = ", ".join("{" + name + "}" for name in names) or "none"
        raise InvalidUiStringText(
            f"The translation must use exactly the English placeholders: {listed}."
        )

    now = datetime.now(UTC)
    row = db.session.get(MasUiStringOverride, (locale, key))
    old = row.text if row else None
    if row is None:
        row = MasUiStringOverride(locale_code=locale, string_key=key)
        db.session.add(row)
    row.text = text
    row.updated_by = actor_id
    row.updated_at = now
    db.session.flush()

    # The audit record of the edit, as instrument_translation_service.update_string
    # writes it: who changed which string, from what to what.
    log.info(
        "ui string corrected | %s | key=%s | by=%s | old=%r | new=%r",
        locale, key, actor_id, _trim(old), _trim(text),
    )
    return {
        "locale": locale,
        "key": key,
        "text": text,
        "status": STATUS_CORRECTED,
        "version": _version(locale),
    }


def revert(locale: str, key: str, actor_id) -> dict:
    """Drop a correction so the bundled text shows again."""
    _editable(locale)
    _english(key)
    row = db.session.get(MasUiStringOverride, (locale, key))
    old = row.text if row else None
    if row is not None:
        db.session.delete(row)
        db.session.flush()
    log.info(
        "ui string reverted | %s | key=%s | by=%s | old=%r",
        locale, key, actor_id, _trim(old),
    )
    bundled = _bundle(locale).get(key)
    return {
        "locale": locale,
        "key": key,
        "status": _status(bundled, None),
        "version": _version(locale),
    }


def overrides(locale: str) -> dict:
    """``{version, strings}`` for the public API: corrections only, no bundle."""
    _editable(locale)
    return {"version": _version(locale), "strings": _corrections(locale)}


def strings_for_admin(
    locale: str, status: str = "all", page: int = 1, page_size: int = 50
) -> dict:
    """One page of the reference keys with the locale's current text and status."""
    _editable(locale)
    if status not in FILTERS:
        raise UiStringError(f"status must be one of {', '.join(FILTERS)}.")
    page = max(1, page)
    page_size = max(1, min(page_size, MAX_STRING_PAGE_SIZE))

    bundled = _bundle(locale)
    corrections = _corrections(locale)
    rows = []
    for key, english in _bundle(BASE_LOCALE).items():
        bundled_text = bundled.get(key)
        corrected = corrections.get(key)
        rows.append({
            "key": key,
            "english": english,
            "bundled": bundled_text,
            "corrected": corrected,
            "status": _status(bundled_text, corrected),
        })

    counts = {
        "all": len(rows),
        STATUS_CORRECTED: sum(r["status"] == STATUS_CORRECTED for r in rows),
        STATUS_MISSING: sum(r["status"] == STATUS_MISSING for r in rows),
    }
    matching = rows if status == "all" else [r for r in rows if r["status"] == status]
    start = (page - 1) * page_size
    return {
        "locale": locale,
        "version": _version(locale),
        "status": status,
        "counts": counts,
        "page": page,
        "page_size": page_size,
        "total": len(matching),
        "rows": matching[start:start + page_size],
    }


def export(locale: str) -> dict:
    """The locale's bundled JSON with every correction applied."""
    _editable(locale)
    merged = dict(_bundle(locale))
    merged.update(_corrections(locale))
    return merged
