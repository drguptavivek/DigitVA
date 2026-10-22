"""``b9e4f2a7c1d3`` adds the device signing-key columns and
``revoked_compromised`` to ``auth_devices`` and the
``auth_device_signing_keys`` history table (bead digitva-gb8w.5).

Builds a throwaway database at the previous head with one device row,
upgrades, checks the columns, the default on the existing row, the index and
the table, then downgrades and checks they are gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_device_signing_keys.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here.
DB_NAME = "minerva_test_device_signing_mig"

PREVIOUS_HEAD = "e5a2c7b9d3f1"
REVISION = "b9e4f2a7c1d3"
NEW_COLUMNS = {"revoked_compromised", "signing_public_key", "signing_key_id", "signing_key_set_at"}
KEY_INDEX = "ix_auth_devices_signing_key_id"
TABLE = "auth_device_signing_keys"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class DeviceSigningKeysConfig(TestConfig):
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


class DeviceSigningKeysMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_adds_and_downgrade_removes(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        def indexdef(name):
            return db.session.execute(
                sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"), {"n": name}
            ).scalar()

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(DeviceSigningKeysConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                db.session.execute(sa.text(
                    "INSERT INTO va_project_master (project_id, project_code, project_name, project_nickname,"
                    " project_status, project_registered_at, project_updated_at)"
                    " VALUES ('MIG01', 'MIG01', 'Migration', 'MIG01', 'active', now(), now())"
                ))
                db.session.execute(sa.text(
                    "INSERT INTO auth_devices (device_id, project_id, name, platform, secret_hash, enrolled_at)"
                    " VALUES ('00000000-0000-4000-8000-000000000001', 'MIG01', 'Old phone', 'android',"
                    " repeat('a', 64), now())"
                ))
                db.session.commit()

                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                columns = {c["name"]: c for c in inspector.get_columns("auth_devices")}
                self.assertTrue(NEW_COLUMNS <= set(columns))
                self.assertFalse(columns["revoked_compromised"]["nullable"])
                self.assertIs(db.session.execute(sa.text(
                    "SELECT revoked_compromised FROM auth_devices WHERE name = 'Old phone'")).scalar(), False)
                self.assertIn("(signing_key_id)", indexdef(KEY_INDEX))
                self.assertIn(TABLE, inspector.get_table_names())
                uniques = [u["column_names"] for u in inspector.get_unique_constraints(TABLE)]
                self.assertIn(["device_id", "signing_key_id"], uniques)
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                inspector = sa.inspect(db.engine)
                columns = {c["name"] for c in inspector.get_columns("auth_devices")}
                self.assertIn("secret_hash", columns)
                self.assertFalse(NEW_COLUMNS & columns)
                self.assertIsNone(indexdef(KEY_INDEX))
                self.assertNotIn(TABLE, inspector.get_table_names())
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()
