"""``b5e2c8d4a9f7`` adds the nullable ``mas_cod_bucket_nodes.va_code`` (digitva-0o3z).

Builds a throwaway database from the migration chain, upgrades to the
revision, checks the column, downgrades one step, checks it is gone, and
upgrades again. Steps back with ``-1`` so re-chaining the revision onto
another parent does not touch this test.
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_vacode_mig"
REVISION = "b5e2c8d4a9f7"
TABLE = "mas_cod_bucket_nodes"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class NodeVaCodeMigrationConfig(TestConfig):
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


def _va_code_column(db):
    columns = {c["name"]: c for c in sa.inspect(db.engine).get_columns(TABLE)}
    return columns.get("va_code")


class NodeVaCodeMigrationTest(unittest.TestCase):
    def test_upgrade_adds_the_column_and_downgrade_drops_it(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(NodeVaCodeMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=REVISION)
                column = _va_code_column(db)
                self.assertIsNotNone(column)
                self.assertTrue(column["nullable"])
                self.assertEqual(column["type"].length, 16)
                db.session.remove()

                alembic_downgrade(revision="-1")
                self.assertIn("node_code", {c["name"] for c in sa.inspect(db.engine).get_columns(TABLE)})
                self.assertIsNone(_va_code_column(db))

                alembic_upgrade(revision=REVISION)
                self.assertIsNotNone(_va_code_column(db))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
