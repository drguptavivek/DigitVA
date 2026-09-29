"""``f2c6a8d4b1e9`` adds ``client_death_id`` to ``va_death_register`` and
``client_attempt_id`` to ``map_case_contact_attempts`` (each unique where not
null) and ``outstanding_client_death_ids`` to ``auth_device_sessions`` (bead
digitva-kmk.4).

Builds a throwaway database at the previous head, upgrades, checks the
columns and partial unique indexes, then downgrades and checks they are gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_device_offline_cases.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here.
DB_NAME = "minerva_test_device_cases_mig"

PREVIOUS_HEAD = "e4b8d2f6a1c7"
REVISION = "f2c6a8d4b1e9"
NEW_COLUMNS = {
    "va_death_register": ("client_death_id", "uq_va_death_register_client_death_id"),
    "map_case_contact_attempts": ("client_attempt_id", "uq_map_case_contact_attempts_client_attempt_id"),
    "auth_device_sessions": ("outstanding_client_death_ids", None),
}


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class DeviceOfflineCasesConfig(TestConfig):
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


class DeviceOfflineCasesMigrationTest(unittest.TestCase):
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
            app = create_app_without_celery_takeover(DeviceOfflineCasesConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                for table, (column, index) in NEW_COLUMNS.items():
                    columns = {c["name"]: c for c in inspector.get_columns(table)}
                    self.assertIn(column, columns)
                    self.assertTrue(columns[column]["nullable"])
                    if index:
                        self.assertIn("UNIQUE", indexdef(index))
                        self.assertIn("IS NOT NULL", indexdef(index))
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                inspector = sa.inspect(db.engine)
                for table, (column, index) in NEW_COLUMNS.items():
                    self.assertNotIn(column, {c["name"] for c in inspector.get_columns(table)})
                    if index:
                        self.assertIsNone(indexdef(index))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()
