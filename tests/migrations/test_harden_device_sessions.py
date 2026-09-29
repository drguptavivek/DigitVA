"""``e4b8d2f6a1c7`` adds the retired-refresh history, rotation time and
outstanding draft ids to ``auth_device_sessions``, a GIN index for the reuse
lookup, and the per-account security-event index (bead digitva-kmk.6).

Builds a throwaway database at the previous head, upgrades, checks the
columns and indexes, then downgrades and checks they are gone.

Run (inside Docker)::

    docker compose exec -T minerva_app_service uv run pytest \
        tests/migrations/test_harden_device_sessions.py -q
"""
import unittest

import sqlalchemy as sa
from flask_migrate import downgrade as alembic_downgrade
from flask_migrate import upgrade as alembic_upgrade

from config import TestConfig

# Its own database, dropped and recreated here.
DB_NAME = "minerva_test_device_harden_mig"

PREVIOUS_HEAD = "d7a3c9e1f5b2"
REVISION = "e4b8d2f6a1c7"
NEW_COLUMNS = {"retired_refresh_hashes", "refreshed_at", "outstanding_client_draft_ids"}
GIN_INDEX = "ix_auth_device_sessions_retired_refresh_hashes"
EVENT_INDEX = "ix_auth_security_events_user_type_time"


def _server_url(database):
    return sa.engine.make_url(TestConfig.SQLALCHEMY_DATABASE_URI).set(database=database)


class HardenDeviceSessionsConfig(TestConfig):
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


class HardenDeviceSessionsMigrationTest(unittest.TestCase):
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
            app = create_app_without_celery_takeover(HardenDeviceSessionsConfig)
            with app.app_context():
                alembic_upgrade(revision=PREVIOUS_HEAD)
                alembic_upgrade(revision=REVISION)
                inspector = sa.inspect(db.engine)
                columns = {c["name"]: c for c in inspector.get_columns("auth_device_sessions")}
                self.assertTrue(NEW_COLUMNS <= set(columns))
                self.assertTrue(all(columns[name]["nullable"] for name in NEW_COLUMNS))
                self.assertIn("gin", indexdef(GIN_INDEX))
                self.assertIn("jsonb_path_ops", indexdef(GIN_INDEX))
                self.assertIn("user_id, event_type, occurred_at", indexdef(EVENT_INDEX))
                db.session.remove()

                alembic_downgrade(revision=PREVIOUS_HEAD)
                inspector = sa.inspect(db.engine)
                columns = {c["name"] for c in inspector.get_columns("auth_device_sessions")}
                self.assertIn("refresh_hash", columns)
                self.assertFalse(NEW_COLUMNS & columns)
                self.assertIsNone(indexdef(GIN_INDEX))
                self.assertIsNone(indexdef(EVENT_INDEX))
                db.session.remove()
                db.engine.dispose()
        finally:
            _drop_database()
