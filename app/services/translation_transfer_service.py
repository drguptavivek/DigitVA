"""Dump and load every translation row, to carry them across a server cutover.

Policy: docs/policy/ui-strings.md ("Keeping translations across a cutover")
and docs/policy/va-form-project-configuration.md ("Carrying translations
across servers"). Digitva-3b65.

Load is insert-only: a row whose natural key already exists on the target, of
any source, is left exactly as it is. User ids differ between servers, so an
author travels as an email. Texts are never logged.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models.mas_instrument_locales import (
    SOURCE_EDITED,
    SOURCE_IMPORTED,
    SOURCE_MACHINE,
    MapInstrumentTranslations,
    MasInstrumentLocales,
)
from app.models.mas_ui_string_override import MasUiStringOverride
from app.models.va_users import VaUsers
from app.services import ui_string_service as ui
from app.services.instrument_translation_service import (
    MAX_TRANSLATION_TEXT_CHARS,
    InstrumentTranslationError,
    _get_or_create_locale,
    reference_items,
)

FORMAT = "digitva-translations"
VERSION = 1
UI_SOURCES = (SOURCE_EDITED, SOURCE_MACHINE)
Q_SOURCES = (SOURCE_IMPORTED, SOURCE_EDITED, SOURCE_MACHINE)
_LOCALE_RE = re.compile(r"^[A-Za-z0-9_-]{2,16}$")
RESULT_KEYS = ("inserted", "skipped_existing", "skipped_unknown", "errors")


class TransferError(RuntimeError):
    """The file is not a translations dump this version can read."""


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


def _emails(user_ids) -> dict:
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    rows = db.session.execute(
        sa.select(VaUsers.user_id, VaUsers.email).where(VaUsers.user_id.in_(ids))
    )
    return {uid: email for uid, email in rows}


def dump(*, ui_strings: bool = True, questionnaire: bool = True, locales=()) -> dict:
    """Every row of the chosen stores as a JSON-ready dict (optionally per locale)."""
    out: dict = {"format": FORMAT, "version": VERSION, "exported_at": _iso(datetime.now(UTC))}
    locales = tuple(locales)
    if ui_strings:
        q = sa.select(MasUiStringOverride).order_by(
            MasUiStringOverride.locale_code, MasUiStringOverride.string_key
        )
        if locales:
            q = q.where(MasUiStringOverride.locale_code.in_(locales))
        rows = db.session.scalars(q).all()
        mail = _emails(r.updated_by for r in rows)
        out["ui_strings"] = [
            {
                "locale": r.locale_code, "key": r.string_key, "text": r.text,
                "source": r.source, "updated_by_email": mail.get(r.updated_by),
                "updated_at": _iso(r.updated_at),
            }
            for r in rows
        ]
    if questionnaire:
        lq = sa.select(MasInstrumentLocales).order_by(
            MasInstrumentLocales.instrument_code, MasInstrumentLocales.locale_code
        )
        tq = sa.select(MapInstrumentTranslations).order_by(
            *MapInstrumentTranslations.__table__.primary_key.columns
        )
        if locales:
            lq = lq.where(MasInstrumentLocales.locale_code.in_(locales))
            tq = tq.where(MapInstrumentTranslations.locale_code.in_(locales))
        locs = db.session.scalars(lq).all()
        rows = db.session.scalars(tq).all()
        mail = _emails([r.updated_by for r in rows] + [c.approved_by_user_id for c in locs])
        out["questionnaire"] = {
            "locales": [
                {
                    "instrument_code": c.instrument_code, "locale_code": c.locale_code,
                    "language_name": c.language_name, "lifecycle_state": c.lifecycle_state,
                    "is_active": c.is_active, "version": c.version,
                    "approved_by_email": mail.get(c.approved_by_user_id),
                    "approved_at": _iso(c.approved_at),
                    "source_document": c.source_document, "source_sha256": c.source_sha256,
                }
                for c in locs
            ],
            "translations": [
                {
                    "instrument_code": r.instrument_code, "locale_code": r.locale_code,
                    "item_kind": r.item_kind, "item_key": r.item_key, "field": r.field,
                    "text": r.text, "source": r.source,
                    "updated_by_email": mail.get(r.updated_by), "updated_at": _iso(r.updated_at),
                }
                for r in rows
            ],
        }
    return out


# -- load ---------------------------------------------------------------


def _text_ok(row) -> bool:
    text = row.get("text")
    return isinstance(text, str) and bool(text.strip()) and len(text) <= MAX_TRANSLATION_TEXT_CHARS


def _when(row):
    try:
        value = datetime.fromisoformat(row["updated_at"])
    except (KeyError, TypeError, ValueError):
        return datetime.now(UTC)
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _author_lookup(rows) -> dict:
    """email (lower-cased) -> user_id for every author named in the file."""
    wanted = {
        r["updated_by_email"].strip().lower()
        for r in rows
        if isinstance(r.get("updated_by_email"), str)
    }
    if not wanted:
        return {}
    found = db.session.execute(
        sa.select(sa.func.lower(VaUsers.email), VaUsers.user_id).where(
            sa.func.lower(VaUsers.email).in_(wanted)
        )
    )
    return {email: uid for email, uid in found}


def _author(row, users, counts, store):
    email = row.get("updated_by_email")
    if not isinstance(email, str) or not email.strip():
        return None
    uid = users.get(email.strip().lower())
    if uid is None:
        counts["unknown_authors"][store] += 1
    return uid


def _english_ui() -> dict | None:
    try:
        return ui._bundle(ui.BASE_LOCALE)
    except (ui.UiStringError, OSError, ValueError):
        return None  # no Expo export on this server: key and placeholder checks are skipped


def _load_ui(rows, dry_run, counts):
    rows = [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
    users = _author_lookup(rows)
    existing = set(
        tuple(r) for r in db.session.execute(
            sa.select(MasUiStringOverride.locale_code, MasUiStringOverride.string_key)
        )
    )
    english = _english_ui()
    for r in rows:
        locale, key, source = r.get("locale"), r.get("key"), r.get("source")
        tally = counts["ui_strings"][(str(locale), str(source))]
        if not (
            isinstance(locale, str) and _LOCALE_RE.match(locale) and locale != ui.BASE_LOCALE
            and isinstance(key, str) and 0 < len(key) <= 255
            and source in UI_SOURCES and _text_ok(r)
        ):
            tally["errors"] += 1
            continue
        if (locale, key) in existing:
            tally["skipped_existing"] += 1
            continue
        if english is not None and (
            key not in english or ui._placeholders(english[key]) != ui._placeholders(r["text"])
        ):
            tally["skipped_unknown"] += 1
            continue
        existing.add((locale, key))
        tally["inserted"] += 1
        if not dry_run:
            db.session.add(MasUiStringOverride(
                locale_code=locale, string_key=key, text=r["text"], source=source,
                updated_by=_author(r, users, counts, "ui_strings"), updated_at=_when(r),
            ))


def _load_questionnaire(block, dry_run, counts):
    block = block if isinstance(block, dict) else {}
    rows = [r for r in block.get("translations") or [] if isinstance(r, dict)]
    names = {
        (c.get("instrument_code"), c.get("locale_code")): c.get("language_name")
        for c in block.get("locales") or [] if isinstance(c, dict)
    }
    users = _author_lookup(rows)
    locale_rows = {
        (c.instrument_code, c.locale_code): c
        for c in db.session.scalars(sa.select(MasInstrumentLocales))
    }
    existing = set(
        tuple(r) for r in db.session.execute(
            sa.select(*MapInstrumentTranslations.__table__.primary_key.columns)
        )
    )
    reference: dict = {}
    bump: set = set()
    new_locales: set = set()
    for r in rows:
        inst, locale, source = r.get("instrument_code"), r.get("locale_code"), r.get("source")
        item = (r.get("item_kind"), r.get("item_key"), r.get("field"))
        tally = counts["questionnaire"][(f"{inst}/{locale}", str(source))]
        if not (
            isinstance(inst, str) and isinstance(locale, str) and _LOCALE_RE.match(locale)
            and all(isinstance(x, str) and 0 < len(x) <= 255 for x in item)
            and source in Q_SOURCES and _text_ok(r)
        ):
            tally["errors"] += 1
            continue
        pk = (inst, locale, *item)
        if pk in existing:
            tally["skipped_existing"] += 1
            continue
        if inst not in reference:
            try:
                reference[inst] = reference_items(inst)
            except InstrumentTranslationError:
                reference[inst] = None
        if reference[inst] is None or item not in reference[inst]:
            tally["skipped_unknown"] += 1
            continue
        if (inst, locale) not in locale_rows and (inst, locale) not in new_locales:
            if not names.get((inst, locale)):
                tally["errors"] += 1  # no locale metadata in the file: cannot create it safely
                continue
            new_locales.add((inst, locale))
            counts["locales_created"].append(f"{inst}/{locale}")
            if not dry_run:
                locale_rows[(inst, locale)] = _get_or_create_locale(inst, locale, names[(inst, locale)])
        existing.add(pk)
        tally["inserted"] += 1
        if source != SOURCE_MACHINE:
            bump.add((inst, locale))
        if not dry_run:
            db.session.add(MapInstrumentTranslations(
                instrument_code=inst, locale_code=locale, item_kind=item[0], item_key=item[1],
                field=item[2], text=r["text"], source=source,
                updated_by=_author(r, users, counts, "questionnaire"), updated_at=_when(r),
            ))
    if not dry_run:
        now = datetime.now(UTC)
        for key in bump:  # served rows arrived: refresh phones and web, as accept/edit does
            locale_rows[key].version = (locale_rows[key].version or 0) + 1
            locale_rows[key].updated_at = now
    counts["versions_bumped"] = sorted(f"{i}/{c}" for i, c in bump)


def load(data, *, dry_run: bool = False) -> dict:
    """Insert the dump's missing rows; returns the counts. Flushes, never commits."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise TransferError("Not a digitva-translations file.")
    if data.get("version") != VERSION:
        raise TransferError(f"Unsupported file version {data.get('version')!r}; expected {VERSION}.")
    counts: dict = {
        "ui_strings": defaultdict(Counter),
        "questionnaire": defaultdict(Counter),
        "unknown_authors": Counter(),
        "locales_created": [],
        "versions_bumped": [],
    }
    if "ui_strings" in data:
        _load_ui(data["ui_strings"], dry_run, counts)
    if "questionnaire" in data:
        _load_questionnaire(data["questionnaire"], dry_run, counts)
    if not dry_run:
        db.session.flush()
    return counts
