"""``g3k7n1s5v9y2`` adds ``map_instrument_translation_suggestions`` (digitva-5op).

Builds a throwaway database from the migration chain, upgrades to the revision,
checks the table, its status CHECK constraints and its three indexes, then
downgrades one step and checks the table is gone. It steps back with ``-1`` so
re-chaining the revision onto another parent does not touch this test.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_instrument_translation_suggestions.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_mits_mig"
REVISION = "g3k7n1s5v9y2"
TABLE = "map_instrument_translation_suggestions"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class SuggestionsMigrationConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(MIGRATION_DB_NAME).render_as_string(hide_password=False)


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
        f"WHERE datname = '{MIGRATION_DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"',
    )


class InstrumentTranslationSuggestionsMigrationTest(unittest.TestCase):
    def test_upgrade_creates_the_table_and_downgrade_drops_it(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(SuggestionsMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                self.assertIn(TABLE, inspector.get_table_names())

                columns = {c["name"]: c for c in inspector.get_columns(TABLE)}
                self.assertEqual(
                    set(columns),
                    {
                        "id", "instrument_code", "locale_code", "item_kind", "item_key",
                        "field", "proposed_text", "seen_text", "reason", "project_id",
                        "suggested_by", "suggested_at", "status", "decided_by",
                        "decided_at", "decision_note",
                    },
                )
                # seen_text is NULL for "the string had no translation".
                self.assertTrue(columns["seen_text"]["nullable"])
                self.assertFalse(columns["proposed_text"]["nullable"])
                self.assertFalse(columns["reason"]["nullable"])

                indexes = {i["name"]: i for i in inspector.get_indexes(TABLE)}
                self.assertEqual(
                    indexes["ix_mits_locale_status"]["column_names"],
                    ["instrument_code", "locale_code", "status", "id"],
                )
                self.assertEqual(
                    indexes["ix_mits_project_status"]["column_names"],
                    ["project_id", "status", "id"],
                )
                self.assertTrue(indexes["uq_mits_pending_per_user"]["unique"])

                checks = {c["name"] for c in inspector.get_check_constraints(TABLE)}
                self.assertEqual(
                    checks,
                    {
                        "ck_map_instrument_translation_suggestions_status",
                        "ck_map_instrument_translation_suggestions_decided_has_decider",
                    },
                )
                db.session.remove()

                alembic_downgrade(revision="-1")
                self.assertNotIn(TABLE, sa.inspect(db.engine).get_table_names())
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
