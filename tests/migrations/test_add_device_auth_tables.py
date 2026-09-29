"""``d7a3c9e1f5b2`` adds the device enrolment/session tables and
``va_web_intake_drafts.client_draft_id`` (bead digitva-kmk.1).

The suite builds its schema with ``create_all()``, so this test builds a
throwaway database at the previous head, upgrades, checks the three tables,
the nullable column and its partial unique index, then downgrades and checks
all of it is gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_add_device_auth_tables.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here.
DB_NAME = "minerva_test_device_auth_mig"

PREVIOUS_HEAD = "c5e2b7a9d4f6"
REVISION = "d7a3c9e1f5b2"
NEW_TABLES = {"auth_device_enrolment_codes", "auth_devices", "auth_device_sessions"}
INDEX = "uq_va_web_intake_drafts_client_draft_id"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class DeviceAuthMigrationConfig(TestConfig):
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


class DeviceAuthTablesMigrationTest(unittest.TestCase):
    """Builds its own database; never touches the shared session schema."""

    def test_upgrade_adds_and_downgrade_removes(self):
        from app import db
        from tests.base import create_app_without_celery_takeover

        _drop_database()
        _admin_execute(f'CREATE DATABASE "{DB_NAME}"')
        try:
            app = create_app_without_celery_takeover(DeviceAuthMigrationConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                self.assertTrue(NEW_TABLES <= set(inspector.get_table_names()))
                columns = {c["name"]: c for c in inspector.get_columns("va_web_intake_drafts")}
                self.assertTrue(columns["client_draft_id"]["nullable"])
                indexdef = db.session.execute(
                    sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"), {"n": INDEX}
                ).scalar_one()
                self.assertIn("UNIQUE", indexdef)
                self.assertIn("client_draft_id IS NOT NULL", indexdef)
                session_uniques = {
                    tuple(u["column_names"]) for u in inspector.get_unique_constraints("auth_device_sessions")
                }
                self.assertTrue({("access_hash",), ("refresh_hash",)} <= session_uniques)
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                inspector = sa.inspect(db.engine)
                self.assertFalse(NEW_TABLES & set(inspector.get_table_names()))
                columns = {c["name"] for c in inspector.get_columns("va_web_intake_drafts")}
                self.assertIn("draft_id", columns)
                self.assertNotIn("client_draft_id", columns)
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()
