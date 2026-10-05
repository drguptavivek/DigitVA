"""Seed Hindi machine drafts for constraint messages and guidance notes

Revision ID: e9h3k6p2s8v4
Revises: d8q4e1h6n3v9
Create Date: 2026-10-06 16:00:00.000000

digitva-8go.1: the 89 constraint messages and 340 guidance notes were English
for every locale. ``constraint_message`` is now a translatable field; this
seeds a Hindi draft of each as ``source='machine'``, so none is served until a
speaker accepts it in the editor (``export_translations`` and coverage both
exclude ``machine``). Same mechanism as 7134cb5dc7b6, for the same reason.

Only Hindi. The other locales have no draft yet and fall back to English.

The 429 strings are read from ``resource/instrument_notes_hi_2026_10_06.csv``
rather than pasted here; the CSV's keys and English structure are checked
against the live reference by tests/migrations/test_seed_hindi_note_drafts.py.
No application code is imported (docs/policy/migration-chaining.md).

No schema change: ``map_instrument_translations.field`` is a plain string with
no CHECK, so the new field value needs no DDL.

Idempotent and non-destructive: a row is inserted only where the locale row
exists and the string is absent (``ON CONFLICT DO NOTHING``), so an ``edited``
or ``imported`` row is never overwritten. A touched locale's ``version`` is
bumped so a client revalidates its cached copy (the drafts themselves are not
served, but the bump is harmless and matches the precedent).

Downgrade removes only untouched ``machine`` rows whose text still matches the
CSV; an accepted (``edited``) or changed row is left alone. The locale row is
never removed.
"""

import csv
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = "e9h3k6p2s8v4"
down_revision = "d8q4e1h6n3v9"
branch_labels = None
depends_on = None

INSTRUMENT_CODE = "WHO_2022_VA"

#: Repo-relative, read at migration time -- same pattern as 7134cb5dc7b6.
CSV_SOURCE_PATH = Path("resource/instrument_notes_hi_2026_10_06.csv")


def _load_seed_rows() -> list[tuple[str, str, str, str, str]]:
    csv_path = Path(__file__).resolve().parents[2] / CSV_SOURCE_PATH
    if not csv_path.exists():
        raise ValueError(f"Note translation seed CSV not found for migration: {csv_path}")
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        return [
            (row["locale_code"], row["item_kind"], row["item_key"], row["field"], row["text"])
            for row in csv.DictReader(handle)
        ]


def upgrade():
    bind = op.get_bind()
    inserted_locales = set()
    for locale_code, item_kind, item_key, field, text in _load_seed_rows():
        result = bind.execute(
            sa.text(
                """
                INSERT INTO map_instrument_translations
                    (instrument_code, locale_code, item_kind, item_key, field,
                     text, source, updated_at)
                SELECT :code, :locale, :kind, :key, :field, :text, 'machine', now()
                FROM mas_instrument_locales l
                WHERE l.instrument_code = :code
                  AND l.locale_code = :locale
                ON CONFLICT (instrument_code, locale_code, item_kind, item_key, field)
                DO NOTHING
                """
            ),
            {
                "code": INSTRUMENT_CODE,
                "locale": locale_code,
                "kind": item_kind,
                "key": item_key,
                "field": field,
                "text": text,
            },
        )
        if result.rowcount:
            inserted_locales.add(locale_code)

    for locale_code in sorted(inserted_locales):
        bind.execute(
            sa.text(
                """
                UPDATE mas_instrument_locales
                SET version = version + 1, updated_at = now()
                WHERE instrument_code = :code AND locale_code = :locale
                """
            ),
            {"code": INSTRUMENT_CODE, "locale": locale_code},
        )


def downgrade():
    bind = op.get_bind()
    for locale_code, item_kind, item_key, field, text in _load_seed_rows():
        bind.execute(
            sa.text(
                """
                DELETE FROM map_instrument_translations
                WHERE instrument_code = :code
                  AND locale_code = :locale
                  AND item_kind = :kind
                  AND item_key = :key
                  AND field = :field
                  AND source = 'machine'
                  AND text = :text
                """
            ),
            {
                "code": INSTRUMENT_CODE,
                "locale": locale_code,
                "kind": item_kind,
                "key": item_key,
                "field": field,
                "text": text,
            },
        )
