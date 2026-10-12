"""``m4v8r2t6q1w9`` adds ``mas_ui_string_override`` (digitva-fsjz).

Builds a throwaway database from the migration chain, upgrades to the revision,
checks the table, its primary key and its foreign key, then downgrades one step
and checks the table is gone. Steps back with ``-1`` so re-chaining the
revision onto another parent does not touch this test.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_mas_ui_string_override.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_uis_mig"
REVISION = "m4v8r2t6q1w9"
TABLE = "mas_ui_string_override"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class UiStringOverrideMigrationConfig(TestConfig):
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


class UiStringOverrideMigrationTest(unittest.TestCase):
    def test_upgrade_creates_the_table_and_downgrade_drops_it(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(UiStringOverrideMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                self.assertIn(TABLE, inspector.get_table_names())

                columns = {c["name"]: c for c in inspector.get_columns(TABLE)}
                self.assertEqual(
                    set(columns), {"locale_code", "string_key", "text", "updated_by", "updated_at"}
                )
                self.assertFalse(columns["text"]["nullable"])
                self.assertTrue(columns["updated_by"]["nullable"])
                self.assertFalse(columns["updated_at"]["nullable"])

                pk = inspector.get_pk_constraint(TABLE)
                self.assertEqual(pk["constrained_columns"], ["locale_code", "string_key"])

                fks = inspector.get_foreign_keys(TABLE)
                self.assertEqual(
                    [(fk["constrained_columns"], fk["referred_table"]) for fk in fks],
                    [(["updated_by"], "va_users")],
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
