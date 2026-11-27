"""``a40477e55b72`` adds ``va_death_register.date_of_death_year_only`` (bead
digitva-xmlw).

Builds a throwaway database at the previous head, upgrades, checks the
nullable boolean with no server default (existing rows stay NULL), then
downgrades, checks it is gone, and upgrades again.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_date_of_death_year_only.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
DB_NAME = "minerva_test_dod_year_only_mig"

PREVIOUS_HEAD = "f3c9d1a7b5e2"
REVISION = "a40477e55b72"
COLUMN = "date_of_death_year_only"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class DateOfDeathYearOnlyMigrationConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(DB_NAME).render_as_string(hide_password=False)


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
        f"WHERE datname = '{DB_NAME}' AND pid <> pg_backend_pid()",
        f'DROP DATABASE IF EXISTS "{DB_NAME}"',
    )


class AddDateOfDeathYearOnlyMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_adds_the_nullable_flag_and_downgrade_removes_it(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        def columns():
            found = {c["name"]: c for c in sa.inspect(db.engine).get_columns("va_death_register")}
            db.session.remove()
            return found

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(DateOfDeathYearOnlyMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self.assertIn("date_of_death", columns())
                self.assertNotIn(COLUMN, columns())

                alembic_upgrade(revision=REVISION)
                column = columns()[COLUMN]
                self.assertIsInstance(column["type"], sa.Boolean)
                self.assertTrue(column["nullable"])
                self.assertIsNone(column["default"])

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertNotIn(COLUMN, columns())

                alembic_upgrade(revision=REVISION)
                self.assertIn(COLUMN, columns())
                db.engine.dispose()
        finally:
            _drop_database()
