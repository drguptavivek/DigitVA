"""``a7d3e9c5b2f1`` adds ``map_org_level_cadre.can_edit_interviews`` (digitva-6dh9).

Builds a throwaway database at the previous head, upgrades (column present,
default false), downgrades (gone) and upgrades again.
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here; never the suite's database.
MIGRATION_DB_NAME = "minerva_test_can_edit_interviews_mig"

PREVIOUS_HEAD = "f4c2a8e6b1d9"
REVISION = "a7d3e9c5b2f1"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class CanEditInterviewsMigrationConfig(TestConfig):
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


def _column(db):
    """The column's default, or None when it is absent."""
    return db.session.scalar(sa.text(
        "SELECT column_default FROM information_schema.columns "
        "WHERE table_name = 'map_org_level_cadre' AND column_name = 'can_edit_interviews'"))


class AddCanEditInterviewsMigrationTest(unittest.TestCase):
    def test_upgrade_downgrade_upgrade(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(CanEditInterviewsMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                self.assertIsNone(_column(db))
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertEqual(_column(db), "false")
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                self.assertIsNone(_column(db))
                db.session.remove()

                alembic_upgrade(revision=REVISION)
                self.assertEqual(_column(db), "false")
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
