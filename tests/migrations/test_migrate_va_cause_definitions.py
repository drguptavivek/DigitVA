"""Migration fba41e2f1f9d: create and seed mas_va_cause_definitions.

Throwaway database built from the migration chain only, like
test_migrate_icd11_cod_bucket_mappings.py.
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_migration_fba41e2f1f9d"
PARENT_REVISION = "6c11b620f48f"
REVISION_UNDER_TEST = "fba41e2f1f9d"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class MigrationConfig(TestConfig):
    SQLALCHEMY_DATABASE_URI = _server_url(MIGRATION_DB_NAME).render_as_string(hide_password=False)


def _admin_execute(statement):
    engine = sa.create_engine(_server_url("postgres"), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            conn.execute(sa.text(statement))
    finally:
        engine.dispose()


class VaCauseDefinitionsMigrationTest(unittest.TestCase):
    def setUp(self):
        _admin_execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"')
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        self.addCleanup(lambda: _admin_execute(f'DROP DATABASE IF EXISTS "{MIGRATION_DB_NAME}"'))

        from tests.base import create_app_without_celery_takeover

        self.app = create_app_without_celery_takeover(MigrationConfig)
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.addCleanup(self.ctx.pop)
        alembic_upgrade(revision=PARENT_REVISION)

        from app import db

        self.db = db
        self.addCleanup(db.engine.dispose)

    def _scalar(self, sql):
        with self.db.engine.connect() as conn:
            return conn.execute(sa.text(sql)).scalar()

    def test_upgrade_seeds_and_downgrade_drops(self):
        self.assertIsNone(self._scalar("SELECT to_regclass('mas_va_cause_definitions')"))

        alembic_upgrade(revision=REVISION_UNDER_TEST)
        self.assertEqual(self._scalar("SELECT count(*) FROM mas_va_cause_definitions"), 63)
        self.assertEqual(
            self._scalar(
                "SELECT count(*) FROM mas_va_cause_definitions "
                "WHERE va_code IN ('VAs-01', 'VAs-12', 'VAs-98')"
            ),
            0,
        )
        self.assertEqual(
            self._scalar("SELECT title FROM mas_va_cause_definitions WHERE va_code = 'VAs-01.01'"),
            "Sepsis",
        )
        self.assertEqual(
            self._scalar("SELECT count(*) FROM mas_va_cause_definitions WHERE updated_by IS NOT NULL"), 0
        )

        alembic_downgrade(revision=PARENT_REVISION)
        self.assertIsNone(self._scalar("SELECT to_regclass('mas_va_cause_definitions')"))
