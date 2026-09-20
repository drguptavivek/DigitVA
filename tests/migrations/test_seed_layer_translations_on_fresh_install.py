"""7134cb5dc7b6 seeds the DigitVA layer translations on a fresh install.

digitva-dms: b6d2f4a9c1e7 only inserts where a ``mas_instrument_locales`` row
already exists, so it writes nothing on an empty database. 7134cb5dc7b6 fixes
that by creating the twelve locale rows first, then the same 214 strings (now
``source='machine'``) against a checked-in CSV rather than a third copy of the
literal tuple.

Three things are proven here, none of them assumed:

* the CSV this migration reads has not drifted from the two *applied*
  migrations' literal ``SEED_ROWS`` tuples (b6d2f4a9c1e7, c1a4b6e8d3f2), which
  must never be edited and were checked byte-for-byte against each other when
  written;
* a fresh database, built from nothing but the migration chain with no
  workbook ever imported, ends with the twelve locales (Khasi excluded) as
  draft/inactive and their machine strings, none of them served;
* running the seed again is idempotent (no duplicate locale or string rows)
  and never overwrites a row an administrator has since edited or a workbook
  has since imported -- and that a subsequent workbook import still finds and
  fills in the locale row this migration created.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_seed_layer_translations_on_fresh_install.py -q
"""
import ast
import csv
import importlib.util
import unittest
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
VERSIONS_DIR = REPO_ROOT / "migrations" / "versions"
CSV_PATH = REPO_ROOT / "resource" / "digitva_layer_translations_2026_09_20.csv"

INSTRUMENT_CODE = "WHO_2022_VA"
EXPECTED_LOCALES = {"ar", "bn", "es", "fr", "hi", "kn", "ml", "mr", "or", "pt", "sw", "ta"}

# Its own database, kept clear of every database the suite or the developer
# uses: it is dropped and recreated here.
SEED_DB_NAME = "minerva_test_layer_seed"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class SeedConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(SEED_DB_NAME).render_as_string(hide_password=False)


def _admin_execute(*statements):
    engine = sa.create_engine(_server_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            for statement in statements:
                conn.execute(sa.text(statement))
    finally:
        engine.dispose()


def _drop_database():
    _admin_execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        f"WHERE datname = '{SEED_DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{SEED_DB_NAME}"',
    )


def _seed_rows_literal(filename: str) -> tuple:
    """Parse a migration's ``SEED_ROWS = (...)`` literal without importing it.

    ``ast.literal_eval``, not ``import``: a migration file is not meant to be
    imported as application code, and the tuple is pure data.
    """
    text = (VERSIONS_DIR / filename).read_text(encoding="utf-8")
    start = text.index("SEED_ROWS = (")
    end = text.index("\n)\n", start)
    return ast.literal_eval(text[start:end + 2][len("SEED_ROWS = "):])


def _csv_rows() -> tuple:
    with CSV_PATH.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return tuple(
            (row["locale_code"], row["item_kind"], row["item_key"], row["field"], row["text"])
            for row in reader
        )


def _load_migration_module():
    """Import 7134cb5dc7b6 by file path, the same way alembic loads a revision.

    Needed to call ``upgrade()`` a second time directly, inside a manually
    opened ``Operations`` context, to prove idempotency without alembic's own
    "already applied" bookkeeping getting in the way.
    """
    path = next(VERSIONS_DIR.glob("7134cb5dc7b6_*.py"))
    spec = importlib.util.spec_from_file_location("_seed_migration_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SeedCsvMatchesAppliedMigrationsTest(unittest.TestCase):
    """No database needed: the CSV must equal both applied migrations' literals."""

    def test_the_csv_matches_b6d2f4a9c1e7_and_c1a4b6e8d3f2_byte_for_byte(self):
        csv_rows = _csv_rows()
        b6d2f4a9c1e7 = _seed_rows_literal("b6d2f4a9c1e7_seed_digitva_layer_translations.py")
        c1a4b6e8d3f2 = _seed_rows_literal("c1a4b6e8d3f2_relabel_machine_translated_seed_rows.py")
        self.assertEqual(len(csv_rows), 214)
        self.assertEqual(csv_rows, b6d2f4a9c1e7)
        self.assertEqual(csv_rows, c1a4b6e8d3f2)


class FreshInstallSeedTest(unittest.TestCase):
    """Deliberate exception to test-harness rule 2, like the schema-drift guard:
    the Alembic env needs an app whose db is bound to the throwaway database.
    This test never touches the shared session schema."""

    def setUp(self):
        _drop_database()
        _admin_execute(f'CREATE DATABASE "{SEED_DB_NAME}"')
        self.addCleanup(_drop_database)

    def test_a_fresh_database_with_no_workbook_ever_imported_ends_with_the_twelve_locales(self):
        from app import db

        from tests.base import create_app_without_celery_takeover

        app = create_app_without_celery_takeover(SeedConfig)
        with app.app_context():
            alembic_upgrade(revision="heads")

            locales = db.session.execute(
                sa.text(
                    "SELECT locale_code, is_active, lifecycle_state FROM "
                    "mas_instrument_locales WHERE instrument_code = :code"
                ),
                {"code": INSTRUMENT_CODE},
            ).all()
            by_code = {row.locale_code: row for row in locales}

            self.assertEqual(set(by_code), EXPECTED_LOCALES)
            self.assertNotIn("kha", by_code)
            for code, row in by_code.items():
                with self.subTest(locale=code):
                    self.assertFalse(row.is_active)
                    self.assertEqual(row.lifecycle_state, "draft")

            strings = db.session.execute(
                sa.text(
                    "SELECT locale_code, source FROM map_instrument_translations "
                    "WHERE instrument_code = :code"
                ),
                {"code": INSTRUMENT_CODE},
            ).all()
            self.assertEqual(len(strings), 214)
            self.assertTrue(all(row.source == "machine" for row in strings))
            # Withheld from serving from the first install (decided
            # 2026-09-20): a 'machine' row is excluded by export_translations
            # and by coverage, so this is the whole enforcement -- see
            # app/services/instrument_translation_service.py.

            db.engine.dispose()

    def test_reapplying_the_seed_is_idempotent_and_never_overwrites_edited_or_imported_rows(self):
        from app import db

        from tests.base import create_app_without_celery_takeover

        app = create_app_without_celery_takeover(SeedConfig)
        with app.app_context():
            alembic_upgrade(revision="heads")

            # An administrator has since corrected one machine row, and a
            # workbook import has since supplied a genuinely different one.
            db.session.execute(
                sa.text(
                    "UPDATE map_instrument_translations SET source = 'edited', "
                    "text = 'Administrator correction' WHERE instrument_code = :code "
                    "AND locale_code = 'hi' AND item_kind = 'question' "
                    "AND item_key = 'consent_mode' AND field = 'label'"
                ),
                {"code": INSTRUMENT_CODE},
            )
            db.session.execute(
                sa.text(
                    "UPDATE map_instrument_translations SET source = 'imported', "
                    "text = 'Workbook text' WHERE instrument_code = :code "
                    "AND locale_code = 'bn' AND item_kind = 'question' "
                    "AND item_key = 'consent_mode' AND field = 'label'"
                ),
                {"code": INSTRUMENT_CODE},
            )
            db.session.commit()

            before_locales = db.session.execute(
                sa.text(
                    "SELECT count(*) FROM mas_instrument_locales WHERE instrument_code = :code"
                ),
                {"code": INSTRUMENT_CODE},
            ).scalar_one()
            before_strings = db.session.execute(
                sa.text(
                    "SELECT count(*) FROM map_instrument_translations WHERE instrument_code = :code"
                ),
                {"code": INSTRUMENT_CODE},
            ).scalar_one()

            module = _load_migration_module()
            with db.engine.connect() as conn:
                ctx = MigrationContext.configure(conn)
                with Operations.context(ctx):
                    module.upgrade()
                conn.commit()

            after_locales = db.session.execute(
                sa.text(
                    "SELECT count(*) FROM mas_instrument_locales WHERE instrument_code = :code"
                ),
                {"code": INSTRUMENT_CODE},
            ).scalar_one()
            after_strings = db.session.execute(
                sa.text(
                    "SELECT count(*) FROM map_instrument_translations WHERE instrument_code = :code"
                ),
                {"code": INSTRUMENT_CODE},
            ).scalar_one()
            self.assertEqual(after_locales, before_locales)
            self.assertEqual(after_strings, before_strings)

            hi_row = db.session.execute(
                sa.text(
                    "SELECT source, text FROM map_instrument_translations WHERE "
                    "instrument_code = :code AND locale_code = 'hi' AND "
                    "item_kind = 'question' AND item_key = 'consent_mode' AND field = 'label'"
                ),
                {"code": INSTRUMENT_CODE},
            ).one()
            self.assertEqual(hi_row.source, "edited")
            self.assertEqual(hi_row.text, "Administrator correction")

            bn_row = db.session.execute(
                sa.text(
                    "SELECT source, text FROM map_instrument_translations WHERE "
                    "instrument_code = :code AND locale_code = 'bn' AND "
                    "item_kind = 'question' AND item_key = 'consent_mode' AND field = 'label'"
                ),
                {"code": INSTRUMENT_CODE},
            ).one()
            self.assertEqual(bn_row.source, "imported")
            self.assertEqual(bn_row.text, "Workbook text")

            db.engine.dispose()

    def test_a_later_workbook_import_still_fills_in_the_migration_created_locale_row(self):
        """The whole point: an operator import must behave exactly as before."""
        from app import db
        from app.models.mas_instrument_locales import MasInstrumentLocales
        from app.services import instrument_translation_service as svc

        from tests.base import create_app_without_celery_takeover

        app = create_app_without_celery_takeover(SeedConfig)
        with app.app_context():
            alembic_upgrade(revision="heads")

            row = db.session.get(MasInstrumentLocales, (INSTRUMENT_CODE, "hi"))
            self.assertIsNotNone(row)
            self.assertIsNone(row.source_document)
            self.assertIsNone(row.source_sha256)

            path = svc.WORKBOOK_DIR / "ND01_ICMRVA_WHOVA2022.xlsx"
            svc.import_translations(INSTRUMENT_CODE, "hi", path)
            db.session.commit()

            db.session.expire_all()
            row = db.session.get(MasInstrumentLocales, (INSTRUMENT_CODE, "hi"))
            self.assertEqual(row.source_document, "ND01_ICMRVA_WHOVA2022.xlsx")
            self.assertIsNotNone(row.source_sha256)
            # Still draft/inactive: an import never approves or activates.
            self.assertEqual(row.lifecycle_state, "draft")
            self.assertFalse(row.is_active)

            db.engine.dispose()


if __name__ == "__main__":
    unittest.main()
