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

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models.mas_ui_locale import MasUiLocale
from app.models.mas_ui_string_override import MasUiStringOverride
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
STATUS_MACHINE = "machine"
#: Row sources. ``machine`` is an unreviewed candidate and is never served.
SOURCE_MACHINE = "machine"
SOURCE_EDITED = "edited"
#: Filters the admin page offers. ``bundled`` is a status, not a filter.
FILTERS = ("all", STATUS_CORRECTED, STATUS_MISSING, STATUS_MACHINE)
#: Indian UI languages that may hold machine candidates before their JSON ships
#: (owner set, digitva-1g1h).
MACHINE_LOCALES = ("hi", "pa", "mr", "kn", "ta", "ml", "te", "gu", "or")

#: Key prefix of the WHO form's own labels (Next, Back, validation messages):
#: the second namespace of a pack, stored in the same table as the app keys.
#: App keys are camelCase identifiers, so the colon cannot collide.
FORM_PREFIX = "form:"
DIRECTIONS = ("ltr", "rtl")

_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")
_LOG_TEXT_LIMIT = 120


class UiStringError(RuntimeError):
    """The edit or read cannot be performed as asked."""


class InvalidUiStringText(UiStringError):
    """The text itself is unsafe or would break a placeholder (422 on the API)."""


class UiLanguageNotPublished(UiStringError):
    """The public API has no such language (404); any other read fault is a 503."""


class NothingToPublish(UiStringError):
    """Publishing a language that has no bundle and no accepted row (422)."""


# ---------------------------------------------------------------------------
# Bundled files
# ---------------------------------------------------------------------------

#: Parsed bundle per file path, re-read only when the file's mtime moves, so a
#: rebuilt export is seen without a restart. Keyed by path, so a test that
#: points EXPO_CLIENT_DIST elsewhere gets its own entry.
_bundle_cache: dict[str, tuple[int, dict]] = {}


def _ui_dir() -> Path:
    # Imported here: app.routes imports the ui_strings API, which imports this
    # module, so a top-level import is circular when a task loads us first.
    from app.routes.expo_client import _dist_root

    return _dist_root() / "ui-strings"


def _read_bundle(path: Path) -> dict:
    mtime = path.stat().st_mtime_ns
    cached = _bundle_cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:  # UnicodeDecodeError and JSONDecodeError both
        # A broken export file is a deploy fault: the admin page names it
        # instead of a 500, and the file is left as it is.
        log.warning("ui_strings bundle unreadable | file=%s", path)
        raise UiStringError(f"The bundled file {path.name} is not valid UTF-8 JSON.") from None
    _bundle_cache[str(path)] = (mtime, data)
    return data


_LOCALE_FILE = re.compile(r"^[a-z]{2,3}$")


def _shipped_codes() -> set[str]:
    folder = _ui_dir()
    if not folder.is_dir():
        return set()
    # Only real locale files: a macOS-built export can carry AppleDouble
    # "._hi.json" metadata files, which are not JSON.
    return {p.stem for p in folder.glob("*.json") if _LOCALE_FILE.match(p.stem)}


def locales() -> list[str]:
    """Bundled locales a reader may correct: every shipped file except ``en``."""
    return sorted(_shipped_codes() - {BASE_LOCALE})


def _configured_codes() -> set[str]:
    """Every UI language an admin has added, published or not."""
    return set(db.session.scalars(sa.select(MasUiLocale.locale_code)))


def reviewable_locales() -> list[str]:
    """Locales the admin page lists: shipped ones, the machine allow-list and
    every language added on the page (digitva-s028)."""
    return sorted(
        (_shipped_codes() | set(MACHINE_LOCALES) | _configured_codes()) - {BASE_LOCALE}
    )


def _optional_file(name: str) -> dict:
    """A side file of the export (theme strings, form labels); ``{}`` when absent."""
    path = _ui_dir() / name
    return _read_bundle(path) if path.is_file() else {}


def _bundle(locale: str, shipped: set[str] | None = None) -> dict:
    """The bundled strings of a locale, ``en`` included, both namespaces.

    The app namespace is ``<locale>.json`` plus ``theme-<locale>.json`` (the
    theme screens' file, merged by the app's i18n.ts as well); the form
    namespace is ``form-<locale>.json`` (the WHO form's labels, written by
    ``scripts/export-form-ui-strings.mjs``), its keys prefixed with
    :data:`FORM_PREFIX`. ``{}`` for an allowed locale with no file yet.
    ``shipped`` lets a caller that reads several bundles glob the folder once.
    """
    # Membership first: the locale names a file, so it must be one the export
    # really ships or one an admin added, never a raw URL value.
    if shipped is None:
        shipped = _shipped_codes()
    if locale not in shipped:
        if locale in MACHINE_LOCALES or (
            _LOCALE_FILE.match(locale) and locale in _configured_codes()
        ):
            merged = {}
        else:
            raise UiStringError(f"No bundled strings for {locale!r}.")
    else:
        merged = dict(_read_bundle(_ui_dir() / f"{locale}.json"))
    merged.update(_optional_file(f"theme-{locale}.json"))
    form = _optional_file(f"form-{locale}.json")
    merged.update({FORM_PREFIX + key: text for key, text in form.items()})
    return merged


def _editable(locale: str) -> None:
    if locale == BASE_LOCALE:
        raise UiStringError(f"{BASE_LOCALE!r} is the reference and is not edited here.")
    if locale not in reviewable_locales():
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
    """The human-edited texts. Machine candidates are never served."""
    rows = db.session.execute(
        sa.select(MasUiStringOverride.string_key, MasUiStringOverride.text).where(
            MasUiStringOverride.locale_code == locale,
            MasUiStringOverride.source == SOURCE_EDITED,
        )
    ).all()
    return dict(rows)


def _candidates(locale: str) -> dict[str, str]:
    rows = db.session.execute(
        sa.select(MasUiStringOverride.string_key, MasUiStringOverride.text).where(
            MasUiStringOverride.locale_code == locale,
            MasUiStringOverride.source == SOURCE_MACHINE,
        )
    ).all()
    return dict(rows)


def _has_accepted_rows(locale: str) -> bool:
    return db.session.scalar(sa.select(sa.exists().where(
        MasUiStringOverride.locale_code == locale,
        MasUiStringOverride.source == SOURCE_EDITED,
    )))


def _versions(codes: list[str]) -> dict[str, str]:
    """A stable token per locale for its corrections: their count and newest edit.

    One grouped query for all ``codes``. Every set moves the newest edit time;
    every revert lowers the count. Both are needed: a revert of an older row
    leaves the newest time as it was.
    """
    rows = db.session.execute(
        sa.select(
            MasUiStringOverride.locale_code,
            sa.func.count(),
            sa.func.max(MasUiStringOverride.updated_at),
        ).where(
            MasUiStringOverride.locale_code.in_(codes),
            MasUiStringOverride.source == SOURCE_EDITED,
        ).group_by(MasUiStringOverride.locale_code)
    ).all()
    found = {code: f"{count}.{newest.isoformat()}" for code, count, newest in rows}
    return {code: found.get(code, "0.none") for code in codes}


def _version(locale: str) -> str:
    return _versions([locale])[locale]


def _status(bundled: str | None, corrected: str | None, machine: str | None = None) -> str:
    if corrected is not None:
        return STATUS_CORRECTED
    if not bundled or not bundled.strip():
        return STATUS_MACHINE if machine is not None else STATUS_MISSING
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
    row.source = SOURCE_EDITED
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


def accept(locale: str, key: str, actor_id) -> dict:
    """Promote a machine candidate to a served correction, text unchanged."""
    _editable(locale)
    _english(key)
    row = db.session.get(MasUiStringOverride, (locale, key))
    if row is None or row.source != SOURCE_MACHINE:
        raise UiStringError("There is no machine candidate to accept for this string.")
    row.source = SOURCE_EDITED
    row.updated_by = actor_id
    row.updated_at = datetime.now(UTC)
    db.session.flush()
    log.info("ui string candidate accepted | %s | key=%s | by=%s", locale, key, actor_id)
    return {
        "locale": locale,
        "key": key,
        "text": row.text,
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
    """``{version, strings}``: the accepted corrections alone, no bundle."""
    _editable(locale)
    return {"version": _version(locale), "strings": _corrections(locale)}


def _published(locale: str) -> MasUiLocale:
    # Shape first, so a path-like value never reaches the database or the disk.
    if locale == BASE_LOCALE or not _LOCALE_FILE.match(locale):
        raise UiLanguageNotPublished(f"{locale!r} is not a published UI language.")
    row = db.session.get(MasUiLocale, locale)
    if row is None or not row.is_published:
        raise UiLanguageNotPublished(f"{locale!r} is not a published UI language.")
    return row


#: The last pack built per locale, with the fingerprint it was built from. One
#: entry per published language, so it stays small.
_pack_cache: dict[str, tuple[tuple, dict]] = {}


def _mtime(path: Path) -> int | None:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return None  # absent: a file that appears later changes the fingerprint


def pack(locale: str) -> dict:
    """The full pack of a published language for the public API (digitva-s028).

    ``strings`` is the app namespace and ``form`` the WHO form's labels: the
    bundled text with the accepted corrections over it, or accepted rows
    alone for a language with no bundle. Machine drafts are never included.
    Only keys of the English reference are served. ``reviewed`` is the share
    of reference keys whose text an administrator wrote or accepted.
    ``version`` is the SHA-256 of the rest of the body, so it moves with a
    correction and with a rebuilt export alike, and has the shape the app's
    ``If-None-Match`` check expects.

    The built pack is kept until its fingerprint moves: the folder, the
    corrections' version, the language row's edit time and the mtimes of the
    six files it reads. A repeat or revalidating read costs two small queries
    and six ``stat`` calls. Raises :class:`UiLanguageNotPublished` for a
    language not on offer and :class:`UiStringError` when the export cannot
    be read.
    """
    row = _published(locale)
    return _pack_for(row, _version(locale))


def _pack_for(row: MasUiLocale, version: str) -> dict:
    locale = row.locale_code
    folder = _ui_dir()
    files = [f"{prefix}{code}.json" for code in (locale, BASE_LOCALE) for prefix in ("", "theme-", "form-")]
    fingerprint = (
        str(folder), version, row.updated_at, tuple(_mtime(folder / name) for name in files),
    )
    cached = _pack_cache.get(locale)
    if cached and cached[0] == fingerprint:
        return cached[1]

    shipped = _shipped_codes()
    reference = _bundle(BASE_LOCALE, shipped)
    corrections = _corrections(locale)
    merged = {**_bundle(locale, shipped), **corrections}
    served = {k: t for k, t in merged.items() if k in reference and (t or "").strip()}
    accepted = sum(1 for k in corrections if k in reference)
    body = {
        "locale": locale,
        "native_name": row.native_name,
        "bcp47_tag": row.bcp47_tag,
        "direction": row.direction,
        "reviewed": round(accepted / len(reference), 3) if reference else 0.0,
        "strings": {k: t for k, t in served.items() if not k.startswith(FORM_PREFIX)},
        "form": {k[len(FORM_PREFIX):]: t for k, t in served.items() if k.startswith(FORM_PREFIX)},
    }
    digest = hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    result = {"version": digest, **body}
    _pack_cache[locale] = (fingerprint, result)
    return result


def published_languages() -> list[dict]:
    """The published UI languages, each with its pack's version and review share.

    Raises :class:`UiStringError` when any pack cannot be built (the export is
    missing or unreadable mid-deploy). The list is never shortened instead: a
    phone drops the stored pack of a language the list no longer names.
    """
    rows = db.session.scalars(
        sa.select(MasUiLocale)
        .where(MasUiLocale.is_published.is_(True))
        .order_by(MasUiLocale.locale_code)
    ).all()
    versions = _versions([row.locale_code for row in rows])
    result = []
    for row in rows:
        body = _pack_for(row, versions[row.locale_code])
        result.append({key: body[key] for key in (
            "locale", "native_name", "bcp47_tag", "direction", "version", "reviewed"
        )})
    return result


_BCP47_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8}){0,3}$")
_NAME_FORBIDDEN_RE = re.compile(r"[<>\x00-\x1f\x7f]")


def ui_languages_for_admin() -> list[dict]:
    rows = db.session.scalars(sa.select(MasUiLocale).order_by(MasUiLocale.locale_code)).all()
    return [
        {
            "locale": r.locale_code,
            "native_name": r.native_name,
            "bcp47_tag": r.bcp47_tag,
            "direction": r.direction,
            "published": r.is_published,
        }
        for r in rows
    ]


def set_ui_language(
    locale: str, native_name: str, bcp47_tag: str, direction: str, published: bool | None, actor_id
) -> dict:
    """Add or change a UI language and whether it is published. Admin only (caller).

    ``published=None`` keeps the language's current state (a new one starts
    unpublished), so editing a name never unpublishes it. Publishing a
    language with no bundled file and no accepted row raises
    :class:`NothingToPublish`: it would serve an empty pack.
    """
    locale = (locale or "").strip()
    if locale == BASE_LOCALE or not _LOCALE_FILE.match(locale):
        raise UiStringError("The language code must be 2 or 3 lower-case letters, not en.")
    native_name = (native_name or "").strip()
    if not native_name or len(native_name) > 64 or _NAME_FORBIDDEN_RE.search(native_name):
        raise UiStringError("The native name must be 1 to 64 characters with no markup.")
    bcp47_tag = (bcp47_tag or "").strip()
    if len(bcp47_tag) > 35 or not _BCP47_RE.match(bcp47_tag) or not bcp47_tag.startswith(locale):
        raise UiStringError("The BCP 47 tag must start with the language code, e.g. hi-IN.")
    if direction not in DIRECTIONS:
        raise UiStringError("The direction must be ltr or rtl.")
    if published is not None and not isinstance(published, bool):
        raise UiStringError("published must be true or false.")
    if published and locale not in _shipped_codes() and not _has_accepted_rows(locale):
        raise NothingToPublish(
            f"{locale!r} has no bundled strings and no accepted translation yet; "
            "accept or write some before publishing it."
        )

    row = db.session.get(MasUiLocale, locale)
    if published is None:
        published = row.is_published if row is not None else False
    old = None if row is None else (row.native_name, row.bcp47_tag, row.direction, row.is_published)
    if row is None:
        row = MasUiLocale(locale_code=locale)
        db.session.add(row)
    row.native_name = native_name
    row.bcp47_tag = bcp47_tag
    row.direction = direction
    row.is_published = published
    row.updated_by = actor_id
    row.updated_at = datetime.now(UTC)
    db.session.flush()
    log.info(
        "ui language set | %s | by=%s | old=%r | new=%r",
        locale, actor_id, old, (native_name, bcp47_tag, direction, published),
    )
    return {
        "locale": locale,
        "native_name": native_name,
        "bcp47_tag": bcp47_tag,
        "direction": direction,
        "published": published,
    }


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
    candidates = _candidates(locale)
    rows = []
    for key, english in _bundle(BASE_LOCALE).items():
        bundled_text = bundled.get(key)
        corrected = corrections.get(key)
        machine = candidates.get(key)
        rows.append({
            "key": key,
            "english": english,
            "bundled": bundled_text,
            "corrected": corrected,
            "machine": machine,
            "status": _status(bundled_text, corrected, machine),
        })

    counts = {
        "all": len(rows),
        STATUS_CORRECTED: sum(r["status"] == STATUS_CORRECTED for r in rows),
        STATUS_MISSING: sum(r["status"] == STATUS_MISSING for r in rows),
        STATUS_MACHINE: sum(r["status"] == STATUS_MACHINE for r in rows),
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
    """The locale's bundled app strings with every correction applied."""
    _editable(locale)
    merged = dict(_bundle(locale))
    merged.update(_corrections(locale))
    # The app file only: the form labels belong to the vendor package, not to
    # src/strings/<locale>.json.
    return {k: t for k, t in merged.items() if not k.startswith(FORM_PREFIX)}
