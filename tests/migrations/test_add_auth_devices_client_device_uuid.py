"""``c7a3e9d1f5b8`` adds ``auth_devices.client_device_uuid``.

Builds a throwaway database from the migration chain, upgrades to the
revision, checks the nullable column and its plain (non-unique) index, then
downgrades one step and checks both are gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_auth_devices_client_device_uuid.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

MIGRATION_DB_NAME = "minerva_test_client_uuid_mig"
REVISION = "c7a3e9d1f5b8"
COLUMN = "client_device_uuid"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class ClientUuidMigrationConfig(TestConfig):
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


def _columns(db):
    return {c["name"]: c for c in sa.inspect(db.engine).get_columns("auth_devices")}


def _index(db):
    return next(
        (i for i in sa.inspect(db.engine).get_indexes("auth_devices") if i["name"] == "ix_auth_devices_client_device_uuid"),
        None,
    )


class ClientDeviceUuidMigrationTest(unittest.TestCase):
    def test_upgrade_adds_a_nullable_indexed_column_and_downgrade_drops_it(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{MIGRATION_DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(ClientUuidMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=REVISION)
                self.assertTrue(_columns(db)[COLUMN]["nullable"])
                index = _index(db)
                self.assertEqual(index["column_names"], [COLUMN])
                self.assertFalse(index["unique"])
                db.session.remove()

                alembic_downgrade(revision="-1")
                self.assertNotIn(COLUMN, _columns(db))
                self.assertIsNone(_index(db))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()


if __name__ == "__main__":
    unittest.main()
