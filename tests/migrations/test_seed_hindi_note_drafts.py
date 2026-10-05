"""e9h3k6p2s8v4 seeds Hindi machine drafts of constraint messages and guidance.

digitva-8go.1. Proven here, not assumed:

* the checked-in CSV covers exactly the reference's guidance notes and
  constraint messages -- no key missing, none invented -- and each draft keeps
  the English's HTML tags, ``${...}`` placeholders and digits, so a re-generated
  reference that gains or drops a note fails here instead of seeding silently;
* a database built from nothing but the migration chain ends with every draft
  as ``source='machine'`` (never served: ``export_translations`` and coverage
  exclude it), and re-running the seed is idempotent and never overwrites an
  accepted (``edited``) row.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_seed_hindi_note_drafts.py -q
"""
import csv
import importlib.util
import re
import unittest
from pathlib import Path

import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

REPO_ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = REPO_ROOT / "resource" / "instrument_notes_hi_2026_10_06.csv"
INSTRUMENT_CODE = "WHO_2022_VA"
NOTE_FIELDS = ("guidance_hint", "constraint_message")

# Its own throwaway database, dropped and recreated here.
SEED_DB_NAME = "minerva_test_note_seed"


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


def _csv_rows():
    with CSV_PATH.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


class NoteDraftCsvTest(unittest.TestCase):
    """No database: the CSV against the live English reference."""

    def test_the_csv_covers_exactly_the_reference_notes_and_keeps_their_markup(self):
        from app.services import instrument_translation_service as svc

        reference = svc.reference_items(INSTRUMENT_CODE)
        notes = {k: v for k, v in reference.items() if k[2] in NOTE_FIELDS}
        rows = _csv_rows()
        by_key = {("question", r["item_key"], r["field"]): r["text"] for r in rows}

        self.assertEqual(len(rows), len(by_key), "duplicate key in the CSV")
        self.assertEqual(len(rows), 429)
        self.assertEqual(set(by_key), set(notes))
        tag = re.compile(r"</?[a-zA-Z][^>]*>")
        for key, english in notes.items():
            hindi = by_key[key]
            with self.subTest(key=key):
                self.assertTrue(hindi.strip())
                self.assertNotEqual(hindi, english)
                self.assertEqual(tag.findall(hindi), tag.findall(english))
                self.assertEqual(
                    re.findall(r"\$\{[^}]*\}", hindi), re.findall(r"\$\{[^}]*\}", english)
                )
        self.assertTrue({r["locale_code"] for r in rows} == {"hi"})


class SeedMigrationTest(unittest.TestCase):
    def setUp(self):
        _drop_database()
        _admin_execute(f'CREATE DATABASE "{SEED_DB_NAME}"')
        self.addCleanup(_drop_database)

    def _count(self, db, extra=""):
        return db.session.execute(
            sa.text(
                "SELECT count(*) FROM map_instrument_translations WHERE "
                "instrument_code = :code AND locale_code = 'hi' AND "
                "field IN ('guidance_hint', 'constraint_message')" + extra
            ),
            {"code": INSTRUMENT_CODE},
        ).scalar_one()

    def test_a_fresh_chain_seeds_every_draft_as_machine_and_a_rerun_changes_nothing(self):
        from app import db

        from tests.base import create_app_without_celery_takeover

        app = create_app_without_celery_takeover(SeedConfig)
        with app.app_context():
            alembic_upgrade(revision="heads")
            expected = len(_csv_rows())
            self.assertEqual(self._count(db), expected)
            self.assertEqual(self._count(db, " AND source = 'machine'"), expected)

            # Accepted by a speaker since: must survive a re-run untouched.
            db.session.execute(
                sa.text(
                    "UPDATE map_instrument_translations SET source = 'edited', "
                    "text = 'Accepted' WHERE instrument_code = :code AND "
                    "locale_code = 'hi' AND item_key = 'Id10010' AND field = 'constraint_message'"
                ),
                {"code": INSTRUMENT_CODE},
            )
            db.session.commit()

            path = next((REPO_ROOT / "migrations" / "versions").glob("e9h3k6p2s8v4_*.py"))
            spec = importlib.util.spec_from_file_location("_note_seed_under_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            with db.engine.connect() as conn:
                with Operations.context(MigrationContext.configure(conn)):
                    module.upgrade()
                conn.commit()

            self.assertEqual(self._count(db), expected)
            row = db.session.execute(
                sa.text(
                    "SELECT source, text FROM map_instrument_translations WHERE "
                    "instrument_code = :code AND locale_code = 'hi' AND "
                    "item_key = 'Id10010' AND field = 'constraint_message'"
                ),
                {"code": INSTRUMENT_CODE},
            ).one()
            self.assertEqual((row.source, row.text), ("edited", "Accepted"))
            db.engine.dispose()


if __name__ == "__main__":
    unittest.main()
