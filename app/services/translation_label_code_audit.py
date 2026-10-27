"""Find and repair translated question labels that show another code.

digitva-fb5, docs/current-state/translation-label-code-mismatches.md. A
translated label starts with its own question code, ``(Id10192) Was ...``;
imported rows sometimes show a different one. Only two kinds are safe to fix
by machine, because the label's text is the question's own and just the
bracketed code is wrong:

* ``case_only`` -- ``Id10161_unit`` shown as ``Id10161_Unit``.
* ``mistyped`` -- the shown code names no question of the reference form
  (``Id100010``, ``Id0282``).

Everything else (``needs_review``) shows a code that IS another question, so
the wording may belong to that question; a speaker decides, never this module.

Repair goes through ``update_string``: it logs old and new text (the existing
audit record), marks the row ``edited`` and bumps the locale version so caches
refetch. ``snapshot`` + ``restore`` give the reversible half: the prior text,
source and author of every row touched are written to a file before any write.
"""

import json
import logging
import re
import uuid
from datetime import UTC, datetime

import sqlalchemy as sa

from app import db
from app.models.mas_instrument_locales import (
    FIELD_LABEL,
    ITEM_KIND_QUESTION,
    MapInstrumentTranslations,
    SOURCE_MACHINE,
)
from app.services.instrument_translation_service import (
    BASE_INSTRUMENT_CODE,
    InstrumentTranslationError,
    get_locale,
    reference_items,
    update_string,
)

log = logging.getLogger(__name__)

CASE_ONLY = "case_only"
MISTYPED = "mistyped"
NEEDS_REVIEW = "needs_review"
AUTO_FIXABLE = (CASE_ONLY, MISTYPED)

_OWN_CODE_RE = re.compile(r"^[Ii][Dd]\d")

# Only "(Id...)" prefixes: "(commentaire)" and the like are content.
_PREFIX_RE = re.compile(r"^\((?P<code>[Ii][Dd]\w*)\)")


def find_label_code_mismatches(
    instrument_code: str = BASE_INSTRUMENT_CODE, locale_code: str | None = None
) -> list[dict]:
    """Translated question labels whose ``(IdNNNNN)`` prefix is not their own.

    One dict per row: ``locale``, ``item_key``, ``shown_code``, ``text``,
    ``kind`` (``case_only`` / ``mistyped`` / ``needs_review``). Machine drafts
    are skipped: they are never served. A row whose ``item_key`` is an ODK-only name
    (not ``Id<digit>...``) is ``needs_review``: it has no WHO code to correct to.
    """
    reference = reference_items(instrument_code)
    question_keys = {k for kind, k, f in reference if kind == ITEM_KIND_QUESTION and f == FIELD_LABEL}
    stmt = sa.select(MapInstrumentTranslations).where(
        MapInstrumentTranslations.instrument_code == instrument_code,
        MapInstrumentTranslations.item_kind == ITEM_KIND_QUESTION,
        MapInstrumentTranslations.field == FIELD_LABEL,
        MapInstrumentTranslations.source != SOURCE_MACHINE,
    ).order_by(MapInstrumentTranslations.locale_code, MapInstrumentTranslations.item_key)
    if locale_code:
        stmt = stmt.where(MapInstrumentTranslations.locale_code == locale_code)
    found = []
    for row in db.session.scalars(stmt):
        match = _PREFIX_RE.match(row.text)
        if not match or match["code"] == row.item_key:
            continue
        shown = match["code"]
        # An ODK-only name (``mother_deliv``) has no WHO code to correct to.
        if not _OWN_CODE_RE.match(row.item_key):
            kind = NEEDS_REVIEW
        elif shown.lower() == row.item_key.lower():
            kind = CASE_ONLY
        elif shown not in question_keys:
            kind = MISTYPED
        else:
            kind = NEEDS_REVIEW
        found.append(
            {"locale": row.locale_code, "item_key": row.item_key,
             "shown_code": shown, "text": row.text, "kind": kind}
        )
    return found


def _corrected(item: dict) -> str:
    return _PREFIX_RE.sub(f"({item['item_key']})", item["text"], count=1)


def snapshot(instrument_code: str, items: list[dict], path: str) -> int:
    """Write the prior state of every row in *items* to *path* and read it
    back to verify. Refuses to overwrite a file. Returns the row count."""
    rows = []
    for item in items:
        row = db.session.get(
            MapInstrumentTranslations,
            (instrument_code, item["locale"], ITEM_KIND_QUESTION, item["item_key"], FIELD_LABEL),
        )
        rows.append({
            "locale": item["locale"], "item_key": item["item_key"], "text": row.text,
            "source": row.source,
            "updated_by": str(row.updated_by) if row.updated_by else None,
            "updated_at": row.updated_at.isoformat(),
        })
    with open(path, "x", encoding="utf-8") as fh:
        json.dump({"instrument_code": instrument_code, "rows": rows}, fh, ensure_ascii=False)
    with open(path, encoding="utf-8") as fh:
        if json.load(fh)["rows"] != rows:
            raise InstrumentTranslationError(f"Backup {path} did not verify; nothing was changed.")
    return len(rows)


def fix_code_only_labels(
    instrument_code: str = BASE_INSTRUMENT_CODE,
    *,
    locale_code: str | None = None,
    dry_run: bool = True,
    backup_path: str | None = None,
    actor_id=None,
) -> dict:
    """Correct the bracketed code of ``case_only`` and ``mistyped`` rows.

    Idempotent: a corrected row no longer mismatches. ``dry_run`` (default)
    writes nothing; a real run needs ``backup_path``, written and verified
    first. Returns ``{"fixed", "needs_review", "rows"}``; ``needs_review``
    rows are left untouched.
    """
    items = find_label_code_mismatches(instrument_code, locale_code)
    fixable = [i for i in items if i["kind"] in AUTO_FIXABLE]
    review = [i for i in items if i["kind"] == NEEDS_REVIEW]
    if not dry_run and fixable:
        if not backup_path:
            raise InstrumentTranslationError("A real run needs a backup path.")
        snapshot(instrument_code, fixable, backup_path)
        for item in fixable:
            update_string(
                instrument_code, item["locale"], item_kind=ITEM_KIND_QUESTION,
                item_key=item["item_key"], field=FIELD_LABEL,
                text=_corrected(item), actor_id=actor_id,
            )
    return {"fixed": len(fixable), "needs_review": len(review), "rows": items}


def restore_from_snapshot(path: str) -> dict:
    """Put back the text, source and author recorded by :func:`snapshot`, and
    bump each touched locale's version once.

    A row is restored only while its text is still the corrected text this
    module wrote (the snapshot text with its code fixed); a row edited since
    is skipped, so a later human edit is never overwritten. Each restored row
    is logged as ``update_string`` logs an edit. Returns
    ``{"restored", "skipped"}``.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    code, touched, restored, skipped = data["instrument_code"], set(), 0, 0
    for saved in data["rows"]:
        row = db.session.get(
            MapInstrumentTranslations,
            (code, saved["locale"], ITEM_KIND_QUESTION, saved["item_key"], FIELD_LABEL),
        )
        expected = _corrected({"item_key": saved["item_key"], "text": saved["text"]}).strip()
        if row is None or row.text != expected:
            skipped += 1
            continue
        log.info(
            "instrument translation restored | %s/%s | item=%s:%s:%s | old=%r | new=%r",
            code, saved["locale"], ITEM_KIND_QUESTION, saved["item_key"], FIELD_LABEL,
            row.text, saved["text"],
        )
        row.text, row.source = saved["text"], saved["source"]
        row.updated_by = uuid.UUID(saved["updated_by"]) if saved["updated_by"] else None
        row.updated_at = datetime.fromisoformat(saved["updated_at"])
        touched.add(saved["locale"])
        restored += 1
    now = datetime.now(UTC)
    for locale in touched:
        locale_row = get_locale(code, locale)
        locale_row.version = (locale_row.version or 0) + 1
        locale_row.updated_at = now
    db.session.flush()
    return {"restored": restored, "skipped": skipped}
