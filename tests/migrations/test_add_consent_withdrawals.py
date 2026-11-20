"""``f4c2a8e6b1d9`` adds ``va_consent_withdrawals`` and
``va_death_register.consent_withdrawn_at`` (digitva-4gu7).

Builds a throwaway database at the previous head, upgrades (table, column and
the one-active-per-case index), downgrades (both gone) and upgrades again.
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
MIGRATION_DB_NAME = "minerva_test_consent_withdrawals_mig"

PREVIOUS_HEAD = "d8a2f4c6e1b3"
REVISION = "f4c2a8e6b1d9"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class ConsentWithdrawalsMigrationConfig(TestConfig):
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


def _schema(db):
    tables = set(db.session.scalars(sa.text(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")))
    columns = set(db.session.scalars(sa.text(
        "SELECT column_name FROM information_schema.columns WHERE table_name = 'va_death_register'")))
    return "va_consent_withdrawals" in tables, "consent_withdrawn_at" in columns


class AddConsentWithdrawalsMigrationTest(unittest.TestCase):
    def test_upgrade_downgrade_upgrade(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(ConsentWithdrawalsMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self.assertEqual(_schema(db), (False, False))
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertEqual(_schema(db), (True, True))
                self.assertEqual(db.session.scalar(sa.text(
                    "SELECT count(*) FROM pg_indexes WHERE indexname = 'uq_va_consent_withdrawals_active_death'")), 1)
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertEqual(_schema(db), (False, False))
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertEqual(_schema(db), (True, True))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
