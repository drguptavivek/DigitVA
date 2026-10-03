"""``b7d4e9f2a6c1`` adds ``va_death_register.date_of_birth_partial`` (bead
digitva-tld2).

Builds a throwaway database at the previous head, upgrades, checks the
nullable column and its two check constraints (format; exclusive with the
exact date), then downgrades, checks all three are gone, and upgrades again.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_partial_birth_date.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
DB_NAME = "minerva_test_partial_dob_mig"

PREVIOUS_HEAD = "f3a8c1d6e2b9"
REVISION = "b7d4e9f2a6c1"
CONSTRAINTS = {
    "ck_va_death_register_date_of_birth_partial_format",
    "ck_va_death_register_date_of_birth_exact_or_partial",
}


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class PartialBirthDateMigrationConfig(TestConfig):
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


class AddPartialBirthDateMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_adds_column_and_checks_and_downgrade_removes_them(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        def state():
            columns = {c["name"]: c for c in sa.inspect(db.engine).get_columns("va_death_register")}
            checks = {
                row.conname: row.condef
                for row in db.session.execute(sa.text(
                    "SELECT conname, pg_get_constraintdef(oid) AS condef FROM pg_constraint "
                    "WHERE conrelid = 'va_death_register'::regclass AND contype = 'c'"
                ))
            }
            db.session.remove()
            return columns, checks

        def check_passes(condition, partial, exact=None):
            return db.session.execute(sa.text(
                f"SELECT {condition} FROM (SELECT CAST(:p AS varchar) AS date_of_birth_partial, "
                "CAST(:e AS date) AS date_of_birth) AS t"
            ), {"p": partial, "e": exact}).scalar()

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(PartialBirthDateMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                columns, checks = state()
                self.assertNotIn("date_of_birth_partial", columns)

                alembic_upgrade(revision=REVISION)
                columns, checks = state()
                self.assertIn("date_of_birth_partial", columns)
                self.assertTrue(columns["date_of_birth_partial"]["nullable"])
                self.assertTrue(CONSTRAINTS <= set(checks), checks)
                # The stored check expressions accept YYYY / YYYY-MM only and
                # never both precisions at once.
                fmt = checks["ck_va_death_register_date_of_birth_partial_format"].removeprefix("CHECK ")
                exclusive = checks["ck_va_death_register_date_of_birth_exact_or_partial"].removeprefix("CHECK ")
                for value, ok in (("1950", True), ("1950-07", True), ("1950-13", False),
                                  ("1950-7", False), ("50", False), (None, True)):
                    with self.subTest(value=value):
                        self.assertIs(bool(check_passes(fmt, value) is not False), ok)
                self.assertFalse(check_passes(exclusive, "1950", "1950-07-01"))
                self.assertTrue(check_passes(exclusive, "1950"))
                self.assertTrue(check_passes(exclusive, None, "1950-07-01"))
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                columns, checks = state()
                self.assertNotIn("date_of_birth_partial", columns)
                self.assertFalse(CONSTRAINTS & set(checks))

                alembic_upgrade(revision=REVISION)
                columns, checks = state()
                self.assertIn("date_of_birth_partial", columns)
                self.assertTrue(CONSTRAINTS <= set(checks))
                db.engine.dispose()
        finally:
            _drop_database()
