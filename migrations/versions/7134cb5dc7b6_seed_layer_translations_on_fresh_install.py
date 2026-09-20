"""Seed DigitVA-authored layer translations on a fresh install too

Revision ID: 7134cb5dc7b6
Revises: d2b5c7f9e4a3
Create Date: 2026-09-20

digitva-dms: b6d2f4a9c1e7 seeds the same 214 strings, but only where a
``mas_instrument_locales`` row already exists -- on a fresh database no
locale rows exist at migration time (an operator creates them later by
importing a workbook), so b6d2f4a9c1e7 writes nothing and, being already
applied, alembic never runs it again. Verified 2026-09-20 on an empty
database: 0 rows inserted; a new deployment sits at 0/2 on ``digitva_core``
and ``abha`` with the shared "Medical and death documents" heading missing.

Owner's decision, 2026-09-20: keep this in a migration, not a CLI seeder, and
make it work on a fresh install. This migration:

* creates the twelve locale rows (Khasi excluded, as in b6d2f4a9c1e7 -- no
  reliable source of Khasi for these strings) when absent, with
  ``lifecycle_state='draft'`` and ``is_active=false``, so nothing is served
  and nothing is offered until an administrator acts;
* inserts the same 214 strings as ``source='machine'`` (not ``imported`` as
  b6d2f4a9c1e7 originally wrote them, before c1a4b6e8d3f2 relabelled them) --
  withheld from serving and from coverage from the very first install,
  rather than needing a later relabel.

A later operator workbook import still works exactly as before:
``_get_or_create_locale`` (app/services/instrument_translation_service.py)
finds the locale row this migration created and fills in
``source_document``/``source_sha256`` on top of it -- see
tests/migrations/test_seed_layer_translations_on_fresh_install.py, which
proves that specifically, not just assumes it.

**Do not paste the 214 strings a third time.** They already exist as literals
in b6d2f4a9c1e7 and again in c1a4b6e8d3f2, both applied and pushed and never
to be edited (docs/policy/migration-chaining.md: migrations must not import
each other's code). This migration instead reads the checked-in
``resource/digitva_layer_translations_2026_09_20.csv``, generated once from
those two migrations' identical literal tuple (see the precedent for a
checked-in data file consumed by a migration:
``resource/icd11_mms_2026_01_hierarchy.csv`` /
b6edb1b7d01a_add_mas_icd11_mms_table.py). Drift between the CSV and the two
applied migrations' literals is guarded by
tests/migrations/test_seed_layer_translations_on_fresh_install.py, which
compares the CSV row-for-row against both.

Idempotent: locale rows are inserted ``ON CONFLICT DO NOTHING`` on the
primary key, and strings the same way on their own primary key -- a locale
or a string that already exists (from an operator import, an edit, or a
previous run of this migration) is left untouched; nothing here overwrites
an ``edited`` or ``imported`` row. Touched locales have their ``version``
bumped so a client revalidates its cached locale, matching b6d2f4a9c1e7.

Reversible, but conservatively: downgrade removes only the untouched
``machine`` rows this migration wrote (matched on locale, item, field and
text, same three-way match b6d2f4a9c1e7.downgrade uses), never a row an
administrator has since edited or a workbook has since imported over. It
deliberately does **not** remove the locale rows themselves: by the time of
a downgrade a locale this migration created may already carry real
workbook-imported strings, an approval, or activation, and deleting the row
would destroy that human work -- the same "no bulk delete without a
recovery path" rule the seed rows already follow.
"""

import csv
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision = '7134cb5dc7b6'
down_revision = 'd2b5c7f9e4a3'
branch_labels = None
depends_on = None

INSTRUMENT_CODE = "WHO_2022_VA"

#: Repo-relative, read at migration time -- same pattern as
#: b6edb1b7d01a_add_mas_icd11_mms_table.py's CSV_SOURCE_PATH.
CSV_SOURCE_PATH = Path("resource/digitva_layer_translations_2026_09_20.csv")

#: (locale_code, language_name). Khasi (kha) is deliberately absent, as in
#: b6d2f4a9c1e7: no reliable source of Khasi for these strings.
LOCALES = (
    ("ar", "Arabic"),
    ("bn", "Bangla"),
    ("es", "Spanish"),
    ("fr", "French"),
    ("hi", "Hindi"),
    ("kn", "Kannada"),
    ("ml", "Malayalam"),
    ("mr", "Marathi"),
    ("or", "Odia"),
    ("pt", "Portuguese"),
    ("sw", "Swahili"),
    ("ta", "Tamil"),
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_seed_rows() -> list[tuple[str, str, str, str, str]]:
    csv_path = _repo_root() / CSV_SOURCE_PATH
    if not csv_path.exists():
        raise ValueError(f"Layer translation seed CSV not found for migration: {csv_path}")
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [
            (row["locale_code"], row["item_kind"], row["item_key"], row["field"], row["text"])
            for row in reader
        ]


def upgrade():
    bind = op.get_bind()
    now = datetime.now(UTC)

    for locale_code, language_name in LOCALES:
        bind.execute(
            sa.text(
                """
                INSERT INTO mas_instrument_locales
                    (instrument_code, locale_code, language_name, is_active,
                     lifecycle_state, version, updated_at)
                VALUES (:code, :locale, :name, false, 'draft', 1, :now)
                ON CONFLICT (instrument_code, locale_code) DO NOTHING
                """
            ),
            {"code": INSTRUMENT_CODE, "locale": locale_code, "name": language_name, "now": now},
        )

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
    """Remove only the untouched 'machine' rows this migration wrote.

    Never the locale rows -- see the module docstring. A row an administrator
    has since edited is 'edited' and is skipped by the source filter; a row
    whose text no longer matches the literal seeded here was changed by
    someone (or replaced by a real import) and is skipped by the text filter.
    """
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
