"""Fold reviewed UI strings into a bundled locale file (digitva-3b65).

Policy: docs/policy/ui-strings.md ("Keeping translations across a cutover").
Reads the source files under ``mobile/digitva-collect/src/strings`` and the
accepted (``edited``) rows of ``mas_ui_string_override``; machine drafts are
never baked. The output is the committed file's exact format: ``en.json`` key
order, two-space indent, no ASCII escaping, trailing newline.
"""

import json
import re
from pathlib import Path

import sqlalchemy as sa

from app import db
from app.models.mas_ui_string_override import MasUiStringOverride
from app.services.ui_string_service import (
    BASE_LOCALE,
    SOURCE_EDITED,
    UiStringError,
    _placeholders,
)

SOURCE_DIR = Path(__file__).resolve().parents[2] / "mobile/digitva-collect/src/strings"
_LOCALE_RE = re.compile(r"^[a-z]{2,3}$")


def bake(locale: str, src_dir: Path = SOURCE_DIR) -> tuple[str, int]:
    """The merged locale file text and how many keys the database changed.

    Raises :class:`UiStringError` (writing nothing) if the locale is invalid,
    nothing is accepted for a locale with no source file, or an accepted text's
    placeholders differ from the English.
    """
    if locale == BASE_LOCALE or not _LOCALE_RE.match(locale):
        raise UiStringError(f"{locale!r} cannot be baked.")
    english = json.loads((src_dir / f"{BASE_LOCALE}.json").read_text(encoding="utf-8"))
    source = src_dir / f"{locale}.json"
    bundled = json.loads(source.read_text(encoding="utf-8")) if source.exists() else {}
    accepted = dict(
        db.session.execute(
            sa.select(MasUiStringOverride.string_key, MasUiStringOverride.text).where(
                MasUiStringOverride.locale_code == locale,
                MasUiStringOverride.source == SOURCE_EDITED,
            )
        ).all()
    )
    accepted = {k: t for k, t in accepted.items() if k in english}
    bad = sorted(k for k, t in accepted.items() if _placeholders(t) != _placeholders(english[k]))
    if bad:
        raise UiStringError(f"Placeholders differ from English for: {', '.join(bad)}")
    if not source.exists() and not accepted:
        raise UiStringError(f"No bundled file and no accepted strings for {locale!r}.")
    merged = {**bundled, **accepted}
    changed = sum(1 for k, t in accepted.items() if bundled.get(k) != t)
    ordered = {k: merged[k] for k in english if k in merged}
    return json.dumps(ordered, ensure_ascii=False, indent=2) + "\n", changed
